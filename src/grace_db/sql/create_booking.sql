-- Create a booking. ONE statement, therefore ONE transaction.
--
-- Written as a single statement deliberately, not as an application-side sequence:
-- Postgres wraps a lone statement in its own transaction, so the hold promotion, the
-- booking row, its audit row, the staff task and the outbox event all land together or
-- not at all. There is no window where a slot is marked taken with no booking behind it.
--
-- A useful property of that choice: this SQL is portable. Anything that can execute a
-- statement — this service, or an n8n Postgres node — gets identical guarantees.
--
-- Idempotency (invariant I3) is the `existing` CTE plus the UNIQUE on
-- (tenant_id, idempotency_key): a repeated createBooking for the same call and slot
-- returns the original booking instead of creating a second one.
WITH params AS (
  SELECT
    %(tenant_id)s::uuid      AS tenant_id,
    %(idempotency_key)s::text AS idempotency_key,
    %(public_slot_id)s::text AS public_slot_id,
    %(service_id)s::uuid     AS service_id,
    %(call_id)s::uuid        AS call_id,
    %(phone)s::text          AS phone,
    %(first_name)s::text     AS first_name,
    %(last_name)s::text      AS last_name,
    %(price_cents)s::int     AS price_cents,
    %(deposit_cents)s::int   AS deposit_cents,
    %(is_member)s::bool      AS is_member,
    %(reservation_ttl)s::int AS reservation_ttl
),
existing AS (
  SELECT b.id, b.state::text AS state, b.starts_at, b.provider_id
  FROM bookings b, params p
  WHERE b.tenant_id = p.tenant_id AND b.idempotency_key = p.idempotency_key
),
cust AS (
  INSERT INTO customers (tenant_id, phone_e164, first_name, last_name)
  SELECT p.tenant_id, p.phone, p.first_name, NULLIF(p.last_name, '')
  FROM params p
  WHERE NOT EXISTS (SELECT 1 FROM existing)
  -- Keep the name already on file. A caller booking for someone else must not rename
  -- the account holder; the appointment's own name goes on the booking row instead.
  ON CONFLICT (tenant_id, phone_e164) DO UPDATE
    SET first_name = COALESCE(customers.first_name, EXCLUDED.first_name),
        updated_at = now()
  RETURNING id
),
-- Promote the hold. Guarded on state and kind, so a hold that expired or was taken by a
-- concurrent caller yields zero rows and the whole statement becomes a no-op.
occ AS (
  UPDATE calendar_occupancy o
  SET kind = 'RESERVATION',
      expires_at = now() + make_interval(secs => (SELECT reservation_ttl FROM params)),
      updated_at = now()
  FROM params p
  WHERE o.tenant_id = p.tenant_id
    AND o.metadata->>'publicId' = p.public_slot_id
    AND o.state = 'ACTIVE'
    AND o.kind = 'HOLD'
    AND NOT EXISTS (SELECT 1 FROM existing)
  RETURNING o.id, o.subject_id, lower(o.service_range) AS starts_at, upper(o.service_range) AS ends_at
),
booked AS (
  INSERT INTO bookings (
    tenant_id, idempotency_key, call_id, customer_id, service_id, provider_id,
    occupancy_id, starts_at, ends_at, state, price_cents, is_member_price,
    deposit_cents, deposit_state, confirmed_at, booked_for_name
  )
  SELECT p.tenant_id, p.idempotency_key, p.call_id, cust.id, p.service_id, occ.subject_id,
         occ.id, occ.starts_at, occ.ends_at,
         -- No deposit owed means the slot is the caller's the moment they say yes.
         CASE WHEN p.deposit_cents > 0 THEN 'PENDING_DEPOSIT' ELSE 'CONFIRMED' END::booking_state,
         p.price_cents, p.is_member, p.deposit_cents,
         CASE WHEN p.deposit_cents > 0 THEN 'PENDING' ELSE 'NOT_REQUIRED' END::deposit_state,
         CASE WHEN p.deposit_cents > 0 THEN NULL ELSE now() END,
         nullif(trim(p.first_name || ' ' || coalesce(p.last_name, '')), '')
  FROM params p, occ, cust
  RETURNING id, tenant_id, state::text AS state, starts_at, provider_id
),
-- The audit row. The trigger on bookings requires one for every state change; writing it
-- here keeps the history complete from the very first state.
audited AS (
  INSERT INTO booking_events (tenant_id, booking_id, from_state, to_state, actor, reason)
  SELECT tenant_id, id, NULL, state::booking_state, 'grace', 'created from a call'
  FROM booked
  RETURNING id
),
-- Track D: Vagaro's write API is unproven, so a human transcribes the booking. Filed as
-- NEEDS_ENTRY rather than a failure, because nothing failed.
tasked AS (
  INSERT INTO staff_tasks (tenant_id, type, priority, title, body, booking_id, call_id)
  SELECT b.tenant_id, 'BOOKING_NEEDS_ENTRY', 2,
         'Enter booking in Vagaro',
         'Grace confirmed this with the caller. It is held in our calendar and must be '
         || 'entered into Vagaro.',
         b.id, p.call_id
  FROM booked b, params p
  ON CONFLICT DO NOTHING
  RETURNING id
),
-- The caller chose one of the three we offered. The other two must go back on sale
-- IMMEDIATELY, not when the call ends or the timer runs out. Holding them any longer
-- denies them to the next caller for no reason — the decision has already been made.
freed AS (
  UPDATE calendar_occupancy o
  SET state = 'RELEASED',
      released_at = now(),
      release_reason = 'another_slot_chosen',
      updated_at = now()
  FROM params p
  WHERE o.tenant_id = p.tenant_id
    AND o.call_id = p.call_id
    AND o.kind = 'HOLD'
    AND o.state = 'ACTIVE'
    AND o.metadata->>'publicId' IS DISTINCT FROM p.public_slot_id
    AND EXISTS (SELECT 1 FROM booked)
  RETURNING o.id
),
queued AS (
  INSERT INTO outbox_events (tenant_id, aggregate_type, aggregate_id, event_type, payload)
  SELECT b.tenant_id, 'booking', b.id, 'pms.write_appointment',
         jsonb_build_object('bookingId', b.id, 'strategy', 'STAFF_QUEUE')
  FROM booked b
  RETURNING id
)
SELECT id, state, starts_at, provider_id, 'created' AS outcome FROM booked
UNION ALL
SELECT id, state, starts_at, provider_id, 'existing' AS outcome FROM existing;
