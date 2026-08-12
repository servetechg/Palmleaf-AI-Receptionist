-- 0010 — calls and tool invocations. data-model.md §10.
CREATE TABLE calls (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  vapi_call_id         text NOT NULL,
  direction            text NOT NULL DEFAULT 'INBOUND' CHECK (direction IN ('INBOUND','OUTBOUND')),
  from_phone           text,
  to_phone             text,
  customer_id          uuid REFERENCES customers(id) ON DELETE SET NULL,
  started_at           timestamptz NOT NULL,
  ended_at             timestamptz,
  duration_seconds     integer,
  ended_reason         text,
  outcome              call_outcome,
  contained            boolean,                       -- resolved without a human
  transferred_to       text,
  recording_consent    boolean NOT NULL DEFAULT true, -- false => recording suppressed (I7)
  recording_uri        text,
  recording_expires_at timestamptz,
  transcript_uri       text,
  summary_redacted     text,                          -- PHI-scrubbed (I6)
  structured           jsonb NOT NULL DEFAULT '{}'::jsonb,
  cost_cents           integer,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, vapi_call_id)
);
CREATE INDEX ON calls (tenant_id, started_at DESC);
CREATE INDEX ON calls (recording_expires_at) WHERE recording_uri IS NOT NULL;

CREATE TABLE tool_invocations (
  id             bigserial PRIMARY KEY,
  tenant_id      uuid NOT NULL,
  call_id        uuid REFERENCES calls(id) ON DELETE CASCADE,
  vapi_call_id   text,
  tool_call_id   text,
  tool_name      text NOT NULL,
  arguments      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- redacted before insert
  result_summary text,
  latency_ms     integer NOT NULL,
  status         text NOT NULL CHECK (status IN ('OK','VALIDATION_ERROR','DOMAIN_ERROR','DEADLINE','ERROR')),
  error_code     text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON tool_invocations (tenant_id, created_at DESC);
CREATE INDEX ON tool_invocations (tool_name, created_at DESC);
