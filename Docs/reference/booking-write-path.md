# booking-write-path — Outbox, Saga, Tracks A/B/C/D

**Status:** Frozen — the outbox unblocks at [08-roadmap](../plans/08-roadmap.md) task **C-04**; the tracks unblock with their adapters in Phase D.
**Read before:** implementing workers, the booking state machine, or any PMS write.
**Implements:** ADR-0005, ADR-0006, ADR-0015
**Enforces:** I8
**Last verified:** 2026-08-04 — rewritten for arq (ADR-0015). **The dedupe guarantee must be re-derived against arq, not assumed — see A-22.**

> **In one paragraph:** this document settles how a booking survives a distributed system that has
> no atomic "create appointment" call — the transactional outbox, the saga states and their
> compensations, and the four write strategies selected by policy rather than by branching. It
> deliberately does **not** decide which track ships first; that follows from GATE-01 and GATE-07.

---

## 1. The problem in one sentence

There is no atomic "create appointment" operation available to us, so a booking is a distributed
transaction across Google Calendar, Stripe, Twilio, the PMS and a staff queue — and the caller hangs up
after 600ms regardless of how it goes.

The answer is: **commit the promise locally and durably, then keep the promise asynchronously, with
compensations for every way it can fail.**

---

## 2. Strategy selection

Which track runs is a *policy decision* made once per booking, from capabilities and flags — never a
scattered `if`.

```ts
// TARGET — src/grace_domain/booking/strategy.py   (PURE)
export function selectWriteStrategy(input: {
  capabilities: PmsCapabilities;
  flags: { trackA: boolean; trackB: boolean; trackC: boolean };
  trackAValidated: boolean;        // ⛔ GATE-07 result
  service: Service;
  callerPrefersSelfServe: boolean;
}): WriteStrategy {
  if (input.capabilities.writeAppointments) return 'NATIVE_PMS';        // best case
  if (input.callerPrefersSelfServe || !input.flags.trackA) return 'SELF_SERVE_LINK';
  if (input.trackAValidated && input.flags.trackA) {
    return input.flags.trackB ? 'CALENDAR_HOLD_THEN_WIDGET' : 'CALENDAR_HOLD_THEN_STAFF';
  }
  return 'STAFF_QUEUE';                                                  // always terminates somewhere
}
```

| Strategy | Slot held by | True PMS appointment created by | Caller experience |
|---|---|---|---|
| `NATIVE_PMS` | PMS write | the API | identical |
| `CALENDAR_HOLD_THEN_WIDGET` | Google Calendar → PMS sync | Playwright worker | identical |
| `CALENDAR_HOLD_THEN_STAFF` | Google Calendar → PMS sync | staff, from a task | identical |
| `SELF_SERVE_LINK` | nothing until they tap | the caller | "I've texted you the link" |
| `STAFF_QUEUE` | our reservation only | staff | identical |

**The caller hears the same thing in the first three and the last.** That is the design goal from the
brief §1.4 and it is preserved here.

⛔ **This function's `trackAValidated` input is false until GATE-07 is answered.** Until then the system
selects `SELF_SERVE_LINK` or `STAFF_QUEUE` and is fully shippable — that is exactly the design brief's
Phase 1. No code is blocked.

---

## 3. The transactional outbox

### 3.1 Write side

Domain writes and outbox rows commit together, always (I8):

```ts
// TARGET — src/grace_db/repositories/outbox.py
export async function emit(tx: Transaction, events: OutboxEvent[]): Promise<void>
```

Called only from inside an existing transaction. There is no `emit` that opens its own transaction —
that would defeat the entire pattern. A lint rule flags `emit(db,` (the pool) as an error.

### 3.2 Dispatch side

```
sync-worker: every 250ms, and on LISTEN 'outbox_new'
  SELECT ... FROM outbox_events
   WHERE status IN ('PENDING','FAILED') AND available_at <= now()
   ORDER BY available_at, id
   LIMIT 50
   FOR UPDATE SKIP LOCKED               ← the whole concurrency story, in one clause
  → mark IN_FLIGHT, locked_by = <worker id>, locked_at = now()
  → enqueue an arq job with job_id = outbox_events.id  ← dedupe hinges on this; see A-22
  → on job success  : status = DONE, processed_at = now()
  → on job failure  : attempts++, status = FAILED,
                      available_at = now() + backoff(attempts)
  → attempts >= max_attempts : status = DEAD + P1 staff task + alert
```

`FOR UPDATE SKIP LOCKED` means N dispatcher instances can run with no coordination and no double-dispatch.
`jobId = outbox id` means a dispatcher crash between enqueue and status-update causes a duplicate enqueue
that a naive queue silently drops. arq replaces the queue named in the original design (ADR-0015).

Backoff: `min(2^attempts × 2s, 30min)` with full jitter. Attempts 1–8 span roughly 2s → 4h.

A row stuck `IN_FLIGHT` for >5 minutes is reclaimed (its `locked_at` is stale) — covers a worker that was
killed mid-job.

### 3.3 Consumer contract

**Every consumer must be idempotent, keyed on the outbox event id.** At-least-once is guaranteed;
exactly-once is not, and pretending otherwise is how duplicate SMS and double charges happen.

| Event type | Consumer | Idempotency mechanism |
|---|---|---|
| `calendar.create_event` | `sync-worker` | deterministic Google event id from booking id; 409 = success |
| `calendar.update_event` / `delete_event` | `sync-worker` | event id lookup; 404 = success |
| `payments.create_deposit_link` | `sync-worker` | Stripe `Idempotency-Key` = outbox id |
| `sms.send` | `sync-worker` | `messages.outbox_event_id` UNIQUE |
| `pms.write_appointment` | `booking-worker` | `bookings.pms_appointment_id` set ⇒ skip; plus §5.3 pre-check |
| `pms.cancel_appointment` | `booking-worker` | idempotent by nature |
| `staff.notify` | `sync-worker` | `staff_tasks` unique on (booking_id, type) where OPEN |
| `call.process_transcript` | `sync-worker` | `calls.summary_redacted IS NOT NULL` ⇒ skip |
| `mirror.apply_webhook` | `sync-worker` | `inbound_webhooks.dedupe_key` |

---

## 4. The booking saga

### 4.1 State machine

```
                      createBooking (tool)
                              │
                      ┌───────▼────────┐
                      │     DRAFT      │  hold promoted, row written, outbox emitted
                      └───┬────────┬───┘
             deposit>0    │        │  deposit == 0
                          ▼        ▼
              ┌───────────────┐   ┌──────────────┐
              │PENDING_DEPOSIT│──►│  CONFIRMED   │◄── stripe: checkout.session.completed
              └──────┬────────┘   └──────┬───────┘
       24h unpaid    │                   │  emit pms.write_appointment
                     ▼                   ▼
               ┌──────────┐      ┌────────────────┐
               │ EXPIRED  │      │ WRITING_TO_PMS │
               │ (slot    │      └───┬────────┬───┘
               │ released)│    success│        │ 3 failures
               └──────────┘          ▼        ▼
                              ┌──────────┐  ┌─────────────┐
                              │  SYNCED  │  │ NEEDS_STAFF │  ← SLOT STAYS HELD
                              └────┬─────┘  └──────┬──────┘
                                   │               │ staff resolves
                                   └───────┬───────┘
                                           ▼
                                     ┌───────────┐
                                     │ CANCELLED │ (from any non-terminal state)
                                     └───────────┘
```

### 4.2 Transition table — implement literally

```ts
// TARGET — src/grace_domain/booking/transitions.py   (PURE)
export const TRANSITIONS: Record<BookingState, readonly BookingState[]> = {
  DRAFT:           ['PENDING_DEPOSIT', 'CONFIRMED', 'CANCELLED'],
  PENDING_DEPOSIT: ['CONFIRMED', 'EXPIRED', 'CANCELLED'],
  CONFIRMED:       ['WRITING_TO_PMS', 'SYNCED', 'NEEDS_STAFF', 'CANCELLED'],
  WRITING_TO_PMS:  ['SYNCED', 'NEEDS_STAFF', 'CANCELLED'],
  NEEDS_STAFF:     ['SYNCED', 'CANCELLED'],
  SYNCED:          ['CANCELLED'],
  CANCELLED:       [],
  EXPIRED:         [],
} as const;

export function assertTransition(from: BookingState, to: BookingState): void {
  if (!TRANSITIONS[from].includes(to))
    throw new IllegalStateTransition(`${from} → ${to}`);
}
```

Every transition goes through one function that (a) asserts legality, (b) bumps `version` with an
optimistic-concurrency `WHERE version = :expected`, (c) writes a `booking_events` row, (d) emits the
outbox events for that transition. There is no other way to change `bookings.state`. A lint rule and a
DB trigger both enforce it — the trigger raises if `state` changed without a matching `booking_events`
insert in the same transaction.

### 4.3 What each state emits

| Transition | Outbox events emitted |
|---|---|
| `→ DRAFT` | `calendar.create_event`, `sms.send:booking_confirmation` (provisional wording), `sms.send:intake_form` if required |
| `→ PENDING_DEPOSIT` | `payments.create_deposit_link`, `sms.send:deposit_link`, schedule `booking.deposit_reminder` (+60 min), `booking.deposit_expiry` (+24h) |
| `→ CONFIRMED` | `sms.send:booking_confirmed`, `pms.write_appointment`, `calendar.update_event` (title → confirmed) |
| `→ SYNCED` | `calendar.update_event` (annotate with PMS id) |
| `→ NEEDS_STAFF` | `staff.notify` P1 |
| `→ EXPIRED` | `calendar.delete_event`, `sms.send:slot_released`, `staff.notify` P3, occupancy release |
| `→ CANCELLED` | `calendar.delete_event`, `pms.cancel_appointment` (if synced), `sms.send:cancellation`, occupancy release, refund/forfeit per policy |

---

## 5. Track implementations

### 5.1 Track A — Google Calendar bridge

```ts
// TARGET — src/grace_worker/processors/calendar_create_event.py
const eventId = base32(booking.id);                       // deterministic ⇒ idempotent
await calendar.createEvent({
  calendarId: provider.googleCalendarId,
  summary: `${service.displayName} — ${customer.firstName} ${initial(customer.lastName)}`,
  description: renderTemplate('calendar_event_body', { booking, customer, service, source: 'Grace' }),
  startsAt: booking.startsAt, endsAt: booking.endsAt, timezone: tenant.timezone,
  idempotencyKey: eventId,
  metadata: { graceBookingId: booking.id, graceOccupancyId: booking.occupancyId },
});
```

Notes:
- Customer surname is initial-only in the calendar title — the calendar may be visible on personal
  devices. Full details live in the description, which is less exposed.
- On success, `bookings.track_a_event_id` is set. On permanent failure (calendar not found, permission
  revoked) → `NEEDS_STAFF` immediately; do not retry into oblivion.
- **Verification step:** 90 seconds after creation, a follow-up job re-reads the mirror to confirm the PMS
  picked the event up. If it did not, emit a P2 staff task. This turns the GATE-07 uncertainty into a
  *monitored* assumption rather than a silent one.

### 5.2 Track C — self-serve link

Simplest and always available. Renders a deep link into the tenant's public booking widget with service,
provider and date pre-selected where the URL scheme supports it, sends by SMS, and creates **no**
occupancy row (nothing is held — be honest with the caller about that: *"I've texted you the link — the
time isn't held until you finish, so grab it soon."*).

This is the Phase 1 shipping path and the permanent fallback. It must be implemented **first**, in
Phase C, before Track A or B.

### 5.3 Track B — headless widget automation

⚠️ **Do not start Track B until: (a) GATE-01 is answered "no write API", (b) PalmLeaf has given written
authorization to automate their own booking widget (design brief §15 item 12), and (c) the Vagaro ToS
review is complete ([infrastructure](infrastructure.md) Phase 0).** These are recorded as GATE-10 in [09-open-decisions](../plans/09-open-decisions.md).

`apps/booking-worker` — separate container, separate image, separate scaling, never shares a process with
the API.

```
Job: pms.write_appointment { bookingId }
 1. Load booking + customer + service + provider. Re-check state == CONFIRMED. Skip if pms_appointment_id set.
 2. PRE-CHECK (mandatory): query the mirror and the live PMS for an appointment matching
    (customer phone, starts_at, provider). If found → link it, mark SYNCED, exit.
    ← This is the anti-double-booking guard. Never skip it. A retried Playwright job that
      does not pre-check is exactly how a customer gets booked twice.
 3. Launch browser (persistent context, no incognito — the widget may set cookies).
 4. Navigate the widget: service → provider → date → slot → details → confirm.
 5. Screenshot at every step into object storage, retained 7 days. Non-negotiable for debugging.
 6. Extract the confirmation id from the success page. If it cannot be extracted → treat as
    UNKNOWN OUTCOME, not failure: go to NEEDS_STAFF with the screenshots attached.
 7. Persist pms_appointment_id, transition CONFIRMED → SYNCED.
```

**Hardening requirements:**

| Requirement | Detail |
|---|---|
| Selector strategy | Prefer accessible roles/labels over CSS/XPath — survives styling changes |
| Selector registry | All selectors in one file with a version stamp; a UI change is a one-file diff |
| Timeouts | Per-step, generous (widget is slow), total job cap 180s |
| Concurrency | **1 job at a time per tenant.** Parallel browser sessions against one widget cause races. |
| Retries | 3, with 2/8/30-minute backoff. Never immediate — a UI change will not fix itself in 5s. |
| Unknown outcome | Any ambiguity → `NEEDS_STAFF`. Never assume failure and retry a possibly-successful booking. |
| Canary | A nightly job books a far-future slot for a test customer and cancels it. Failure alerts before real bookings break. This is the early-warning system for Vagaro UI changes. |
| Rate | Respect the widget; add human-like pacing. Do not hammer. |
| Resource limits | 1 vCPU / 2 GB per browser; `--disable-dev-shm-usage`; kill on job timeout |

**Maintenance budget: 4–8 developer-hours/month** (design brief §16). Track the actual number — it is the
strongest argument for pursuing native API access commercially.

### 5.4 Track D — staff queue

`staff_tasks` row + a staff notification + SMS to the manager for P1. The payload must contain everything a
human needs to finish the job without opening five tabs: customer name and phone, service, provider,
exact datetime, price, deposit status, booking id, call recording link, and a one-line summary of what
the automation could not do.

**The caller's slot remains held** while the task is open. This is the promise the whole design makes and
it must not be quietly broken by a sweeper — the reservation TTL for `NEEDS_STAFF` bookings is extended
to 48 hours, and the sweeper skips them.

---

## 6. Reschedule and cancel

Both are `grace_domain/policy` decisions executed as saga transitions.

```ts
// TARGET — src/grace_domain/policy/change_fee.py   (PURE — invariant I4)
export function evaluateChange(input: {
  appointmentStartsAt: Date; now: Date; policy: CancellationPolicy;
  depositCents: number; pricePaidCents: number; isReschedule: boolean;
}): ChangeDecision {
  const hoursUntil = differenceInHours(input.appointmentStartsAt, input.now);
  const insideWindow = hoursUntil < input.policy.windowHours;
  // returns { allowed, feeCents, depositDisposition, reasonCode, spokenExplanation }
}
```

**Never let the LLM compute the 48-hour boundary** (design brief §7.1). The prompt says "call the tool";
the tool decides; the tool's `reasonCode` drives the SMS, the staff task, and the dispute record.

The reschedule flow is: evaluate → find new slot ([availability-engine](availability-engine.md)) → hold new → create a *new* booking row with
`rescheduled_from` set → cancel the old → release old occupancy. Two rows, linked. Never mutate the
original booking's time — the history matters in a dispute.

⛔ **GATE-02 blocks the policy content, not the engine.** Build `evaluateChange` now with the policy read
from the `policies` table; the client's sign-off populates a row. If no approved `CANCELLATION` policy
exists, the tool returns `PolicyNotApprovedError` and Grace transfers to a human — a correct, safe
degradation (design brief §15 item 1).

---

## 7. Deleting Track B when Vagaro says yes

If ⛔ GATE-01 resolves to "write endpoints available", the change set is:

1. `VagaroAdapter.capabilities.writeAppointments = true` and implement the four write methods.
2. `selectWriteStrategy` returns `NATIVE_PMS` (already coded — no change).
3. `pms.write_appointment` consumer calls `pms.createAppointment()` instead of enqueueing to
   `booking-worker`.
4. Delete `apps/booking-worker`, its image, its container, its canary, and its maintenance budget.
5. Track A becomes optional (still useful for staff-side visibility).

**Zero changes to:** the domain, the availability engine, the saga states, the outbox, the tools, the
prompt, or the database. That is the return on ADR-0006 and ADR-0007, and it is why building the saga
now — before the answer arrives — is the right call rather than premature.

---

## 8. Failure catalogue

| Failure | Detection | Response | Caller impact |
|---|---|---|---|
| Google Calendar 403 (permission revoked) | adapter error | booking → `NEEDS_STAFF`, P1 alert | none; slot still held |
| Calendar event created but PMS never syncs | 90s verification job | P2 staff task | none; slot held |
| Stripe link creation fails | adapter error | retry ×4, then send a "we'll call you" SMS + staff task | mild |
| Deposit unpaid at 24h | scheduled job | release slot, SMS caller, notify staff | slot lost — as designed |
| Track B fails 3× | job attempts | `NEEDS_STAFF`, slot held, P1 staff notification | none |
| Track B outcome unknown | no confirmation id | `NEEDS_STAFF` with screenshots | none; staff verifies |
| PMS books over our reservation | mirror sync exclusion violation | P1 task, both kept, immediate alert | possible — human resolves fast |
| SMS filtered (carrier) | Twilio status callback | email fallback; alert if 10DLC lapsed | mild |
| Outbox row DEAD | dispatcher | P1 task + alert; the event is inspectable and replayable | depends |
| Worker down | queue depth alert | outbox accumulates; nothing lost | delayed SMS |
| Whole cold path down | health | **calls still work end-to-end**; bookings queue up | none during call |

That last row is the architectural payoff: the outbox means the cold path can be entirely offline and
Grace still answers the phone, quotes prices, and takes bookings — they simply complete a few minutes late.

---

## 9. Acceptance criteria

✅ **AC-07.1** An outbox event survives a hard kill of the worker mid-job and is executed exactly once
(observable effect appears once).
✅ **AC-07.2** Dispatching with 3 concurrent workers produces no duplicate job execution.
✅ **AC-07.3** Every illegal state transition throws and writes nothing.
✅ **AC-07.4** Changing `bookings.state` by raw SQL without a `booking_events` row raises a trigger error.
✅ **AC-07.5** The full happy-path saga (DRAFT → PENDING_DEPOSIT → CONFIRMED → WRITING_TO_PMS → SYNCED)
runs end-to-end against fakes in CI with no network.
✅ **AC-07.6** Track B failing 3 times leaves the booking `NEEDS_STAFF`, the occupancy `ACTIVE`, and a P1
task with screenshots.
✅ **AC-07.7** Track B pre-check prevents a duplicate appointment when a retry follows a job whose write
actually succeeded.
✅ **AC-07.8** Flipping `capabilities.writeAppointments` to true on the fake switches the saga to the
native path with no other change (§7).
✅ **AC-07.9** `evaluateChange` has unit tests at 47h59m, 48h00m, 48h01m, across a DST boundary, and for
a zero-deposit service.
✅ **AC-07.10** With an unapproved cancellation policy, the cancel tool transfers to a human and does not
quote a fee.

## 10. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **A-22** | Does arq's `job_id` dedupe window cover the outbox retry schedule? | ADR-0015 chose arq by analogy with the queue this document was originally written against, whose dedupe the design leans on explicitly. arq deduplicates within a *keep-alive window*, not for the job's lifetime — so a late retry could send a caller a **second confirmation text**. **Re-derive it in C-04; do not assume it.** The mitigation (a consumer-side `UNIQUE` constraint) is already required by at-least-once delivery. | Engineering, at C-04 |
| **GATE-10** | Written client authorization to automate their own booking widget, plus a Vagaro ToS review | Track B is browser automation against a third party's UI. Without written authorization it should not be built, regardless of whether it works. | PalmLeaf + counsel |
| **A-20** | How does the escalation path place its final "call the manager" step? | `VoicePort.createOutboundCall` is Phase F. Until then the path terminates at a repeat SMS plus a staff notification — degraded, but never silently dropped. | Engineering, at Phase F |
| **Q-BW.1** | If GATE-01 comes back positive, when is Track B deleted? | ADR-0006 shaped the saga so that deletion is a small diff. But a Track B that already works is easy to keep "just in case", and carrying both paths doubles the failure surface for no benefit. Decide the trigger in advance. | Engineering |
