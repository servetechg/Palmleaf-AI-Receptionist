# Technical Daily Log

Engineering detail, newest first — mechanisms, file paths, API shapes, and defects with their
root cause. **This is the companion to [DAILY-LOG.md](DAILY-LOG.md)**, which covers the same days
in plain language for non-technical readers and deliberately carries no code, paths or library
names.

Each entry addresses features and workflows **separately**, so a change can be traced from the
commit to the artefact it produced.

---

## 7 August 2026

**Commits:** *(uncommitted working tree)*

---

### 1. Schema — 15 forward-only migrations, `data-model.md` implemented literally

| | |
|---|---|
| **New** | `platform/postgres/migrations/0001…0015_*.sql`, `src/grace_db/{migrate,seeds}.py`, `docker-compose.yml` |
| **Targets** | `make db-up · db-migrate · db-seed · db-psql · db-down` |
| **Applied live** | Postgres 16.14 in Docker, all 15 migrations, seeds idempotent across two runs |

Tables: `tenants`, `tenant_channels`, `providers`, `resources`, `services`,
`provider_services`, `business_hours`, `provider_shifts`, `schedule_exceptions`,
`calendar_occupancy`, `customers`, `appointments_mirror`, `bookings`, `booking_events`,
`calls`, `tool_invocations`, `message_templates`, `messages`, `consent_log`,
`knowledge_entries`, `policies`, `outbox_events`, `idempotency_keys`, `staff_tasks`,
`sync_state`, `audit_log`, `inbound_webhooks`.

**Not Alembic**, deliberately: there is no ORM, `data-model.md` §17 specifies forward-only
SQL, and every file here is DDL copied from that document. `migrate.py` tracks applied
versions in `schema_migrations` and runs each file in its own transaction — a rejected
statement leaves earlier files applied and the failing one rolled back.

**Host port 5434, not 5432.** This machine already runs a native Postgres on the default
port; the first `docker compose up` failed with `address already in use`. Overridable via
`GRACE_DB_PORT`, but the default must not collide with something already serving.

---

### 2. I2 proven, not asserted — the exclusion constraint rejects a real overlap

`calendar_occupancy` carries the constraint verbatim from `data-model.md` §6:

```sql
CONSTRAINT calendar_occupancy_no_overlap EXCLUDE USING gist (
  tenant_id WITH =, subject_type WITH =, subject_id WITH =, blocked_range WITH &&
) WHERE (state = 'ACTIVE')
```

Exercised against the live database with three inserts — hold for Maria 15:00–16:15,
overlapping hold for Maria 16:00–17:00, same window for James:

```
INSERT 0 1
ERROR:  conflicting key value violates exclusion constraint "calendar_occupancy_no_overlap"
DETAIL:  Key (…, blocked_range)=(["2026-09-01 16:00:00+00","2026-09-01 17:00:00+00"))
         conflicts with existing key (…, ["2026-09-01 15:00:00+00","2026-09-01 16:15:00+00"))
INSERT 0 1
 active_holds: 2
```

Third insert succeeding is the half that matters as much as the rejection: the constraint
is scoped to the subject, so it does not serialise the whole calendar. `btree_gist` is what
allows uuid equality beside range overlap in one EXCLUDE; without it the constraint cannot
be created at all.

---

### 3. `bookings.state` cannot move without its audit row

`0015_booking_state_trigger.sql` adds a `CONSTRAINT TRIGGER … DEFERRABLE INITIALLY
DEFERRED` that raises unless a `booking_events` row exists for the exact `from_state →
to_state` pair by commit. Deferred rather than immediate so the transition function may
write the event and the row in either order within one transaction.

This is `booking-write-path.md` §4's "a lint rule **and** a DB trigger both enforce it",
implemented as the half that cannot be argued with.

---

### 4. `PmsPort`, `FakePms`, and the resilient client

`src/grace_contracts/ports/pms.py` — Protocol plus Pydantic models, `PmsCapabilities` as a
frozen dataclass with **every write flag defaulting False**. Vagaro's write story is
unknown until discovery runs, and the flag is how that uncertainty is carried without
leaking into the domain.

`src/grace_testing/fake_pms.py` — stateful store with cursor pagination, injectable latency
and failure rate, and constructor-set capabilities. AC-05.7 is a test:
`set_capabilities(FULL_WRITE)` turns `create_appointment` from `NotSupportedByProvider`
into a working write with no other change.

`src/grace_adapters/resilient.py` — retry (4 attempts, exponential with **full** jitter,
429/5xx/transport only, honours `Retry-After`), breaker (5 consecutive or ≥50% of a
20-request window → open 30s → half-open probe), explicit timeouts, and a token bucket at
**2 rps / 3,000 per day** against Vagaro's 5,000-per-month plan, warning at 80% of the
projected monthly figure. In-process state, because one instance runs today; shared state
is a Redis change if a second ever does.

---

### 5. Availability engine — one query, proven against the live database

`src/grace_db/sql/find_free_slots.sql` + migration `0016_business_hours_fn.sql`.

Single statement, no N+1: `days × provider_shifts` expand into concrete ranges, intersect
with `business_hours_for_date()` (a STABLE SQL function applying SPECIAL_HOURS over the
weekly template), a 15-minute `generate_series` grid produces candidates, and one
`NOT EXISTS` over `calendar_occupancy` subtracts what is taken — riding the GiST index the
exclusion constraint already built.

The `svc` CTE carries the GATE-04 gate: `AND s.approved_at IS NOT NULL`. Measured on the
seeded catalogue, 3-day window, `massage_60`:

```
service massage_60: approved_at=None
  -> 0 free slots            # the gate, in SQL — not in the prompt
  -> after approval: 148 free slots
       Maria 2026-08-07 19:00   James 2026-08-07 19:00   Maria 2026-08-07 19:15
```

Then the subtraction, with one HOLD inserted on Maria's 19:00:

```
before: 148 slots
after one hold: 143 slots  (removed 5)
the held slot still offered? False
same time still offered by another therapist: 1 -> ['James']
```

Five removed is correct arithmetic, not a coincidence: a 60-minute service with a
15-minute after-buffer blocks 75 minutes, which is five 15-minute grid positions. James
keeping 19:00 is the other half — the constraint is scoped to the subject, so one hold does
not serialise the whole clinic. Both probes ran inside a transaction and were rolled back;
the catalogue remains unapproved.

---

### 6. Freshness gate — an addition to the frozen design, not part of it

`src/grace_domain/availability/freshness.py`. `availability-engine.md` specifies refresh
cadences (webhook <5s, poller 10 min, nightly reconcile) and drift *alerts*, but nothing
stops the engine answering from a mirror that stopped updating. Given I1 routes every
in-call read to the mirror, that gap is load-bearing: a broken sync produces confident
wrong availability, and **an empty mirror is indistinguishable from a free calendar**.

Three refusal cases, all pure and unit-tested: `last_success_at IS NULL` (never synced),
age > 30 min, and `mirror_has_rows=False` despite a recent timestamp. The refusal speaks
core-api §6.4's honest fallback rather than inventing times. 30 minutes is several
consecutive poller failures — past a blip, short of a caller noticing.

---

### 7. State machine + ranking, both pure

`src/grace_domain/booking/transitions.py` — the 8-state table verbatim from
booking-write-path.md §4, plus `EMISSIONS`. All 64 state pairs are enumerated in the test
rather than sampled; the table *is* the contract. Two assertions worth naming:
`pms.write_appointment` is emitted from `CONFIRMED` and nowhere else (never write into the
salon's calendar before the deposit settles), and `CANCELLED` is reachable from every
non-terminal state (a trapped booking would need a DBA to release the slot).

`src/grace_domain/availability/rank.py` — §4's weights, then diversification.
**Defect found by its own test:** the first cut had a "thin day" padding pass that
re-added candidates diversification had just rejected, so a crowded morning could still
produce "nine, nine fifteen, nine thirty with Maria". The comment already said padding was
wrong; the code did it anyway. Padding removed — a thin day now returns two slots, or one,
which is the correct answer.

`slot_id.py` reconciles the id conflict flagged in planning: `hold-XXX` wins
(`grace_contracts.tools.shared` and core-api agree; availability-engine §5.1's
`'h' + base32` is the outlier). Crockford alphabet minus I/L/O/U, asserted over 200
generated ids — those four are exactly the characters a caller repeating an id gets wrong.

---

### 8. `grace_api` — the tool server, exercised live

`src/grace_api/{main,envelope,handlers}.py` + `src/grace_db/repositories/{availability,catalogue,calls}.py`.
`make api-run` (uvicorn :8080).

`POST /vapi/tools` implements core-api.md §4.1 verbatim: batched `toolCalls`, results
matched by `toolCallId`, spoken sentences, **HTTP 200 even on failure** — a 5xx gives the
model nothing to say and the caller hears silence. A handler exception is caught per tool
call, so one broken tool cannot mute the assistant.

`POST /webhooks/vagaro`: one INSERT into `inbound_webhooks`, then 200. Dedupe on Vagaro's
own event `id` (their docs state it exists "to ensure that an event is not processed
twice") with a payload hash as fallback — this is the plan's amendment to core-api §9.1,
which specified `hashPayload(raw)` and would have stopped deduping the moment Vagaro varied
anything between retries.

`/internal/reports/{calls,reconciliation}` are **actually bearer-authenticated**, closing
the gap core-api.md flagged against itself ("as written these routes are unauthenticated").
WF-07 and WF-11 now have a real endpoint behind their `__URL__:core-api` placeholder.

Live transcript against the seeded database:

```
getServicesAndPricing (unapproved)  -> "Let me get someone who can confirm that for you."
checkAvailability     (no sync yet) -> "I'm having trouble reaching the schedule..."
getServicesAndPricing (approved)    -> "We have the sixty minute massage at one fifteen,
                                        the sixty minute deep tissue at one thirty, or the
                                        ninety minute massage at one sixty."
checkAvailability     (mirror fresh)-> "I have twelve with Maria or twelve fifteen with James."
```

Catalogue restored to `approved_at IS NULL` afterwards; test rows removed.

---

### 9. Three defects found by running it, not by reading it

**(a) Vapi's call id is not our call id.** `calendar_occupancy.call_id` is a uuid FK to our
`calls` row; the handler was passing Vapi's opaque string straight in. Postgres rejected it
(`invalid input syntax for type uuid`) on the first live hold. Fixed with
`calls_repo.ensure_call()`, which upserts on `(tenant_id, vapi_call_id)` and returns ours.
Quiet class of bug: it only surfaces on a write, and every read had passed.

**(b) `preferredDate` parsed as UTC.** `datetime.fromisoformat(date).replace(tzinfo=UTC)`
for an America/Chicago tenant shifts the window five hours, so "Monday" started offering
Sunday evening. Now `datetime.combine(date, time.min, tzinfo=ZoneInfo(tenant.timezone))`.
`_matches_preference` and the earliness score were making the same mistake — "afternoon"
was being tested against a UTC hour, which is why an afternoon request returned 9:15am.

**(c) The same start time offered twice.** First live answer was "nine fifteen with Maria
or nine fifteen with James" — two therapists, one time, giving the caller a choice of *whom*
but not *when*. availability-engine.md §4 says "prefer spread across time, **then** across
providers"; only the provider half was implemented. Diversification now rejects a duplicate
start time before the 45-minute same-provider rule.

---

### 10. I1 is enforced, not aspirational

`[tool.importlinter]` in `pyproject.toml`, wired into `make check` as `make imports`. Three
contracts: the hot path (`grace_api`, `grace_domain`) cannot import `grace_adapters`; the
domain cannot import `grace_db`, `fastapi`, `psycopg` or `httpx`; `grace_contracts` imports
nothing of ours.

00-INDEX.md has carried "⚠️ I1 is currently unenforced — the boundary rules were lost in the
language port, and their replacement (ADR-0018) is task A-08, not yet done" since the port.
This is A-08. Negative-tested by adding `from grace_adapters.resilient import ...` to a
handler:

```
Broken contracts
I1 — the hot path cannot reach a third party
grace_api is not allowed to import grace_adapters:
-   grace_api.handlers -> grace_adapters.resilient (l.17)
```

Reverted; 3 kept, 0 broken. 82 files, 208 dependencies analysed.

---

### 11. Correction — n8n *can* do the booking transaction; the earlier objection was wrong

Recorded because it changed an architectural argument, not just an implementation.

The claim made repeatedly in this project was that a booking needs a multi-step
application-side saga, since n8n's Postgres node cannot span a transaction across nodes.
The second half is true; **the conclusion did not follow.** Postgres wraps a *lone
statement* in its own transaction, and the whole booking fits in one statement. Proven
before rewriting anything:

```
WITH cust AS (INSERT … customers … RETURNING id),
     occ  AS (UPDATE calendar_occupancy … RETURNING id),
     bk   AS (INSERT … bookings … RETURNING id),
     ev   AS (INSERT … booking_events …)
INSERT INTO outbox_events …
-- bookings=1  events=1  outbox=1  occ_kind=RESERVATION
```

Four tables, one statement, atomic, and the state-audit trigger satisfied. So
`createBooking` is now `sql/create_booking.sql` — a single statement — rather than a
sequence. Two consequences: the atomicity guarantee is structural instead of procedural,
and the SQL is portable to anything that can execute a statement, including an n8n
Postgres node. The remaining argument for application code is testability of money and
speech, not atomicity.

---

### 12. `createBooking` — live, with all three guarantees exercised

`src/grace_db/{sql/create_booking.sql,repositories/booking.py}` + the handler.

```
1. availability : "I have nine fifteen with Maria or nine thirty with James."
   held slot     : hold-GY2
2. no screening : "Before I book, I'd like one of our team to go over a couple of
                   health questions with you."          ← I4, server-side
3. booking      : "You're all set, Jordan — nine fifteen. Your reference is bk-XMME."
4. SAME request : "You're already set for nine fifteen. Your reference is bk-XMME."
   bookings rows : 1                                    ← I3, one row from two requests
   staff task    : BOOKING_NEEDS_ENTRY, priority 2, "Enter booking in Vagaro"
   outbox        : pms.write_appointment
```

Step 2 matters: the medical gate is enforced by the handler, not the prompt. A model that
forgets to ask, or a caller talking over the question, cannot produce a screened-looking
booking.

Step 4 is invariant I3 end to end — `{callId}:{slotPublicId}` against the UNIQUE on
`(tenant_id, idempotency_key)`, returning the original booking rather than a second one.

Migration 0017 adds `BOOKING_NEEDS_ENTRY`. Track D bookings are **not** failures and must
not be filed as `BOOKING_WRITE_FAILED` — an operator triaging the queue needs to see the
difference between "Grace booked this, transcribe it" and "something broke".

---

### 13. Deployment — one Hostinger box, verified as a container

`Dockerfile` + `docker-compose.prod.yml`. The overlay adds the API beside the existing
Postgres service and `!override`s Postgres's published ports away, so the database is
reachable only from the app on that box.

Built and run against the live database over the container network: `/readyz` ok, tool
calls returning correct sentences, `/internal/*` rejecting an unauthenticated request and
answering an authenticated one. `GRACE_INTERNAL_API_TOKEN` uses compose's
`${VAR:?message}` form, so a deployment without it **fails to start** rather than exposing
unauthenticated internal routes.

Incidental: `grace-postgres` was found exited with code 255, clean logs, no OOM — the
daemon stopped it, matching several other containers on this host. `restart:
unless-stopped` in the production overlay is the guard.

---

### 14. A real deadlock under concurrent calls — found, proved, eradicated

Two callers running `check_availability` at the same instant:

```
psycopg.errors.DeadlockDetected: deadlock detected
DETAIL: Process 62298 waits for ShareLock on transaction 822; blocked by 62297.
        Process 62297 waits for ShareLock on transaction 823; blocked by 62298.
CONTEXT: while checking exclusion constraint on tuple (0,39) in calendar_occupancy
```

Caller A was served; **caller B's request raised**, which reaches a real customer as "I'm
having trouble". Data integrity never wavered (zero overlapping holds) — the failure was
entirely in the experience.

**Cause.** `place_holds` inserted in *ranking* order, and ranking depends on the caller's
stated preference (`time_preference` +100, `requested_provider_name` +200). Two callers
therefore took locks on overlapping ranges in different orders. The per-slot savepoint
caught `ExclusionViolation` but not `DeadlockDetected`, so it aborted the whole request.
Note two callers with *identical* preferences cannot deadlock — the sort is total, so they
queue rather than cycle. Divergent preferences are the trigger.

**Fix — ordering, not retrying.** Insert in `(provider_id, starts_at)` order and re-sort
the result back into ranking order for speech. Insertion order is a *locking* decision;
speech order is a *product* decision; they are now decoupled. This removes the class by
argument rather than making it rarer: conflicts exist only within one provider, and if
every transaction takes that provider's ranges in ascending start order, a cycle would
require a range to begin before a range it already sits after.

Defence in depth alongside it: the savepoint now also catches `DeadlockDetected` (40P01)
and `LockNotAvailable` (55P03) — to a caller all three mean "offer the other two" — and the
request sets `SET LOCAL lock_timeout = '250ms'` so a lock wait can never eat the 400ms
voice budget.

**Verified.** 18 concurrent requests, deliberately divergent preferences, three rounds:
`served: 18, crashed: 0`, zero overlapping holds, and `pg_stat_database.deadlocks` still
reading **1** — the single pre-fix event, no new ones.

---

### 15. "That time just went" was sometimes a lie

Found while designing the above. `create_booking` matched only `state='ACTIVE' AND
kind='HOLD'`, so a hold that merely hit its 4-minute timer produced *"That time just went
while we were talking"* — **even when the slot was sitting empty**. Expiry means the
sweeper released it, not that anybody took it. A caller who paused to ask their partner
was being told a falsehood and losing a booking for no reason.

Two fixes, covering the two shapes of slow caller:

- `refresh_holds_for_call` — every tool call in a conversation pushes the caller's holds
  out (`greatest()`, so it can only extend). A caller who is still talking cannot lose
  their slot to the clock. Takes Vapi's call id and joins to ours: passing one where the
  other belongs has already caused one failure in this codebase, so the join removes the
  chance to get it wrong again.
- `sql/resurrect_hold.sql` — for the caller who goes silent and produces no tool calls,
  bring the row back if the slot is still free. Setting `state='ACTIVE'` re-enters the
  exclusion constraint's predicate, so the constraint itself adjudicates: success proves
  the slot was free, and 23P01 proves it really was resold. Narrow by design — only rows
  this same call expired on a timer, never a `RELEASED` row, never another caller's.

The remaining honest failure is now only the case where the world genuinely changed under
the caller — which is exactly when saying so is right.

---

### 16. Toolchain friction, recorded so it is not re-hit

- `psycopg[binary]>=3.2` added (not psycopg2 — native range and jsonb handling).
- `pytest-asyncio` with `asyncio_mode = "auto"`: every port method is async, and marking
  each test individually is noise.
- mypy strict: `src/grace_testing/fake_pms.py` was "found twice under different module
  names" until `__init__.py` existed in the three new packages.
- ruff: `Page` moved to PEP 695 `class Page[T](BaseModel)`; `TC003`/`N818` are per-file
  ignored under `ports/` — Pydantic resolves annotations at runtime so its imports cannot
  move into a `TYPE_CHECKING` block, and the error names are fixed by `provider-adapters.md`.

`make check`: mypy 48 files, ruff, **31 tests** (14 pre-existing + 17 new), vapi checks,
n8n 18 rules, docs-check, docs-lint 21 documents — green. The new tests touch neither the
database nor the network, so the gate still runs on a machine with no Postgres.

---

## 6 August 2026

**Commits:** *(uncommitted working tree)*

---

### 1. `.env` was gitignored, documented, and inert — the Makefile never loaded it

`.env.example` existed; nothing sourced `.env` at all, so every value in it was decorative. Fixed
with:

```make
-include .env
export
```

at the top of the `Makefile`, ahead of the `.PHONY` line, so every recipe inherits it. Verified
rather than assumed: a `make`-assignment take precedence over an *inherited* environment value,
including an **empty** one — confirmed live by writing a throwaway `.env` with a blank
`N8N_API_KEY=` and watching a real, working deploy 401.

**Consequence caught before it shipped:** the first draft of `.env.example` wrote all 24 project
variables as `KEY=` (unset ones included). Given the precedence above, copying that template
verbatim would silently blank any variable the user had already exported in their shell — a
functioning credential replaced by an empty string, with no error. Fixed by leaving every
currently-unset variable **commented out** instead of assigned-blank; the warning is now stated in
the file, the Makefile comment block, and `Docs/plans/10-access-and-credentials.md`.

`.env.example` trimmed from ~140 lines (per-variable rationale prose) to ~35 (variable + one-line
grouping comment); the rationale moved to `10-access-and-credentials.md`, which is where a reader
goes to ask *why*, not *what to fill in*. Real `.env` populated from the live shell and from
`platform/.env` (found holding the same RingCentral secrets as two raw JSON blobs, `KEY=value`
malformed, confirmed never git-tracked) — values parsed and rewritten file-to-file, never echoed
into the conversation; only lengths were checked to confirm non-empty.

**Side effect:** re-running `make n8n-diff` after this surfaced real drift on WF-12 and WF-17 —
node positions shifted, some parameters normalized — the signature of a dashboard save happening
after their last known-clean deploy. `make n8n-apply` pushed git's version back over it; two
consecutive diffs afterward reported clean. First time the drift check has caught a real,
unexplained change rather than a comparison-methodology bug.

---

### 2. Vapi phone number — created live, and answered a real call

| | |
|---|---|
| **Number** | `+1 651-386-9103` (`fe95f6cf-191a-496e-b6c1-c6c34efb77f1`) |
| **Command** | `make vapi-apply ENV=dev` |
| **Tunnel** | `cloudflared tunnel --url http://localhost:4242` → `https://voip-adelaide-treating-settled.trycloudflare.com`, health-checked (`{"ok": true}`) before apply |
| **`.lock.json`** | `phoneNumberIds."Grace line (dev)"` now recorded; `lastAppliedSha f32b025…`, `lastAppliedAt 2026-08-06T10:37:05Z` |

First `--apply` moved all 15 tools and the assistant's `server.url` off `placeholder.invalid` onto
the tunnel cleanly, then raised on phone-number creation: Vapi had **no 847 numbers available** on
this account and offered `272`/`572`/`651` instead. Not a deploy defect —
`deploy_phone_numbers()` stopped rather than silently substituting an area code, exactly as
designed. `platform/vapi/phone-numbers/grace-line.json`'s `numberDesiredAreaCode` changed to
`651`; the area code is cosmetic here (the number is never customer-facing — RingCentral will
eventually forward to it invisibly), so the substitution carries no design consequence. Second
apply reported `=` on everything already applied and created only the number.

**Live test:** dialled `+1 651-386-9103` from a personal phone. Grace answered, spoke the required
recording disclosure, and the mock server's logs showed tool calls arriving through the tunnel for
a full booking conversation. User-confirmed working. This is the **first call to reach Grace since
the assistant went live on 3 August** — every prior "deployed" claim about her was necessarily
unverified past the assistant/tool-registration level, because nothing had ever dialled in.

**Still not true, stated plainly:** the number is not wired to RingCentral's forwarding — 847.961.4800
still routes through its nine existing company rules, untouched, because no RingCentral write code
exists yet (§ RingCentral, prior entry). Every answer Grace gave came from
`mock_server/fixtures.py`, not Vagaro.

---

### 3. Vagaro integration — live-doc research complete, phased plan approved, zero implementation

GATE-01 (does Vagaro's API support appointment writes, and what does its data channel actually look
like) has been open since the project's first design doc. Today, for the first time, it was
answered from Vagaro's own current documentation rather than from the 31 July secondary-source
reading recorded in `Docs/PalmLeaf_AI_Receptionist_Architecture.md` §1.

**Fetched:** `docs.vagaro.com/public/docs/introduction`, `.../reference/api-introduction`,
`.../docs/webhook-events`, `.../docs/appointment-events`, `.../docs/transaction-events`;
`support.vagaro.com`'s webhook-setup article 403'd every automated fetch attempt (site blocks
bots), so its content was reconstructed via `WebSearch` snippets instead.

**Confirmed, not assumed:**

| Finding | Detail |
|---|---|
| Webhook event types | 6: `appointment`, `customer`, `transaction`, `formResponse`, `businessLocation`, `employee` — each with `created`/`updated`/`deleted` actions |
| Dedupe key | Every event carries a unique `id`, documented for exactly this: "may be used to ensure that an event is not processed twice" |
| Delivery SLA | Endpoint must return 2xx within **20s**; undelivered events retry **5 times over 15 minutes** with backoff |
| Appointment payload | `appointmentId, serviceId, serviceTitle, serviceProviderId, customerId, businessId, startTime/endTime, bookingStatus, amount, bookingSource…` |
| Transaction payload | Full tender breakdown (`ccAmount, cashAmount, checkAmount, achAmount, …`), tip, tax, discount, `appointmentId`/`customerId` linkage — reconciliation-grade |
| Rate limit | **~5,000 calls/month ≈ 166/day** — the number the whole mirror-architecture decision (I1) was designed around, now confirmed rather than assumed |

**Resolved via `AskUserQuestion`:** Vagaro API access has already been **requested and is in the
7-business-day activation queue** ($10/mo, 5,000 calls/mo) — not yet submitted, as the architecture
doc's outstanding action item implied. Payments scope for this phase: **read-only + booking**
(Grace can book; money still changes hands at the salon; transaction webhooks feed reporting only,
no deposit links, no card data spoken — I5 upheld). One user misconception corrected in-plan: Vapi
and n8n host themselves under their own paid plans; the only self-hosted pieces are the tool server
(`grace_api`) and its Postgres mirror.

**Plan produced and approved** (`/home/mehmood/.claude/plans/currently-if-you-memoized-fountain.md`,
`ExitPlanMode` approved 2026-08-06T12:28:50Z): four phases — V0 foundations (schema, ports, fakes,
`grace_api`, availability engine, booking saga — no Vagaro credentials required, can start
immediately), V1 discovery + read integration (gated on the activation email), V2 writes
(evidence-gated: native PMS write if discovery confirms it, otherwise the existing STAFF_QUEUE path
ships as-is), V3 real data on the real line. Contract conflicts the research surfaced and resolved:
slot-id format (`hold-XXX` wins over availability-engine's `'h'+base32`), webhook dedupe key
(Vagaro's `id`, hash kept only as fallback), and a **new mirror-staleness gate** — if the local
sync hasn't succeeded in 30 minutes, `checkAvailability` refuses to offer slots rather than risk
confidently-wrong availability.

**Session ended here** — Fable hit its monthly spend limit immediately after plan approval
(`2026-08-06T12:28:51Z`), before Opus began V0. Zero implementation code exists for this plan; the
next session picks up at V0.1 (schema).

---

## 5 August 2026

**Commits:** *(uncommitted working tree)*

---

### 1. Reporting domain → one orchestrator + two library sub-workflows

| | |
|---|---|
| **New files** | `WF-23-core-api-report-fetch.json`, `WF-24-vapi-call-fetch.json`, `WF-25-reporting-orchestrator.json` |
| **Converted** | WF-07, WF-11, WF-20, WF-21, WF-22 — `scheduleTrigger` → `executeWorkflowTrigger` (`inputSource: passthrough`) |
| **Live ids (dev)** | WF-23 `R83ajpEc5kBPOkW8` · WF-24 `4wKh5fUagueLVmRH` · WF-25 `2RQYvTa95jSt3Qeh` |
| **Doc** | `Docs/plans/04-n8n-layer.md` §10.5 |

WF-25 holds five `scheduleTrigger` nodes (03:15 daily, hourly :20, 07:30 daily, Mon 09:00, hourly
:07), each wired to an `executeWorkflow` node targeting `__WF__:wf-07/-11/-20/-21/-22`. It is the
only file in the reporting domain with `settings.timezone: America/Chicago` now; the five reports
had theirs removed along with their triggers.

Each report is now six nodes: `Called by WF-25` → `Shape the request` (a Code node emitting just the
window and page size, or a `{path}`) → `Fetch via WF-23/24` → the existing summarise Code node →
Data Table → the disabled Postgres node. **The Data Table and Postgres nodes were carried across
byte-identically** apart from an x-position shift, because a changed column shape would be a silent
data break rather than a visible failure (AC-09.15).

WF-24's contract: one item, `{ calls: [...] }`, each call carrying `{id, startedAt,
durationSeconds, endedReason, booked, escalated, medicalHold, intent, recordingUrl}` — `booked` and
friends compared with strict `=== true`, `intent` defaulting to `'unknown'`, matching what
WF-20/21/22 previously computed inline three times over. WF-23's contract: `{ok, statusCode, body,
unreachableMessage}`.

**The one-switch property** is a consequence of the trigger type, not of convention: a workflow
whose only trigger is `executeWorkflowTrigger` cannot fire without a caller, so deactivating WF-25
stops all five reports and nothing else (AC-09.16).

**Cost, recorded honestly:** every Execute Sub-workflow call is a separate n8n execution against
the plan's shared dev+prod quota. A report run went from ~1 execution to ~3 (~50/day → ~150/day
across the five). WF-19's 15-minute heartbeat was deliberately left standalone — a watchdog must not
share a switch with what it watches, and it is the highest-frequency workflow we own.

---

### 2. Deploy ordering defect: n8n validates sub-workflow references on **write**, not on activate

`deploy.py` already activated in dependency order. That was not enough. The first `--apply` died at:

```
PUT /workflows/CaqwD6oqREcr2mza → 400
Cannot publish workflow: Node "Fetch via WF-23" references workflow R83ajpEc5kBPOkW8
("[dev] WF-23 Core API Report Fetch") which is not published.
```

WF-07 sorts before WF-23 alphabetically, so its body was written before its callee was published.
Fixed with `in_dependency_order()`, a depth-first topological sort over `dependencies_of()` that
runs once on the local file list; the update loop then activates each workflow **immediately after**
its PUT rather than queueing it for a later pass. The reconcile-the-inactive pass still runs, now
skipping anything already published in the main loop. Re-running `--diff` afterwards reports
`✓ no drift` across all eleven deployable workflows.

---

### 3. WF-12 → native Header Auth (Q-04.5 closed)

Deleted: `Verify signature` (Code, HMAC-SHA256 over `${ts}.${rawBody}` reading
`$env.GRACE_N8N_WEBHOOK_SECRET`), `Authenticated?` (IF), `Respond 401`. Added: `Parse event`, a Code
node that only parses `rawBody`. The Webhook node gained `authentication: "headerAuth"` plus the
`__CRED__:n8n-inbound` credential block copied from WF-17; `webhookId: grace-escalation` and
`rawBody: true` are unchanged, so the live URL does not move.

Root cause: an n8n Cloud Code node can read neither the environment
(`N8N_BLOCK_ENV_ACCESS_IN_NODE`) nor a credential, so the HMAC check could never execute — the
workflow was undeployable as written, not merely unproven. Consequence: `ENV_ACCESS_KNOWN_BLOCKED`
in `lint.py` is now the empty set, and rule 17 has no exceptions left. WF-12 (like WF-17) is now
SKIPPED by `make n8n-apply` until the `n8n-inbound` credential exists on the instance — expected,
and reported as "waiting on configuration" rather than failing the run.

---

### 4. Lint rules 16 and 18

**Rule 18 (new).** An `executeWorkflow` node's `workflowId` must match `^__WF__:[a-z0-9-]+$`. Same
failure class rule 11 covers for `errorWorkflow`: a raw id deploys green against one environment and
throws at runtime against the other. Negative test: WF-07's target set to `"abc123"` → rejected;
reverted.

**Rule 16 (extended).** The `alwaysOutputData` requirement was gated on the file containing a
`scheduleTrigger`. The report fetches moved into WF-23/WF-24, whose trigger is
`executeWorkflowTrigger`, so the rule would have silently stopped covering the exact nodes it was
written for. Gate widened to either trigger type. Negative test: `alwaysOutputData` dropped from
WF-24's fetch → rejected; reverted.

The widened gate also caught **WF-18**'s three HTTP nodes, which was not anticipated but is a
genuine instance of the same bug: an empty response from `Still unacknowledged?` would skip
`Final escalation`, silently ending an escalation chain. `alwaysOutputData: true` added to all
three.

---

### 5. `WORKFLOW_ALIASES` replaced by a derivation

The hand-maintained `{"wf-00": "WF-00", ...}` dict would have needed eight new entries after this
refactor. Replaced with `_alias_prefix()` over `^wf-(\d+)$` — validated, not looked up. A malformed
alias still fails closed through the existing `unresolved` path rather than resolving to nothing.

---

### 6. Vapi: deploy-time transfer number, phone-number skeleton

`platform/vapi/tools/transferToHuman.json` **keeps `"destinations": []`** in git — a placeholder
string there would fail Vapi's own schema validation, and `validate.py` asserts the empty list.
Instead `deploy.py` injects `{"type": "number", "number": <GRACE_TRANSFER_NUMBER>, "message":
"Transferring you now."}` at deploy time (`TransferDestinationNumber`, required fields `type` and
`number`, checked against the committed OpenAPI snapshot). When the env var is unset the deployer
prints a waiting-on-configuration notice and leaves the list empty — it never substitutes a
stand-in, because an invalid number makes Vapi attempt a real transfer to garbage mid-call
(AC-09.18).

New `platform/vapi/phone-numbers/main.json` is a `CreateByoPhoneNumberDTO` skeleton (required:
`provider`, `credentialId`) with `"__PHONE__:main-line"` as the number. `deploy_phone_numbers()` is
a printed no-op while `GRACE_MAIN_LINE_NUMBER` is unset; the rationale and the placeholder table live
in `platform/vapi/phone-numbers/README.md` rather than in the JSON, since the DTO does not declare a
comment field. The kill switch stays RingCentral-side per `telephony.md` §3.1 — nothing in Vapi
implements a stop.

---

### 7. Generated docs: call graph

`gen_workflows.py` now scans every workflow's `executeWorkflow` nodes for `__WF__:wf-(\d+)` and
builds `calls` / `called_by` maps, printed as `**Calls:**` / `**Called by:**` lines under each
page's error-handler line and as a new "Calls" column in the index. Without it, WF-23's page could
say only "called by another workflow" and never by whom. `LIVE_IDS` gained WF-07, WF-11, WF-17 and
the three new ids above.

---

### 8. WF-26 Send Report Email — the third library sub-workflow

| | |
|---|---|
| **New file** | `platform/n8n/workflows/WF-26-send-report-email.json` |
| **Nodes** | `Called by report` (`executeWorkflowTrigger` 1.1, `inputSource: passthrough`) → `Send email` (`emailSend` 2.1, `smtp` credential) |
| **Contract** | in: one item `{subject, body}` · out: one email, text format, from `grace@palmleafmassage.com` |
| **Callers** | WF-07, WF-20, WF-21, WF-22 — each via an `executeWorkflow` 1.2 node targeting `__WF__:wf-26` |
| **Doc** | `Docs/plans/04-n8n-layer.md` §10.5 |

Same shape as WF-23/WF-24: no independent trigger, so it cannot fire without a caller. Each caller
gained two nodes between its Data Table node and its disabled Postgres node — `Shape the email`
(Code 2) and `Email via WF-26` (`executeWorkflow` 1.2) — with the Postgres node shifted +440 on x.

The `Shape the email` nodes differ in exactly one respect, and it is the one that matters: WF-07 and
WF-20 read `$json` (their summarise step emits a single row), while **WF-21 and WF-22 read
`$input.all()`** because their Data Table node ran once per sampled/flagged call. Reading
`$input.first()` there would have sent 20 separate emails for a weekly sample. WF-22 additionally
short-circuits with `if (!items.length) return []`, preserving the existing property that a clean
hour produces no output at all — `Flag problem calls` already returns `[]`, so this is belt-and-braces.

---

### 9. Defect fixed: WF-07's email node addressed an undefined field

The deleted node:

```jsonc
{ "name": "Email the report", "type": "n8n-nodes-base.emailSend", "disabled": true,
  "parameters": { "toEmail": "={{ $json.email_to }}", ... } }
```

Nothing in WF-07 ever set `email_to`. `Summarise the night` emits `{ran_at, checks_total,
checks_failed, drift_records, summary}` — no recipient field, and WF-23 does not supply one either.
Enabling the node would have resolved `toEmail` to the empty string and failed at send time, after
the credential had been created and the node deliberately switched on — i.e. the failure was staged
to appear at exactly the moment someone believed they had finished the configuration. The node is
deleted rather than repaired; the recipient now comes from the environment via WF-26.

---

### 10. `__EMAIL__:` placeholder — mirrors `__URL__:`, but blocks instead of falling back

`src/grace_platform/n8n/deploy.py`:

```python
EMAIL_VARS: dict[str, str] = {"reports-to": "GRACE_REPORTS_EMAIL_TO"}
```

resolved in `render()`'s `walk()` alongside the existing `__CRED__:` / `__URL__:` / `__WF__:`
branches. WF-26 commits `"toEmail": "=__EMAIL__:reports-to"`. Deploy-time resolution is forced by
the same constraint as `URL_VARS`: n8n Cloud sets `N8N_BLOCK_ENV_ACCESS_IN_NODE`, so `$env` inside a
node throws on every execution.

**The deliberate asymmetry:** `__URL__:` substitutes `URL_UNSET`
(`https://core-api.not-built.invalid`) when the variable is unset and lets the deploy proceed —
an unreachable host fails loudly and harmlessly. There is no safe placeholder email address. A wrong
one bounces somewhere unintended, or is accepted by the SMTP server and silently delivered to
nobody, which is indistinguishable from success inside n8n. So an unset `GRACE_REPORTS_EMAIL_TO`
appends to `unresolved`, `render()` returns `None`, and the deploy **skips WF-26** exactly as it
does for a missing credential. No new lint rule was needed: rule 10 (credential placeholder format)
and rules 6/11 (`errorWorkflow`) already cover `emailSend` and `executeWorkflow` generically.

---

### 11. Verification

`make check` green: mypy strict 34 files, ruff, 14 tests, 13 tool schemas, `n8n-lint` **14
workflows × 18 rules**, `docs-check` 16 tool + 15 workflow pages, `docs-lint` 20 documents.

`make n8n-diff ENV=dev` reports five SKIPPED and no drift among the rest:

```
  ⚠ SKIPPED WF-26-send-report-email.json — blocked on configuration:
      email "=__EMAIL__:reports-to" — set GRACE_REPORTS_EMAIL_TO
      credential "smtp" → PalmLeaf Email (dev)
  ⚠ SKIPPED WF-07 / WF-20 / WF-21 / WF-22 — blocked on configuration:
      workflow "wf-26" → WF-26
```

The four callers are skipped **transitively**: `__WF__:wf-26` cannot resolve because WF-26 was never
created on the instance, so `dependencies_of()` has nothing to point at. This is the same transient
state WF-07 and WF-11 passed through before WF-23 existed, and it clears on the first
`make n8n-apply` after the `smtp` credential and `GRACE_REPORTS_EMAIL_TO` are supplied. Nothing was
applied. The nine already-deployed workflows still report `=`.

---

### 12. Review defect: Postgres would have received the email item, not the report row

First cut wired the new nodes serially — `Save digest` → `Shape the email` → `Email via WF-26` →
`Archive to Postgres` — in WF-20/21/22. Postgres is disabled today, so nothing broke, but the wiring
meant that whoever flips it on later (per §9's "five steps and no redesign") would get `{subject,
body}` written into `call_metrics`/`call_samples`/`call_flags` instead of the real columns, since a
node receives whatever its immediate predecessor emits — silently, because a disabled node's column
mapping isn't checked against what actually reaches it until it runs. Same defect class as WF-07's
`email_to`: correct-looking today, broken at the moment someone finishes the configuration it was
waiting on.

Fixed by branching `Shape the email` and `Archive to Postgres` **in parallel** off the Data Table
node, rather than chaining them — n8n's `connections` format fans a single output to multiple targets
from one array entry:

```json
"Save digest": { "main": [[ {"node": "Shape the email"}, {"node": "Archive to Postgres"} ]] }
```

Both branches now receive the same items the Data Table node did. WF-07 was never affected — it has
no Postgres node. Re-verified: `make check` green, `make n8n-diff ENV=dev` unchanged (still five
skipped, nine at `=`).

---

### 13. Generator gap: a workflow with no `STATUS` entry rendered as `—`

`gen_workflows.py` reads two hand-maintained dicts keyed by `WF-NN`. WF-26 was added to
`platform/n8n/workflows/` without a `STATUS` entry, and `STATUS.get(wf_id, "—")` silently produced a
page whose status line read `—`. `docs-check` passed, because the generated output matched what the
generator produced — the check compares generated-to-committed, and cannot detect a missing input.
Entry added; the same fallback still exists and will do this again for WF-27.

Added alongside it: a `PURPOSE` dict and a **"What it does, and when it runs"** section on every
workflow page, mirroring the tool pages' "What it does, and when Grace calls it". The node table
already said what each node did; nothing said what the workflow was *for*, which is the one thing a
reader cannot reconstruct from a node list.

---

### 14. Recorded why the orchestrator pattern stops at the async boundary

`04-n8n-layer.md` §10.6, written in response to the question directly: should there be a Vapi-facing
mirror of WF-25 — one workflow receiving every tool call, routing to sub-workflows, replying to
Vapi?

No. That is ADR-0002's rejected design, and the router it describes already exists as `grace_api`.
The routing idea is sound; the placement is what differs, and the four reasons are all specific to
the synchronous path: a 400 ms p95 budget decided by the tail, ~3 hops of queue time on a shared
dev+prod instance, a booking that must be one Postgres transaction (n8n has no primitive spanning
nodes), and money logic under I4 that must be unit-testable in CI.

The execution-multiplication argument is not hypothetical here — item 1 above measured it at ~1 → ~3
per report run. Free when nothing waits; unaffordable mid-sentence. ADR-0002's documented fallback
(n8n calling the same domain logic through one internal endpoint per tool, ~a day) keeps the
decision reversible. Recorded in the document because §10.5 actively invites the question.

Also added: `Docs/plans/10-access-and-credentials.md`, the access/credential register — every
`__CRED__:`, `__URL__:` and `__EMAIL__:` alias, what supplies it, and what it blocks. 21 documents
now conform to the template.

---

### 15. RingCentral read-only client + snapshot (`make rc-snapshot`)

| | |
|---|---|
| **New files** | `src/grace_platform/ringcentral/{__init__,client,snapshot}.py`, `platform/ringcentral/README.md`, `platform/ringcentral/snapshot/*.json` (21 files) |
| **Dependency** | `ringcentral>=0.9` (+ a mypy `ignore_missing_imports` override — the SDK ships no `py.typed`) |
| **Auth** | Private JWT app, `SDK(client_id, client_secret, "https://platform.ringcentral.com")` → `platform.login(jwt=…)` |

Live run succeeded first attempt, no scope errors. Account `3041612036`, RingEX Core™,
`mainNumber: +18479614800`, `operator.id 3041612036` (ext 101). 17 extensions, 4 numbers
(1 main, 2 DID, 1 fax-only).

**The finding that moves Phase 2.** `GET /account/~/extension/{id}/answering-rule` returns
`403 This API is not available with enabled feature [NewCallHandlingAndForwarding]`. The
**company-level** `GET /account/~/answering-rule` is unaffected, and that is where the routing for
the main line lives: 9 rules, every custom one keyed on
`calledNumbers: [{"phoneNumber": "+18479614800"}]` plus a `schedule.weeklyRanges`, every one using
`callHandlingAction: "Bypass"` with `extension: {id}` — i.e. handing off to an IVR menu or voicemail
box, never forwarding to a number. So Phase 2's `grace-pilot-whitelist` is a company rule, and the
one shape still unobserved is an *external forward*: no existing rule performs one, so it must be
confirmed against a live GET before any write.

Enabled: `business-hours-rule`→ext 3226354036 (IVR 1002), `after-hours-rule`→ext 3981763036
(Voicemail 4), `5980745036` 1st Shift, `539433037` 2nd Shift, `6068302036` Wknd Open hrs,
`6244998036` In-Office Receptionist. Disabled: `4516027036`, `6071753036`, `6203771036`.

- **L3 unresolved by design, not by omission.** No rule declares a `forwarding` object, so there are
  no `ringCount`/`mobileTimeout` values to read — the timing sits inside the IVR menus each rule
  bypasses to. Stays an empirical Stage A observation.
- **L9 unresolved from the account.** `service-info.limits` publishes `cloudRecordingStorage`,
  `freeSoftPhoneLinesPerExtension`, `maxExtensionNumberLength`, `maxMonitoredExtensionsPerUser`,
  `meetingSize` — nothing about concurrency; `billingPlan.includedPhoneLines: 0`.
- `/extension/{id}/greeting` 404s on this account; greeting refs are captured inside each rule
  instead (`greetings[].custom.id` / `.preset.id`). No further endpoint guessing on a live line.

Every GET is wrapped: a failure writes `{"_unavailable": "<status> <message>", "_path": …}` into
that file rather than aborting the run — which is why the 403 above is itself committed, as
`extension-answering-rules.json`. `_error_note()` deliberately does **not** use the SDK's
`ApiResponse.error()`, which appends the full prepared request including the `Authorization` header.
`scrub()` strips `token`/`accessToken`/`refreshToken`/`password`/`authorization`/`clientSecret` at
any depth and redacts any string value containing `access_token=`; phone numbers are kept on
purpose. Second run reported `✓ no drift`; `grep` for credential keys over the snapshot is clean.

---

### 16. `deploy_phone_numbers()` — stub → real, diff-only this pass

`platform/vapi/phone-numbers/grace-line.json`: `provider: "vapi"`,
`numberDesiredAreaCode: "847"`, `assistantId: "${GRACE_ASSISTANT_ID}"`,
`fallbackDestination` → `${GRACE_FRONT_DESK_NUMBER}` (`CreateVapiPhoneNumberDTO`, required:
`provider`). `main.json`'s dead `"__PHONE__:main-line"` — which had no resolver at all — became
`"${GRACE_MAIN_LINE_NUMBER}"`.

- `${GRACE_ASSISTANT_ID}` resolves from `.lock.json`'s `assistantId`, **not** the environment:
  the only id certain to be real is the one the last apply recorded. Missing lock → hard exit with
  the command to run.
- Unresolved `${VAR}` ⇒ the file is **skipped** with a waiting-on-configuration notice (the n8n
  deployer's blocked-workflow UX), except `GRACE_FRONT_DESK_NUMBER`, which prunes only its own
  block. `prune_empty()` drops the empty `number` key but leaves the enclosing object, and
  `TransferDestinationNumber` requires `number` — so the deployer pops the whole
  `fallbackDestination` explicitly and says why.
- `numberDesiredAreaCode` is create-only (absent from `UpdateVapiPhoneNumberDTO`), so it is excluded
  from both the comparison body and the PATCH — otherwise it would report drift that can never
  converge, the same failure mode as n8n's server-minted `webhookId`.
- Diff reuses `compute_drift` (remote vs `deep_merge(remote, local)`), matches by `name`, and
  `--apply` records `phoneNumberIds` in `.lock.json`. Client gained
  `list_/create_/update_phone_number`. The step moved **inside** the client context manager, after
  the assistant, since a number binds to an assistant id.

`make vapi-diff ENV=dev` → `+ phone-number Grace line (dev) (would create)`, `main.json` skipped on
`GRACE_MAIN_LINE_NUMBER, GRACE_SIP_TRUNK_CREDENTIAL_ID`, everything else `=`. **Not applied.**

---

### 17. `transfer_destinations()` enriched; L11 resolved in comments

Now emits `callerId: "{{customer.number}}"` (A-04 — otherwise the transfer target sees Grace's
number, not the caller's) and a `transferPlan`: `mode: "warm-transfer-experimental"`,
`sipVerb: "dial"`, `dialTimeout: 25`, `fallbackPlan: {message, endCallEnabled: false}`. Every field
checked against `.vapi-openapi.json` before writing — `TransferPlan.mode` enum contains
`warm-transfer-experimental`, `sipVerb` enum contains `dial`, `dialTimeout` ≤ 600, `fallbackPlan`
→ `TransferFallbackPlan` (required: `message`). Mirrors the mock server's
`transfer-destination-request` response.

**L11**: `validate.py` mandates `destinations: []` so Vapi asks our server at transfer time; that
server-driven path is authoritative whenever a server is live (only it carries the per-call whisper
`flagEscalation` primes). This static injection is the **no-server fallback**, and the docstring now
says so.

Also: `make tunnel` wraps `cloudflared tunnel --url http://localhost:${GRACE_MOCK_PORT:-4242}`,
printing the two `.env` lines to paste before it execs, and failing with an install hint plus the
ngrok alternative if cloudflared is absent. `Docs/reference/infrastructure.md`'s claim that local
dev uses `vapi listen` was wrong and is corrected: `vapi listen` forwards Vapi's events to a local
port but gives the **tools** no reachable origin.

---

## 4 August 2026

**Commits:** `cf71434` · `2bfa938` · `8243e88` · `ec1a73e` · `f32b025` · *(restructure, uncommitted)*

---

### 1. Language port — TypeScript → Python (`cf71434`)

| | |
|---|---|
| **Scope** | ~3,200 lines across the two live platform layers |
| **Decision** | ADR-0014, superseding ADR-0001 |
| **Toolchain** | `uv`, Pydantic v2, httpx, pytest, ruff, mypy `strict` |

The generate-everything-from-one-schema pipeline was the strongest argument for the previous
stack. Pydantic reproduces it exactly via `model_json_schema()`, so the migration is parity rather
than regression. What stayed JavaScript: the browser web-call harness (it runs in a browser) and
n8n Code nodes (n8n executes them) — about 60 lines combined.

**Verified at the port boundary**, against the *same* live assistant and workflows:

- generated tool JSON differs only where deliberately improved (portable regex, wording)
- `deploy --apply` then `--diff` → zero drift on the same assistant id
- the n8n linter catches the same five injected defects
- the mock server returns byte-identical spoken output; all 14 speech tests pass unchanged

**Three defects the port surfaced**, none of which existed before:

1. **Pydantic uses the class docstring as the schema `description`.** Internal implementation notes
   were being transmitted to the model as tool instructions — a live prompt-contamination bug. The
   generator now strips docstrings and `validate.py` fails the build if any reappear.
2. **Pydantic hoists enums into `$defs` and `$ref`s them.** Vapi has no `$ref` resolver, so the
   generator inlines them.
3. **Python distinguishes `1` from `1.0`; JSON does not.** Vapi echoed `1`, our config held `1.0`,
   and the drift check went permanently red on the first run. Integral floats are now collapsed
   before comparison.

**Separately, a pre-existing bug the port exposed:** `deploy.py` was writing an internal credential
*id* into the field n8n uses for the credential *display name*. n8n silently corrected it on every
apply, so the diff reported a change that could never converge. All three workflows now match
cleanly.

---

### 2. Four Python ADRs (`8243e88`)

The port moved the code that exists. The document set describes a much larger system that does
not — Core API, workers, the database — and named the old stack throughout. Three of these are
library choices; **the fourth is a safety guarantee that was being lost silently.**

| ADR | Decision | Why it is not a rename |
|---|---|---|
| **0015** | **arq** for the job queue | The outbox leans on *enqueue-same-id-runs-once*. arq dedupes within a **keep-alive window**, not for the job's lifetime — a different guarantee. Tracked as **A-22**; must be re-derived at task C-04, not assumed |
| **0016** | **SQLAlchemy 2.0 + Alembic** | Double-booking is prevented by `EXCLUDE … USING gist` over a `tstzrange`, expressed as `postgresql.ExcludeConstraint`. Whether Alembic round-trips it is **A-23**, open |
| **0017** | **FastAPI** | The replaced framework enforced request-lifecycle order via ordered plugin encapsulation. FastAPI has no equivalent: raw-body capture and signature verification must be **middleware** (they precede body parsing); tenant, deadline and idempotency are **`Depends`**. Getting it wrong does not crash — it verifies a signature against a re-serialised body |
| **0018** | **import-linter** | **ruff cannot express per-package boundaries.** `flake8-tidy-imports` bans a module globally, not "package A may not import package B". Without it, invariant **I1** is unenforced with no error and no warning |

> ⚠️ **ADR-0018 is decided but not implemented.** Contract 1 (`grace_contracts` imports nothing) is
> applicable today; contracts 2 and 3 need `grace_domain` and `grace_api`. Until then **I1 has no
> mechanical enforcement.** Tracked as roadmap task **A-08**.

---

### 3. Workflow WF-20 — Daily Call Digest (`ec1a73e`)

| | |
|---|---|
| **Source** | `platform/n8n/workflows/WF-20-daily-call-digest.json` |
| **Trigger** | Schedule, 07:30, `settings.timezone = America/Chicago` |
| **Data source** | `GET https://api.vapi.ai/call`, 30s timeout, `__CRED__:vapi` (Header Auth) |
| **Sink** | Data Table `call_metrics`, 7 columns |
| **Deferred sink** | Postgres node, **disabled**, `__CRED__:postgres` |
| **Error handler** | `__WF__:wf-00` |

Emits one row per day: `day`, `total_calls`, `booked`, `escalated`, `medical_holds`,
`avg_duration_seconds`, `containment_pct`. Containment is the headline number for an AI
receptionist — the share of calls handled without a human.

### 4. Workflow WF-21 — Weekly QA Sampler (`ec1a73e`)

| | |
|---|---|
| **Trigger** | Schedule, Monday 09:00 `America/Chicago` |
| **Sink** | Data Table `call_samples`, 9 columns |

Random sample of 20 calls with recording links and structured outcome. **Random, not
worst-first** — deliberately, so ordinary calls get listened to and slow behavioural drift is
caught rather than only the calls that already went wrong.

### 5. Workflow WF-22 — Call Quality Alert (`ec1a73e`)

| | |
|---|---|
| **Trigger** | Schedule, hourly at :07 `America/Chicago` |
| **Sink** | Data Table `call_flags`, 5 columns, `UNIQUE (call_id, reasons)` in the Postgres mirror |

Three signals, each meaning something different: the call **errored**, ended **under 15 seconds**
(a hang-up or a failure to engage), or **escalated**.

**All three workflows share one shape** — Schedule → HTTP → Code → Data Table → *(disabled)*
Postgres — and depend on **nothing that is blocked**: no Core API, no Postgres, no Vagaro, no
phone number. One new credential covers all three.

**Scope constraint (I6):** no transcript, caller name, phone number or health detail is collected.
Recording URLs are pointers into Vapi under Vapi's retention, not copies. A reporting pipeline is
the easiest place to accidentally create a second unlogged copy of sensitive data.

> ✅ **Correction (2026-08-04, later).** An earlier revision of this entry said these were "built
> but not deployed", inferred from the absence of an entry in the generator's hand-maintained
> `LIVE_IDS` map. **That map is not evidence.** Querying the instance shows all three deployed and
> `active`: WF-20 `p6dyf5QO26ZtApgG`, WF-21 `aqt18Lr8Y7pjBfcC`, WF-22 `45tFStlOPZ7yMizO`, and the
> `PalmLeaf Vapi (dev)` credential already exists. `LIVE_IDS` is now populated.
>
> They will still return empty results until Grace takes a real call.

---

### 6. Empty-result handling (`f32b025`)

A day with no calls previously wrote no row. **A missing report is ambiguous** — it could mean no
calls, or a broken workflow, and those demand opposite responses. All three workflows now emit an
explicit zero row.

This is also why lint rule 16 exists: an HTTP node feeding a scheduled report must set
`alwaysOutputData`, or n8n halts the branch on an empty response and the Code node never runs.

---

### 7. Postgres persistence — shipped switched off (`ec1a73e`)

n8n Cloud cannot reach a database on a laptop, so Postgres waits on a hosted instance (Neon or
Supabase free tier). Rather than defer the design, the path ships **present but disabled**:

- `platform/postgres/schema.sql` — `call_metrics`, `call_samples`, `call_flags`, all `IF NOT EXISTS`
- a disabled Postgres node already positioned after each Data Table write, query written
- `credentials.example.json` lists `postgres` under `deferred` with blocker and enabling steps

**The non-obvious part is lint rule 14.** The linter hard-fails any unresolved `__CRED__:`
placeholder — correct, because n8n deploys such a workflow green and then throws on first
execution. Shipping a half-wired integration would normally mean weakening that check globally.
Instead the exemption is scoped to **disabled nodes only**, so the check stays at full strength
everywhere it matters. Regression test: **AC-09.13**.

Turning it on is five steps and no redesign: create the database, run `schema.sql`, add the
credential, enable the node, `make n8n-apply`.

---

### 8. Generated reference — `gen_tools.py`, `gen_workflows.py` (`8243e88`)

Closes a real gap: of 15 tools, exactly one had any parameter documentation, split across three
documents, with its parameters shown as a code sample in the wrong file.

- **`gen_tools.py`** reads `TOOL_REGISTRY`, the generated JSON and `.lock.json` → 16 pages: every
  parameter with type, required, default, allowed values and meaning (from `Field(description=…)`);
  async/timeout/retry/p95/idempotency/outbox settings; spoken fallbacks; live Vapi id; source model.
- **`gen_workflows.py`** reads the workflow JSON → 7 pages: node-by-node table, mermaid connection
  graph, credentials, live workflow id.

`make docs-check` fails CI when either is stale, so these **cannot** drift.

**Two defects found and fixed today by reading the generated output** — both cases of the generator
misreporting *correct* configuration, which is the worst failure mode for a tool whose only job is
trustworthy documentation:

| Defect | Root cause | Effect |
|---|---|---|
| Three workflows documented as *"no timezone set"* | Read `parameters.timezone` on the schedule node; n8n stores it at **workflow** `settings.timezone` | Three correctly-pinned crons documented as unpinned — the exact ambiguity lint rule 15 exists to prevent |
| Data Table target rendered as `` `?` `` | Read `parameters.tableId`; the field is `dataTableId`, a **resource locator** (`{__rl, mode, value}`) | Every Data Table node's destination was unreadable |

Both now render correctly (`America/Chicago`, `call_metrics` / `call_samples` / `call_flags`, with
column counts).

---

### 9. Document template linter — `lint_docs.py` (`8243e88`, restructure)

Enforces the template mechanically across `Docs/plans/` and `Docs/reference/`: complete header
block; exactly one H1 on line 1; sections numbered contiguously from 1; **no heading inside a
fenced block**; a single cross-reference syntax; and no reference to the superseded stack outside a
line explaining the replacement.

Two mechanics worth knowing before editing a document:

1. **Banned-term exemption is line-based.** A superseded name and the word explaining its
   replacement must be on the **same physical line**. A wrapped sentence fails.
2. **Any `# ` prefix inside a fence trips the heading rule**, including Python and YAML comments.
   Use `#:` (valid in both) or move the note outside the fence.

The fenced-heading rule fixed a concrete problem: the Vapi prompt content was inlined inside a
```markdown fence, so ten prompt sections (`## IDENTITY`, `## STYLE`, …) leaked into the document
outline and broke every table of contents.

**Now wired into `make check` and `.github/workflows/ci.yml`** — the CI job ran explicit steps
rather than `make check`, so both needed the change. Result: ✓ 20 documents conform.

---

### 10. n8n scope change — WF-14 withdrawn (restructure)

WF-14 carried two surfaces on a third-party chat platform: an interactive "Resolved" button, and
`/grace-kill` — **the kill switch's only human-triggerable surface**. Neither is served by n8n's
trigger node for that platform (Events API only: no `block_actions`, no slash commands), so each
needed a raw Webhook node plus hand-written HMAC verification.

The workflow is **removed, not deferred**. What survives:

| Was | Now |
|---|---|
| Staff marks a task resolved | `POST /internal/tasks/:id/resolve` — callable from any future surface |
| `/grace-kill` | Runbook procedure against `POST /internal/tenants/:slug/kill-switch` |

Assumption **A-19** (who may invoke `/grace-kill`) is retired with the workflow; the authorization
question survives as **Q-05.1**.

> ⚠️ **Recorded as a regression, not a win.** The kill switch is now an authenticated API call made
> by a human following a runbook — measurably slower under pressure than a button, and the
> replacement has never been timed (AC-16.2). Restoring a one-click surface is a Phase F task.

---

### ⚠️ Open technical risks after today

| Risk | Status |
|---|---|
| **I1 has no mechanical enforcement** | ADR-0018 decided, task A-08 not done. Contract 1 is applicable today |
| **A-13 — Vapi HMAC payload format unknown** | Blocks C-05 outright: verification fails closed, so *every* tool call would be rejected |
| **A-22 — arq dedupe window** | Could produce a duplicate confirmation SMS. Mitigation (consumer-side `UNIQUE`) already required by at-least-once delivery |
| **A-16 — `toolCallId` on retry** | If a `backoffPlan` retry mints a new id, idempotency silently stops deduplicating. **Threatens I3** |
| **WF-20/21/22 undeployed** | Need the `vapi` credential in n8n; no live ids yet |
| **Grace has never taken a live call** | Tool URLs point at `placeholder.invalid`; every tool would fail |
| **WF-12 JSON edited** | A code-node comment changed; `make n8n-diff` will report drift until redeployed |

---

## 5 August 2026 (overnight — items 11-15 ran into the small hours of the 5th)

### 11. Two live production failures, found by querying the instance

Reading the n8n executions API rather than trusting the repository turned up two failures that no
document recorded.

**A. `Data table with name "call_metrics" not found` — WF-20, execution 7.**

The Data Table nodes reference tables by name (`dataTableId.mode = "name"`). **None of the tables
had ever been created** — `search_data_tables` returned zero. Every workflow that emits a row was
therefore dying at its final node.

The reason this went unnoticed is the interesting part. **WF-22 reported six consecutive successes
on the same broken configuration**, because its Code node returns `[]` when no call trips a signal —
so the Data Table node never executed. It was succeeding *vacuously*. The failure only surfaced on
WF-20, because WF-20 always emits a row — the "a quiet day must still produce a report" change from
commit `f32b025` is precisely what exposed it.

Fixed by creating five tables via the n8n API: `call_metrics` (7 cols), `call_samples` (9),
`call_flags` (5), `platform_heartbeat` (5), `workflow_errors` (5). Column types match what each Code
node emits — numbers as `number`, flags as `boolean` — rather than everything as text.

**B. `access to env vars denied` — WF-00, execution 8.**

n8n Cloud sets `N8N_BLOCK_ENV_ACCESS_IN_NODE`, so `{{ $env.X }}` throws on **every** execution.
Three workflows used it: WF-00, WF-12, WF-18.

The consequence was severe and silent: **WF-00 is the global error handler.** It failed while
handling WF-20's failure, so a failed workflow produced no report at all. Every n8n failure to date
has been invisible unless someone opened the executions list.

Two fixes:

1. **`__URL__:` placeholder, resolved at deploy time** by `deploy.py` from `URL_VARS`, exactly as
   `__CRED__:` already worked. Unset resolves to `https://core-api.not-built.invalid` — obvious, and
   non-routable by design.
2. **Lint rule 17** bans `$env.` in workflow JSON. `GRACE_N8N_WEBHOOK_SECRET` is the one entry in an
   explicit `ENV_ACCESS_KNOWN_BLOCKED` allowlist — see §13.

*(Rule 17's first regex was `\$env\.([A-Z_]+)`, which truncated `GRACE_N8N_WEBHOOK_SECRET` to
`GRACE_N` because environment names contain digits. Now `[A-Z0-9_]+`.)*

### 12. WF-00 rebuilt to report failures without Core API

Recording an error by POSTing to a service that does not exist is not error reporting. WF-00 now:

`Error Trigger → Format → **Record the failure** (Data Table `workflow_errors`) → Notify ops (HTTP)`

The Format node emits structured fields rather than one text blob. **`Notify ops` carries
`onError: continueRegularOutput`**, so the unreachable Core API can never be the reason a failure
goes unrecorded. Redaction is unchanged — workflow name, node name and message only, never the
failing payload (I6).

### 13. WF-12's HMAC secret — a real blocker, not fixed

WF-12 verifies an inbound signature inside a Code node, which needs the secret at runtime. On n8n
Cloud a Code node can read **neither** the environment **nor** a credential.

Deploy-time substitution — the fix used for URLs — is **wrong here**: it would write the signing
secret in plaintext into the workflow stored on the instance, readable by anyone with instance
access. That is worse than the problem.

Recorded as **Q-04.5** and allowlisted explicitly in the linter rather than silently tolerated.
WF-12 is dormant until Core API exists, so it cannot fire in production today.

### 14. WF-19 built and deployed

`WF-19 Platform Heartbeat` — `cmkpTUzQNe2hgycY`, active, every 15 min, `America/Chicago`.

Probes `GET https://api.vapi.ai/call?limit=1` with `neverError` + `fullResponse`, so a 4xx/5xx
arrives as data instead of throwing — a Vapi outage is *recorded* rather than destroying the
heartbeat meant to report it. Gap since the previous beat comes from
`$getWorkflowStaticData('global')`, avoiding a read-back node.

**Limit, stated plainly:** it cannot alert while n8n is fully down, because nothing runs. It gives
continuous liveness, missed-window detection on recovery, and Vapi-outage detection within 15
minutes — which had no coverage at all. A true dead-man's switch needs an external watchdog:
**Q-04.4**.

### 15. WF-15 and WF-16 were duplicates of WF-20 and WF-21

WF-16 and WF-21 shared a name (*Weekly QA Sampler*), a schedule (Mon 09:00 `America/Chicago`) and a
description (20 random calls). WF-15 and WF-20 likewise (both 07:30 daily). Building the inventory
as written would have fired two workflows at Mon 09:00 doing the same job.

Merged: WF-15 → WF-20, WF-16 → WF-21. When Core API exists those two gain the fields Vapi cannot
supply (bookings, open tasks, deposits outstanding) rather than being duplicated. Remaining n8n
workflows to build: **WF-07, WF-11, WF-17** — all gated on Core API.

### 16. WF-07, WF-11, WF-17 — the set completed ahead of access

Built so that the arrival of Vagaro, email, RingCentral or a phone number is a **configuration**
event, not a development one.

| ID | Live id | Trigger | Reads | Sink | Outstanding |
|---|---|---|---|---|---|
| **WF-07** Nightly Reconciliation | `CaqwD6oqREcr2mza` | 03:15 daily, `America/Chicago` | `__URL__:core-api/internal/reports/reconciliation` | `reconciliation_reports` (5 cols) | Core API; `__CRED__:smtp` to enable the disabled Email node |
| **WF-11** Hourly Call Digest | `rOz6zbgZzWIBY9Fv` | hourly at :20 | `__URL__:core-api/internal/reports/calls?window=1h` | `call_digests` (6 cols) | Core API |
| **WF-17** Vagaro Fan-out | `XNrOQHCRUOxffQG7` | webhook `POST {{ENV}}/fanout` | worker `webhook.fanout` event | `fanout_log` (5 cols) | `__CRED__:n8n-inbound`; consumer URLs |

**Each degrades to a row rather than a crash.** Every fetch sets `neverError` + `fullResponse` and
`onError: continueRegularOutput`, so an absent Core API arrives as a `statusCode` the Code node
inspects, emitting `"Core API unreachable (HTTP …) — not yet built"`. Same reasoning as §6.

**WF-11 is not a duplicate of WF-22.** WF-11 reports normal activity (calls, bookings, open staff
tasks) and needs Core API because Vapi cannot know about bookings or tasks; WF-22 reports faults
from Vapi directly. Both hourly, different questions.

### 17. WF-17 uses native Header Auth — the proposed fix for Q-04.5

WF-12 verifies an HMAC inside a Code node, which cannot work on Cloud: a Code node reads neither
the environment nor a credential. WF-17 instead sets the Webhook node's
`authentication: "headerAuth"` with `__CRED__:n8n-inbound`, which **n8n verifies itself before the
workflow runs**.

Trade-off, stated rather than glossed: a bearer token authenticates the *caller*; an HMAC over the
body additionally proves **body integrity** and gives **replay protection** via the timestamp. On
an internal worker→n8n hop over TLS with a ≥32-char secret, the bearer is defensible — and it is
the only one of the two that functions on this tier. **Migrating WF-12 to the same mechanism would
remove the last `$env` read in the set**; that is the proposed resolution for Q-04.5.

### 18. Deploy: skip a config-blocked workflow instead of aborting

`render()` previously called `sys.exit(1)` on an unresolved placeholder. Correct in intent —
n8n accepts such a workflow and throws on first execution (AC-09.8) — but it meant **one
un-created credential blocked every other workflow from deploying**, which is the wrong trade in a
phase where several integrations are deliberately waiting.

It now returns `None`; the caller skips that workflow, does not create a shell for it, and prints a
summary naming what it waits on. The guarantee is unchanged: a workflow that would throw is still
never published.

### 19. Deploy: activation is reconciled, not inferred from a diff

A second, quieter defect. Activation was queued only for workflows whose *definition changed*, so
one reported `=` (matching) but sitting `active: false` would **stay inactive forever**. WF-11 was
in exactly that state after the aborted run in §18.

The apply phase now checks `remote.active` for every non-blocked workflow and activates any that is
deployed but off. Deployed and running are different states, and only the second does any work.

### 20. New tables, credentials and URL aliases

Data Tables created: `reconciliation_reports`, `call_digests`, `fanout_log` — bringing the total to
eight. `platform/postgres/schema.sql` gained matching DDL for these plus `workflow_errors`.

`CREDENTIAL_NAMES` gained `n8n-inbound` and `smtp`. `URL_VARS` gained `crm` and `marketing`
(`GRACE_CRM_WEBHOOK_URL`, `GRACE_MARKETING_WEBHOOK_URL`) for WF-17's two disabled delivery nodes.

### 21. A third non-converging diff, same family as the first two

After WF-07 deployed, `n8n-diff` reported it changed on every run. n8n **mints a `webhookId` on
save** for some node types even when the committed file declares none — here on the disabled Email
node. Comparing raw meant a difference that could never be resolved.

`comparable()` now strips a `webhookId` from the remote node **only when the local file does not
declare one**. A declared `webhookId` is still compared, because dropping those would change a live
webhook URL — precisely what must not happen.

That is the third instance of this family today (credential *name* vs *id*; server-materialised
Vapi defaults; now server-minted `webhookId`). The pattern is worth naming: **any config-as-code
diff must compare against what the server does with our input, not against our input.**

Result: `make n8n-diff` → **no drift** across all nine deployed workflows.

### ⚠️ What is still genuinely blocked

| Item | Needs |
|---|---|
| WF-17 deployment | The `n8n-inbound` credential created in n8n |
| WF-07 email step | An SMTP credential and the client's sending domain |
| WF-07/11 producing real data | Core API `/internal/reports/*` |
| WF-17 consumer delivery | CRM and marketing endpoint URLs from the client |
| WF-12 on Cloud | Migration to Header Auth (Q-04.5) |
| Grace taking a call | A tunnel and a redeploy (B-12) |
