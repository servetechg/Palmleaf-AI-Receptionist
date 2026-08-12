-- 0003 — tenancy and routing. data-model.md §3.
--
-- ROW-LEVEL SECURITY IS DELIBERATELY NOT ENABLED HERE. Every table carries tenant_id
-- exactly as the frozen design specifies, but FORCE ROW LEVEL SECURITY is deferred to
-- multi-tenant onboarding (one tenant today, single instance). Recorded as a conscious
-- right-sizing decision in the Vagaro integration plan; do not treat its absence as an
-- oversight, and do not add a second tenant without turning it on first.
CREATE TABLE tenants (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text NOT NULL UNIQUE,
  legal_name    text NOT NULL,
  display_name  text NOT NULL,
  timezone      text NOT NULL DEFAULT 'America/Chicago',
  locale        text NOT NULL DEFAULT 'en-US',
  status        text NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','PAUSED','OFFBOARDED')),
  pms_provider  text NOT NULL DEFAULT 'vagaro'
                CHECK (pms_provider IN ('vagaro','mindbody','booker','none')),
  settings      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- How an inbound Vapi payload resolves to a tenant. No hardcoded ids anywhere in code.
CREATE TABLE tenant_channels (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('VAPI_ASSISTANT','VAPI_PHONE_NUMBER','TWILIO_NUMBER','PMS_BUSINESS')),
  external_id text NOT NULL,
  metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, external_id)
);
CREATE INDEX ON tenant_channels (tenant_id) WHERE active;
