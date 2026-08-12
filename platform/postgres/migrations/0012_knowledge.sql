-- 0012 — knowledge entries and approved policy. data-model.md §12.
--
-- Both tables gate on approved_at: an unapproved policy makes Grace say "let me get
-- someone who can confirm that" and transfer, rather than quoting something the client
-- never signed off (GATE-02/GATE-04). Sign-off is a data edit, not a deploy.
CREATE TABLE knowledge_entries (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key              text NOT NULL,
  category         text NOT NULL,
  question_aliases text[] NOT NULL DEFAULT '{}',
  answer_spoken    text NOT NULL,       -- <=2 sentences. What Grace says.
  answer_detail    text,
  active           boolean NOT NULL DEFAULT true,
  approved_by      text,
  approved_at      timestamptz,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, key)
);

CREATE TABLE policies (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key            text NOT NULL CHECK (key IN ('CANCELLATION','DEPOSIT','NO_SHOW','LATE_ARRIVAL','INTAKE','MEDICAL')),
  params         jsonb NOT NULL,      -- machine-readable: {"windowHours":48,...}
  spoken_text    text NOT NULL,       -- verbatim wording Grace uses
  effective_from timestamptz NOT NULL DEFAULT now(),
  effective_to   timestamptz,
  approved_by    text NOT NULL,
  approved_at    timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX policies_active_uq ON policies (tenant_id, key) WHERE effective_to IS NULL;
