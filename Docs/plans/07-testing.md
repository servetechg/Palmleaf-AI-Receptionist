# 07 — Testing

**Status:** Active
**Read before:** writing a test, or adding a CI stage.
**Implements:** ADR-0011, ADR-0014
**Enforces:** I4, I5, I6, I7
**Last verified:** 2026-08-04 against `make check`, `.github/workflows/ci.yml` and the 14 passing tests in `tests/`.

> **In one paragraph:** this document settles how Grace is tested — what runs today, what is
> planned, and which gate blocks which action. A voice product fails *audibly*, in real time, to a
> paying customer, with no undo, so the weighting is deliberate: heavy investment in the
> deterministic core, plus a small non-negotiable suite of real voice tests. It deliberately
> separates **what exists** (§2–§4) from **what is designed but unbuildable** (§6–§9), because
> conflating the two is how a test plan starts describing coverage the project does not have.

---

## 1. What is actually tested today

Start here, because the honest answer is small and the sections after it are mostly aspiration.

| Layer | Status | Where |
|---|---|---|
| Spoken-output formatters | ✅ **14 tests, passing** | `tests/test_speech.py` |
| Generated-artefact determinism | ✅ enforced in CI | `make vapi-build-check`, `make docs-check` |
| Vapi schema conformance | ✅ enforced in CI | `make vapi-validate`, against the live OpenAPI document |
| n8n workflow lint | ✅ enforced in CI | `make n8n-lint`, 15 rules |
| Invariant I7 (recording disclosure) | ✅ enforced in CI | two greps, both halves — see §3 |
| Document template | ✅ enforced in CI | `make docs-lint` |
| Live tool behaviour under a real model | ⚠️ **mock server only, never run against a live call** | §4 |
| Domain, integration, saga, load, chaos | ⛔ **not built** — no Core API, no database | §6–§9 |

**The single biggest untested gap** is that the web harness has never been driven through a live
call. Everything in §4 is verified against the mock server by direct HTTP, not by a model actually
talking. That gap closes with one tunnel and one call, and it should be closed early — it is
cheap, and it is the only thing that validates the prompt, the grounding rule, the medical gate
and endpointing together.

---

## 2. Unit tests — the spoken layer, and later the domain

The only unit tests that exist today cover **speech formatting**, and they exist because the mock
server found three defects that would all have been audible on a real call:

| # | Defect | What a caller would have heard |
|---|---|---|
| 1 | `date("2026-08-04")` parsed as UTC midnight, rendering as the previous day in `America/Chicago` | *"Monday the third"* for a Tuesday appointment |
| 2 | The tens table had no entry below 20, so `11500` decomposed wrongly | *"one ten-five"* instead of *"one fifteen"* |
| 3 | Times and prices hyphenated inconsistently | *"five forty five"* beside *"one thirty-five"* in one sentence |

All three are now locked by tests. Defect 1 is the instructive one: it is a timezone bug that
**only appears west of UTC**, which is precisely why §5 requires the suite to run under more than
one `TZ`.

The 14 cases are things a caller would actually hear — the hour alone on the hour, "oh" for
single-digit minutes, noon and midnight as twelve rather than zero, a bare `YYYY-MM-DD` treated as
a Chicago calendar date, irregular ordinals (first, second, third, fifth, ninth, twelfth,
twentieth, twenty-first, thirty-first), and `speak_list` never reading more than three options
aloud.

**When `grace_domain` exists**, it inherits the same standard, and these become its
highest-value targets:

| Target | Why it is first |
|---|---|
| `evaluate_change` (the 48-hour engine) | Money and legal exposure. Test 47h59m, 48h00m, 48h01m, across DST, zero-deposit, member and non-member, already-cancelled |
| `rank_slots` | Decides what the caller hears. Property-test: output ⊆ input, never more than max, never two slots under 45 minutes apart from one provider |
| `resolve_pricing` | Member and non-member, provider overrides, unapproved service raises |
| `redact_transcript` | Compliance (I6). A fixture corpus of realistic utterances, including near-miss card numbers and health phrasings |
| Time helpers | DST in both directions, midnight, week boundaries, tenant timezone ≠ server timezone |
| `assert_transition` | Every legal transition passes, every illegal one raises. Exhaustive over the state × state matrix |

Coverage gate when that package lands: **`grace_domain` ≥ 95%** lines and branches — it is pure,
so there is no excuse — and ≥ 75% elsewhere. Coverage is a floor to catch untested new code, not a
number to optimise.

Property-based tests (`hypothesis`) for slot-ranking invariants, redaction never lengthening a
sensitive span, and change-fee monotonicity: a later cancellation never costs less.

---

## 3. The invariant checks — cheap, and the ones that have caught real defects

These are greps and schema validations rather than tests, and they are the highest
value-per-second in the pipeline.

| Check | Guards | Why it is shaped this way |
|---|---|---|
| `"may be recorded"` present in `first-message.txt` | I7 | Illinois all-party consent, in the first utterance |
| `"virtual assistant"` present in `first-message.txt` | I7 | AI disclosure |
| `grace.json` **injects** rather than inlines `firstMessage` | I7 | **Both halves are required.** Checking only the file lets an edit to `grace.json` ship a greeting with no disclosure and still pass |
| Generated tool JSON matches the Pydantic models | — | The schema published to Vapi and the schema handlers validate against cannot silently diverge |
| `grace.json` and every tool validate against the live Vapi OpenAPI | — | Catches a deprecated or misspelled field **locally**, before a deploy 400s |
| No class docstring reaches a published schema | — | Pydantic uses docstrings as descriptions; internal notes were being sent to the model as instructions |

That third row is worth dwelling on. The original check tested a file that was never shipped —
the acceptance criterion passed while the invariant it claimed to protect was bypassable. A test
that guards the wrong artefact is worse than no test, because it also removes the suspicion that
something is unguarded.

---

## 4. The mock tool server — the contract double

Core API does not exist. Without a stand-in, every tool returns nothing on a web call, Grace says
*"I'm having trouble"* on every turn, and none of the prompt, grounding rule, medical gate, PCI
refusal, endpointing or generated schemas can be exercised at all.

`src/grace_platform/vapi/mock_server/` serves the same two routes as Core API
(`POST /vapi/tools`, `POST /webhooks/vapi/events`) with the same envelope, so switching between
them is one environment variable.

**Its real job is validating every tool call against the real Pydantic models** — which is what
proves the JSON Schema published to Vapi and the schema our handlers expect actually agree, under
a live model, before Core API exists.

| Capability | Detail |
|---|---|
| Schema validation | Real Pydantic models; rejects with a spoken retry and a loud console error, never a 500 |
| Spoken formatters | `speech.py` — times, dates, prices, lists capped at three |
| Deterministic clock | `GRACE_MOCK_NOW` freezes "now", so date-dependent output is reproducible |
| Fault injection | `GRACE_MOCK_LATENCY_MS`, `GRACE_MOCK_FAIL=<tool>`, `GRACE_MOCK_TIMEOUT=<tool>` |
| Idempotency | In-memory map keyed `{call_id}:{tool_call_id}`; replays the stored response |
| Whisper priming | Captures `flagEscalation.summary` and serves it on `transfer-destination-request` (60s TTL) |
| Medical gate | Refuses to book when `medical_screen_passed` is false — **server-side, not prompt-only** (I4) |

That last row is the design principle in miniature: a rule that matters is enforced in code, not
in prose the model may or may not follow.

**Verified behaviour**, live against the running server: spoken number formatting, member pricing,
`extra="forbid"` rejecting an invented parameter, the server-side medical gate refusing to book,
and idempotent replay returning a byte-identical response for a repeated `tool_call_id`.

**It is not throwaway.** When Core API lands, this becomes the contract-test double that proves
both implementations agree on all 15 envelopes.

Known limits, stated rather than discovered later: there are no tests for the fixtures themselves,
only for `speech.py`; there is no contract test asserting the mock and Core API agree, because
Core API does not exist; and `GRACE_MOCK_TIMEOUT` sleeps rather than modelling the real deadline
middleware.

---

## 5. CI — the gate that exists

```yaml
#: LIVE — .github/workflows/ci.yml, job "T1 static"
typecheck        → mypy src tests (strict)
lint             → ruff check + ruff format --check
unit             → pytest
invariants       → I7 disclosure greps, both halves
generated        → vapi tool JSON + system.md are current
schema           → validate against the live Vapi OpenAPI (--refresh)
n8n              → workflow lint, 15 rules
docs             → generated reference current; document template conforms
```

`make check` runs the same targets, so **a green `make check` locally means a green CI.** Any
divergence between them is itself a defect.

**Budget: under 90 seconds, $0.** No Vapi calls, no credentials, no network beyond the OpenAPI
fetch. This is the tier that catches a deprecated-field defect before it reaches a deploy, and it
is the cheapest tier in the plan by a wide margin.

Two things it deliberately does **not** do: it never talks to a model, and it never touches
production. Those belong to §6 and to CI's deploy jobs respectively.

---

## 6. Voice and chat simulations — the three tiers

Vapi Simulations, using the 16 scenarios in [03-vapi-layer](03-vapi-layer.md) §9.2. **T1 exists
today; T2 and T3 are specified but not yet wired.**

| Tier | Trigger | Budget | Mechanism | Gates |
|---|---|---|---|---|
| **T1 Static** | every PR | <90s, $0 | §5. No model calls at all | merge |
| **T2 Chat** | PRs touching `prompts/**`, `tools/**`, `assistants/**`, `contracts/**` | 3–5 min | 10 scenarios over web chat, with tool mocks | merge |
| **T3 Voice** | nightly and on a release tag | 20–30 min | All 16 scenarios over a real audio path, 2 iterations, against the mock server | release |

**Gating rules.** Any change to `platform/vapi/prompts/**` or to a tool schema or description runs
the full suite before merge. Any model change runs the full suite *plus* a manual listen to five
recordings.

**Voice tests are non-deterministic.** Treat a single failure as a signal to listen, not as a hard
block — but three consecutive failures on the same scenario is a block. Record the judgement in
the pull request, so the next person sees that it was a decision rather than an oversight.

**Manual listening is not optional.** Before production traffic, one person listens to at least 20
complete test calls end to end. No metric captures *"she sounds like she is reading a form."*

---

## 7. Integration and saga tests — planned, blocked on the database

Nothing here can be built until `grace_db` and `grace_api` exist. It is specified now so the
schema work lands with its tests rather than acquiring them later.

**Integration** — real Postgres via testcontainers, migrations applied fresh, per-test transaction
rollback for isolation:

| # | Test | Asserts |
|---|---|---|
| I-1 | Exclusion constraint | Overlapping ACTIVE rows → `23P01`; overlap with a RELEASED row → fine |
| I-2 | Row-level security | Tenant A cannot read or write tenant B |
| I-3 | Free-slot correctness | Split shifts, time off, special hours, buffers, lead time, advance cap |
| I-4 | Free-slot **query plan** | `EXPLAIN` shows the GiST index anti-join, not a sequential scan. Fails on plan regression |
| I-5 | Free-slot performance | p95 < 40ms with 100k seeded active occupancy rows |
| I-6 | Hold placement under conflict | Concurrent inserts; exactly one wins; the loser gets a clean skip |
| I-7 | Idempotent booking | The same key five times → one row, five identical responses |
| I-8 | Deadline rollback | Simulated deadline mid-transaction → zero rows, hold intact |
| I-9 | Outbox atomicity | Forced failure after the business write → neither business nor outbox rows exist |
| I-10 | Outbox dispatch | Three concurrent dispatchers, 500 events → each dispatched exactly once |
| I-11 | Mirror collision | A PMS appointment overlapping a Grace reservation → P1 staff task, both rows kept |

**End-to-end saga** — in-process, real Postgres and Redis, **fakes for every port**, frozen clock.
No network, no credentials, under 60 seconds in CI. Fifteen scenarios covering the happy booking
with and without a deposit, an unpaid deposit expiring, Track B failing three times, a retry after
a successful-but-unrecorded write, the native write path enabled by flipping one capability flag,
two callers racing for one slot, reschedules inside and outside 48 hours, an unapproved policy, a
medical hold, the kill switch, and the entire cold path being down while a booking still succeeds.

That last scenario is the one worth naming explicitly: **the outbox exists so a booking survives
every downstream system being unavailable.** If it is not tested, it is not a guarantee.

---

## 8. Load, soak and chaos — planned, blocked on Core API

| Profile | Shape | Pass criteria |
|---|---|---|
| Nominal | 3 concurrent calls, 20 min | p95 < 400ms on all read tools; zero errors |
| Design target | 25 concurrent calls, 15 min | p95 < 400ms read, < 600ms `createBooking`; pool never saturated |
| Burst | 0→50 concurrent in 10s, 5 min | p95 < 800ms; graceful degradation only; zero data errors |
| **Contention** | 50 virtual callers, **10 slots** | Exactly 10 bookings. Zero double bookings. Losers get alternatives |
| Soak | 5 concurrent, 8 hours | No memory growth, no connection leak, no queue backlog, no unreleased holds |

**The contention profile is the most important load test in the suite** — it is the only direct
proof that ADR-0004's exclusion constraint does what the entire booking guarantee assumes.

Chaos drills, run deliberately on staging, each matching a row in
[booking-write-path](../reference/booking-write-path.md) §8: killing Core API mid-call, killing the
worker for ten minutes, Postgres failover, Redis down (**calls must still work**), a calendar 403,
Stripe 500s, Twilio 429s, the PMS returning garbage, clock skew on a worker, and a network
partition between worker and database.

---

## 9. Test data

- **Builders, not literals.** `a_booking().for_service("massage_60").at("2026-08-04T18:30").in_state("CONFIRMED").build()`.
- **Never real customer data** in tests, seeds or fixtures. Generated names, phone numbers from the
  reserved 555 range.
- **Never point a test at production.** A `GRACE_DATABASE_URL` containing `prod` fails the test
  bootstrap loudly.
- Live-PMS write tests sit behind `GRACE_ALLOW_LIVE_PMS_WRITES`, never set in CI.

---

## 10. Acceptance criteria

✅ **AC-13.1** `make check` runs the full available suite with no credentials and no network beyond
the Vapi schema fetch, in under 90 seconds.
✅ **AC-13.2** The speech suite passes under both `TZ=UTC` and `TZ=Pacific/Kiritimati`. A suite that
passes in only one timezone is a latent production bug — this is the regression guard for defect 1
in §2.
✅ **AC-13.3** Removing `"may be recorded"` from `first-message.txt` fails CI, **and** inlining a
literal `firstMessage` in `grace.json` also fails CI.
✅ **AC-13.4** A deliberately invented tool parameter is rejected by the mock server with a spoken
retry, not a 500.
✅ **AC-13.5** The same `tool_call_id` submitted twice returns a byte-identical response.
✅ **AC-13.6** `make docs` and `make vapi-build` are each byte-identical on a second run.
✅ **AC-13.7** *(blocked — needs `grace_domain`)* Domain coverage ≥ 95%; CI fails below it.
✅ **AC-13.8** *(blocked — needs Core API)* The contention profile produces exactly the available
number of bookings and zero doubles.
✅ **AC-13.9** *(blocked — needs Core API)* Every failure mode in
[booking-write-path](../reference/booking-write-path.md) §8 has a corresponding test or a
documented chaos drill.
✅ **AC-13.10** The 16 voice scenarios exist and pass on the dev assistant.

## 11. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-07.1** | When does the web harness get driven through a live call? | It is the largest untested gap (§1) and needs only a tunnel. Until it happens, the prompt, grounding rule, medical gate and endpointing are verified by direct HTTP against the mock, never by a model actually speaking. | Engineering — unblocked, do it early |
| **Q-07.2** | Are T2/T3 simulations affordable at the intended cadence? | T3 is 16 scenarios × 2 iterations of real audio, nightly. No per-call or account spend cap exists in Vapi ([03-vapi-layer](03-vapi-layer.md) §11.2), so an accidental loop has no ceiling. Establish the cost before enabling the nightly trigger. | Engineering + commercial |
| **Q-07.3** | Does `hypothesis` earn its place, or is a table of cases enough? | Property tests are specified for slot ranking, redaction and fee monotonicity. At the current domain size, well-chosen table cases may cover the same ground more legibly. Decide when the first of those functions is written, not before. | Engineering, at Phase B |
| **Q-07.4** | What replaces testcontainers if CI cannot run Docker? | §7 assumes testcontainers for real Postgres. If the CI runner cannot, the fallback is a service container, which changes isolation and cleanup. Worth confirming before the schema work starts. | Engineering, at Phase A |
