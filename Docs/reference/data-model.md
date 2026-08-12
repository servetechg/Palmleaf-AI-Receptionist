# data-model — Data Model

**Status:** Frozen — unblocks at [08-roadmap](../plans/08-roadmap.md) task **C-02**. No external dependency; frozen because it is not yet being built, not because anything blocks it.
**Read before:** any database or repository work.
**Implements:** ADR-0003, ADR-0004, ADR-0005, ADR-0008, ADR-0016
**Enforces:** I2, I3, I6
**Last verified:** 2026-08-04 — rewritten for SQLAlchemy 2.0 + Alembic (ADR-0016); the DDL itself is unchanged and was never language-specific.

> **In one paragraph:** this document settles the complete Postgres schema — every table, index,
> constraint, enum and row-level-security policy — and the migration discipline around it. Its
> load-bearing element is the `EXCLUDE` constraint that makes double-booking **physically
> impossible to insert** (ADR-0004). It deliberately does **not** describe how any of it is
> queried; that is [availability-engine](availability-engine.md) and [core-api](core-api.md).

---

## 1. Principles

1. **The database enforces truth, not the application.** Anything expressible as a constraint is a
   constraint. Application checks are a nicety on top, never the guarantee.
2. **One occupancy table.** Every reason a provider or room is busy — soft hold, reservation, confirmed
   appointment, mirrored PMS booking, external calendar block, time off — is a row in the same table with
   the same range type. This is what makes a single exclusion constraint sufficient (ADR-0004).
3. **`tenant_id` on every business table**, first column after `id`, in every index prefix, enforced by RLS.
4. **Time is `timestamptz`.** Recurring schedule templates use `time` + a weekday and are resolved against
   the tenant's timezone at query time. Never store local time in a `timestamp`.
5. **Money is `integer` cents.** Never `float`. Never `numeric` for currency in this codebase — cents are
   exact and JSON-safe.
6. **PHI is not stored.** Screening produces a boolean. Free text that could contain health information is
   redacted before persistence ([05-security-and-compliance](../plans/05-security-and-compliance.md) §4).
7. **Migrations are forward-only and additive-first.** Never edit a merged migration. Destructive changes
   are two deploys: stop writing, then drop.

---

## 2. Extensions and enums

```sql
-- migration 0001_extensions.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gist;  -- REQUIRED: uuid/text equality inside EXCLUDE
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- fuzzy provider/service/customer name matching
CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive email
```

```sql
-- migration 0002_enums.sql
CREATE TYPE occupancy_kind  AS ENUM ('HOLD','RESERVATION','APPOINTMENT','EXTERNAL_BLOCK','TIME_OFF','CLOSURE');
CREATE TYPE occupancy_state AS ENUM ('ACTIVE','RELEASED','EXPIRED','SUPERSEDED');
CREATE TYPE subject_type    AS ENUM ('PROVIDER','RESOURCE');

CREATE TYPE booking_state AS ENUM (
  'DRAFT',            -- hold promoted, row created, nothing external yet
  'PENDING_DEPOSIT',  -- deposit required and link sent
  'CONFIRMED',        -- deposit satisfied (or not required); slot is the caller's
  'WRITING_TO_PMS',   -- Track B / native write in flight
  'SYNCED',           -- a real PMS appointment exists and is linked
  'NEEDS_STAFF',      -- automation exhausted; Track D. SLOT REMAINS HELD.
  'CANCELLED',
  'EXPIRED'           -- deposit never paid; slot released
);

CREATE TYPE deposit_state AS ENUM ('NOT_REQUIRED','PENDING','PAID','FAILED','REFUNDED','FORFEITED');
CREATE TYPE outbox_status AS ENUM ('PENDING','IN_FLIGHT','DONE','FAILED','DEAD');
CREATE TYPE task_status   AS ENUM ('OPEN','ACKNOWLEDGED','RESOLVED','CANCELLED');
CREATE TYPE message_channel AS ENUM ('SMS','EMAIL','VOICE');
CREATE TYPE call_outcome  AS ENUM (
  'BOOKED','RESCHEDULED','CANCELLED','INFO_ONLY','MESSAGE_TAKEN',
  'TRANSFERRED','MEDICAL_HOLD','ABANDONED','FAILED'
);
```

> **Why enums and not lookup tables:** these values are referenced in code as exhaustive `switch`
> statements. A Postgres enum plus a Python `Literal` (which replaced the TypeScript union) gives a type error when a state is added and a
> handler is not updated. Adding a value is `ALTER TYPE ... ADD VALUE` — cheap and non-blocking in PG 16.

---

## 3. Tenancy and routing

```sql
-- migration 0003_tenancy.sql
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

-- How an inbound Vapi payload is resolved to a tenant. No hardcoded IDs anywhere in code.
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
```

`tenants.settings` holds non-relational tenant config, validated by a Pydantic model in
`grace_contracts`:

```jsonc
// TARGET — shape of tenants.settings
{
  "holdTtlSeconds": 240,
  "reservationTtlSeconds": 900,
  "depositExpiryMinutes": 1440,
  "maxSlotsOffered": 3,
  "transferExtension": "101",
  "managerMobile": "+1847...",
  "recordingRetentionDays": 90,
  "featureFlags": { "trackA": true, "trackB": false, "trackC": true, "deposits": true },
  "killSwitch": false
}
```

---

## 4. Catalog: services, providers, resources

```sql
-- migration 0004_catalog.sql
CREATE TABLE providers (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pms_employee_id    text,
  display_name       text NOT NULL,          -- "Maria Alvarez"
  spoken_name        text NOT NULL,          -- "Maria"  — what Grace says aloud
  google_calendar_id text,                   -- Track A target
  bio_short          text,
  active             boolean NOT NULL DEFAULT true,
  accepts_new_clients boolean NOT NULL DEFAULT true,
  sort_order         integer NOT NULL DEFAULT 100,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, pms_employee_id)
);
CREATE INDEX ON providers (tenant_id) WHERE active;
CREATE INDEX providers_name_trgm ON providers USING gin (spoken_name gin_trgm_ops);

CREATE TABLE resources (                     -- treatment rooms, equipment
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name        text NOT NULL,
  kind        text NOT NULL DEFAULT 'ROOM',
  capacity    integer NOT NULL DEFAULT 1,
  active      boolean NOT NULL DEFAULT true,
  UNIQUE (tenant_id, name)
);

CREATE TABLE services (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id              uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  code                   text NOT NULL,         -- 'massage_60' — the LLM-facing identifier
  pms_service_id         text,
  display_name           text NOT NULL,         -- "60-Minute Therapeutic Massage"
  spoken_name            text NOT NULL,         -- "sixty minute massage"
  aliases                text[] NOT NULL DEFAULT '{}',  -- "hour massage","60 min","deep tissue hour"
  category               text,
  duration_min           integer NOT NULL CHECK (duration_min > 0),
  buffer_before_min      integer NOT NULL DEFAULT 0 CHECK (buffer_before_min >= 0),
  buffer_after_min       integer NOT NULL DEFAULT 15 CHECK (buffer_after_min >= 0),
  price_member_cents     integer CHECK (price_member_cents >= 0),
  price_nonmember_cents  integer NOT NULL CHECK (price_nonmember_cents >= 0),
  deposit_cents          integer NOT NULL DEFAULT 0 CHECK (deposit_cents >= 0),
  deposit_type           text NOT NULL DEFAULT 'FLAT' CHECK (deposit_type IN ('FLAT','PERCENT','NONE')),
  deposit_percent_bp     integer CHECK (deposit_percent_bp BETWEEN 0 AND 10000), -- basis points
  requires_intake        boolean NOT NULL DEFAULT true,
  requires_resource_kind text,
  bookable_by_ai         boolean NOT NULL DEFAULT true,   -- kill-switch per service
  min_lead_time_min      integer NOT NULL DEFAULT 120,
  max_advance_days       integer NOT NULL DEFAULT 90,
  active                 boolean NOT NULL DEFAULT true,
  approved_at            timestamptz,           -- [08-roadmap](../plans/08-roadmap.md) sign-off gate: unapproved ⇒ Grace won't quote it
  approved_by            text,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, code)
);
CREATE INDEX ON services (tenant_id) WHERE active AND bookable_by_ai;
CREATE INDEX services_alias_gin ON services USING gin (aliases);

CREATE TABLE provider_services (
  tenant_id            uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider_id          uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  service_id           uuid NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  price_override_cents integer,
  duration_override_min integer,
  proficiency          smallint NOT NULL DEFAULT 3 CHECK (proficiency BETWEEN 1 AND 5),
  PRIMARY KEY (provider_id, service_id)
);
CREATE INDEX ON provider_services (tenant_id, service_id);
```

> **`approved_at` is load-bearing.** Design brief §15 lists an unresolved service catalog and contradictory
> policies. Grace **MUST NOT** quote a price or book a service whose `approved_at IS NULL`. This turns a
> project-management risk into an enforced data rule: an unsigned-off service simply routes to a human.

---

## 5. Schedule templates and exceptions

```sql
-- migration 0005_schedule.sql
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
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  provider_id  uuid REFERENCES providers(id) ON DELETE CASCADE,  -- NULL ⇒ whole business
  on_date      date NOT NULL,
  kind         text NOT NULL CHECK (kind IN ('CLOSED','HOLIDAY','TIME_OFF','SPECIAL_HOURS')),
  opens_at     time,
  closes_at    time,
  note         text,
  source       text NOT NULL DEFAULT 'MANUAL',
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (kind <> 'SPECIAL_HOURS' OR (opens_at IS NOT NULL AND closes_at IS NOT NULL))
);
CREATE INDEX ON schedule_exceptions (tenant_id, on_date);
```

---

## 6. `calendar_occupancy` — the core table

This is the most important table in the system. Read [availability-engine](availability-engine.md) before changing it.

```sql
-- migration 0006_occupancy.sql
CREATE TABLE calendar_occupancy (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  subject_type  subject_type NOT NULL,
  subject_id    uuid NOT NULL,            -- provider_id or resource_id (polymorphic by design)

  -- blocked_range INCLUDES buffers; service_range is what the customer is told.
  blocked_range tstzrange NOT NULL,
  service_range tstzrange NOT NULL,

  kind          occupancy_kind  NOT NULL,
  state         occupancy_state NOT NULL DEFAULT 'ACTIVE',

  -- provenance
  source        text NOT NULL CHECK (source IN ('GRACE','PMS','GOOGLE','MANUAL','SYSTEM')),
  source_ref    text,                     -- pms appointment id / google event id
  call_id       uuid,
  booking_id    uuid,

  expires_at    timestamptz,              -- HOLD and RESERVATION only
  released_at   timestamptz,
  release_reason text,

  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),

  CHECK (NOT isempty(blocked_range)),
  CHECK (blocked_range @> service_range),
  CHECK ((kind IN ('HOLD','RESERVATION')) = (expires_at IS NOT NULL)),

  -- ★ INVARIANT I2 / ADR-0004 — physically impossible to double-book ★
  CONSTRAINT calendar_occupancy_no_overlap EXCLUDE USING gist (
    tenant_id    WITH =,
    subject_type WITH =,
    subject_id   WITH =,
    blocked_range WITH &&
  ) WHERE (state = 'ACTIVE')
);

-- The exclusion constraint creates its own GiST index, which also serves range queries.
CREATE INDEX occupancy_expiry_idx ON calendar_occupancy (expires_at)
  WHERE state = 'ACTIVE' AND expires_at IS NOT NULL;
CREATE INDEX occupancy_booking_idx ON calendar_occupancy (booking_id) WHERE booking_id IS NOT NULL;
CREATE INDEX occupancy_source_idx  ON calendar_occupancy (tenant_id, source, source_ref);
CREATE INDEX occupancy_call_idx    ON calendar_occupancy (call_id) WHERE call_id IS NOT NULL;
```

### 6.1 Why this shape

| Choice | Reason |
|---|---|
| One table for holds *and* appointments | A hold must block an appointment and vice versa. Two tables means two constraints and a race between them. |
| `blocked_range` ⊇ `service_range` | Room turnover buffer is invisible to the caller but must block the calendar. Storing both means we never recompute buffers when quoting. |
| Polymorphic `subject_type`/`subject_id` | Rooms need the identical guarantee. One constraint covers providers and rooms. |
| Partial index `WHERE state='ACTIVE'` | Released and expired rows accumulate forever but never participate in overlap checks; the index stays small. |
| Soft delete via `state` | A released hold is evidence in a dispute. Never `DELETE`. |

### 6.2 The lifecycle

```
                  checkAvailability
                         │
                   INSERT kind=HOLD, expires_at = now()+4min
                         │
          ┌──────────────┼──────────────────────┐
     caller accepts   TTL passes           call ends
          │              │                      │
   kind→RESERVATION  state→EXPIRED        state→RELEASED
   expires_at=+15min   (sweeper)          (end-of-call)
          │
   deposit paid / not required
          │
   kind→APPOINTMENT, expires_at=NULL, booking_id set
          │
   PMS write-back succeeds → source_ref = pms appointment id
```

Transitions are `UPDATE`s on the same row — the row's identity is stable from hold to appointment, so
`occupancy_id` is a durable handle to "the caller's slot" through the whole saga.

---

## 7. Customers

```sql
-- migration 0007_customers.sql
CREATE TABLE customers (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pms_customer_id      text,
  phone_e164           text NOT NULL CHECK (phone_e164 ~ '^\+[1-9]\d{7,14}$'),
  email                citext,
  first_name           text,
  last_name            text,
  preferred_name       text,
  membership_tier      text,
  membership_active    boolean NOT NULL DEFAULT false,
  membership_expires_at timestamptz,
  preferred_provider_id uuid REFERENCES providers(id) ON DELETE SET NULL,
  intake_completed_at  timestamptz,
  medical_hold         boolean NOT NULL DEFAULT false,   -- BOOLEAN ONLY. See [05-security-and-compliance](../plans/05-security-and-compliance.md) §4 / I6.
  medical_hold_set_at  timestamptz,
  sms_opt_out_at       timestamptz,
  do_not_record        boolean NOT NULL DEFAULT false,
  visit_count          integer NOT NULL DEFAULT 0,
  last_visit_at        timestamptz,
  last_synced_at       timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, phone_e164)
);
CREATE UNIQUE INDEX customers_pms_idx ON customers (tenant_id, pms_customer_id)
  WHERE pms_customer_id IS NOT NULL;
CREATE INDEX customers_email_idx ON customers (tenant_id, email) WHERE email IS NOT NULL;
```

> **`medical_hold` is a boolean and nothing else.** There is deliberately no `medical_notes` column.
> If someone proposes adding one, that is an invariant I6 violation and requires a legal review, not a
> migration ([05-security-and-compliance](../plans/05-security-and-compliance.md) §4).

---

## 8. Appointment mirror

```sql
-- migration 0008_mirror.sql
CREATE TABLE appointments_mirror (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pms_appointment_id text NOT NULL,
  provider_id        uuid REFERENCES providers(id) ON DELETE SET NULL,
  service_id         uuid REFERENCES services(id) ON DELETE SET NULL,
  customer_id        uuid REFERENCES customers(id) ON DELETE SET NULL,
  occupancy_id       uuid REFERENCES calendar_occupancy(id) ON DELETE SET NULL,
  starts_at          timestamptz NOT NULL,
  ends_at            timestamptz NOT NULL,
  status             text NOT NULL,
  booked_via         text,
  pms_updated_at     timestamptz,
  last_synced_at     timestamptz NOT NULL DEFAULT now(),
  raw                jsonb NOT NULL DEFAULT '{}'::jsonb,   -- PMS payload, for debugging drift
  CHECK (ends_at > starts_at),
  UNIQUE (tenant_id, pms_appointment_id)
);
CREATE INDEX ON appointments_mirror (tenant_id, starts_at);
CREATE INDEX ON appointments_mirror (tenant_id, provider_id, starts_at);
CREATE INDEX ON appointments_mirror (tenant_id, customer_id, starts_at DESC);
```

Every mirror row with a future `starts_at` **must** have a corresponding `ACTIVE` occupancy row. The
nightly reconciliation asserts this and reports violations ([booking-write-path](booking-write-path.md) §6).

---

## 9. Bookings — the saga aggregate

```sql
-- migration 0009_bookings.sql
CREATE TABLE bookings (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id          uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

  idempotency_key    text NOT NULL,          -- '{callId}:{slotId}' — see [availability-engine](availability-engine.md) §6
  call_id            uuid,
  customer_id        uuid NOT NULL REFERENCES customers(id),
  service_id         uuid NOT NULL REFERENCES services(id),
  provider_id        uuid NOT NULL REFERENCES providers(id),
  occupancy_id       uuid NOT NULL REFERENCES calendar_occupancy(id),

  starts_at          timestamptz NOT NULL,
  ends_at            timestamptz NOT NULL,

  state              booking_state NOT NULL DEFAULT 'DRAFT',
  state_reason       text,
  state_changed_at   timestamptz NOT NULL DEFAULT now(),
  version            integer NOT NULL DEFAULT 1,   -- optimistic concurrency

  price_cents        integer NOT NULL,
  is_member_price    boolean NOT NULL DEFAULT false,
  deposit_cents      integer NOT NULL DEFAULT 0,
  deposit_state      deposit_state NOT NULL DEFAULT 'NOT_REQUIRED',
  deposit_due_at     timestamptz,

  stripe_session_id      text,
  stripe_payment_intent  text,

  track_a_event_id   text,                   -- Google Calendar event id
  track_b_status     text NOT NULL DEFAULT 'NOT_STARTED',
  track_b_attempts   smallint NOT NULL DEFAULT 0,
  track_b_last_error text,
  pms_appointment_id text,

  intake_sent_at     timestamptz,
  confirmation_sent_at timestamptz,
  confirmed_at       timestamptz,
  cancelled_at       timestamptz,
  cancellation_reason text,
  change_fee_cents   integer NOT NULL DEFAULT 0,
  rescheduled_from   uuid REFERENCES bookings(id),

  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),

  CHECK (ends_at > starts_at),
  CONSTRAINT bookings_idempotency_uq UNIQUE (tenant_id, idempotency_key)   -- ★ I3 ★
);
CREATE INDEX ON bookings (tenant_id, state) WHERE state NOT IN ('CANCELLED','EXPIRED','SYNCED');
CREATE INDEX ON bookings (tenant_id, starts_at);
CREATE INDEX ON bookings (tenant_id, customer_id, starts_at DESC);
CREATE INDEX ON bookings (deposit_due_at) WHERE deposit_state = 'PENDING';
CREATE UNIQUE INDEX bookings_occupancy_uq ON bookings (occupancy_id)
  WHERE state NOT IN ('CANCELLED','EXPIRED');

-- Full audit trail of every state transition. Append-only.
CREATE TABLE booking_events (
  id          bigserial PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  booking_id  uuid NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  from_state  booking_state,
  to_state    booking_state NOT NULL,
  actor       text NOT NULL,       -- 'grace' | 'worker:track-b' | 'stripe' | 'staff:<id>' | 'system'
  reason      text,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON booking_events (booking_id, occurred_at);
```

`bookings.idempotency_key` UNIQUE is the database-level defence against Vapi retrying a `createBooking`
tool call. The handler relies on `ON CONFLICT DO NOTHING ... RETURNING` and re-reads on conflict ([availability-engine](availability-engine.md) §6).

---

## 10. Calls, tool invocations, transcripts

```sql
-- migration 0010_calls.sql
CREATE TABLE calls (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  vapi_call_id      text NOT NULL,
  direction         text NOT NULL DEFAULT 'INBOUND' CHECK (direction IN ('INBOUND','OUTBOUND')),
  from_phone        text,
  to_phone          text,
  customer_id       uuid REFERENCES customers(id) ON DELETE SET NULL,
  started_at        timestamptz NOT NULL,
  ended_at          timestamptz,
  duration_seconds  integer,
  ended_reason      text,
  outcome           call_outcome,
  contained         boolean,                       -- resolved without a human
  transferred_to    text,
  recording_consent boolean NOT NULL DEFAULT true, -- false ⇒ recording suppressed (IL, [05-security-and-compliance](../plans/05-security-and-compliance.md) §2)
  recording_uri     text,
  recording_expires_at timestamptz,                -- retention enforcement
  transcript_uri    text,
  summary_redacted  text,                          -- PHI-scrubbed. See [05-security-and-compliance](../plans/05-security-and-compliance.md) §4.
  structured        jsonb NOT NULL DEFAULT '{}'::jsonb,
  cost_cents        integer,
  created_at        timestamptz NOT NULL DEFAULT now(),
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
```

> **Volume note.** `tool_invocations` grows at ~8 rows/call. At 45 calls/day that is ~130k rows/year —
> trivial. At 50 tenants it is 6.5M/year, still fine. Convert to monthly `PARTITION BY RANGE (created_at)`
> when it passes 50M rows; the schema is already partition-compatible (no unique constraint that excludes
> the partition key). Do not partition prematurely.

---

## 11. Messaging and consent

```sql
-- migration 0011_messaging.sql
CREATE TABLE message_templates (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key           text NOT NULL,           -- 'booking_confirmation','deposit_link','intake_form',...
  channel       message_channel NOT NULL,
  body          text NOT NULL,           -- mustache-style {{placeholders}}
  variables     text[] NOT NULL DEFAULT '{}',
  category      text NOT NULL DEFAULT 'TRANSACTIONAL'
                CHECK (category IN ('TRANSACTIONAL','MARKETING')),
  active        boolean NOT NULL DEFAULT true,
  approved_at   timestamptz,
  version       integer NOT NULL DEFAULT 1,
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
CREATE INDEX ON messages (tenant_id, created_at DESC);

CREATE TABLE consent_log (
  id          bigserial PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  customer_id uuid REFERENCES customers(id) ON DELETE SET NULL,
  phone_e164  text,
  kind        text NOT NULL CHECK (kind IN ('SMS_TRANSACTIONAL','SMS_MARKETING','CALL_RECORDING','POLICY_ACK')),
  granted     boolean NOT NULL,
  source      text NOT NULL,       -- 'voice','sms_stop','web_form','staff'
  evidence    jsonb NOT NULL DEFAULT '{}'::jsonb,  -- utterance timestamp, call_id, transcript offset
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON consent_log (tenant_id, phone_e164, kind, occurred_at DESC);
```

`consent_log` with `kind='POLICY_ACK'` is how the design brief's "get explicit verbal confirmation, log it
for dispute defence" (§7.1) is satisfied. It records *that* consent was given, with a pointer to the
transcript offset — not the audio itself.

---

## 12. Knowledge and approved policy

Directly implements the design brief's §4.5 "one voice, one policy set" requirement.

```sql
-- migration 0012_knowledge.sql
CREATE TABLE knowledge_entries (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key          text NOT NULL,        -- 'hours','address','parking','memberships','holidays'
  category     text NOT NULL,
  question_aliases text[] NOT NULL DEFAULT '{}',
  answer_spoken text NOT NULL,       -- ≤2 sentences. What Grace says.
  answer_detail text,                -- longer form, used for SMS/email follow-up
  active       boolean NOT NULL DEFAULT true,
  approved_by  text,
  approved_at  timestamptz,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, key)
);

CREATE TABLE policies (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key           text NOT NULL CHECK (key IN ('CANCELLATION','DEPOSIT','NO_SHOW','LATE_ARRIVAL','INTAKE','MEDICAL')),
  params        jsonb NOT NULL,      -- machine-readable: {"windowHours":48,"feeType":"DEPOSIT_FORFEIT"}
  spoken_text   text NOT NULL,       -- verbatim wording Grace uses. Approved by the client.
  effective_from timestamptz NOT NULL DEFAULT now(),
  effective_to  timestamptz,
  approved_by   text NOT NULL,
  approved_at   timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX policies_active_uq ON policies (tenant_id, key) WHERE effective_to IS NULL;
```

> **Enforcement:** `getBusinessInfo` and every policy-quoting path read from these tables and return
> `approved_at IS NOT NULL` rows only. If a policy is unapproved, Grace says *"Let me get someone who can
> confirm that for you"* and transfers. That converts design brief §15 items 1–5 from a launch blocker
> into a graceful degradation, and it makes the client's sign-off a data-entry action with an audit trail.

---

## 13. Operations: outbox, tasks, idempotency, sync state

```sql
-- migration 0013_ops.sql
CREATE TABLE outbox_events (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL,
  aggregate_type  text NOT NULL,     -- 'booking','call','customer'
  aggregate_id    uuid NOT NULL,
  event_type      text NOT NULL,     -- 'booking.confirmed','sms.send','pms.write_appointment', ...
  payload         jsonb NOT NULL,
  status          outbox_status NOT NULL DEFAULT 'PENDING',
  attempts        smallint NOT NULL DEFAULT 0,
  max_attempts    smallint NOT NULL DEFAULT 8,
  available_at    timestamptz NOT NULL DEFAULT now(),
  locked_by       text,
  locked_at       timestamptz,
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  processed_at    timestamptz
);
CREATE INDEX outbox_ready_idx ON outbox_events (available_at, id)
  WHERE status IN ('PENDING','FAILED');
CREATE INDEX outbox_aggregate_idx ON outbox_events (aggregate_type, aggregate_id);

CREATE TABLE idempotency_keys (
  tenant_id     uuid NOT NULL,
  scope         text NOT NULL,        -- tool name or endpoint
  key           text NOT NULL,
  request_hash  text NOT NULL,
  status        text NOT NULL CHECK (status IN ('IN_FLIGHT','COMPLETED')),
  status_code   integer,
  response      jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL DEFAULT now() + interval '24 hours',
  PRIMARY KEY (tenant_id, scope, key)
);
CREATE INDEX ON idempotency_keys (expires_at);

CREATE TYPE staff_task_type AS ENUM (
  'MESSAGE','MEDICAL_HOLD','BOOKING_WRITE_FAILED','DISPUTE','CALLBACK',
  'ESCALATION',          -- flagEscalation, [03-vapi-layer](../plans/03-vapi-layer.md) §7
  'OUTBOX_DEAD',         -- attempts >= max_attempts, [booking-write-path](booking-write-path.md) §88
  'RECONCILIATION_DRIFT',-- [01-architecture](../plans/01-architecture.md)
  'PMS_COLLISION'        -- [availability-engine](availability-engine.md)
);

CREATE TABLE staff_tasks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  type            staff_task_type NOT NULL,
  priority        smallint NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  title           text NOT NULL,
  body            text,
  payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  call_id         uuid REFERENCES calls(id) ON DELETE SET NULL,
  booking_id      uuid REFERENCES bookings(id) ON DELETE SET NULL,
  customer_id     uuid REFERENCES customers(id) ON DELETE SET NULL,
  status          task_status NOT NULL DEFAULT 'OPEN',
  due_at          timestamptz,
  assigned_to     text,
  acknowledged_at timestamptz,     -- ← set when status → ACKNOWLEDGED. WF-18 depends on this.
  resolved_at     timestamptz,
  resolution      text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON staff_tasks (tenant_id, status, priority, created_at);

-- Backs the `staff.notify` idempotency contract in [booking-write-path](booking-write-path.md), which asserted this index
-- but never defined it. Partial: only OPEN rows collide.
CREATE UNIQUE INDEX staff_tasks_open_booking_type_idx
  ON staff_tasks (tenant_id, booking_id, type)
  WHERE status = 'OPEN' AND booking_id IS NOT NULL;

-- Booking-less tasks (MESSAGE, CALLBACK, MEDICAL_HOLD, ESCALATION) dedupe on the call instead.
CREATE UNIQUE INDEX staff_tasks_open_call_type_idx
  ON staff_tasks (tenant_id, call_id, type)
  WHERE status = 'OPEN' AND booking_id IS NULL AND call_id IS NOT NULL;

-- Priority semantics. [booking-write-path](booking-write-path.md) writes these as the STRINGS "P1"/"P3"; the column is a smallint.
-- This is the mapping. Only 1–3 are routed by WF-12; 4–5 exist for future backlog grooming.
--
--   1 = P1  page now      → staff notification + SMS manager + 15-min unacknowledged escalation (WF-18)
--   2 = P2  same day      → staff notification, or queued to the 08:00 digest out of hours
--   3 = P3  batch         → appended to the daily digest only            [DEFAULT]
--   4 = P4  backlog       → visible in the console, not notified
--   5 = P5  informational → audit trail only
--
-- `acknowledged_at` MUST be set whenever status moves to 'ACKNOWLEDGED'; WF-18's
-- "P1 unacknowledged for 15 minutes" check is unanswerable otherwise ([04-n8n-layer](../plans/04-n8n-layer.md) §3.3).

CREATE TABLE sync_state (
  tenant_id      uuid NOT NULL,
  source         text NOT NULL,      -- 'vagaro.appointments','vagaro.customers','google.calendar'
  cursor         text,
  window_from    timestamptz,
  window_to      timestamptz,
  last_success_at timestamptz,
  last_attempt_at timestamptz,
  last_error     text,
  consecutive_failures smallint NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, source)
);

CREATE TABLE audit_log (
  id          bigserial PRIMARY KEY,
  tenant_id   uuid,
  actor_type  text NOT NULL,   -- 'grace','staff','system','worker'
  actor_id    text,
  action      text NOT NULL,
  entity_type text,
  entity_id   text,
  before      jsonb,
  after       jsonb,
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (tenant_id, occurred_at DESC);
CREATE INDEX ON audit_log (entity_type, entity_id);
```

---

## 14. Row-level security

```sql
-- migration 0014_rls.sql
-- Applied to every table carrying tenant_id.
ALTER TABLE calendar_occupancy ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_occupancy FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON calendar_occupancy
  USING (tenant_id = current_setting('grace.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('grace.tenant_id', true)::uuid);
-- ... repeat for every tenant-scoped table (generate this migration, do not hand-write 20 copies).

-- Application connects as this role; it is NOT the table owner, so FORCE RLS binds it.
CREATE ROLE grace_app LOGIN;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO grace_app;
-- No DELETE grant: this system soft-deletes. Enforced at the privilege level.

-- Migration/admin role, RLS-exempt, used only by CI.
CREATE ROLE grace_migrator LOGIN BYPASSRLS;
```

Every request opens a transaction that first executes:

```sql
SELECT set_config('grace.tenant_id', $1, true);   -- true = transaction-local
```

```ts
// TARGET — src/grace_db/client.py
export async function withTenant<T>(
  tenantId: string,
  fn: (tx: Transaction) => Promise<T>,
): Promise<T> {
  return db.transaction(async (tx) => {
    await tx.execute(sql`SELECT set_config('grace.tenant_id', ${tenantId}, true)`);
    return fn(tx);
  });
}
```

**Rule:** repositories accept a `Transaction`, never the raw pool. There is no code path that touches a
tenant table outside `withTenant`. A lint rule forbids importing the pool outside `client.py`.

---

## 15. Seed data

`src/grace_db/seed/` — idempotent, safe to re-run, used by dev and by CI integration tests.

| Seed file | Contents | Source |
|---|---|---|
| `00_tenant.py` | PalmLeaf tenant, timezone `America/Chicago`, channels | design brief §4.4 |
| `01_hours.py` | Mon–Sun 08:00–20:30 | design brief §4.4 |
| `02_services.py` | Service catalog — **`approved_at` NULL until client sign-off** | ⛔ GATE-04 |
| `03_providers.py` | Provider roster + shifts — **placeholder until sign-off** | ⛔ GATE-05 |
| `04_knowledge.py` | Address, landmarks, parking, holidays, memberships | design brief §4.4 |
| `05_policies.py` | Cancellation/deposit — **inserted unapproved** | ⛔ GATE-02 |
| `06_templates.py` | SMS templates incl. STOP/HELP footer | [telephony](telephony.md) §5 |
| `99_demo.py` | Fake customers + appointments, **dev/test only, never staging or prod** | — |

> Seeds insert the real business facts we already have and insert the *contested* ones (policy wording,
> prices, roster) with `approved_at = NULL`. The system is therefore fully runnable and testable today,
> and the client's sign-off is a single `UPDATE ... SET approved_at = now()` per row rather than a code change.

---

## 16. Data retention and deletion

| Data | Retention | Mechanism |
|---|---|---|
| Call recordings | 90 days (tenant-configurable) | `calls.recording_expires_at`; nightly purge job deletes from Vapi/S3 and nulls the column |
| Transcripts | 90 days, redacted at write | same job |
| `tool_invocations` | 180 days | monthly purge |
| `outbox_events` (DONE) | 30 days | monthly purge |
| `audit_log`, `booking_events`, `consent_log` | 7 years | never purged — legal/dispute evidence |
| `bookings`, `customers` | life of relationship + 7 years | subject-access deletion request → [05-security-and-compliance](../plans/05-security-and-compliance.md) §7 |
| `idempotency_keys` | 24 hours | sweeper |

⛔ **GATE-06:** the 90-day figure is the design brief's *recommendation* (§11.1), not the client's decision.
Confirm with PalmLeaf + counsel before go-live; it is a config value, so this does not block the build.

---

## 17. Migration workflow

```bash
alembic revision --autogenerate -m "add occupancy exclusion constraint"
#: review the generated SQL by hand — always. Rename it descriptively.
alembic upgrade head                  # apply to the local stack
alembic check                         # drift detection: models vs migrations
```

Rules:

1. Migrations are numbered, sequential, and **never edited once merged**.
2. Every migration that adds a `NOT NULL` column supplies a `DEFAULT` or ships in three steps
   (add nullable → backfill → set not null).
3. Index creation on tables >100k rows uses `CREATE INDEX CONCURRENTLY` in a separate, non-transactional
   migration.
4. CI runs migrations against a fresh Postgres, then runs them again to prove idempotency of the runner,
   then asserts `db:check` reports no drift.
5. Every migration PR states the rollback: either a down-migration or "forward-fix only, because X".

---

## 18. Acceptance criteria

✅ **AC-03.1** All 14 migrations apply cleanly to an empty Postgres 16 and produce zero drift.
✅ **AC-03.2** Inserting two overlapping `ACTIVE` occupancy rows for the same provider raises `23P01`.
✅ **AC-03.3** Inserting an overlapping row where one is `RELEASED` succeeds.
✅ **AC-03.4** A session with `grace.tenant_id` set to tenant A cannot read tenant B's rows — proven by test.
✅ **AC-03.5** A second `INSERT` with the same `(tenant_id, idempotency_key)` on `bookings` raises `23505`.
✅ **AC-03.6** `blocked_range @> service_range` violation is rejected.
✅ **AC-03.7** Seeds run twice with no error and no duplicate rows.
✅ **AC-03.8** `grace_app` role cannot `DELETE` from any table.

## 19. Open questions

| # | Question | Why it is still open | Who decides |
|---|---|---|---|
| **A-23** | Can Alembic autogenerate and round-trip `EXCLUDE … USING gist` and the `btree_gist` extension? | ADR-0016 asserts it can, verified against documentation rather than a running migration. **The entire double-booking guarantee is this one constraint**, so if autogeneration cannot express it, those migrations become hand-written. Task C-02 answers it. | Engineering, at C-02 |
| **GATE-04** | The full service catalog — durations, prices, buffers, deposit amounts | Every service row ships with `approved_at = NULL` so Grace degrades gracefully rather than quoting an unapproved price. That is a safe default, not a substitute for the answer. | PalmLeaf |
| **GATE-06** | The recording and transcript retention period | The 90-day figure is the design brief's recommendation, not a decision. The purge job and the privacy notice must agree, and today they agree on an unconfirmed number. | PalmLeaf + counsel |
| **Q-DM.1** | Does `tenant_id` on every table survive contact with the first real second tenant? | ADR-0008 adds the column everywhere and RLS policies to match, on assumption A-01. Nobody has run a two-tenant test, so the isolation is designed but unproven. | Engineering, at Phase F |
