-- 0013 — operations: outbox, idempotency, staff tasks, sync state, audit. data-model.md §13.
CREATE TABLE outbox_events (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL,
  aggregate_type text NOT NULL,     -- 'booking','call','customer'
  aggregate_id   uuid NOT NULL,
  event_type     text NOT NULL,     -- 'pms.write_appointment','sms.send','staff.notify', ...
  payload        jsonb NOT NULL,
  status         outbox_status NOT NULL DEFAULT 'PENDING',
  attempts       smallint NOT NULL DEFAULT 0,
  max_attempts   smallint NOT NULL DEFAULT 8,
  available_at   timestamptz NOT NULL DEFAULT now(),
  locked_by      text,
  locked_at      timestamptz,
  last_error     text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  processed_at   timestamptz
);
-- The dispatcher's index: everything it polls for, in the order it wants.
CREATE INDEX outbox_ready_idx     ON outbox_events (available_at, id)
  WHERE status IN ('PENDING','FAILED');
CREATE INDEX outbox_aggregate_idx ON outbox_events (aggregate_type, aggregate_id);

CREATE TABLE idempotency_keys (
  tenant_id    uuid NOT NULL,
  scope        text NOT NULL,        -- tool name or endpoint
  key          text NOT NULL,
  request_hash text NOT NULL,
  status       text NOT NULL CHECK (status IN ('IN_FLIGHT','COMPLETED')),
  status_code  integer,
  response     jsonb,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL DEFAULT now() + interval '24 hours',
  PRIMARY KEY (tenant_id, scope, key)
);
CREATE INDEX ON idempotency_keys (expires_at);

-- Priority semantics (booking-write-path writes these as "P1"/"P3"; the column is smallint):
--   1 = P1 page now  2 = P2 same day  3 = P3 batch/digest  4 = P4 backlog  5 = P5 audit only
-- acknowledged_at MUST be set when status moves to ACKNOWLEDGED; WF-18's "P1 unacknowledged
-- for 15 minutes" check is unanswerable otherwise.
CREATE TABLE staff_tasks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  type            staff_task_type NOT NULL,
  priority        smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  title           text NOT NULL,
  body            text,
  payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  call_id         uuid REFERENCES calls(id) ON DELETE SET NULL,
  booking_id      uuid REFERENCES bookings(id) ON DELETE SET NULL,
  customer_id     uuid REFERENCES customers(id) ON DELETE SET NULL,
  status          task_status NOT NULL DEFAULT 'OPEN',
  due_at          timestamptz,
  assigned_to     text,
  acknowledged_at timestamptz,
  resolved_at     timestamptz,
  resolution      text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON staff_tasks (tenant_id, status, priority, created_at);

-- Backs the staff.notify idempotency contract. Partial: only OPEN rows collide.
CREATE UNIQUE INDEX staff_tasks_open_booking_type_idx
  ON staff_tasks (tenant_id, booking_id, type)
  WHERE status = 'OPEN' AND booking_id IS NOT NULL;

-- Booking-less tasks (MESSAGE, CALLBACK, MEDICAL_HOLD, ESCALATION) dedupe on the call.
CREATE UNIQUE INDEX staff_tasks_open_call_type_idx
  ON staff_tasks (tenant_id, call_id, type)
  WHERE status = 'OPEN' AND booking_id IS NULL AND call_id IS NOT NULL;

-- The staleness anchor: the availability engine refuses to offer slots when
-- last_success_at for 'vagaro.appointments' is too old to trust.
CREATE TABLE sync_state (
  tenant_id            uuid NOT NULL,
  source               text NOT NULL,   -- 'vagaro.appointments','vagaro.customers','google.calendar'
  cursor               text,
  window_from          timestamptz,
  window_to            timestamptz,
  last_success_at      timestamptz,
  last_attempt_at      timestamptz,
  last_error           text,
  consecutive_failures smallint NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, source)
);

CREATE TABLE audit_log (
  id          bigserial PRIMARY KEY,
  tenant_id   uuid,
  actor_type  text NOT NULL,   -- 'grace','staff','system','worker'
  actor_id    text,
  action      text NOT NULL,
  entity_type text,
  entity_id   text,
  before      jsonb,
  after       jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (tenant_id, occurred_at DESC);
CREATE INDEX ON audit_log (entity_type, entity_id);
