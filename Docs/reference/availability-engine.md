# availability-engine — Availability Engine

**Status:** Frozen — unblocks at [08-roadmap](../plans/08-roadmap.md) task **C-03**. No external dependency.
**Read before:** implementing `checkAvailability`, `createBooking`, or any occupancy write.
**Implements:** ADR-0003, ADR-0004, ADR-0011
**Enforces:** I2, I3
**Last verified:** 2026-08-04 — rewritten for Python; the SQL and the concurrency argument are unchanged.

> **In one paragraph:** this document settles how a free slot is computed, held, and promoted to a
> reservation — the occupancy model, the anti-join query that must use the GiST index, hold and
> reservation TTLs, and what happens when two callers race for the same slot. It is the subsystem
> that decides whether Grace feels like a receptionist or like an IVR.

This is the subsystem that decides whether Grace feels like a receptionist or like an IVR. It has two
jobs: **answer "what's free?" in under 50ms**, and **make double-booking physically impossible**.

---

## 1. Conceptual model

```
   candidate slots   =   provider is working
                     ∩   business is open
                     ∩   service fits before closing
                     ∩   respects lead time and advance limit
                     −   ACTIVE occupancy (holds, reservations, appointments,
                         external blocks, time off, closures)
                     −   buffers (already baked into blocked_range)
```

Everything on the subtraction side lives in one table (`calendar_occupancy`, [data-model](data-model.md) §6). Everything on the
intersection side comes from schedule templates (`business_hours`, `provider_shifts`) and per-date
overrides (`schedule_exceptions`). That asymmetry is deliberate: **templates generate, occupancy subtracts.**

---

## 2. Slot granularity

Slots are generated on a **15-minute grid** anchored to the provider's shift start, in the tenant's
timezone.

| Decision | Value | Why |
|---|---|---|
| Grid | 15 min | Matches how humans book massage; 5-min would triple candidates for no UX gain |
| Anchor | shift start, not midnight | A 10:15 shift start produces 10:15/10:30/…, not 10:00 |
| Search window (max) | 21 days forward per query | Bounds the query; "anything next month?" is a second query |
| Slots returned | 3 (tenant-configurable) | Design brief §4.3 — never list more than 3 aloud |
| Timezone | `tenants.timezone` | All grid math in local time, stored UTC |

**DST.** Grid generation uses `generate_series` over a `timestamptz` range with the session timezone set
to the tenant's, so the spring-forward hour simply produces no slots and the fall-back hour does not
produce duplicates. This is tested explicitly ([07-testing](../plans/07-testing.md)) with America/Chicago 2027-03-14 and 2026-11-01.

---

## 3. The free-slot query

One query. No N+1. No application-side interval arithmetic.

```sql
-- TARGET — src/grace_db/repositories/occupancy.find-free-slots.sql
WITH params AS (
  SELECT
    $1::uuid       AS tenant_id,
    $2::uuid       AS service_id,
    $3::tstzrange  AS window,
    $4::uuid       AS provider_filter,     -- NULL = any provider
    $5::timestamptz AS now,
    $6::text       AS tz
),
svc AS (
  SELECT s.id, s.duration_min, s.buffer_before_min, s.buffer_after_min,
         s.min_lead_time_min, s.max_advance_days
  FROM services s, params p
  WHERE s.id = p.service_id AND s.tenant_id = p.tenant_id
    AND s.active AND s.bookable_by_ai AND s.approved_at IS NOT NULL
),
eligible_providers AS (
  SELECT pr.id, pr.spoken_name, ps.duration_override_min, ps.price_override_cents, ps.proficiency
  FROM provider_services ps
  JOIN providers pr ON pr.id = ps.provider_id
  , params p
  WHERE ps.tenant_id = p.tenant_id
    AND ps.service_id = p.service_id
    AND pr.active AND pr.accepts_new_clients
    AND (p.provider_filter IS NULL OR pr.id = p.provider_filter)
),
-- Expand recurring shifts into concrete datetime ranges inside the window.
shift_instances AS (
  SELECT ep.id AS provider_id, ep.spoken_name,
         tstzrange(
           (d::date + sh.starts_at) AT TIME ZONE p.tz,
           (d::date + sh.ends_at)   AT TIME ZONE p.tz, '[)'
         ) AS shift_range
  FROM params p
  CROSS JOIN generate_series(lower(p.window)::date, upper(p.window)::date, interval '1 day') d
  JOIN provider_shifts sh ON sh.tenant_id = p.tenant_id
       AND sh.day_of_week = EXTRACT(DOW FROM d)::smallint
       AND sh.effective_from <= d::date
       AND (sh.effective_to IS NULL OR sh.effective_to >= d::date)
  JOIN eligible_providers ep ON ep.id = sh.provider_id
  WHERE NOT EXISTS (                      -- provider time off / business closure that day
    SELECT 1 FROM schedule_exceptions se
    WHERE se.tenant_id = p.tenant_id AND se.on_date = d::date
      AND se.kind IN ('CLOSED','HOLIDAY','TIME_OFF')
      AND (se.provider_id IS NULL OR se.provider_id = ep.id)
  )
),
-- Intersect shifts with business hours (and SPECIAL_HOURS overrides).
open_ranges AS (
  SELECT si.provider_id, si.spoken_name,
         si.shift_range * bh.range AS open_range
  FROM shift_instances si
  JOIN LATERAL business_hours_for_date(
         (SELECT tenant_id FROM params), lower(si.shift_range)::date
       ) bh ON true
  WHERE si.shift_range && bh.range
),
-- 15-minute grid anchored to each open range's start.
candidates AS (
  SELECT o.provider_id, o.spoken_name, g.start_ts,
         tstzrange(
           g.start_ts - make_interval(mins => svc.buffer_before_min),
           g.start_ts + make_interval(mins => COALESCE(NULL, svc.duration_min) + svc.buffer_after_min),
           '[)'
         ) AS blocked_range,
         tstzrange(g.start_ts,
                   g.start_ts + make_interval(mins => svc.duration_min), '[)') AS service_range
  FROM open_ranges o, svc,
       generate_series(lower(o.open_range),
                       upper(o.open_range) - make_interval(mins => svc.duration_min),
                       interval '15 minutes') AS g(start_ts)
)
SELECT c.provider_id, c.spoken_name, c.start_ts, c.service_range, c.blocked_range
FROM candidates c, params p, svc
WHERE c.start_ts >= p.now + make_interval(mins => svc.min_lead_time_min)
  AND c.start_ts <= p.now + make_interval(days => svc.max_advance_days)
  AND c.service_range <@ (SELECT open_range FROM open_ranges o2
                          WHERE o2.provider_id = c.provider_id
                            AND o2.open_range && c.service_range LIMIT 1)
  AND NOT EXISTS (                                   -- ← the subtraction
    SELECT 1 FROM calendar_occupancy occ
    WHERE occ.tenant_id = p.tenant_id
      AND occ.state = 'ACTIVE'
      AND occ.subject_type = 'PROVIDER'
      AND occ.subject_id = c.provider_id
      AND occ.blocked_range && c.blocked_range
  )
ORDER BY c.start_ts
LIMIT 200;
```

`business_hours_for_date(tenant, date)` is a small SQL function returning the effective open range for
that date, applying `SPECIAL_HOURS` exceptions over the weekly template. Defined in migration 0016.

**Performance.** The `NOT EXISTS` uses the GiST index created by the exclusion constraint. With ~10k
active occupancy rows and a 7-day window the plan is an index-only anti-join; measured target
**p95 < 25ms**. Add an EXPLAIN assertion to the integration test ([07-testing](../plans/07-testing.md) §4) so a regression in the plan is
caught by CI, not by a caller.

**Room/resource constraint.** When `services.requires_resource_kind` is set, a second `NOT EXISTS` over
`subject_type='RESOURCE'` is added, plus a check that at least one room of that kind is free. Implemented
in the same query; omitted above for readability.

---

## 4. Ranking (pure domain)

The SQL returns up to 200 candidates. Choosing the three Grace offers is a **product decision** and lives
in `grace_domain.availability.rank` — pure, unit-tested, no I/O.

```ts
// TARGET
export function rankSlots(candidates: Candidate[], opts: RankOptions): RankedSlot[]
```

Scoring, highest wins:

| Signal | Weight | Rationale |
|---|---|---|
| Matches caller's stated time preference (morning/afternoon/evening) | +100 | They asked |
| Provider is the customer's `preferred_provider_id` | +60 | Retention; they have a relationship |
| Provider explicitly requested by name in this call | +200 | Overrides everything except availability |
| Earlier in the requested day | +0…30 (linear) | Sooner is generally better |
| Provider proficiency for this service | +0…20 | Quality |
| Slot leaves no orphan gap < shortest service | +25 | **Calendar packing** — protects revenue |
| Slot is the provider's first of the day, and another slot exists | −10 | Prefer contiguous blocks |

Then: **diversify.** Never return three slots from the same provider within 45 minutes of each other —
that is a bad menu. Prefer spread across time, then across providers, subject to score.

> The calendar-packing signal matters commercially. A naive "earliest first" engine fragments the day and
> measurably reduces bookable hours. This is a one-function improvement with real revenue impact and is
> worth getting right in Phase B.

---

## 5. Placing holds

```ts
// TARGET — src/grace_db/repositories/occupancy.py
export async function placeHolds(tx: Transaction, req: {
  slots: RankedSlot[]; callId: string; ttlSeconds: number;
}): Promise<HeldSlot[]> {
  const held: HeldSlot[] = [];
  for (const slot of req.slots) {
    try {
      const [row] = await tx.insert(calendarOccupancy).values({
        tenantId: ctx.tenantId, subjectType: 'PROVIDER', subjectId: slot.providerId,
        blockedRange: slot.blockedRange, serviceRange: slot.serviceRange,
        kind: 'HOLD', state: 'ACTIVE', source: 'GRACE',
        callId: req.callId, expiresAt: addSeconds(ctx.now, req.ttlSeconds),
      }).returning();
      held.push(toHeldSlot(row));
    } catch (e) {
      if (isExclusionViolation(e)) continue;   // 23P01 — someone took it in the last 20ms. Skip it.
      throw e;
    }
  }
  if (held.length === 0) throw new SlotNoLongerAvailableError('all offered slots were taken');
  return held;
}
```

Key points:

- Each hold is inserted **in its own savepoint** so one collision does not abort the transaction.
- A `23P01` on an *offered* slot is normal under contention and is not an error — it is skipped.
- If **all** candidates collide, throw `SlotNoLongerAvailableError`; the handler re-queries once with a
  widened window before giving up (bounded: exactly one retry, never a loop).
- Holds are placed on **all three offered slots** (design brief §5.3). This deliberately over-holds for up
  to 4 minutes. At PalmLeaf's volume the cost is negligible; at high volume, reduce `maxSlotsOffered` or
  the TTL rather than removing the guarantee.

### 5.1 Public slot identifiers

Never expose a UUID to an LLM — it will mangle it. Each hold gets a short, human-safe public id:

```
publicId = 'h' + base32Crockford(hashids(occupancyId)).slice(0, 4)   // e.g. "h7K2M"
```

Stored in `calendar_occupancy.metadata->>'publicId'` (add column in migration 0017), unique per call.
The formatter never speaks it, but the handler accepts it, so the LLM can pass back which slot the caller
picked. If the model returns something unrecognisable, `createBooking` falls back to matching on
`(providerName, startsAt)` from the transcript arguments — always have this fallback; models garble ids.

---

## 6. Promotion to reservation and the idempotency contract

`createBooking` is the only write that matters. Its full transaction:

```
BEGIN
  SET LOCAL grace.tenant_id = :tenantId

  -- 1. Idempotency. UNIQUE (tenant_id, idempotency_key) on bookings. ★ I3 ★
  INSERT INTO bookings (..., idempotency_key = :callId || ':' || :slotPublicId, state='DRAFT')
  ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
  RETURNING *;
  -- no row returned ⇒ this is a retry. SELECT the existing booking and return its stored response.

  -- 2. Promote the hold. Guarded by state so a double-promote is impossible.
  UPDATE calendar_occupancy
     SET kind='RESERVATION', expires_at = now() + :reservationTtl,
         booking_id = :bookingId, updated_at = now()
   WHERE id = :occupancyId AND state='ACTIVE' AND kind='HOLD' AND call_id = :callId
  RETURNING *;
  -- zero rows ⇒ the hold expired or was released ⇒ raise SlotExpired, re-check availability,
  --             and if still free, insert a fresh RESERVATION row directly (may hit 23P01).

  -- 3. Upsert the customer (phone is the natural key)
  -- 4. Compute price + deposit  (PURE: grace_domain/pricing, grace_domain/policy)
  -- 5. Write outbox rows — ALL side effects, in this same transaction ★ I8 ★
  --      calendar.create_event      (Track A)
  --      payments.create_deposit_link  (if deposit > 0)
  --      sms.send booking_confirmation
  --      sms.send intake_form        (if service.requires_intake)
  --      pms.write_appointment       (Track B / native)
  --      staff.notify                (if anything is unusual)
  -- 6. booking_events row: DRAFT → PENDING_DEPOSIT | CONFIRMED
COMMIT
```

**Nothing external is called.** The handler returns in <600ms because it did six local writes and zero
network calls. Everything the caller was promised is now durable in the outbox and will happen.

### 6.1 Why the idempotency key is `{callId}:{slotPublicId}`

- Vapi retries a tool call on timeout with the **same** `toolCallId` — so `{callId}:{toolCallId}` also
  works and is what the middleware ([core-api](core-api.md) §6.3) uses at the HTTP layer.
- `bookings.idempotency_key` uses the **slot**, not the tool call, because it must also collapse the case
  where the LLM calls `createBooking` twice in one call for the same slot (it happens — models double-fire
  after a long pause). Two different `toolCallId`s, one booking.
- Both layers are needed. The HTTP layer makes the *response* identical; the DB layer makes the *data*
  correct.

---

## 7. Deadline safety on writes

Per ADR-0012, a handler that loses the deadline race must not leave partial state. For write handlers:

```ts
// TARGET
await withTenant(tenantId, async (tx) => {
  const result = await doBookingWork(tx, args);
  if (ctx.deadlineExceeded) {
    throw new RollbackSignal();     // caught outside; transaction rolls back
  }
  return result;
});
```

The caller then hears the fallback sentence, no booking exists, no hold was promoted, and the original
hold still stands for its remaining TTL — so a retry (by the model or by the caller repeating themselves)
succeeds cleanly. **A partially-committed booking is far worse than a retried one.**

---

## 8. Expiry sweeper

`sync-worker`, every 30 seconds (design brief says 1 minute; 30s halves the worst-case wasted hold):

```sql
UPDATE calendar_occupancy
   SET state = 'EXPIRED', released_at = now(), release_reason = 'ttl'
 WHERE state = 'ACTIVE' AND expires_at IS NOT NULL AND expires_at < now()
 RETURNING id, booking_id, kind;
```

For each expired `RESERVATION` with a booking in `PENDING_DEPOSIT`, transition the booking to `EXPIRED`
and emit outbox events: notify the caller by SMS, notify staff, and log a `booking_events` row.

Also released on `end-of-call-report`: any `HOLD` still `ACTIVE` for that `call_id` is released
immediately rather than waiting for TTL. This is a meaningful availability improvement at low cost.

---

## 9. Mirror synchronisation

| Source | Cadence | Handles |
|---|---|---|
| PMS webhook → `inbound_webhooks` → worker | real-time (<5s) | appointment create/update/cancel, customer changes |
| PMS poller `listAppointments` | every 10 min, rolling −7/+60 days | missed webhooks, drift |
| Google Calendar watch push | real-time | staff-side manual blocks |
| Google Calendar incremental sync (`syncToken`) | every 15 min | missed pushes |
| Full reconciliation | nightly 03:00 America/Chicago | authoritative resync + integrity report |

**Applying a PMS appointment to the mirror** is an upsert on `(tenant_id, pms_appointment_id)` plus an
occupancy upsert:

```
if appointment is new/updated and in the future:
    upsert appointments_mirror
    upsert calendar_occupancy (kind=APPOINTMENT, source=PMS, source_ref=pms_id)
       on exclusion violation:
         → the overlapping row is one of OURS (a Grace reservation)
         → this is the collision case: PMS booked over us, or this IS us syncing back
         → if occupancy.booking_id matches a booking with the same customer+time → LINK, don't duplicate
         → otherwise → CONFLICT: create a P1 staff task, keep both, alert immediately
if appointment is cancelled:
    mark mirror row cancelled; release its occupancy row
```

> **The collision branch is the most important error path in the system.** It is how "the front desk
> booked someone into the slot Grace just gave away" becomes a staff task within seconds instead of two
> people arriving at 6:30. Test it explicitly (§13 §5). Design brief §15 item 9 (Massagebook/Vagaro
> dual-running) makes this scenario likely during transition, not theoretical.

---

## 10. Reconciliation integrity report

Nightly, produce and store a report answering:

| Check | Expected | Action on failure |
|---|---|---|
| Every future mirror appointment has an ACTIVE occupancy row | 100% | auto-repair, log |
| Every ACTIVE `APPOINTMENT` occupancy has a mirror row | 100% | auto-repair, log |
| Every `CONFIRMED`/`SYNCED` booking has an ACTIVE occupancy row | 100% | **P1 staff task** — a customer thinks they're booked |
| Occupancy rows overlapping across subjects for the same booking | 0 | investigate |
| Bookings stuck in `WRITING_TO_PMS` > 2h | 0 | staff task |
| Holds active > 2× TTL | 0 | sweeper is broken → alert |
| Mirror rows not synced in > 24h | 0 | poller is broken → alert |

Report is written to `reconciliation_reports` (migration 0018), emailed to staff, and its failure counts
are exported as Prometheus gauges so they can be alerted on rather than read.

---

## 11. Capacity and scaling notes

| Concern | At 1 tenant / 45 calls day | At 50 tenants / 2,000 calls day | Mitigation |
|---|---|---|---|
| Active occupancy rows | ~1.5k | ~75k | GiST index; partial index keeps it small |
| Free-slot query p95 | ~15ms | ~40ms | add `(tenant_id, subject_id)` covering index; consider per-tenant partitioning at 1M rows |
| Hold churn | ~150/day | ~7k/day | released rows excluded from the index automatically |
| Historical occupancy growth | ~30k/yr | ~1.5M/yr | archive `state<>'ACTIVE'` rows older than 1 year to a cold table |

Nothing here requires a different architecture at 50× current volume. That is the point of ADR-0004:
the guarantee comes from an index, and indexes scale.

---

## 12. Acceptance criteria

✅ **AC-06.1** Free-slot query returns correct slots for a provider with a split shift (e.g. 9–12, 14–20).
✅ **AC-06.2** A `TIME_OFF` exception removes that provider's slots for that date only.
✅ **AC-06.3** A `SPECIAL_HOURS` exception narrows availability correctly.
✅ **AC-06.4** Buffers block the calendar but are invisible in what Grace speaks.
✅ **AC-06.5** DST spring-forward and fall-back dates produce no duplicate or impossible slots.
✅ **AC-06.6** Two concurrent `checkAvailability` + `createBooking` sequences targeting the same slot
result in exactly one booking; the loser receives `SlotNoLongerAvailableError` and is offered alternatives.
✅ **AC-06.7** 50 parallel bookings against 50 distinct slots all succeed with zero exclusion violations.
✅ **AC-06.8** Replaying the same `createBooking` five times produces one booking and five identical responses.
✅ **AC-06.9** Free-slot query p95 < 40ms with 100k active occupancy rows (seeded benchmark).
✅ **AC-06.10** A PMS appointment syncing onto a Grace reservation produces a P1 staff task, not silent data loss.
✅ **AC-06.11** Deadline expiry during `createBooking` leaves zero rows written and the hold intact.
✅ **AC-06.12** An unapproved service (`approved_at IS NULL`) yields zero candidate slots.

## 13. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **A-05** | Is a 15-minute slot grid right for massage booking? | Industry norm, not a measured choice. Changing it is one constant and its tests, so the cost of being wrong is low — but nobody has checked it against PalmLeaf's actual book. | PalmLeaf, at Phase D |
| **A-06** | Are the 4-minute hold and 15-minute reservation TTLs right? | They are tenant settings rather than code, so they are tunable in production. Too short strands a deciding caller; too long strands the slot. Real call data settles it. | Engineering, after the pilot |
| **Q-AE.1** | Does the anti-join hold its plan at production data volumes? | The design requires the GiST index anti-join rather than a sequential scan, and I-4 tests exactly that. Until there are 100k real occupancy rows, the test seeds are a proxy. | Engineering, at C-03 |
| **Q-AE.2** | What is the right behaviour when *every* candidate slot is unapproved? | An unapproved service yields zero slots (AC-06.12), which is correct. But a caller hearing "nothing available" when the truth is "nothing approved" is misleading, and the transfer wording should probably differ. | Product |
