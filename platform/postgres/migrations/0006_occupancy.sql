-- 0006 — calendar_occupancy, the core table. data-model.md §6, availability-engine.md.
--
-- ONE table holds holds, reservations, real appointments and staff blocks, because a hold
-- must block an appointment and vice versa. Two tables would mean two constraints and a
-- race between them.
CREATE TABLE calendar_occupancy (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  subject_type   subject_type NOT NULL,
  subject_id     uuid NOT NULL,           -- provider_id or resource_id (polymorphic by design)

  -- blocked_range INCLUDES buffers; service_range is what the customer is told.
  blocked_range  tstzrange NOT NULL,
  service_range  tstzrange NOT NULL,

  kind           occupancy_kind  NOT NULL,
  state          occupancy_state NOT NULL DEFAULT 'ACTIVE',

  source         text NOT NULL CHECK (source IN ('GRACE','PMS','GOOGLE','MANUAL','SYSTEM')),
  source_ref     text,                    -- pms appointment id / google event id
  call_id        uuid,
  booking_id     uuid,

  expires_at     timestamptz,             -- HOLD and RESERVATION only
  released_at    timestamptz,
  release_reason text,
  metadata       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- carries publicId ("hold-7K2")

  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),

  CHECK (NOT isempty(blocked_range)),
  CHECK (blocked_range @> service_range),
  CHECK ((kind IN ('HOLD','RESERVATION')) = (expires_at IS NOT NULL)),

  -- INVARIANT I2 / ADR-0004 — double-booking is physically impossible, not merely
  -- prevented by application code. Two ACTIVE rows cannot overlap for one subject.
  CONSTRAINT calendar_occupancy_no_overlap EXCLUDE USING gist (
    tenant_id     WITH =,
    subject_type  WITH =,
    subject_id    WITH =,
    blocked_range WITH &&
  ) WHERE (state = 'ACTIVE')
);

-- The exclusion constraint creates its own GiST index, which also serves range queries.
CREATE INDEX occupancy_expiry_idx  ON calendar_occupancy (expires_at)
  WHERE state = 'ACTIVE' AND expires_at IS NOT NULL;
CREATE INDEX occupancy_booking_idx ON calendar_occupancy (booking_id) WHERE booking_id IS NOT NULL;
CREATE INDEX occupancy_source_idx  ON calendar_occupancy (tenant_id, source, source_ref);
CREATE INDEX occupancy_call_idx    ON calendar_occupancy (call_id) WHERE call_id IS NOT NULL;
CREATE INDEX occupancy_public_idx  ON calendar_occupancy ((metadata->>'publicId'))
  WHERE metadata->>'publicId' IS NOT NULL;
