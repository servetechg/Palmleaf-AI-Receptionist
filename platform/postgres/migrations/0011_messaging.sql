-- 0011 — messaging templates, sent messages, consent. data-model.md §11.
CREATE TABLE message_templates (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key         text NOT NULL,
  channel     message_channel NOT NULL,
  body        text NOT NULL,                     -- mustache-style {{placeholders}}
  variables   text[] NOT NULL DEFAULT '{}',
  category    text NOT NULL DEFAULT 'TRANSACTIONAL'
              CHECK (category IN ('TRANSACTIONAL','MARKETING')),
  active      boolean NOT NULL DEFAULT true,
  approved_at timestamptz,
  version     integer NOT NULL DEFAULT 1,
  UNIQUE (tenant_id, key, version)
);

CREATE TABLE messages (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id         uuid REFERENCES customers(id) ON DELETE SET NULL,
  booking_id          uuid REFERENCES bookings(id) ON DELETE SET NULL,
  call_id             uuid REFERENCES calls(id) ON DELETE SET NULL,
  channel             message_channel NOT NULL,
  template_key        text,
  to_address          text NOT NULL,
  body_rendered       text NOT NULL,
  provider_message_id text,
  status              text NOT NULL DEFAULT 'QUEUED',
  error_code          text,
  queued_at           timestamptz NOT NULL DEFAULT now(),
  sent_at             timestamptz,
  delivered_at        timestamptz,
  outbox_event_id     uuid                       -- dedupe key: at-least-once delivery
);
CREATE UNIQUE INDEX messages_outbox_uq ON messages (outbox_event_id) WHERE outbox_event_id IS NOT NULL;
-- data-model.md indexes this on created_at, which the table does not have; queued_at is
-- the equivalent column and is what the ordering actually needs.
CREATE INDEX ON messages (tenant_id, queued_at DESC);

CREATE TABLE consent_log (
  id          bigserial PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  customer_id uuid REFERENCES customers(id) ON DELETE SET NULL,
  phone_e164  text,
  kind        text NOT NULL CHECK (kind IN ('SMS_TRANSACTIONAL','SMS_MARKETING','CALL_RECORDING','POLICY_ACK')),
  granted     boolean NOT NULL,
  source      text NOT NULL,                       -- 'voice','sms_stop','web_form','staff'
  evidence    jsonb NOT NULL DEFAULT '{}'::jsonb,  -- utterance timestamp, call_id, transcript offset
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON consent_log (tenant_id, phone_e164, kind, occurred_at DESC);
