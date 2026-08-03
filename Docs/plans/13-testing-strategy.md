# 13 — Testing Strategy

**Read before:** Phase B.

A voice product fails in ways a web app does not: it fails *audibly*, in real time, to a paying customer,
with no undo. The test strategy is weighted accordingly — heavy investment in the deterministic core
(availability, money, state machine), and a small but non-negotiable suite of real voice tests.

---

## 1. The shape of the pyramid

```
                    ╱╲     Voice suites (16)          — slow, real, run on every prompt/model change
                   ╱  ╲    Smoke (prod, 5)            — post-deploy, 2 min
                  ╱────╲
                 ╱      ╲  E2E saga (≈15)             — full booking against fakes, in CI
                ╱────────╲
               ╱          ╲ Integration (≈120)        — real Postgres + Redis via testcontainers
              ╱────────────╲
             ╱              ╲ Contract (≈40)          — adapter ⟷ fake parity
            ╱────────────────╲
           ╱                  ╲ Unit (≈400)           — pure domain, formatters, redaction
          ╱────────────────────╲
```

Coverage gates in CI: `@grace/domain` **≥ 95%** lines and branches (it is pure; there is no excuse).
Everything else ≥ 75%. Coverage is a floor, not a goal — the gates exist to catch untested new code, not
to be optimised.

Runner: **Vitest** everywhere. `@testcontainers/postgresql` and `@testcontainers/redis` for integration.
**Playwright** for the Track B worker's own tests. No mocking library for our own code — use the fakes.

---

## 2. Unit tests — the pure core

Everything in `@grace/domain` and every formatter.

**Highest-value targets, in order:**

| Target | Why it is first |
|---|---|
| `evaluateChange` (48-hour engine) | Money + legal exposure. Test 47h59m, 48h00m, 48h01m, across DST, zero-deposit, member vs non-member, already-cancelled. |
| `rankSlots` | Decides what the caller hears. Property-test: output ⊆ input, never >max, never two slots <45min apart from the same provider. |
| `resolvePricing` | Member/non-member, provider overrides, unapproved service → throws. |
| `redactTranscript` | Compliance. Fixture corpus of realistic utterances, including near-miss card numbers and health phrasings. |
| Time helpers | DST both directions, midnight, week boundaries, tenant timezone ≠ server timezone. **Run CI with `TZ=UTC` and again with `TZ=Pacific/Kiritimati`** — a test suite that only passes in one timezone is a latent production bug. |
| `assertTransition` | Every legal transition passes; every illegal one throws. Exhaustive over the state × state matrix. |
| `selectWriteStrategy` | Exhaustive over the capability × flag matrix. |
| Formatters | Snapshot tests. `speakTime`, `speakPrice`, `speakRelativeDay` across edge cases (noon, midnight, "tomorrow" at 11:59pm). |

**Property-based tests** (fast-check) for: slot ranking invariants, redaction never lengthens sensitive
spans, and change-fee monotonicity (later cancellation never costs less).

---

## 3. Contract tests

Per §05 §9: every port's behavioural spec runs against both the fake and the real adapter (via recorded
cassettes). This is what keeps the fakes honest — and the fakes are what let the entire booking saga be
tested in CI without a single credential.

---

## 4. Integration tests — real Postgres

Testcontainers, migrations applied fresh, seeds loaded, per-suite transaction rollback for isolation.

**Must cover:**

| # | Test | Asserts |
|---|---|---|
| I-1 | Exclusion constraint | Overlapping ACTIVE rows → 23P01; RELEASED overlap → OK (AC-03.2/3) |
| I-2 | RLS | Tenant A cannot read/write tenant B (AC-03.4) |
| I-3 | Free-slot query correctness | Split shifts, time off, special hours, buffers, lead time, advance cap |
| I-4 | Free-slot **query plan** | `EXPLAIN` shows the GiST index anti-join, not a seq scan. Fails on plan regression. |
| I-5 | Free-slot performance | p95 < 40ms with 100k seeded active occupancy rows (AC-06.9) |
| I-6 | Hold placement under conflict | Concurrent inserts; exactly one wins; loser gets a clean skip |
| I-7 | Idempotent booking | Same key ×5 → one row, five identical responses |
| I-8 | Deadline rollback | Simulated deadline mid-transaction → zero rows, hold intact |
| I-9 | Outbox atomicity | Forced failure after business write → neither business rows nor outbox rows exist |
| I-10 | Outbox dispatch | 3 concurrent dispatchers, 500 events → each dispatched once |
| I-11 | Sweeper | Expired holds released; `NEEDS_STAFF` reservations skipped |
| I-12 | Mirror apply | New/updated/cancelled PMS appointment → correct mirror + occupancy state |
| I-13 | **Mirror collision** | PMS appointment overlapping a Grace reservation → P1 staff task, both rows kept (AC-06.10) |
| I-14 | Reconciliation | Seeded drift is detected and reported with correct counts |
| I-15 | Migration idempotency | Migrations twice → no error, no drift |

---

## 5. End-to-end saga tests

In-process: `buildApp()` + real Postgres + real Redis + **fakes** for every port + frozen clock.
No network, no credentials, runs in CI in under 60 seconds.

| # | Scenario | Asserts |
|---|---|---|
| E-1 | Happy booking, deposit required | DRAFT→PENDING_DEPOSIT; outbox has calendar+stripe+2×sms; fake Stripe driven to paid → CONFIRMED → WRITING_TO_PMS → SYNCED |
| E-2 | Happy booking, no deposit | DRAFT→CONFIRMED directly |
| E-3 | Deposit never paid | 24h clock advance → EXPIRED, occupancy released, SMS sent, staff notified |
| E-4 | Track B fails 3× | NEEDS_STAFF, occupancy still ACTIVE, P1 task with payload |
| E-5 | Track B retry after a successful-but-unrecorded write | Pre-check finds it, links it, no duplicate (AC-07.7) |
| E-6 | Native write path | Flip `capabilities.writeAppointments` on the fake → NATIVE_PMS strategy, no code change (AC-07.8/AC-05.7) |
| E-7 | Two callers, one slot | One booking, one `SlotNoLongerAvailable`, alternatives offered |
| E-8 | Reschedule outside 48h | New booking linked via `rescheduled_from`, old cancelled, no fee |
| E-9 | Reschedule inside 48h | Fee decision correct, confirmation logged to `consent_log` |
| E-10 | Cancel with unapproved policy | `PolicyNotApprovedError` → transfer; no fee quoted (AC-07.10) |
| E-11 | Medical hold | Boolean set, no booking, transfer, zero health text persisted |
| E-12 | Unapproved service | Zero slots; graceful transfer |
| E-13 | Kill switch on | First tool call returns transfer |
| E-14 | Cold path entirely down | Booking still succeeds; outbox accumulates; nothing lost |
| E-15 | End-of-call processing | Transcript redacted before first write; holds released; call row complete |

---

## 6. Load and soak

```
Tool: k6.  Target: staging with production-shaped data (100k occupancy rows, 5k customers).
```

| Profile | Shape | Pass criteria |
|---|---|---|
| **Nominal** | 3 concurrent calls, 20 min | p95 < 400ms all read tools; zero errors |
| **Design target** | 25 concurrent calls, 15 min | p95 < 400ms read / < 600ms `createBooking`; zero errors; pool never saturated |
| **Burst** | 0→50 concurrent in 10s, 5 min | p95 < 800ms; graceful degradation only; zero data errors |
| **Contention** | 50 virtual callers, **10 slots** | Exactly 10 bookings. Zero double bookings. Losers get alternatives. **This is the most important load test in the suite.** |
| **Soak** | 5 concurrent, 8 hours | No memory growth, no connection leak, no queue backlog, no unreleased holds |

Run the design-target and contention profiles before every production deploy of the availability or
booking code. Run the soak weekly on staging.

---

## 7. Voice testing

Vapi test suites, the 16 scenarios in §08 §9.

**Gating rules:**
- Any change to `platform/vapi/prompts/**` → full suite must pass before merge.
- Any change to a tool schema or description → full suite.
- Any model change → full suite, plus a manual listen to 5 recordings.
- Weekly scheduled run against the dev assistant to catch upstream drift (model updates, provider changes).

Voice tests are non-deterministic. Treat a single failure as a signal to listen, not as a hard block —
but three failures in a row on the same scenario is a block. Record the judgement in the PR.

**Manual listening is not optional.** Before production traffic, one person listens to at least 20
complete test calls end to end. Metrics do not capture "she sounds like she's reading a form."

---

## 8. Chaos and failure injection

Run these deliberately on staging; each corresponds to a row in §07 §8.

| Injection | Expected behaviour |
|---|---|
| Kill Core API mid-call | Vapi tool timeout → Grace's fallback sentence → transfer; call does not drop |
| Kill sync-worker for 10 min | Outbox accumulates; on restart everything drains; nothing lost or duplicated |
| Postgres failover | Reconnect within 30s; in-flight transactions fail cleanly with a spoken fallback |
| Redis down | Tenant cache misses fall back to DB; queues pause; **calls still work** |
| Google Calendar 403 | Booking → NEEDS_STAFF, P1, slot held |
| Stripe 500s | Retries, then "we'll call you" SMS + staff task |
| Twilio 429 | Backoff; no lost messages |
| PMS returns garbage | Zod rejects; mirror unchanged; alert raised; **no bad data enters the mirror** |
| Clock skew on a worker | Idempotency and TTL logic unaffected (all times from the DB) |
| Network partition worker↔DB | Locks expire, jobs reclaimed, no duplicate side effects |

---

## 9. CI pipeline

```yaml
# TARGET — .github/workflows/ci.yml (stages)
lint            → eslint, prettier, dependency-cruiser, gitleaks, n8n workflow lint
typecheck       → tsc --build
unit            → vitest, coverage gates, TZ=UTC and TZ=Pacific/Kiritimati matrix
contract        → adapters vs fakes (cassettes)
integration     → testcontainers postgres+redis, migrations, seeds
e2e             → full saga against fakes
build           → docker images (not pushed on PR)
invariants      → I7 greeting check, BIPA grep, generated-tools drift, platform diff
```

PR merge requires all green. `main` additionally runs: image push, staging deploy, smoke tests, and the
k6 nominal profile.

**Total PR pipeline target: under 8 minutes.** Beyond that people stop running it locally and start
merging hopefully.

---

## 10. Test data

- **Fixtures** in `packages/testing/src/fixtures` — builders, not literals:
  `aBooking().forService('massage_60').at('2026-08-04T18:30').inState('CONFIRMED').build()`.
- **Never** use real customer data in tests, seeds, or fixtures. Names from a generated list, phone
  numbers from the reserved 555 range.
- **Never** point a test at production. `GRACE_DATABASE_URL` containing `prod` fails the test bootstrap
  with a loud error.
- Live-PMS write tests are gated behind `GRACE_ALLOW_LIVE_PMS_WRITES`, never set in CI (§05 §3.2).

---

## 11. Acceptance criteria

✅ **AC-13.1** `pnpm test` runs the full suite (unit + contract + integration + e2e) with no credentials
and no network, in under 5 minutes.
✅ **AC-13.2** Domain coverage ≥95%; CI fails below it.
✅ **AC-13.3** The unit suite passes under both `TZ=UTC` and `TZ=Pacific/Kiritimati`.
✅ **AC-13.4** The contention load profile produces exactly the available number of bookings, zero doubles.
✅ **AC-13.5** Every failure mode in §07 §8 has a corresponding test or a documented chaos drill.
✅ **AC-13.6** The 16 voice scenarios exist and pass on the dev assistant.
✅ **AC-13.7** A deliberately introduced regression in the 48-hour engine is caught by a unit test.
✅ **AC-13.8** A deliberately introduced seq-scan regression in the free-slot query is caught by I-4.
