-- 0005 — schedule templates and exceptions. data-model.md §5.
CREATE TABLE business_hours (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  day_of_week    smallint NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0 = Sunday
  opens_at       time NOT NULL,
  closes_at      time NOT NULL,
  effective_from date NOT NULL DEFAULT CURRENT_DATE,
  effective_to   date,
  CHECK (closes_at > opens_at)
);
CREATE INDEX ON business_hours (tenant_id, day_of_week);

CREATE TABLE provider_shifts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider_id    uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  day_of_week    smallint NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  starts_at      time NOT NULL,
  ends_at        time NOT NULL,
  effective_from date NOT NULL DEFAULT CURRENT_DATE,
  effective_to   date,
  CHECK (ends_at > starts_at)
);
CREATE INDEX ON provider_shifts (tenant_id, provider_id, day_of_week);

CREATE TABLE schedule_exceptions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider_id uuid REFERENCES providers(id) ON DELETE CASCADE,  -- NULL => whole business
  on_date     date NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('CLOSED','HOLIDAY','TIME_OFF','SPECIAL_HOURS')),
  opens_at    time,
  closes_at   time,
  note        text,
  source      text NOT NULL DEFAULT 'MANUAL',
  created_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (kind <> 'SPECIAL_HOURS' OR (opens_at IS NOT NULL AND closes_at IS NOT NULL))
);
CREATE INDEX ON schedule_exceptions (tenant_id, on_date);
