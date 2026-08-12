-- 0007 — customers. data-model.md §7.
--
-- medical_hold is a boolean and NOTHING else. There is deliberately no medical_notes
-- column: storing health detail is an invariant I6 violation requiring legal review,
-- not a migration.
CREATE TABLE customers (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pms_customer_id       text,
  phone_e164            text NOT NULL CHECK (phone_e164 ~ '^\+[1-9]\d{7,14}$'),
  email                 citext,
  first_name            text,
  last_name             text,
  preferred_name        text,
  membership_tier       text,
  membership_active     boolean NOT NULL DEFAULT false,
  membership_expires_at timestamptz,
  preferred_provider_id uuid REFERENCES providers(id) ON DELETE SET NULL,
  intake_completed_at   timestamptz,
  medical_hold          boolean NOT NULL DEFAULT false,
  medical_hold_set_at   timestamptz,
  sms_opt_out_at        timestamptz,
  do_not_record         boolean NOT NULL DEFAULT false,
  visit_count           integer NOT NULL DEFAULT 0,
  last_visit_at         timestamptz,
  last_synced_at        timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, phone_e164)
);
CREATE UNIQUE INDEX customers_pms_idx ON customers (tenant_id, pms_customer_id)
  WHERE pms_customer_id IS NOT NULL;
CREATE INDEX customers_email_idx ON customers (tenant_id, email) WHERE email IS NOT NULL;
