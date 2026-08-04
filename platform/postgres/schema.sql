-- Permanent record of Grace's call reporting.
--
-- STATUS: not yet applied anywhere. n8n Cloud cannot reach a database on a laptop, so this
-- waits for a hosted instance (Neon or Supabase free tier is sufficient).
--
-- Until then WF-20/21/22 write to n8n Data Tables, which are viewable in the n8n UI but are
-- capped and not queryable with SQL. The Postgres node in each workflow is already present
-- and wired — just disabled. Turning this on is:
--
--   1. create the database
--   2. run this file
--   3. add a `PalmLeaf Postgres (dev)` credential in n8n
--   4. enable the "Archive to Postgres" node in each workflow
--   5. make n8n-apply
--
-- No workflow redesign and no documentation change.

-- One row per day. The headline operating numbers.
CREATE TABLE IF NOT EXISTS call_metrics (
    day                   date PRIMARY KEY,
    total_calls           integer     NOT NULL DEFAULT 0,
    booked                integer     NOT NULL DEFAULT 0,
    escalated             integer     NOT NULL DEFAULT 0,
    medical_holds         integer     NOT NULL DEFAULT 0,
    avg_duration_seconds  integer     NOT NULL DEFAULT 0,
    -- Share of calls handled without a human. The headline number for an AI receptionist.
    containment_pct       integer     NOT NULL DEFAULT 0,
    recorded_at           timestamptz NOT NULL DEFAULT now()
);

-- Calls chosen for human review. Random sampling, so ordinary calls get listened to and
-- slow drift in Grace's behaviour is caught — not just the ones that already went wrong.
CREATE TABLE IF NOT EXISTS call_samples (
    call_id           text PRIMARY KEY,
    sampled_week      date        NOT NULL,
    started_at        timestamptz,
    duration_seconds  integer     NOT NULL DEFAULT 0,
    intent            text        NOT NULL DEFAULT 'unknown',
    booked            boolean     NOT NULL DEFAULT false,
    escalated         boolean     NOT NULL DEFAULT false,
    recording_url     text,
    reviewed          boolean     NOT NULL DEFAULT false,
    reviewer_notes    text,
    recorded_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS call_samples_week_idx ON call_samples (sampled_week, reviewed);

-- Calls that tripped a quality signal: errored, ended under 15 seconds, or escalated.
CREATE TABLE IF NOT EXISTS call_flags (
    id                bigserial PRIMARY KEY,
    call_id           text        NOT NULL,
    detected_at       timestamptz NOT NULL DEFAULT now(),
    reasons           text        NOT NULL,
    duration_seconds  integer     NOT NULL DEFAULT 0,
    recording_url     text,
    -- Same call can trip on different days; dedupe per call per reason set.
    UNIQUE (call_id, reasons)
);
CREATE INDEX IF NOT EXISTS call_flags_detected_idx ON call_flags (detected_at DESC);

-- NOTE ON SCOPE (I6): none of these tables holds a transcript, a caller name, a phone
-- number, or any health detail. Reporting needs counts and outcomes, not content. The
-- recording URL is a pointer into Vapi, governed by Vapi's retention, not copied here.
