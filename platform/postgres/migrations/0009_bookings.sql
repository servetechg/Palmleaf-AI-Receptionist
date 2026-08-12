-- 0009 — bookings, the saga aggregate. data-model.md §9, booking-write-path.md §4.
CREATE TABLE bookings (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  idempotency_key       text NOT NULL,     -- '{callId}:{slotPublicId}'
  call_id               uuid,
  customer_id           uuid NOT NULL REFERENCES customers(id),
  service_id            uuid NOT NULL REFERENCES services(id),
  provider_id           uuid NOT NULL REFERENCES providers(id),
  occupancy_id          uuid NOT NULL REFERENCES calendar_occupancy(id),

  starts_at             timestamptz NOT NULL,
  ends_at               timestamptz NOT NULL,

  state                 booking_state NOT NULL DEFAULT 'DRAFT',
  state_reason          text,
  state_changed_at      timestamptz NOT NULL DEFAULT now(),
  version               integer NOT NULL DEFAULT 1,   -- optimistic concurrency

  price_cents           integer NOT NULL,
  is_member_price       boolean NOT NULL DEFAULT false,
  deposit_cents         integer NOT NULL DEFAULT 0,
  deposit_state         deposit_state NOT NULL DEFAULT 'NOT_REQUIRED',
  deposit_due_at        timestamptz,

  stripe_session_id     text,
  stripe_payment_intent text,

  track_a_event_id      text,
  track_b_status        text NOT NULL DEFAULT 'NOT_STARTED',
  track_b_attempts      smallint NOT NULL DEFAULT 0,
  track_b_last_error    text,
  pms_appointment_id    text,

  intake_sent_at        timestamptz,
  confirmation_sent_at  timestamptz,
  confirmed_at          timestamptz,
  cancelled_at          timestamptz,
  cancellation_reason   text,
  change_fee_cents      integer NOT NULL DEFAULT 0,
  rescheduled_from      uuid REFERENCES bookings(id),

  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CHECK (ends_at > starts_at),
  -- INVARIANT I3 — a retried createBooking tool call cannot create a second booking.
  CONSTRAINT bookings_idempotency_uq UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX ON bookings (tenant_id, state) WHERE state NOT IN ('CANCELLED','EXPIRED','SYNCED');
CREATE INDEX ON bookings (tenant_id, starts_at);
CREATE INDEX ON bookings (tenant_id, customer_id, starts_at DESC);
CREATE INDEX ON bookings (deposit_due_at) WHERE deposit_state = 'PENDING';
-- One live booking per slot.
CREATE UNIQUE INDEX bookings_occupancy_uq ON bookings (occupancy_id)
  WHERE state NOT IN ('CANCELLED','EXPIRED');

-- Full audit trail of every state transition. Append-only.
CREATE TABLE booking_events (
  id          bigserial PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  booking_id  uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  from_state  booking_state,
  to_state    booking_state NOT NULL,
  actor       text NOT NULL,   -- 'grace' | 'worker:track-b' | 'stripe' | 'staff:<id>' | 'system'
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON booking_events (booking_id, occurred_at);
