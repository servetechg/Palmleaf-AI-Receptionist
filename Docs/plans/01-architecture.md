# 01 — Architecture Foundation & Decision Records

**Status:** Active
**Read before:** anything else — every other document assumes the layering and the ADRs settled here.
**Enforces:** I1, I2, I4, I8, I9
**Last verified:** 2026-08-04 against the ported Python source in `src/` and the four ADRs added by the restructure.

> **In one paragraph:** this document settles the *shape* of the system — the six forces that
> produced it, the eight layers, the hard split between the hot path (a caller is waiting) and
> the cold path (nobody is), and the eighteen architecture decisions with the exit criteria that
> would reopen each one. It deliberately does **not** specify any schema, endpoint, or workflow;
> those live in the documents this one constrains.

---

## 1. Design forces

Everything in this architecture is a response to one of six forces. When you are unsure why something
is shaped the way it is, it is because of one of these.

| Force | Consequence |
|---|---|
| **F1 — Voice is a hard real-time medium.** Silence over ~900ms reads as a broken system. | All read paths must be local. No third-party call is ever on the synchronous path. |
| **F2 — Vagaro has no appointment-write API.** | The write path is a multi-track saga with compensation, not a function call. It must be swappable the day Vagaro ships a real endpoint. |
| **F3 — Two callers can be on two lines in the same second.** | Concurrency control must be at the database, not in application logic. |
| **F4 — Money and legal policy are attached to date math.** | Business rules are pure, unit-tested, deterministic code. Never prompt text. |
| **F5 — Illinois: all-party consent, BIPA, healthcare-adjacent PHI.** | Compliance is a build-time constraint, not a launch checklist. |
| **F6 — This is a productized service, not a one-off.** | Multi-tenancy, PMS-agnostic ports, and config-as-code from commit #1. |

> **On F6 — stated assumption.** The design brief is written for a single client (PalmLeaf). This plan
> assumes PalmLeaf is *tenant one of a service*, not the only tenant, and therefore builds multi-tenant
> data structures and a swappable PMS port from the start. The cost of this is roughly one extra column
> and one extra interface; the cost of retrofitting it later is a rewrite. If PalmLeaf is genuinely a
> one-off engagement, the multi-tenant scaffolding is inert and harmless — nothing needs removing.
> Logged as **A-01** in `09-open-decisions.md`.

---

## 2. Layered view

```
┌───────────────────────────────────────────────────────────────────────────┐
│ L0  CARRIER            Twilio Elastic SIP Trunk · RingCentral forward      │
│                        Owns: PSTN transport, DID, SIP TLS/SRTP            │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │ SIP INVITE
┌─────────────────────────────────▼─────────────────────────────────────────┐
│ L1  CONVERSATION       Vapi — Deepgram STT · LLM · ElevenLabs TTS         │
│                        Owns: turn-taking, ASR, phrasing, tool selection   │
│                        Owns NOTHING about business truth                  │
└─────────────────────────────────┬─────────────────────────────────────────┘
                                  │ HTTPS tool call (POST, HMAC-signed)
                                  │ ── SYNCHRONOUS BUDGET: p95 < 400 ms ──
┌─────────────────────────────────▼─────────────────────────────────────────┐
│ L2  CORE API  (grace_api — FastAPI + Python 3.12)                         │
│     ┌──────────────┬──────────────┬──────────────┬─────────────────────┐  │
│     │ tool router  │ idempotency  │ deadline     │ hmac + tenant       │  │
│     └──────────────┴──────────────┴──────────────┴─────────────────────┘  │
│     Owns: request lifecycle, auth, deadlines, NL response formatting      │
└───────┬─────────────────────────────────────────────────┬─────────────────┘
        │ calls (in-process)                              │ writes
┌───────▼─────────────────────────────────┐   ┌───────────▼─────────────────┐
│ L3  DOMAIN  (grace_domain)              │   │ L4  PERSISTENCE             │
│  · availability engine                  │   │  Postgres 16                │
│  · hold / reservation state machine     │◄──┤  · availability mirror      │
│  · 48-hour change-fee engine            │   │  · occupancy (EXCLUDE)      │
│  · pricing & membership resolution      │   │  · bookings saga state      │
│  · medical-screen gate                  │   │  · outbox                   │
│  PURE. No I/O. 100% unit-testable.      │   │  Redis: queues, locks, cache│
└─────────────────────────────────────────┘   └───────────┬─────────────────┘
                                                          │ outbox dispatch
┌─────────────────────────────────────────────────────────▼─────────────────┐
│ L5  ASYNC EXECUTION                                                       │
│   sync-worker (arq)                  booking-worker (Playwright)          │
│   n8n (ops workflows, staff alerting, low-code integrations)              │
│   ── NO LATENCY BUDGET. Retries, backoff, dead-letter. ──                 │
└─────────────────────────────────────────────────────────┬─────────────────┘
                                                          │
┌─────────────────────────────────────────────────────────▼─────────────────┐
│ L6  PORTS & ADAPTERS   (grace_adapters)                                   │
│   PmsPort ──► VagaroAdapter (+ future: MindbodyAdapter, BookerAdapter)    │
│   CalendarPort ──► GoogleCalendarAdapter                                  │
│   PaymentsPort ──► StripeAdapter    MessagingPort ──► TwilioAdapter       │
│   Every adapter: typed, retried, circuit-broken, recorded in tests        │
└─────────────────────────────────────────────────────────┬─────────────────┘
                                                          │
┌─────────────────────────────────────────────────────────▼─────────────────┐
│ L7  SYSTEMS OF RECORD   Vagaro · Google Calendar · Stripe · Twilio        │
└───────────────────────────────────────────────────────────────────────────┘
```

**The dependency rule:** dependencies point inward and downward only.
`grace_domain` imports nothing from `L2`, `L5`, or `L6`. Adapters depend on port protocols defined in
`grace_contracts`, never the reverse. Enforced by **import-linter** contracts in CI (ADR-0018).

---

## 3. The two paths through the system

Every request is on exactly one of two paths. Confusing them is the primary way this system gets slow
or loses data.

### 3.1 The hot path (synchronous, caller is waiting)

```
Vapi tool call
  → HMAC verify (≈1ms)
  → tenant resolve from cache (≈0ms)
  → idempotency check (1 indexed SELECT, ≈2ms)
  → Pydantic parse (≈0ms)
  → handler: 1–3 Postgres queries against local mirror (≈10–40ms)
  → domain computation, pure (≈1ms)
  → format natural-language string (≈0ms)
  → write outbox rows in the SAME transaction (≈5ms)
  → respond
TOTAL BUDGET: p50 < 120ms, p95 < 400ms, hard deadline 2500ms
```

**Permitted on the hot path:** Postgres (local), Redis (local), pure computation.
**Forbidden on the hot path:** Vagaro, Google Calendar, Stripe, Twilio, n8n, Playwright, any LLM call,
any network egress to a third party. **No exceptions.** Enforced by an import-linter contract on
`grace_api.routes.vapi.handlers` (ADR-0018).

### 3.2 The cold path (asynchronous, nobody is waiting)

```
outbox row committed
  → dispatcher polls (250ms tick) or is woken by NOTIFY
  → enqueues an arq job (at-least-once)
  → worker executes: adapter call with retry + circuit breaker
  → success: mark outbox row done, emit domain event
  → failure: exponential backoff, N attempts, then dead-letter + staff task
BUDGET: none. Correctness and durability only.
```

Everything the caller does not wait for lives here: Vagaro writes, Google Calendar writes, Stripe link
creation, SMS, staff alerts, transcript processing, mirror reconciliation, Track B automation.

---

## 4. Architecture Decision Records

Each ADR states the decision, the alternatives that were real, and the exit criteria — the condition
under which the decision should be revisited. An ADR without exit criteria is dogma, not engineering.

---

### ADR-0001 — ~~TypeScript~~ monorepo as the single source of truth

> ⚠️ **The language choice here is SUPERSEDED by ADR-0014 (Python).** Everything else in
> this ADR — one monorepo, config-as-code, CI as the only deployer, one schema source
> spanning tool definition to handler — stands unchanged and is what ADR-0014 preserves.

**Decision.** *(All three tools named here were replaced by ADR-0014.)* One pnpm+Turborepo monorepo, TypeScript everywhere (Node 22 LTS, ESM).
Vapi assistant definitions and n8n workflow definitions live in this repo as version-controlled
JSON and are deployed by CI, not authored in a dashboard.

**Why.** The design brief §20 already establishes both platforms are code-first. A single repo means one
CI, one type system spanning tool schema → API handler → database row, and one review surface. Type
drift between a Vapi tool's JSON schema and the endpoint that serves it is the single most likely
integration bug; sharing Pydantic models eliminates the class entirely.

**Alternatives.** Python for the core service (better ML ecosystem, irrelevant here — no model training).
Polyrepo (better isolation, worse for a 3-person team and cross-cutting schema changes).

**Exit criteria.** Revisit if the Track B worker needs a language Playwright serves better (it does not),
or if the team composition changes to Python-primary.

---

### ADR-0002 — Core API owns synchronous tools; n8n owns asynchronous orchestration

**Decision.** The Vapi tools are served by `grace_api`, a typed FastAPI service (ADR-0017). n8n remains in the
architecture and owns: the Vagaro webhook **fan-out to secondary consumers**, staff alerting and
escalation, operational digests, the nightly reconciliation **report**, and any future low-code
integration the client's team wants to modify without a deploy.

> *Corrected 2026-08-03.* This paragraph previously also credited n8n with "end-of-call post-processing"
> and "SMS templating dispatch". Both moved into code — transcript processing is the
> `call.process_transcript` outbox consumer, and SMS dispatch must be transactional with the outbox
> ([04-n8n-layer](04-n8n-layer.md) §3, WF-09/WF-11). Staff SMS specifically must route through the messaging adapter rather than an
> n8n Twilio node, or it bypasses 10DLC and opt-out enforcement ([04-n8n-layer](04-n8n-layer.md) §3.4). The tool count is also no
> longer 13 — see [03-vapi-layer](03-vapi-layer.md) §4.

**Why.** This is the one place this plan set diverges materially from the design brief, so the reasoning
is spelled out:

1. **Latency determinism.** A voice tool call has a p95 budget of 400ms. n8n's execution model — per-execution
   workflow load, per-node JSON serialization, sub-workflow invocation overhead, and a shared execution
   queue — makes the *tail* unpredictable even when the median is acceptable. Voice quality is decided by
   the tail, not the median.
2. **Transactional integrity.** Promoting a hold to a reservation, writing the booking row, and enqueuing
   the outbox rows must be **one Postgres transaction**. n8n has no transaction primitive spanning nodes.
   Without it, a crash between two nodes leaves a hold with no booking, or a booking with no SMS.
3. **Testability of money.** Invariant I4 requires the 48-hour rule and pricing to be unit-tested. A
   Function node in a canvas is not unit-testable in CI, cannot be property-tested, and diffs unreadably.
4. **Concurrency.** The double-booking defence (ADR-0004) requires a DB-level exclusion constraint and
   correct handling of the resulting serialization errors with retry. This is application-code work.

**What n8n is genuinely better at, and therefore keeps.** Ops workflows a non-developer may need to
change; notification fan-out with visual routing; connector breadth for integrations we have not
foreseen; and giving the client's technical contact a legible view of the operational plumbing.

**Fallback if this decision is rejected.** The tool endpoints are thin: HTTP in, JSON out, all logic in
`grace_domain`. If a stakeholder requires n8n on the hot path, n8n can call the same domain logic via a
single internal HTTP endpoint per tool. The domain package is unaffected. This is a one-day change and
is why the decision is not a one-way door.

**Exit criteria.** Revisit if measured n8n p99 on a representative tool workflow lands under 250ms in
the production topology, *and* a transaction-spanning primitive exists.

---

### ADR-0003 — Local availability mirror; Vagaro is eventually consistent

**Decision.** Postgres holds a continuously-reconciled projection of the Vagaro calendar. All in-call
reads answer from it. Vagaro is synchronized by webhooks (primary), 10-minute polling (drift
correction), and a nightly full reconciliation (authority).

**Why.** F1. Also: Vagaro's API is metered per call ($0.002 over 5,000/month) and rate-limited by an
undocumented limit. Serving `checkAvailability` live from Vagaro is both slow and a cost/limit hazard.

**The consistency contract this creates.** The mirror may be stale by at most:
- the webhook delivery latency (typically <5s) in the normal case,
- 10 minutes if a webhook is lost,
- until 03:00 if both webhook and poller miss a record.

The system is therefore designed so that **staleness costs a phone call, not a double booking**:
the DB exclusion constraint (ADR-0004) prevents Grace double-booking against her own holds, and the
reconciliation job ([booking-write-path](../reference/booking-write-path.md) §6) detects and reports mirror-vs-Vagaro divergence, raising a staff task rather
than silently correcting a customer-visible booking.

**Exit criteria.** Revisit if Vagaro ships a real-time availability endpoint with a p95 under 150ms and
an unmetered tier.

---

### ADR-0004 — Double-booking is prevented by a Postgres exclusion constraint, not application logic

**Decision.** A single table `calendar_occupancy` holds every reason a provider's time is unavailable —
soft holds, reservations, confirmed appointments, mirrored Vagaro bookings, Google Calendar blocks,
time off — as a `tstzrange`. A `btree_gist` `EXCLUDE` constraint makes overlapping *active* rows for the
same provider physically impossible.

**Why.** F3. Application-level "check then insert" is a race by construction. Two concurrent calls will
both read "free" and both insert. Advisory locks help but are easy to bypass from a new code path. A
database constraint cannot be bypassed by any code path, including a manual `psql` session, a future
migration script, or a subtly wrong n8n workflow.

**Consequence to design for.** Callers will now see `23P01 exclusion_violation` under contention. The
repository layer MUST translate this into a domain `SlotNoLongerAvailable` error and the handler MUST
recover gracefully ("that one just went — I also have 6:30"). This is specified in [availability-engine](../reference/availability-engine.md) §5.

**Alternatives.** Redis distributed lock (fast, but not durable and not authoritative);
`SERIALIZABLE` isolation on a check-then-insert (correct, but higher abort rate and still application-dependent).

**Exit criteria.** None foreseen. This is the strongest available guarantee.

---

### ADR-0005 — Transactional outbox for every externally-visible side effect

**Decision.** Domain writes and their side effects are committed in one transaction: the business rows plus
one `outbox_events` row per side effect. A dispatcher moves outbox rows onto an arq queue (ADR-0015). Workers execute them
with retry, backoff, and dead-lettering.

**Why.** F2 and I8. The alternative — call Stripe/Twilio/Google inline, or enqueue directly to Redis — loses
the side effect if the process dies between the DB commit and the enqueue, and duplicates it if the
enqueue succeeds but the commit rolls back. For a booking confirmation that is an annoyance; for a
deposit link or a held slot it is a customer-facing failure and possibly a chargeback.

**Consequence.** Delivery is **at-least-once**. Every consumer MUST be idempotent, keyed on
`outbox_events.id`. Specified in [booking-write-path](../reference/booking-write-path.md) §3.

**Exit criteria.** None. This is table stakes for a system that touches money.

---

### ADR-0006 — The write path is a saga with explicit states and compensations

**Decision.** `bookings` carries an explicit state machine. Transitions are made by named, tested
functions. Every state has a defined compensation and a defined terminal outcome. Track A (calendar
hold), Track B (true Vagaro appointment), Track C (self-serve link) and Track D (staff task) are
*strategies* selected by a policy object, not branches scattered through handlers.

**Why.** F2. With no atomic "create appointment" call, the booking is a distributed transaction across
Google Calendar, Stripe, Vagaro and SMS. Sagas are the standard answer. Making the states explicit means
"what happened to booking X?" is answerable from one column, and a stuck booking is queryable rather
than archaeological.

**Exit criteria.** If Vagaro grants a real `POST /appointments`, the saga collapses to two states and
Track B is deleted. The saga is designed to make that deletion a small diff — see [booking-write-path](../reference/booking-write-path.md) §7.

---

### ADR-0007 — Ports and adapters for every external system

**Decision.** `grace_contracts` defines `PmsPort`, `CalendarPort`, `PaymentsPort`, `MessagingPort`,
`VoicePort` as `typing.Protocol` classes. `grace_adapters` implements them. Domain and handlers depend
only on the protocol.

**Why.** F2 and F6. The Vagaro write-path answer is unknown at design time ([09-open-decisions](09-open-decisions.md) GATE-01), so the code must
tolerate three different Vagaro futures without a rewrite. The same port makes a second PMS a new package,
not a refactor. It also makes testing tractable — every port has an in-memory fake used by the entire
integration suite.

**Exit criteria.** None. Cost is near zero, optionality is high.

---

### ADR-0008 — Multi-tenant from commit one; single-tenant in production initially

**Decision.** Every business table carries `tenant_id uuid not null`. Postgres RLS policies enforce
isolation. Tenant is resolved at the edge from the Vapi `assistantId`/`phoneNumberId` and pinned into
`AsyncLocalStorage` for the request. Production runs exactly one tenant (PalmLeaf) until Phase F.

**Why.** F6. Retrofitting tenancy requires touching every query, every index, and every cache key, under
production load, with live customer data. Adding it now costs one column and one policy per table.

**Exit criteria.** None.

---

### ADR-0009 — ~~Drizzle ORM~~ with hand-written SQL for the hot path

> ⚠️ **The ORM choice here is SUPERSEDED by ADR-0016 (SQLAlchemy 2.0 + Alembic).** The
> *reasoning* — schema and migrations from a typed source, but hand-written SQL for the two
> queries that decide whether the product feels fast — is language-independent and still holds.

**Decision (historical — the toolkit was replaced by ADR-0016).** Drizzle for schema definition,
migrations, and ordinary CRUD. The availability query and the occupancy insert are hand-written
SQL because they use `tstzrange`, GiST indexes, `generate_series`, and `ON CONFLICT` semantics
that no ORM expresses well.

**Why.** Type-safe schema and migrations without an ORM's opinion on the two queries that decide
whether the product feels fast, and no runtime query-builder cost. **That reasoning is
language-independent and is exactly what ADR-0016 carries forward** — only the library changed.

**Alternatives.** Prisma (heavier client, historically weaker on Postgres range types and raw SQL typing);
raw `pg` (loses migration and type safety).

**Exit criteria.** Revisit if migration ergonomics become a bottleneck.

---

### ADR-0010 — Config-as-code for Vapi and n8n; CI is the only deployer

**Decision.** `platform/vapi/*.json` and `platform/n8n/workflows/*.json` are the source of truth. A deploy
script diffs local against remote and applies. MCP servers and dashboards are for **authoring against the
dev environment only**. Production API tokens exist only in CI secrets.

**Why.** I9, and the design brief §20.3 already states it. An LLM or a human silently mutating the assistant
answering a client's phone is not an acceptable deployment model. Config-as-code also makes prompt changes
reviewable and revertable — a prompt edit is a deploy and deserves the same treatment.

**Exit criteria.** None.

---

### ADR-0011 — Business rules are pure functions in `grace_domain`

**Decision.** The 48-hour change-fee engine, member vs non-member pricing, deposit calculation, buffer
application, medical-screen gating, and slot ranking are pure functions taking explicit inputs
(including "now") and returning explicit decisions with a machine-readable `reason`. They perform no I/O
and read no clock.

**Why.** F4 and I4. Passing `now` explicitly makes every boundary case — 47h59m, DST transitions,
midnight, the holiday calendar — a unit test rather than a production incident. Returning a `reason`
code means the SMS, the staff task, the transcript annotation and the dispute-defence log all quote the
same explanation.

**Exit criteria.** None.

---

### ADR-0012 — Deadline propagation with graceful degradation

**Decision.** Every tool request carries a deadline. Handlers race their work against it. On expiry the
handler returns a valid, natural-sounding `result` string that moves the conversation forward
("Let me get someone who can pull that up for you") and emits a `tool.deadline_exceeded` metric.

**Why.** I10. A timeout at the Vapi layer produces dead air and then an awkward recovery; a fast graceful
answer produces a call that still ends well. The failure is logged and alerted regardless — degradation
is visible to us, not to the caller.

> ⚠️ **The deadline is NOT the p95 target.** The deadline is `GRACE_TOOL_DEADLINE_MS` (2500ms). The
> per-tool numbers in §5 below and in [03-vapi-layer](03-vapi-layer.md) §4 are **p95 latency targets** — by definition ~5% of calls
> exceed them. [core-api](../reference/core-api.md) §6.4 currently races handlers against the per-tool budget, which would fire the
> graceful-fallback sentence on one call in twenty *by construction*. Budgets drive alerting; the
> deadline drives degradation. Corrected 2026-08-03; see [03-vapi-layer](03-vapi-layer.md) §12 correction #12.

**Exit criteria.** None.

---

### ADR-0013 — One n8n Cloud instance; invariant I9 relaxed to "CI is the only publisher"

**Status.** Accepted 2026-08-03. Supersedes the two-instance assumption in the original [04-n8n-layer](04-n8n-layer.md) §4.2.

**Context.** I9 says *"no agent, MCP server, or human edits production directly"*, and was to be enforced
structurally: a dev n8n on `:5679` for authoring, a prod n8n whose API key existed only in CI. We have a
single n8n Cloud pay-as-you-go subscription. Separate environments and Git source control are
higher-tier features. A second self-hosted instance was considered and rejected as operational overhead
disproportionate to a single-tenant pilot.

**Decision.** Run one instance. Separate dev from prod by **tag** (`env:dev` / `env:prod`, plus
`managed:git`), **name prefix** (`[dev] ` / `[prod] `), **webhook path prefix**, and **per-environment
credentials**. `deploy.py` filters on the tag pair and refuses to touch anything lacking it. CI holds the
only production API key and is the only publisher.

**What this costs us, stated plainly** — the enforcement is convention plus detection, not permission:

1. **API keys cannot be scoped below Enterprise.** Verified on the live instance: one key carries
   `workflow:create/update/delete/publish` and credential access across everything. Dev and prod are
   indistinguishable to the API. **Unmitigable on this tier.**
2. **The n8n MCP server exposes `publish_workflow`**, and its `search_workflows` returns every workflow
   regardless of the per-workflow "Available in MCP" opt-in. An agent with MCP access has a live path to
   production.
3. **Detection replaces prevention.** An hourly job diffs deployed workflows against git; any drift is a
   P2 alert. On lower Cloud tiers, execution retention and workflow history are short enough that **git
   is the only durable audit trail** — which makes that job load-bearing, not optional.
4. **Shared quota.** Concurrency and execution retention are shared between dev and prod. A dev test loop
   can starve production.

**Why accept it.** The alternative — blocking all n8n work until a tier upgrade — stops the only
orchestration work that is currently unblocked, while Vagaro, RingCentral, Stripe and Google remain
inaccessible. The exposure is bounded: a single-tenant pilot, no PHI in n8n (I6 keeps it out), and no
payment authority ([05-security-and-compliance](05-security-and-compliance.md) §18).

**Exit criteria.** Move to true two-instance environments when **either** the account reaches a tier with
environments/source-control, **or** a second client shares the instance. Whichever comes first.

---

### ADR-0014 — Python, not TypeScript. Supersedes ADR-0001.

**Status.** Accepted 2026-08-03, replacing ADR-0001's language choice. The monorepo,
config-as-code and CI-only-deploy parts of ADR-0001 stand unchanged.

**Context.** ADR-0001 chose TypeScript and dismissed Python in a single line — *"better ML
ecosystem, irrelevant here — no model training"* — which is not an argument against Python
for an API service. Its own exit criteria named the condition that has now been met: *"the
team composition changes to Python-primary."*

The decision was never put to the client; it was inherited and built upon.

**Decision.** Python 3.12+, Pydantic v2, httpx, pytest, ruff, mypy strict. `uv` for
environments. The browser web-call harness stays in JavaScript because it runs in a
browser; n8n Code nodes stay JavaScript because n8n runs them.

**Why the case for the replaced language was weaker than it looked.** The strongest argument was the
generate-everything-from-one-schema pipeline — tool definitions, prompt table and runtime
validation all derived from one source, so they cannot drift. **Pydantic does this
identically** via `model_json_schema()`. That is parity, not an advantage. The remaining
arguments (browser SDK, n8n Code nodes) cover ~60 lines and are unaffected by the language
of everything else.

**What actually decided it.** What the team can maintain. A system the people who own it
can debug at 2am beats a marginally more elegant one they cannot. Every other consideration
here was close enough to be noise.

**Cost, and why now.** 3,232 lines ported in one session; 14 of 20 plan documents mention
Node-stack specifics. After Core API is built the same switch is 15,000+ lines against
working code. This was the cheapest moment it would ever be, by a wide margin.

**Verified at the port boundary.** The Python implementation was pointed at the *same* live
Vapi assistant that the replaced implementation had deployed:

- generated tool JSON differs only where deliberately improved (portable regex, wording)
- `deploy --apply` then `--diff` reports **zero drift** on the same assistant id
- the n8n linter catches the same five injected defects
- the mock server returns byte-identical spoken output
- all 14 speech tests pass unchanged

**Three defects the port surfaced**, none of which existed in the replaced version:

1. Pydantic uses the **class docstring** as a schema `description`, so internal
   implementation notes were being sent to the model as instructions. The generator now
   strips them, and the validator fails if any reappear.
2. Pydantic hoists enums into `$defs` and references them; Vapi has no `$ref` resolver.
   The generator inlines them.
3. Python distinguishes `1` from `1.0`; JSON does not. Vapi echoes `1`, our config said
   `1.0`, and the drift check went permanently red on the first run. Integral floats are
   now collapsed before comparison.

**Exit criteria.** Revisit if the team becomes JavaScript-primary, or if a required Vapi or
n8n capability ships as a JS-only SDK with no REST equivalent.

---

> **ADR-0015 to ADR-0018 exist because of ADR-0014.** The port moved the code that exists, but
> this document set describes a much larger system that is not built yet — Core API, background
> workers, the database — and it named the replaced stack's libraries throughout. Rewriting those
> documents in Python means naming the Python equivalent. For most things that is a
> find-and-replace. For these four it is a real decision, and leaving one unmade would mean
> rewriting a document with a hole in it.
>
> Three are library choices. **The fourth is a safety guarantee that would otherwise be lost
> silently.**

---

### ADR-0015 — Job queue: arq. Replaces BullMQ.

**Status.** Accepted 2026-08-04, consequent on ADR-0014.

**What it is for.** When Grace books an appointment, sending the confirmation text must not make
the caller wait. The tool handler writes an outbox row and returns; a worker sends the text
moments later. That worker needs a queue.

**Decision.** **arq** — Redis-backed, async-native, with scheduled and delayed jobs.

**Why this is a decision and not a rename.** ADR-0005's outbox design leans on one specific
behaviour of the replaced queue: **enqueuing the same `jobId` twice runs the job once.** That is
what stops a caller receiving two confirmation texts when a dispatcher retries after a crash.
[booking-write-path](../reference/booking-write-path.md) states the guarantee explicitly —
`jobId = outbox_events.id`, and *"the queue dedupes on jobId."*

Python's queues do not all provide this identically:

| Option | Why not |
|---|---|
| **Celery** | Heavier, sync-first, and its dedupe story is an add-on rather than a primitive |
| **Dramatiq** | Clean, but scheduling and delayed jobs need an extension |
| **SAQ** | Very close to arq; smaller community |
| **Postgres `LISTEN/NOTIFY` + a jobs table** | No new dependency, and dedupe becomes a `UNIQUE` index we control. Genuinely viable — the fallback if arq disappoints |

arq keeps Redis, which is already in the topology for caching and locks, and its API is the
closest analogue to what [booking-write-path](../reference/booking-write-path.md) already describes.

⚠️ **The dedupe guarantee must be re-derived against arq, not assumed.** arq deduplicates by
`job_id` within a keep-alive window, which is *not* the same lifetime guarantee the replaced
queue gave. If
the window proves too short, the answer is a `UNIQUE` constraint on the consumer side — which
[booking-write-path](../reference/booking-write-path.md) §3 already requires anyway, because delivery is at-least-once regardless.

**Exit criteria.** Revisit if arq's dedupe window cannot be reconciled with the outbox
retry schedule, or if the worker fleet outgrows a single Redis.

---

### ADR-0016 — Database toolkit: SQLAlchemy 2.0 + Alembic. Supersedes ADR-0009.

**Status.** Accepted 2026-08-04, replacing ADR-0009's choice of Drizzle.

**What it is for.** Defining tables, generating migrations, and ordinary reads and writes.

**Decision.** **SQLAlchemy 2.0** with **Alembic** for migrations. The two hot-path queries stay
hand-written SQL, exactly as ADR-0009 intended — that reasoning was language-independent and
still holds.

**Why this is a decision and not a rename.** Double-booking is not prevented by application
logic. It is prevented by a Postgres `EXCLUDE` constraint over a `tstzrange` with a GiST index,
which makes two overlapping active rows for one provider **physically impossible to insert**
(ADR-0004). That is the strongest guarantee in the system and everything else assumes it.

SQLAlchemy 2.0 expresses it via `postgresql.ExcludeConstraint`, and Alembic can autogenerate it.
Both were verified as capable before this ADR was written — but the constraint is load-bearing
enough that it is named here rather than assumed.

**Alternatives.** Raw `asyncpg` with hand-written migrations (maximum control, loses schema
typing and migration ergonomics). SQLModel (thin layer over SQLAlchemy; adds a dependency
without removing the need to understand SQLAlchemy underneath).

**Exit criteria.** Revisit if Alembic autogeneration proves unable to round-trip the exclusion
constraint or the GiST index, in which case those migrations become hand-written.

---

### ADR-0017 — Web framework: FastAPI. Replaces Fastify.

**Status.** Accepted 2026-08-04, consequent on ADR-0014.

**What it is for.** Serving the Vapi tool endpoint and the webhooks — the hot path.

**Decision.** **FastAPI** on **uvicorn**, with Pydantic models already defined in
`grace_contracts` reused directly as request models.

**Why this is a decision and not a rename.** [core-api](../reference/core-api.md) does not merely say "a web framework" — it
specifies an exact execution order: capture the raw body, verify the signature, resolve the
tenant, open the deadline, check idempotency, then dispatch. The replaced framework enforced
that through ordered plugin registration with encapsulation. FastAPI has no equivalent construct:

| Replaced framework | FastAPI |
|---|---|
| Ordered plugin registration | Middleware stack (outermost first) + `Depends` (per-route) |
| `AsyncLocalStorage` for request context | `contextvars` |
| Plugin encapsulation scoping | Explicit router inclusion with dependencies |

The distinction matters because signature verification needs the **raw** body before parsing,
and the deadline must start before any handler work. In FastAPI that means middleware for the
first two, dependencies for the rest — a different shape, so [core-api](../reference/core-api.md) §3 and §6 are rewritten rather
than renamed.

**Exit criteria.** None foreseen. Revisit only if per-request overhead measurably threatens the
p95 budget, which at this scale it will not.

---

### ADR-0018 — Import boundaries: import-linter. Replaces the ESLint boundary rules.

**Status.** Accepted 2026-08-04, consequent on ADR-0014.

**What it is for.** Making it **impossible to accidentally call Vagaro, Stripe, Twilio or Google
from the code path where a caller is waiting on the line.** That is invariant I1, and it is the
difference between a fast answer and dead air.

**Decision.** **import-linter** contracts, run in CI.

**Why this is a decision and not a rename.** The boundary rules that the replaced linter
provided, defined in [02-python-and-repo](02-python-and-repo.md), were not a style
preference — they were a mechanical control enforcing the dependency rule in §2 and invariant
I1. **ruff cannot express them.** ruff's `flake8-tidy-imports` can ban a module globally, but not
"this package may not import that package" per-layer, which is what the architecture needs.

Without a replacement the protection disappears **silently** — no error, no warning, just a
guarantee that quietly stopped being enforced. That is the worst kind of regression, and it is
why this warrants an ADR rather than a line in the tooling doc.

```ini
; TARGET — .importlinter
[importlinter]
root_packages = grace_contracts, grace_domain, grace_db, grace_adapters, grace_api

[importlinter:contract:1]
name = contracts depends on nothing
type = forbidden
source_modules = grace_contracts
forbidden_modules = grace_domain, grace_db, grace_adapters, grace_api

[importlinter:contract:2]
name = domain is pure — no I/O
type = forbidden
source_modules = grace_domain
forbidden_modules = grace_db, grace_adapters, httpx, asyncpg, redis

[importlinter:contract:3]
name = I1 — the hot path cannot reach a third party
type = forbidden
source_modules = grace_api.routes.vapi.handlers
forbidden_modules = grace_adapters
```

Restores AC-02.3 and AC-04.10, which were unenforceable after the port.

**Exit criteria.** None. Cost is one CI step; the guarantee is load-bearing.

---

## 5. Quality attribute targets

These are the numbers the architecture is designed to hit. [observability](../reference/observability.md) defines how they are measured and alerted.

| Attribute | Target | Measured by |
|---|---|---|
| Tool latency (read tools) | p50 ≤ 120ms · p95 ≤ 400ms · p99 ≤ 800ms | Core API histogram, excludes network |
| Tool latency (`createBooking`) | p95 ≤ 600ms · p99 ≤ 1200ms | as above |
| Perceived turn latency | ≤ 900ms p95 | Vapi call analytics |
| Core API availability | 99.9% monthly (≈43 min) | Uptime probe on `/healthz` |
| Booking durability | Zero lost confirmed bookings | Outbox dead-letter = 0; nightly reconciliation |
| Double-booking rate | Exactly zero | DB constraint + nightly integrity report |
| Concurrent calls supported | 25 sustained, 50 burst | Load test [07-testing](07-testing.md) §6 |
| Mirror staleness | p95 < 30s · worst case < 10 min | `mirror_lag_seconds` gauge |
| Outbox dispatch lag | p95 < 2s | `outbox_lag_seconds` gauge |
| RTO / RPO | 30 min / 5 min | PITR + restore drill [infrastructure](../reference/infrastructure.md) §8 |

**Sizing note.** At the design brief's ~45 calls/day the real concurrency is 2–3. The 25/50 target exists
so that (a) a marketing spike or a Groupon promotion does not degrade the phone line, and (b) tenant #5
does not require an architecture change. It costs nothing to hit at this scale — it is a consequence of
local reads and connection pooling, not of extra infrastructure.

---

## 6. What is deliberately NOT in this architecture

Stating these prevents well-intentioned scope creep.

| Excluded | Why |
|---|---|
| Voice biometrics / speaker ID | BIPA. Invariant, not a preference ([05-security-and-compliance](05-security-and-compliance.md) §3). |
| Card capture by voice | PCI scope explosion (I5). |
| Storing medical detail | PHI minimization (I6). |
| A custom STT/TTS/LLM stack | Vapi's managed pipeline is better than we would build and is not the differentiator. |
| Kubernetes | Two services and two workers at this scale. Docker Compose on a VPS, with a documented ECS path ([infrastructure](../reference/infrastructure.md) §7). |
| An event bus (Kafka/NATS) | Outbox + arq is sufficient to ≥100× current volume. |
| A separate microservice per tool | 15 tools sharing one database and one domain model. Distribution would add latency and failure modes for no benefit. |
| Real-time staff UI in Phase A–D | SMS and email cover it. A dashboard is Phase F. |
| LLM-generated SQL or dynamic queries | Injection and non-determinism on a money path. |

---

## 7. Glossary

| Term | Meaning in this codebase |
|---|---|
| **Tenant** | One business using Grace. PalmLeaf is tenant one. |
| **Mirror** | The local Postgres projection of the PMS calendar. |
| **Occupancy** | Any row in `calendar_occupancy`; a reason a provider's time is not free. |
| **Hold** | Short-TTL occupancy created during a call while the caller decides. |
| **Reservation** | Occupancy promoted after the caller accepts, pending deposit/write-back. |
| **Track A/B/C/D** | Write-path strategies (calendar bridge / widget automation / self-serve link / staff queue). |
| **Hot path** | Synchronous request while a caller waits. |
| **Cold path** | Asynchronous work after the response is sent. |
| **Outbox** | Table of pending side effects committed with the business transaction. |
| **Port / Adapter** | Interface in `contracts` / implementation in `adapters`. |
| **Saga** | The multi-step booking transaction with compensations. |

---

## 8. Acceptance criteria

An architecture document cannot be tested by running it. What *can* be tested is whether the
code still obeys it — so every criterion here is a CI check, not a review opinion.

✅ **AC-01.1** — `import-linter` runs in CI with the three contracts in ADR-0018, and fails the
build when `grace_domain` imports `httpx`, `asyncpg` or `redis`, or when
`grace_api.routes.vapi.handlers` imports `grace_adapters`. This is invariant **I1** made
mechanical; without it the guarantee is only a convention.

✅ **AC-01.2** — `grace_contracts` imports nothing from any other first-party package. Verified
by contract 1, not by inspection.

✅ **AC-01.3** — Every ADR in §4 carries a status, a decision, the alternatives that were real,
and exit criteria. An ADR without exit criteria is dogma; `docs-lint` cannot judge prose, so
this is a review gate at merge time.

✅ **AC-01.4** — Every superseded ADR (0001, 0009) keeps its original text under a superseding
banner rather than being edited in place, so the reasoning that survived is visibly separated
from the choice that did not.

✅ **AC-01.5** — Every quality-attribute target in §5 names a measurement source in
[observability](../reference/observability.md). A target nobody measures is an aspiration.

## 9. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-01.1** | Does arq's `job_id` dedupe window actually cover the outbox retry schedule? | ADR-0015 accepts arq as the replacement queue, but its window is a keep-alive, not a lifetime guarantee. The fallback — a `UNIQUE` constraint on the consumer side — is already required by at-least-once delivery, so the exposure is bounded. **Re-derive it when the outbox is built; do not assume it.** | Engineering, at Phase C |
| **Q-01.2** | Can Alembic round-trip the `EXCLUDE … USING gist` constraint and the `btree_gist` extension? | ADR-0016 asserts it can, verified against documentation rather than a running migration. If autogeneration cannot express it, those migrations become hand-written — a small cost, but one to discover before the schema lands. | Engineering, at Phase A |
| **Q-01.3** | Is the multi-tenant assumption (A-01, force F6) right for this engagement? | The entire data model carries `tenant_id` on the premise that PalmLeaf is tenant one of a service. If it is genuinely a one-off, the scaffolding is inert and harmless — but nobody has confirmed which it is. | Client / commercial |
| **Q-01.4** | Does ADR-0013's "detection replaces prevention" stay acceptable as the client's team grows? | One n8n Cloud instance means API keys cannot be scoped below Enterprise, so dev and prod are indistinguishable to the API. Defensible for a single-tenant pilot; not once a second person holds a token. | Revisit at tier upgrade or client #2 |
