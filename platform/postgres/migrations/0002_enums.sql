-- 0002 — enums. data-model.md §2.
-- Enums, not lookup tables: these are exhaustive match statements in Python. Adding a
-- value is ALTER TYPE ... ADD VALUE, which is cheap and non-blocking in PG 16.
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

CREATE TYPE deposit_state   AS ENUM ('NOT_REQUIRED','PENDING','PAID','FAILED','REFUNDED','FORFEITED');
CREATE TYPE outbox_status   AS ENUM ('PENDING','IN_FLIGHT','DONE','FAILED','DEAD');
CREATE TYPE task_status     AS ENUM ('OPEN','ACKNOWLEDGED','RESOLVED','CANCELLED');
CREATE TYPE message_channel AS ENUM ('SMS','EMAIL','VOICE');
CREATE TYPE call_outcome    AS ENUM (
  'BOOKED','RESCHEDULED','CANCELLED','INFO_ONLY','MESSAGE_TAKEN',
  'TRANSFERRED','MEDICAL_HOLD','ABANDONED','FAILED'
);

CREATE TYPE staff_task_type AS ENUM (
  'MESSAGE','MEDICAL_HOLD','BOOKING_WRITE_FAILED','DISPUTE','CALLBACK',
  'ESCALATION','OUTBOX_DEAD','RECONCILIATION_DRIFT','PMS_COLLISION'
);
