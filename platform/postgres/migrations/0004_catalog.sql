-- 0004 — catalog: services, providers, resources. data-model.md §4.
CREATE TABLE providers (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pms_employee_id     text,
  display_name        text NOT NULL,
  spoken_name         text NOT NULL,          -- what Grace says aloud
  google_calendar_id  text,
  bio_short           text,
  active              boolean NOT NULL DEFAULT true,
  accepts_new_clients boolean NOT NULL DEFAULT true,
  sort_order          integer NOT NULL DEFAULT 100,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, pms_employee_id)
);
CREATE INDEX ON providers (tenant_id) WHERE active;
CREATE INDEX providers_name_trgm ON providers USING gin (spoken_name gin_trgm_ops);

CREATE TABLE resources (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name      text NOT NULL,
  kind      text NOT NULL DEFAULT 'ROOM',
  capacity  integer NOT NULL DEFAULT 1,
  active    boolean NOT NULL DEFAULT true,
  UNIQUE (tenant_id, name)
);

-- approved_at is load-bearing: Grace MUST NOT quote a price or book a service whose
-- approved_at IS NULL (GATE-04). The availability SQL enforces it, not the prompt.
CREATE TABLE services (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id              uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  code                   text NOT NULL,
  pms_service_id         text,
  display_name           text NOT NULL,
  spoken_name            text NOT NULL,
  aliases                text[] NOT NULL DEFAULT '{}',
  category               text,
  duration_min           integer NOT NULL CHECK (duration_min > 0),
  buffer_before_min      integer NOT NULL DEFAULT 0 CHECK (buffer_before_min >= 0),
  buffer_after_min       integer NOT NULL DEFAULT 15 CHECK (buffer_after_min >= 0),
  price_member_cents     integer CHECK (price_member_cents >= 0),
  price_nonmember_cents  integer NOT NULL CHECK (price_nonmember_cents >= 0),
  deposit_cents          integer NOT NULL DEFAULT 0 CHECK (deposit_cents >= 0),
  deposit_type           text NOT NULL DEFAULT 'FLAT' CHECK (deposit_type IN ('FLAT','PERCENT','NONE')),
  deposit_percent_bp     integer CHECK (deposit_percent_bp BETWEEN 0 AND 10000),
  requires_intake        boolean NOT NULL DEFAULT true,
  requires_resource_kind text,
  bookable_by_ai         boolean NOT NULL DEFAULT true,
  min_lead_time_min      integer NOT NULL DEFAULT 120,
  max_advance_days       integer NOT NULL DEFAULT 90,
  active                 boolean NOT NULL DEFAULT true,
  approved_at            timestamptz,
  approved_by            text,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);
CREATE INDEX ON services (tenant_id) WHERE active AND bookable_by_ai;
CREATE INDEX services_alias_gin ON services USING gin (aliases);

CREATE TABLE provider_services (
  tenant_id             uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider_id           uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  service_id            uuid NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  price_override_cents  integer,
  duration_override_min integer,
  proficiency           smallint NOT NULL DEFAULT 3 CHECK (proficiency BETWEEN 1 AND 5),
  PRIMARY KEY (provider_id, service_id)
);
CREATE INDEX ON provider_services (tenant_id, service_id);
