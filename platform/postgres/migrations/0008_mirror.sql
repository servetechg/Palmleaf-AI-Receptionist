-- 0008 — appointment mirror. data-model.md §8.
--
-- This is what invariant I1 rests on: in-call availability reads hit THIS table, never
-- Vagaro. Vagaro's 5,000-calls/month quota makes that architectural, not merely fast.
CREATE TABLE appointments_mirror (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pms_appointment_id text NOT NULL,
  provider_id        uuid REFERENCES providers(id) ON DELETE SET NULL,
  service_id         uuid REFERENCES services(id) ON DELETE SET NULL,
  customer_id        uuid REFERENCES customers(id) ON DELETE SET NULL,
  occupancy_id       uuid REFERENCES calendar_occupancy(id) ON DELETE SET NULL,
  starts_at          timestamptz NOT NULL,
  ends_at            timestamptz NOT NULL,
  status             text NOT NULL,
  booked_via         text,
  pms_updated_at     timestamptz,
  last_synced_at     timestamptz NOT NULL DEFAULT now(),
  raw                jsonb NOT NULL DEFAULT '{}'::jsonb,   -- PMS payload, for debugging drift
  CHECK (ends_at > starts_at),
  UNIQUE (tenant_id, pms_appointment_id)
);
CREATE INDEX ON appointments_mirror (tenant_id, starts_at);
CREATE INDEX ON appointments_mirror (tenant_id, provider_id, starts_at);
CREATE INDEX ON appointments_mirror (tenant_id, customer_id, starts_at DESC);
