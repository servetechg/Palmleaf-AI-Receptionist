-- Bring back a hold that merely timed out, when the slot is genuinely still free.
--
-- Why this exists: a caller who goes quiet for six minutes ("let me ask my husband")
-- produces no tool calls, so the refresh cannot help them and the sweeper expires their
-- hold. But expiring a hold does NOT mean anyone took the slot. Without this, Grace tells
-- that caller "sorry, that time just went" when it is sitting there empty — a statement
-- that is simply false, and the kind of thing that loses a booking for no reason.
--
-- Setting state back to 'ACTIVE' re-enters the exclusion constraint's WHERE predicate, so
-- the constraint is re-checked on this UPDATE. Success therefore *proves* the slot was
-- still free. A 23P01 here means it really was resold, which is the one case where "that
-- just went" is the honest answer.
--
-- Deliberately narrow: only rows this same call expired on a timer. Never a RELEASED row
-- (that call has ended) and never another caller's hold.
UPDATE calendar_occupancy
SET state = 'ACTIVE',
    kind = 'RESERVATION',
    expires_at = now() + make_interval(secs => %(reservation_ttl)s),
    released_at = NULL,
    release_reason = NULL,
    updated_at = now()
WHERE tenant_id = %(tenant_id)s
  AND metadata->>'publicId' = %(public_slot_id)s
  AND state = 'EXPIRED'
  AND release_reason = 'ttl'
  AND kind = 'HOLD'
  AND call_id = %(call_id)s
RETURNING id, subject_id, lower(service_range) AS starts_at, upper(service_range) AS ends_at;
