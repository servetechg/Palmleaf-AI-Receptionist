# 15 — Implementation Roadmap

**This document is the work.** Execute tasks in order. Each task states what to read, what to build,
and how you know it is done.

**Task ID format:** `<PHASE>-<NN>`. Reference the ID in the commit footer (`Task: B-04`).
**Effort:** `S` ≈ half a day · `M` ≈ 1–2 days · `L` ≈ 3–5 days. Assumes one focused implementer.
**⛔** marks a task blocked on an external answer — see [17-open-decisions.md](17-open-decisions.md).
**🔓** marks a task with no external dependency — always safe to start.

---

## Phase overview

| Phase | Theme | External dependency | Calendar |
|---|---|---|---|
| **A** | Foundation | none 🔓 | Week 1 |
| **B** | Core domain & API | none 🔓 | Weeks 1–3 |
| **C** | Integration & orchestration | Vapi, Google, Stripe, Twilio accounts | Weeks 3–5 |
| **D** | Telephony & pilot | carrier + client sign-off | Weeks 5–7 |
| **E** | Write-path hardening | ⛔ Vagaro answer | Weeks 6–9 |
| **F** | Scale & optimise | — | Week 10+ |

> **Phases A and B are ~3 weeks of work with zero external dependencies.** Start them the same day the
> Vagaro and 10DLC clocks start (`Docs/PalmLeaf_Outreach_Package.md` Part 3). The waiting period costs
> nothing if sequenced this way.

---

# PHASE A — Foundation

*Goal: a clean clone builds, tests, migrates, and runs. Nothing business-specific yet.*

---

### A-01 🔓 Repository scaffold — `S`
**Read:** [02](02-repository-and-tooling.md)

1. `git init`, Node 22 via `.nvmrc`, corepack + pnpm 9.
2. Create the full directory tree from §02 §1 with placeholder `package.json` + `README.md` per package.
3. `pnpm-workspace.yaml`, `turbo.json`, `tsconfig.base.json` (verbatim from §02 §3), root `package.json`
   scripts (§02 §7).
4. `.gitignore` (must include `.env*`, `!.env.example`, `dist`, `node_modules`, `coverage`, `.turbo`).
5. `LICENSE`, `README.md` skeleton, `CODEOWNERS`.

✅ **AC:** `pnpm install && pnpm build` succeeds on a clean clone.
`Task: A-01` · `chore(repo): scaffold monorepo`

---

### A-02 🔓 Tooling and boundary enforcement — `M`
**Read:** [02](02-repository-and-tooling.md) §5, §6

1. Prettier 3, ESLint 9 flat config with `typescript-eslint` strict-type-checked.
2. **The boundary rules from §02 §6, verbatim.** These are the architecture's immune system.
3. `dependency-cruiser` config encoding the package graph in §02 §1.1.
4. commitlint + lefthook (pre-commit format/lint, pre-push typecheck/unit).
5. Vitest root config with coverage thresholds (domain 95%, rest 75%).

✅ **AC-02.3:** Write a throwaway file importing `@grace/db` from `packages/domain` — `pnpm lint` fails
with the ADR-0011 message. Revert. Repeat for the handler→adapters rule (I1) and contracts→anything.
`Task: A-02` · `chore(ci): add lint, boundary rules, and commit hooks`

---

### A-03 🔓 `@grace/config` — `S`
**Read:** [02](02-repository-and-tooling.md) §8

1. Zod schemas: `BaseEnv`, `CoreApiEnv`, `WorkerEnv`, `BookingWorkerEnv`.
2. `loadConfig()` — parse once at startup, throw a readable aggregate error naming every missing
   or invalid variable.
3. `.env.example` with every variable, a placeholder, and a one-line comment.
4. `scripts/bootstrap-env.ts` — generates `.env.local` with random dev secrets.

✅ **AC-02.4:** Removing `GRACE_DATABASE_URL` fails startup with a message naming it.
`Task: A-03` · `feat(config): zod-validated environment loading`

---

### A-04 🔓 `@grace/observability` — `M`
**Read:** [12](12-observability-and-slo.md) §2, §3, §4; [11](11-security-and-compliance.md) §7.3

1. Pino logger with the redaction path list (§11 §7.3) and base fields.
2. `AsyncLocalStorage` request context: `requestId`, `tenantId`, `vapiCallId`, `toolName`, `traceId`.
3. `prom-client` registry + the metric definitions from §12 §3 (register them all now; they will be
   incremented as features land).
4. OpenTelemetry NodeSDK with OTLP exporter, auto-instrumentation for http/pg/ioredis.
5. Sentry init behind a config flag.

✅ **AC:** A log line emitted inside a context carries all correlation fields; a phone number passed in a
log object is masked.
`Task: A-04` · `feat(observability): logging, metrics, tracing foundation`

---

### A-05 🔓 Local stack — `S`
**Read:** [14](14-infrastructure-and-deployment.md) §4

`infra/docker/compose.dev.yml`: Postgres 16 (with `btree_gist` available), Redis 7, n8n-dev on 5679,
optional Mailhog. Named volumes, healthchecks, sane resource limits.

✅ **AC-02.2:** `pnpm stack:up` → all healthy; `psql` connects.
`Task: A-05` · `chore(infra): local docker compose stack`

---

### A-06 🔓 Database schema and migrations — `L`
**Read:** [03](03-data-model.md) — **all of it**

1. Drizzle schema files under `packages/db/src/schema/`, one per group (tenancy, catalog, schedule,
   occupancy, customers, mirror, bookings, calls, messaging, knowledge, ops).
2. Migrations 0001–0014 exactly as specified. **Hand-write the parts drizzle-kit cannot express:**
   the `EXCLUDE` constraint, the partial indexes, the RLS policies, the roles, `business_hours_for_date`.
3. Migration 0015 `inbound_webhooks` (§04 §9.1), 0016 `business_hours_for_date`, 0017 occupancy
   `metadata jsonb` for `publicId`, 0018 `reconciliation_reports`.
4. `client.ts` with the pool and `withTenant()` (§03 §14).
5. The `booking_events` trigger enforcing that `bookings.state` never changes without an event row.

✅ **AC-03.1 → AC-03.8** — all eight. In particular prove AC-03.2 (exclusion violation) and AC-03.4 (RLS)
with real tests before moving on. These two constraints are the foundation everything else assumes.
`Task: A-06` · `feat(db): complete schema, constraints, and RLS`

---

### A-07 🔓 Seeds — `M`
**Read:** [03](03-data-model.md) §15

Implement seed files 00–06 and 99. PalmLeaf's known facts go in as approved; everything contested
(policies, prices, roster, greeting variants) goes in with `approved_at = NULL`.

✅ **AC-03.7:** seeds run twice, no duplicates. A query for approved services returns zero rows until
sign-off — and that is correct.
`Task: A-07` · `feat(db): seed data with approval gating`

---

### A-08 🔓 CI pipeline — `M`
**Read:** [13](13-testing-strategy.md) §9; [14](14-infrastructure-and-deployment.md) §6

`.github/workflows/ci.yml` with the stages in §13 §9, including the timezone matrix and gitleaks.

✅ **AC-02.5** + pipeline under 8 minutes.
`Task: A-08` · `ci: pull request pipeline`

---

### A-09 🔓 `@grace/testing` — `M`
**Read:** [13](13-testing-strategy.md) §10; [05](05-provider-adapters.md) §8

Testcontainers helpers (Postgres + Redis, migrations, seeds, per-test rollback), fixture builders,
frozen `Clock`, and the four port fakes as stubs (behaviour lands in Phase C).

✅ **AC:** An integration test can spin up a database, seed it, and assert in under 5 seconds warm.
`Task: A-09` · `feat(testing): testcontainers harness and fixtures`

---

**🚩 Phase A gate:** clean clone → `pnpm install && pnpm check && pnpm stack:up && pnpm db:migrate && pnpm db:seed`
all green, CI passing, boundary rules proven to bite.

---

# PHASE B — Core domain and API

*Goal: Grace's brain works, is fast, and is provably correct — without a single external credential.*

---

### B-01 🔓 `@grace/contracts` — tool schemas — `L`
**Read:** [02](02-repository-and-tooling.md) §4; [08](08-vapi-layer.md) §4

1. Zod input/output schema per tool — all 13. Invest real effort in `.describe()` text; it is prompt
   engineering (§02 §4).
2. `errors.ts` — the full taxonomy from §04 §7.
3. Port interfaces (§05) — `PmsPort`, `CalendarPort`, `PaymentsPort`, `MessagingPort`, `VoicePort`,
   plus `PmsCapabilities`.
4. Webhook payload schemas (Vapi, Vagaro, Stripe, Twilio).
5. Outbox event payload schemas, discriminated on `event_type`.
6. `generate-tools.ts` → JSON Schema files in `platform/vapi/tools/`.

✅ **AC-05.1** · **AC-08.2** (drift check fails when generated output is not committed).
`Task: B-01` · `feat(contracts): tool schemas, ports, and error taxonomy`

---

### B-02 🔓 `@grace/domain` — time and policy — `L`
**Read:** [07](07-booking-write-path.md) §6; [01](01-architecture-foundation.md) ADR-0011

1. `time/` — business-hours arithmetic, tenant-timezone helpers, DST-safe day math. All take `now`.
2. `policy/change-fee.ts` — `evaluateChange` (§07 §6).
3. `policy/deposit.ts` — flat vs percent resolution.
4. `pricing/resolve.ts` — member/non-member, provider override, unapproved → throw.
5. `screening/medical.ts` — the gate decision.

✅ **AC-07.9** plus the §13 §2 unit table. Domain coverage ≥95%. Suite passes under both timezones.
`Task: B-02` · `feat(domain): policy, pricing, and time engines`

---

### B-03 🔓 Availability query — `L`
**Read:** [06](06-availability-engine.md) §2, §3

1. `business_hours_for_date` SQL function.
2. The free-slot query as a parameterised, hand-written SQL file, wrapped by a typed repository method.
3. Resource/room variant.

✅ **AC-06.1 → AC-06.5**, **AC-06.12**, and integration tests **I-3, I-4, I-5** (including the EXPLAIN
assertion — a seq-scan regression must fail CI).
`Task: B-03` · `feat(availability): free-slot query with GiST anti-join`

---

### B-04 🔓 Slot ranking — `M`
**Read:** [06](06-availability-engine.md) §4

`rankSlots` with the scoring table and the diversification rule. Pure. Property-tested.

✅ Output ⊆ input; never exceeds `max`; never two slots <45 min apart from the same provider; explicit
provider request always wins when available.
`Task: B-04` · `feat(availability): slot ranking and diversification`

---

### B-05 🔓 Occupancy repository and holds — `L`
**Read:** [06](06-availability-engine.md) §5, §6, §8

1. `placeHolds` with per-slot savepoints and `23P01` translation to `SlotNoLongerAvailableError`.
2. Public slot ids (§06 §5.1) + the `(providerName, startsAt)` fallback matcher.
3. Hold → reservation → appointment promotion, each state-guarded.
4. Release, expire, and the sweeper query.

✅ **AC-06.6**, **AC-06.7**, integration tests **I-1, I-6, I-11**.
`Task: B-05` · `feat(availability): occupancy repository, holds, and promotion`

---

### B-06 🔓 Outbox — `M`
**Read:** [07](07-booking-write-path.md) §3

`emit(tx, events)` (transaction-only), the dispatcher query with `FOR UPDATE SKIP LOCKED`, backoff,
stale-lock reclaim, dead-lettering. Dispatcher lives in `sync-worker` but the repository is in `db`.

✅ **AC-07.1**, **AC-07.2**, integration tests **I-9, I-10**.
`Task: B-06` · `feat(outbox): transactional outbox and dispatcher`

---

### B-07 🔓 Booking state machine — `M`
**Read:** [07](07-booking-write-path.md) §4

Transition table, `assertTransition`, the single `transitionBooking()` function that asserts, bumps
`version`, writes `booking_events`, and emits the transition's outbox events (§07 §4.3).

✅ **AC-07.3**, **AC-07.4**.
`Task: B-07` · `feat(booking): saga state machine`

---

### B-08 🔓 Core API skeleton — `L`
**Read:** [04](04-core-api-service.md) §3, §4, §5, §6

`buildApp()`, plugin chain in order, the single `/vapi/tools` route with dispatch and batch support,
health endpoints, graceful shutdown.

✅ **AC-04.1 → AC-04.3**, **AC-04.6**, **AC-04.9**, **AC-04.10**.
`Task: B-08` · `feat(core-api): server skeleton and middleware chain`

---

### B-09 🔓 Idempotency and deadline middleware — `M`
**Read:** [04](04-core-api-service.md) §6.3, §6.4; [06](06-availability-engine.md) §7

✅ **AC-04.4**, **AC-04.5**, **AC-06.8**, **AC-06.11**, integration tests **I-7, I-8**.
`Task: B-09` · `feat(core-api): idempotency and deadline middleware`

---

### B-10 🔓 Read tools 1–4 — `L`
**Read:** [04](04-core-api-service.md) §8; [08](08-vapi-layer.md) §4

`getBusinessInfo`, `lookupCustomer`, `getServicesAndPricing`, `checkAvailability`. Approved-data-only
enforcement throughout. Formatters with snapshot tests.

✅ Each within budget on seeded data. **AC-11.5** (`lookupCustomer` cannot query another number).
`Task: B-10` · `feat(tools): business info, customer lookup, pricing, availability`

---

### B-11 🔓 Write tools 5–7 — `L`
**Read:** [06](06-availability-engine.md) §6; [07](07-booking-write-path.md) §4, §6

`createBooking`, `rescheduleAppointment`, `cancelAppointment` — the full transaction from §06 §6,
outbox emission, 48-hour engine, `consent_log` capture on in-window changes.

✅ **AC-07.10**, e2e **E-1, E-2, E-8, E-9, E-10**.
`Task: B-11` · `feat(tools): booking, reschedule, and cancel`

---

### B-12 🔓 Tools 8–13 — `M`
`sendIntakeForm`, `sendDepositLink`, `sendBookingConfirmation` (async, outbox-only), `transferToHuman`,
`takeMessage`, `flagMedicalHold`.

✅ **AC-04.7**, e2e **E-11**. `flagMedicalHold` persists a boolean and nothing else.
`Task: B-12` · `feat(tools): messaging, transfer, message-taking, medical hold`

---

### B-13 🔓 Redaction — `M`
**Read:** [11](11-security-and-compliance.md) §4.1

`redactTranscript` with the five classes, sentence-scoped health redaction, the lexicon file, hit
metrics, and the card-detection alert counter.

✅ **AC-11.3**, **AC-11.4**. Fixture corpus including near-miss card numbers and realistic health phrasings.
`Task: B-13` · `feat(compliance): transcript and summary redaction`

---

### B-14 🔓 Load and contention testing — `M`
**Read:** [13](13-testing-strategy.md) §6

k6 scripts for all five profiles. Seed 100k occupancy rows.

✅ **AC-06.9**, **AC-13.4** — the contention profile is the one that matters: 50 callers, 10 slots,
exactly 10 bookings, zero doubles.
`Task: B-14` · `test(load): k6 profiles including slot contention`

---

**🚩 Phase B gate:** all 13 tools respond correctly and within budget against seeded data, with no network
access. The contention test passes. Domain coverage ≥95%.
**At this point the product's brain is complete and provably correct.** Everything after this is plumbing
to the outside world.

---

# PHASE C — Integration and orchestration

*Needs: Vapi account, Google Cloud project, Stripe account, Twilio account. Not Vagaro.*

---

### C-01 🔓 Port fakes — `M`
**Read:** [05](05-provider-adapters.md) §8

Full stateful fakes for all four ports with injectable latency, failure rates, and capability flags.

✅ **AC-05.5** (contract suite green against fakes), e2e **E-6** setup.
`Task: C-01` · `feat(testing): stateful port fakes`

---

### C-02 🔓 Resilient client — `M`
**Read:** [05](05-provider-adapters.md) §2

Shared retry / circuit breaker / timeout / instrumentation / Redis token bucket.

✅ **AC-05.2**, **AC-05.3**, **AC-05.4**.
`Task: C-02` · `feat(adapters): resilient HTTP client foundation`

---

### C-03 ⛔ Vagaro adapter (read-only) — `L`
**Blocked by:** GATE-01 (credentials). **Build against cassettes/fake first; wire live when creds land.**
**Read:** [05](05-provider-adapters.md) §3

OAuth with single-flight refresh, read methods, Zod-validated responses, mappers, `capabilities`
object with `writeAppointments: false`, `unsupported.ts` for write methods.

✅ **AC-05.7** — flipping the capability flag on the fake switches the saga path with no other change.
`Task: C-03` · `feat(adapters): vagaro read-only PMS adapter`

---

### C-04 🔓 Twilio messaging adapter — `M`
**Read:** [05](05-provider-adapters.md) §6; [10](10-telephony-and-messaging.md) §4.2

Adapter with opt-out enforcement, consent checks, STOP/HELP footer, segment warning, status callbacks.
Templates seeded and rendered.

✅ **AC-05.6**, **AC-10.7**, **AC-10.8**.
`Task: C-04` · `feat(adapters): twilio messaging with TCPA enforcement`

---

### C-05 🔓 Stripe adapter + payment webhook — `M`
**Read:** [05](05-provider-adapters.md) §5; [04](04-core-api-service.md) §9.2

Hosted payment links with idempotency keys, status lookup, refunds, signature-verified webhook mapping
to booking transitions.

✅ e2e **E-1** (deposit paid → CONFIRMED), **E-3** (unpaid → EXPIRED).
`Task: C-05` · `feat(payments): stripe deposit links and webhook handling`

---

### C-06 🔓 `sync-worker` — `L`
**Read:** [07](07-booking-write-path.md) §3.3; [06](06-availability-engine.md) §8, §9

BullMQ setup, outbox dispatcher, hold sweeper (30s), and processors for `sms.send`,
`payments.create_deposit_link`, `staff.notify`, `call.process_transcript`, `mirror.apply_webhook`.
Every processor idempotent on the outbox id.

✅ Integration **I-10, I-11**; e2e **E-14, E-15**.
`Task: C-06` · `feat(worker): sync-worker with outbox processors`

---

### C-07 ⛔ Google Calendar adapter (Track A) — `M`
**Blocked by:** GATE-07 (the 30-minute validation test) **and** Google credentials.
**Read:** [05](05-provider-adapters.md) §4; [07](07-booking-write-path.md) §5.1

Deterministic event ids, extended properties, watch channels + renewal cron, incremental sync,
the 90-second verification job.

> ⚠️ **Run GATE-07 before writing this code.** If a synced Google event does not *block* the slot on
> Vagaro's side, Track A does not hold anything and the composite strategy must be re-planned. This is a
> 30-minute manual test with no code — do it first.

✅ Track A event created, mirrored, verified; permission failure → `NEEDS_STAFF`.
`Task: C-07` · `feat(calendar): google calendar bridge for track A`

---

### C-08 🔓 Track C — self-serve link — `S`
**Read:** [07](07-booking-write-path.md) §5.2

Deep-link builder, SMS template, honest "not held" wording. **Ship this before Track A or B** — it is the
Phase 1 path and the permanent fallback.

✅ A booking-intent call with `SELF_SERVE_LINK` sends a working link and holds nothing.
`Task: C-08` · `feat(booking): self-serve booking link path`

---

### C-09 🔓 Track D — staff queue and escalation — `M`
**Read:** [07](07-booking-write-path.md) §5.4; [09](09-n8n-layer.md) §3

`staff_tasks` lifecycle, `/internal/tasks/*` endpoints, payload completeness (everything a human needs
in one place).

✅ **AC-07.6** task payload contains customer, service, time, price, booking id, recording link, summary.
`Task: C-09` · `feat(booking): staff task queue and escalation payloads`

---

### C-10 🔓 PMS mirror sync — `L`
**Read:** [06](06-availability-engine.md) §9, §10

Webhook ingestion (`inbound_webhooks`, <100ms ACK), the apply logic, the poller, the collision branch,
the nightly reconciliation and integrity report.

✅ **AC-04.8**, **AC-06.10**, integration **I-12, I-13, I-14**. The collision test is mandatory — it is the
single most important error path in the system.
`Task: C-10` · `feat(sync): PMS mirror ingestion, polling, and reconciliation`

---

### C-11 🔓 Vapi assistant and tools as code — `M`
**Read:** [08](08-vapi-layer.md) §2, §3, §5, §8

`grace.json`, prompt sections, `first-message.txt` + the CI invariant check, `deploy.ts` with diff/apply
and the dirty-tree guard.

✅ **AC-08.1**, **AC-08.3**, **AC-08.4**, **AC-08.8**, **AC-11.2** (BIPA grep).
`Task: C-11` · `feat(vapi): assistant and tool definitions as code`

---

### C-12 🔓 Vapi webhook processing — `M`
**Read:** [04](04-core-api-service.md) §9.3

`end-of-call-report` → ack, enqueue, redact-then-persist, release holds, classify outcome, update
`visit_count`, write structured data.

✅ e2e **E-15**; **AC-11.3** end to end from a real Vapi payload fixture.
`Task: C-12` · `feat(core-api): vapi event webhooks and end-of-call processing`

---

### C-13 🔓 n8n workflows — `M`
**Read:** [09](09-n8n-layer.md)

WF-07, 11, 12, 14, 15, 16, 18 authored on dev, exported, normalised, committed. `lint.ts` and `deploy.ts`.

✅ **AC-09.1 → AC-09.7**.
`Task: C-13` · `feat(n8n): operational workflows as code`

---

### C-14 🔓 Voice test suites — `M`
**Read:** [08](08-vapi-layer.md) §9

All 16 scenarios in `platform/vapi/suites/`, wired into CI as a gate on prompt/tool/model changes.

✅ **AC-08.5**, **AC-08.6**, **AC-08.7**, **AC-13.6**.
`Task: C-14` · `test(voice): vapi regression suites`

---

### C-15 🔓 Staging deployment — `M`
**Read:** [14](14-infrastructure-and-deployment.md) §2, §6

Dockerfiles, compose/task definitions, `deploy-staging.yml` with migration step, health-gated rolling
deploy, smoke tests, auto-rollback.

✅ **AC-14.2 → AC-14.6**.
`Task: C-15` · `ci: staging build and deploy pipeline`

---

**🚩 Phase C gate:** a real call to the staging Vapi number books a slot, sends SMS, takes a deposit in
Stripe test mode, appears on a Google Calendar, and lands in the mirror — end to end, with the PMS faked.

---

# PHASE D — Telephony and pilot

---

### D-01 ⛔ Twilio trunk — `M`
**Blocked by:** Twilio account + number. **Read:** [10](10-telephony-and-messaging.md) §2
Steps 1–10, including every gotcha test in §2.1. Document results in
`docs/runbooks/telephony-acceptance.md`.
✅ **AC-10.1**, **AC-10.9**. `Task: D-01`

---

### D-02 ⛔ A2P 10DLC — `S` (effort) / **1–3 weeks (clock)**
**Start on day one of the project, not in Phase D.** **Read:** [10](10-telephony-and-messaging.md) §4.1
✅ **AC-10.6**. `Task: D-02`

---

### D-03 ⛔ RingCentral forwarding — `S`
**Blocked by:** client access. **Read:** [10](10-telephony-and-messaging.md) §3
After-hours rule first. Document the exact click-path with screenshots.
✅ **AC-10.2**. `Task: D-03`

---

### D-04 ⛔ Kill switch drill — `S`
**Read:** [10](10-telephony-and-messaging.md) §3.1
Both layers. **The manager performs layer 1 unassisted, timed.** Laminated card at the front desk.
✅ **AC-10.5**. `Task: D-04`

---

### D-05 🔓 Transfer path — `M`
**Read:** [08](08-vapi-layer.md) §7
Warm transfer, whisper (including the caller's number spoken aloud, per A-04), 25s ring, no-answer
fallback to `takeMessage` + manager SMS + Slack.
✅ **AC-10.3**, **AC-10.4**. `Task: D-05`

---

### D-06 🔓 Observability go-live — `M`
**Read:** [12](12-observability-and-slo.md) §5, §6
All four dashboards provisioned; every alert wired with a runbook link; P1 routing tested end to end.
✅ **AC-12.1 → AC-12.7**. `Task: D-06`

---

### D-07 🔓 Runbooks — `M`
**Read:** [16](16-runbooks.md)
Write every runbook referenced by an alert. Walk through three of them with a second person.
✅ **AC-12.5**. `Task: D-07`

---

### D-08 ⛔ Client sign-off ingestion — `S`
**Blocked by:** GATE-02/04/05 (design brief §15). **Read:** [03](03-data-model.md) §12
As approvals arrive, set `approved_at` on policies, services, providers, knowledge entries, templates.
Each approval is a data change with an audit row — no code change.
✅ Approved rows exist; unapproved paths still degrade gracefully. `Task: D-08`

---

### D-09 🔓 Production deploy + pilot — `M`
**Read:** [14](14-infrastructure-and-deployment.md) §6
Production environment, protected deploy, synthetic call smoke test. Then **after-hours only** for
7 days with daily QA review.
✅ **AC-14.4**, **AC-14.10**; 7 consecutive days with zero P1s before widening. `Task: D-09`

---

**🚩 Phase D gate — go-live checklist (all must be true):**
- [ ] 10DLC `VERIFIED`
- [ ] Kill switch drilled by the manager, timed under 60s
- [ ] Legal review complete (**AC-11.12**)
- [ ] Cancellation policy and deposit amount approved in writing (design brief §15 items 1, 2)
- [ ] Greeting approved and passing the CI invariant check
- [ ] All P1 alerts tested end to end
- [ ] Recording retention configured and the purge job proven
- [ ] Restore drill performed (**AC-14.7**)
- [ ] 20 test calls listened to by a human
- [ ] Staff briefed: what Grace does, what she never does, how to kill it

---

# PHASE E — Write-path hardening

⛔ **Entirely gated on GATE-01** — Vagaro's written answer.

### E-01a — If Vagaro grants write access — `M`
**Read:** [07](07-booking-write-path.md) §7
Implement the four write methods, flip `capabilities.writeAppointments`, route `pms.write_appointment` to
the native call, **delete `apps/booking-worker` entirely**, remove its maintenance budget.
✅ **AC-07.8**; e2e **E-6** now runs against the real adapter. `Task: E-01a`

### E-01b — If Vagaro does not — `L`
**Blocked additionally by:** GATE-10 (written client authorization + ToS review).
**Read:** [07](07-booking-write-path.md) §5.3
Playwright worker with **the mandatory pre-check**, selector registry, screenshots, 1-per-tenant
concurrency, 3 retries, unknown-outcome → `NEEDS_STAFF`, nightly canary.
✅ **AC-07.6**, **AC-07.7**; e2e **E-4, E-5**; canary alerting proven. `Task: E-01b`

### E-02 🔓 Reconciliation hardening — `M`
Full integrity report (§06 §10) with all seven checks exported as gauges and alerted.
✅ **AC-12.5** for the drift alerts. `Task: E-02`

### E-03 🔓 Daytime overflow rollout — `S`
Move from after-hours-only → overflow → primary, one step per week, each gated on a clean QA week.
`Task: E-03`

---

# PHASE F — Scale and optimise

| Task | Description |
|---|---|
| `F-01` | Outbound reminders (24h/2h) using `VoicePort.createOutboundCall` + SMS |
| `F-02` | No-show recovery and waitlist backfill on cancellation |
| `F-03` | Membership upsell flow (design brief §4.4) |
| `F-04` | Spanish assistant — second Vapi assistant, shared tools, translated knowledge/policies |
| `F-05` | Staff admin console (`apps/admin-console`) — task queue, call review, knowledge editing, approvals UI |
| `F-06` | Second tenant onboarding — prove the multi-tenant path end to end |
| `F-07` | Second PMS adapter (Mindbody/Booker) — prove `PmsPort` |
| `F-08` | Move to ECS; add a read replica for reporting |
| `F-09` | Trunk consolidation / port 847.961.4800 if the pilot is stable ≥60 days |
| `F-10` | Containment optimisation loop: unanswered-questions panel → knowledge entries → measure |

---

## Critical path summary

```
Day 0 ────────────────────────────────────────────────────────────────────►
  │  Send Vagaro Enterprise email + in-app form   (7 business days)  ⛔ GATE-01
  │  Start A2P 10DLC registration                 (1–3 weeks)        ⛔ GATE-09
  │  Run the 30-minute Track A validation test    (same day!)        ⛔ GATE-07
  │  Send the §15 sign-off checklist to PalmLeaf  (client clock)     ⛔ GATE-02/04/05
  │  Pull 90 days of RingCentral call logs        (validates volume)
  └─ IN PARALLEL, IMMEDIATELY: Phase A → Phase B  (≈3 weeks, zero dependencies)
```

**The three things to do on day one are not code.** They are the Vagaro email, the 10DLC registration,
and the 30-minute Track A test — because each one has a clock or a decision behind it that the build
cannot compress. Everything else starts the same day and runs alongside.

---

## Progress tracker

| Phase | Tasks | Done | Gate met |
|---|---|---|---|
| A | 9 | ☐ | ☐ |
| B | 14 | ☐ | ☐ |
| C | 15 | ☐ | ☐ |
| D | 9 | ☐ | ☐ |
| E | 3 | ☐ | ☐ |
| F | 10 | ☐ | — |
