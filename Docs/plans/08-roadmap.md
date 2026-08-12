# 08 — Implementation Roadmap

**Status:** Active
**Read before:** picking up any task. This document is the work.
**Implements:** every ADR in [01-architecture](01-architecture.md) §4
**Last verified:** 2026-08-04 against [`Docs/Completed/`](../Completed/00-STATUS.md) and the live Vapi and n8n instances.

> **In one paragraph:** this is the ordered task list. It keeps the A–F phase model, but every task
> body has been re-cut for Python, and completed tasks carry the evidence that proves them rather
> than a checkbox. It deliberately does **not** restate design decisions — each task names the
> document to read, and that document is where any disagreement gets settled.

**Task ID format:** `<PHASE>-<NN>`. Reference the ID in the commit footer (`Task: C-04`).
**Effort:** `S` ≈ half a day · `M` ≈ 1–2 days · `L` ≈ 3–5 days, for one focused implementer.
**🔓** no external dependency — always safe to start.
**⛔** blocked on an external answer — see [09-open-decisions](09-open-decisions.md).
**✅** done, with evidence in [`Docs/Completed/`](../Completed/00-STATUS.md).

---

## 1. Phase overview

| Phase | Theme | External dependency | State |
|---|---|---|---|
| **A** | Foundation | none 🔓 | ✅ done, bar one task |
| **B** | Conversation & orchestration layers | Vapi, n8n 🔓 | ✅ done |
| **C** | Core domain & API | none 🔓 | **next — the entire remaining critical path** |
| **D** | Integration | Vagaro, Google, Stripe, Twilio | ⛔ blocked |
| **E** | Telephony & pilot | carrier + client sign-off | ⛔ blocked |
| **F** | Scale & optimise | — | later |

**The phase order changed, and the reason matters.** The original plan ran Foundation → Core domain
→ Integration → Telephony, assuming Vagaro access would arrive early. It did not. Vapi and n8n
turned out to be the only fully accessible platforms, so the conversation and orchestration layers
were built first. That was the right call: it produced a working, demonstrable Grace while every
other clock was still running.

**What that leaves.** Phases A and B are complete. Phase C — the domain, the database and Core API —
has **no external dependency and has not been started**. It is the whole remaining critical path,
and it is unblocked today.

---

## 2. Phase A — Foundation ✅

*Goal: a clean clone builds, checks and deploys. Nothing business-specific.*

| # | Task | State | Evidence |
|---|---|---|---|
| **A-01** | Repository scaffold — `pyproject.toml`, `src/` layout, `.gitignore` | ✅ | `make install` from a clean clone |
| **A-02** | Toolchain — uv, ruff, mypy strict, pytest, the Makefile | ✅ | `make check` green |
| **A-03** | CI — the T1 static gate | ✅ | `.github/workflows/ci.yml`, <90s, $0 |
| **A-04** | `grace_contracts` — Pydantic models for all 15 tools | ✅ | `platform/vapi/tools/*.json`, generated |
| **A-05** | Generated-artefact determinism | ✅ | `make vapi-build-check`; digest stable |
| **A-06** | Document template + `make docs-lint` | ✅ | this document conforms to it |
| **A-07** | Generated per-tool and per-workflow reference | ✅ | [Docs/generated/](../generated/) |
| **A-08** | **Import boundaries — `import-linter`** | ⚠️ **not done** | see below |

### A-08 🔓 Import boundaries — `S`
**Read:** [02-python-and-repo](02-python-and-repo.md) §6; ADR-0018

This is the one Phase A task still outstanding, and it is not cosmetic. ADR-0018 restores invariant
**I1** — the rule making it impossible to call a third party from the path where a caller is
waiting. The rules the language port removed were never replaced, so **the guarantee is currently
unenforced, silently.**

Contracts 2 and 3 name packages that do not exist yet, so they land with those packages (C-01 and
C-05). **Contract 1 applies today** and should not wait.

✅ **AC-02.3:** a deliberate violation of each contract fails CI. Prove it on a throwaway commit,
then revert.
`Task: A-08` · `chore(ci): restore import boundaries`

---

## 3. Phase B — Conversation and orchestration layers ✅

*Goal: Grace exists, is deployed, and is testable without Core API.*

| # | Task | State | Evidence |
|---|---|---|---|
| **B-01** | Assistant config-as-code, drift-checked | ✅ | `make vapi-diff` → zero drift against a live assistant |
| **B-02** | 15 tools live — 13 generated + `transferToHuman` + `endCall` | ✅ | AC-08.4 |
| **B-03** | System prompt assembled from `prompts/sections/` | ✅ | `make vapi-prompt`; CI fails when stale |
| **B-04** | Greeting + recording disclosure, CI-protected (I7) | ✅ | AC-08.3 — both halves, file *and* injection |
| **B-05** | Structured outputs replacing the deprecated analysis plan | ✅ | `grace-call-outcome` live |
| **B-06** | Mock tool server — real Pydantic validation, fault injection | ✅ | [07-testing](07-testing.md) §4 |
| **B-07** | Spoken formatters + 14 tests | ✅ | `tests/test_speech.py`; three audible defects fixed |
| **B-08** | Web harness | ✅ | built — **never driven through a live call** |
| **B-09** | n8n: WF-00/12/18 deployed, linted, tagged | ✅ | published, and correctly **dormant** |
| **B-10** | n8n: WF-20/21/22 — reporting that actually runs | ✅ | [04-n8n-layer](04-n8n-layer.md) §5 |
| **B-11** | Postgres reporting skeleton, switched off | ✅ | `platform/postgres/schema.sql` + disabled nodes |

### B-12 🔓 Drive one live web call — `S`

**The highest-value unblocked task in the plan, and it is half a day.**

Everything above is verified by direct HTTP against the mock server. **Nothing has been verified
with a model actually speaking.** The prompt, the grounding rule, the medical gate, the PCI
refusal, endpointing and filler timing are all unproven in the only way that counts.

1. `make vapi-mock`, then `cloudflared tunnel --url http://localhost:4242`.
2. Redeploy the dev assistant with the tunnel URL — the tool URLs currently point at
   `placeholder.invalid`, so **every tool fails on a real call until this is done**.
3. Open `platform/vapi/web-harness/index.html` and talk to her.
4. Confirm the greeting carries both disclosures, a booking completes, and the medical gate fires.

✅ **AC-08.9:** a completed web call whose `end-of-call-report` arrives with populated
`structuredData`, and a transcript showing the grounding rule holding.
`Task: B-12` · `test(vapi): first live web call`

### B-13 🔓 Trigger WF-20 by hand — `S`

Proves the n8n instance does real work rather than merely holding correct configuration. Needs the
`vapi` credential from [06-platform-setup](06-platform-setup.md) §3.3 and nothing else.

✅ **AC-09.12:** a real Execution with real output, and a row in the Data Table.
`Task: B-13` · `test(n8n): first real execution`

---

## 4. Phase C — Core domain and API 🔓

*Goal: Grace's brain works, is fast, and is provably correct — without one external credential.*

**Nothing in this phase is blocked.** It is roughly three weeks of work that can start today. Until
it lands, eight of the eleven n8n workflows stay dormant and every write tool is a stub.

### C-01 🔓 `grace_domain` — the pure core — `L`
**Read:** [01-architecture](01-architecture.md) ADR-0011; [availability-engine](../reference/availability-engine.md)

1. The 48-hour change-fee engine, taking `now` explicitly and returning a machine-readable `reason`.
2. Pricing resolution — member and non-member, provider overrides, unapproved service raises.
3. Slot ranking, buffer application, the medical-screen gate.
4. **No I/O, no clock.** Add `import-linter` contract 2 in this task, not afterwards.

✅ **AC:** coverage ≥ 95%; the suite passes under `TZ=UTC` and `TZ=Pacific/Kiritimati`.
`Task: C-01` · `feat(domain): pure business rules`

### C-02 🔓 `grace_db` — schema and migrations — `L`
**Read:** [data-model](../reference/data-model.md); ADR-0004, ADR-0016

1. SQLAlchemy 2.0 models for every table, each carrying `tenant_id`.
2. **The `EXCLUDE` constraint over `tstzrange` with `btree_gist`.** The entire double-booking
   guarantee rests on this one constraint (ADR-0004).
3. Alembic migrations. **Verify autogeneration round-trips the exclusion constraint and the GiST
   index** — this is Q-01.2, and this task is where it gets answered. If it cannot, those
   migrations become hand-written; discover that here rather than at Phase D.
4. Row-level security policies for tenant isolation.
5. The two hot-path queries as hand-written SQL — ADR-0009's reasoning survived its supersession.

✅ **AC:** overlapping active rows raise `23P01`; migrations run twice with no error and no drift.
`Task: C-02` · `feat(db): schema, migrations, and the exclusion constraint`

### C-03 🔓 Availability engine — `M`
**Read:** [availability-engine](../reference/availability-engine.md)

Free-slot computation against the local mirror, hold placement under contention, hold and
reservation TTLs, and translating `23P01` into a domain `SlotNoLongerAvailable` that the handler
recovers from gracefully.

✅ **AC:** `EXPLAIN` shows the GiST anti-join, not a sequential scan; p95 < 40ms with 100k rows.
`Task: C-03` · `feat(availability): slot computation and holds`

### C-04 🔓 The transactional outbox — `M`
**Read:** [booking-write-path](../reference/booking-write-path.md) §3; ADR-0005, ADR-0015

1. `outbox_events`, written **in the same transaction** as the business rows.
2. A dispatcher onto arq.
3. **Re-derive the dedupe guarantee against arq rather than assuming it** (Q-01.1). arq deduplicates
   within a keep-alive window, which is not the lifetime guarantee the design was written against.
   If the window is too short, add the consumer-side `UNIQUE` constraint — which at-least-once
   delivery requires anyway.

✅ **AC:** a forced failure after the business write leaves neither business nor outbox rows; three
concurrent dispatchers over 500 events dispatch each exactly once.
`Task: C-04` · `feat(outbox): transactional outbox and dispatcher`

### C-05 🔓 `grace_api` — Core API — `L`
**Read:** [core-api](../reference/core-api.md); ADR-0012, ADR-0017

1. FastAPI app with the execution order [core-api](../reference/core-api.md) §3 specifies —
   **middleware for raw-body capture and signature verification, dependencies for everything after.**
   That ordering is a correctness requirement, not a style choice (ADR-0017).
2. HMAC verification. ⛔ **Gated on A-13** — the payload format is unconfirmed, verification fails
   closed, and *every* tool call is rejected until it is known. Close A-13 before starting this.
3. Tenant resolution pinned into `contextvars`.
4. Idempotency middleware keyed on `tool_call_id`.
5. Deadline propagation returning a graceful sentence, **raced against `GRACE_TOOL_DEADLINE_MS` and
   never against the per-tool p95 budget** — racing the budget fires the fallback on ~5% of calls by
   construction (ADR-0012).
6. The 15 tool handlers, reusing the `grace_contracts` models directly as request models.
7. The `/internal/*` endpoints the n8n workflows already call.
8. `import-linter` contract 3 — handlers may not import adapters.

✅ **AC-02.3** · **AC-04.10:** a handler importing `grace_adapters` fails CI.
`Task: C-05` · `feat(core-api): tool endpoints and request lifecycle`

### C-06 🔓 Contract-test the mock against the real thing — `S`

The mock server becomes the contract double it was always designed to be. Both implementations must
agree on all 15 envelopes.

✅ **AC:** identical responses from mock and Core API for every tool fixture.
`Task: C-06` · `test(contracts): mock and core-api parity`

### C-07 🔓 Wake the dormant workflows — `S`

WF-00/12/18 come alive the moment `/internal/*` exists. **No workflow redesign** — rotate the
`PalmLeaf Core API (dev)` credential off its placeholder token and redeploy.

✅ **AC-09.4** · **AC-09.10.**
`Task: C-07` · `feat(n8n): activate the escalation path`

---

## 5. Phase D — Integration ⛔

*Blocked on credentials that do not exist. Each task is ready the day its gate clears; build against
fakes and cassettes first, then wire live.*

| # | Task | Effort | Blocked by |
|---|---|---|---|
| **D-01** | Port fakes — stateful, with injectable latency, failure rates and capability flags | `M` | 🔓 **none — start any time** |
| **D-02** | Resilient client — retry, circuit breaker, timeout, rate limiting | `M` | 🔓 **none** |
| **D-03** | `PmsPort` + Vagaro adapter, read-only, capability-flagged | `L` | ⛔ GATE-01, GATE-03 |
| **D-04** | Availability mirror — webhooks, 10-min polling, nightly reconciliation | `L` | ⛔ GATE-01 |
| **D-05** | `CalendarPort` + Google Calendar adapter (Track A) | `M` | ⛔ GATE-07 |
| **D-06** | `PaymentsPort` + Stripe adapter, deposit links, signed webhook | `M` | ⛔ GATE-08 |
| **D-07** | `MessagingPort` + Twilio adapter — opt-out, consent, STOP/HELP | `M` | ⛔ GATE-09 |
| **D-08** | The booking saga — Tracks A, C and D | `L` | after D-03…D-07 |
| **D-09** | Track B automation | `L` | ⛔ GATE-01 decides whether this exists at all |

> **D-01 and D-02 are not blocked.** They are the parts of Phase D that need no credential, and
> doing them early means every later adapter has a tested foundation and a fake to develop against.
> They are good work to interleave with Phase C.

> **D-09 may never be built.** If Vagaro grants a real `POST /appointments`, the saga collapses to
> two states and Track B is deleted. ADR-0006 shaped the saga specifically so that deletion is a
> small diff rather than a rewrite — [booking-write-path](../reference/booking-write-path.md) §7.

---

## 6. Phase E — Telephony and pilot ⛔

| # | Task | Blocked by |
|---|---|---|
| **E-01** | A2P 10DLC registration | ⛔ GATE-09 — **start the clock now; it takes 1–3 weeks** |
| **E-02** | Twilio Elastic SIP trunk, DID, TLS/SRTP | ⛔ GATE-11 |
| **E-03** | RingCentral forwarding | ⛔ GATE-11 |
| **E-04** | Transfer path verified end to end | ⛔ needs a real number — closes A-14 and A-15 |
| **E-05** | Legal review of the greeting and consent flows | ⛔ GATE-05, then AC-11.12 |
| **E-06** | Kill-switch drill | before go-live |
| **E-07** | After-hours pilot | ⛔ client sign-off |

---

## 7. Phase F — Scale and optimise

Multi-tenant onboarding — including the n8n tenant problem in
[04-n8n-layer](04-n8n-layer.md) §11 — a second PMS adapter, waitlist, reminders, a Spanish
assistant, and a staff dashboard. The dashboard is also where the kill switch regains a one-click
surface (Q-04.2), which is why it is not merely cosmetic.

---

## 8. Critical path

```
TODAY ──────────────────────────────────────────────────────────────────────►
  │  B-12  drive one live web call        (half a day, unblocked)  ← do this first
  │  B-13  trigger WF-20 by hand          (half a day, unblocked)
  │  A-08  import-linter contract 1       (an hour, unblocked)
  │
  │  PHASE C — domain, database, Core API (≈3 weeks, ZERO dependencies)
  │     └─ close A-13 (HMAC payload format) before C-05, or C-05 cannot finish
  │     └─ D-01/D-02 (fakes, resilient client) interleave here — also unblocked
  │
  └─ IN PARALLEL, and none of it is code:
        Vagaro Enterprise email + in-app form      ⛔ GATE-01   (7 business days)
        A2P 10DLC registration                     ⛔ GATE-09   (1–3 weeks)
        The 30-minute Track A validation test      ⛔ GATE-07   (same day)
        Client sign-off checklist to PalmLeaf      ⛔ GATE-02/04/05
        Pull 90 days of RingCentral call logs      (validates the volume assumption A-09)
```

**Today's work is two half-day tasks and four emails.** B-12 and B-13 convert a plausible-looking
deployment into a demonstrated one, and they cost almost nothing. The four external clocks cannot
be compressed by any amount of engineering, so they should already be running while Phase C is
built.

---

## 9. Acceptance criteria

✅ **AC-15.1** Every task names the documents to read, and no task requires a decision that is not
either settled in an ADR or logged in [09-open-decisions](09-open-decisions.md).
✅ **AC-15.2** Every completed task is marked ✅ with evidence in
[`Docs/Completed/`](../Completed/00-STATUS.md) — an artefact, not a checkbox.
✅ **AC-15.3** Every blocked task names the gate blocking it, and that gate exists in
[09-open-decisions](09-open-decisions.md).
✅ **AC-15.4** No task in Phase C has an external dependency. If one appears, it belongs in Phase D
and the phase boundary was drawn wrong.

## 10. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **Q-08.1** | Is three weeks realistic for Phase C? | The estimate assumes one focused implementer and no surprises in the exclusion-constraint migration (Q-01.2) or the arq dedupe window (Q-01.1). Both are flagged as risks precisely because either could cost days. Re-estimate after C-02. | Engineering, after C-02 |
| **Q-08.2** | Could a pilot start before Phase D completes? | D and E are drawn sequentially, but a pilot on Track C alone — self-serve links, no PMS write — could start much earlier and would produce real call data sooner. That would also give WF-20/21/22 something to report on. | Product / client |
| **Q-08.3** | Which Phase F item comes first? | Multi-tenancy, a second PMS and the staff dashboard are listed without an order. The dashboard closes a live regression (the kill switch, Q-04.2), which arguably outranks the other two. | Product, at Phase F |
| **Q-08.4** | Does the roadmap still assume a single implementer? | Effort estimates and the strict task ordering both assume one person. Two would change the critical path — C-01 and C-02 are genuinely parallel, as are D-01/D-02 against Phase C. | Engineering / commercial |
