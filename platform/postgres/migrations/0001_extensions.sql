-- 0001 — extensions. data-model.md §2.
-- btree_gist is REQUIRED: the calendar_occupancy exclusion constraint (I2) mixes uuid
-- equality with range overlap in one EXCLUDE, which core GiST cannot do alone.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
