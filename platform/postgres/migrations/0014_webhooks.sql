-- 0014 — inbound webhook staging. core-api.md §9.1.
--
-- Vagaro demands a 2xx within 20 seconds and retries 5 times over 15 minutes otherwise.
-- The receiver therefore does ONE insert and returns; all parsing happens in the worker.
-- dedupe_key is Vagaro's own event id where present (their docs say it exists precisely
-- "to ensure that an event is not processed twice"), falling back to a payload hash.
CREATE TABLE inbound_webhooks (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid,
  source       text NOT NULL,       -- 'vagaro','stripe','twilio','vapi'
  dedupe_key   text NOT NULL,
  payload      jsonb NOT NULL,
  received_at  timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  attempts     smallint NOT NULL DEFAULT 0,
  last_error   text,
  UNIQUE (source, dedupe_key)
);
CREATE INDEX inbound_webhooks_unprocessed_idx ON inbound_webhooks (received_at)
  WHERE processed_at IS NULL;
