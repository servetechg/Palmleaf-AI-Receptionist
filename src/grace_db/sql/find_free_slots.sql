-- The free-slot query. availability-engine.md §3.
--
-- ONE statement: no N+1, no interval arithmetic in Python. Templates generate candidate
-- slots (shifts ∩ business hours ∩ lead-time rules); calendar_occupancy subtracts what is
-- already taken, riding the GiST index the exclusion constraint already created.
--
-- The svc CTE is where GATE-04 is enforced: `approved_at IS NOT NULL`. An unapproved
-- service returns zero rows, so Grace cannot offer a time for something the client has
-- not signed off — the prompt is not the thing preventing it.
WITH params AS (
  SELECT
    %(tenant_id)s::uuid        AS tenant_id,
    %(service_id)s::uuid       AS service_id,
    %(window_from)s::timestamptz AS window_from,
    %(window_to)s::timestamptz   AS window_to,
    %(provider_filter)s::uuid  AS provider_filter,   -- NULL = any provider
    %(now)s::timestamptz       AS now,
    %(tz)s::text               AS tz
),
svc AS (
  SELECT s.id, s.duration_min, s.buffer_before_min, s.buffer_after_min,
         s.min_lead_time_min, s.max_advance_days
  FROM services s, params p
  WHERE s.id = p.service_id AND s.tenant_id = p.tenant_id
    AND s.active AND s.bookable_by_ai AND s.approved_at IS NOT NULL
),
eligible_providers AS (
  SELECT pr.id, pr.spoken_name, ps.proficiency
  FROM provider_services ps
  JOIN providers pr ON pr.id = ps.provider_id
  CROSS JOIN params p
  WHERE ps.tenant_id = p.tenant_id
    AND ps.service_id = p.service_id
    AND pr.active AND pr.accepts_new_clients
    AND (p.provider_filter IS NULL OR pr.id = p.provider_filter)
),
days AS (
  SELECT d::date AS on_date
  FROM params p,
       generate_series(p.window_from::date, p.window_to::date, interval '1 day') d
),
-- Recurring shifts expanded into concrete ranges, minus time off.
shift_instances AS (
  SELECT ep.id AS provider_id, ep.spoken_name, ep.proficiency,
         tstzrange(
           ((dy.on_date + sh.starts_at) AT TIME ZONE p.tz),
           ((dy.on_date + sh.ends_at)   AT TIME ZONE p.tz), '[)'
         ) AS shift_range,
         dy.on_date
  FROM params p
  CROSS JOIN days dy
  JOIN provider_shifts sh
    ON sh.tenant_id = p.tenant_id
   AND sh.day_of_week = EXTRACT(DOW FROM dy.on_date)::smallint
   AND sh.effective_from <= dy.on_date
   AND (sh.effective_to IS NULL OR sh.effective_to >= dy.on_date)
  JOIN eligible_providers ep ON ep.id = sh.provider_id
  WHERE NOT EXISTS (
    SELECT 1 FROM schedule_exceptions se
    WHERE se.tenant_id = p.tenant_id AND se.on_date = dy.on_date
      AND se.kind IN ('CLOSED','HOLIDAY','TIME_OFF')
      AND (se.provider_id IS NULL OR se.provider_id = ep.id)
  )
),
-- A shift only counts while the business is actually open.
open_ranges AS (
  SELECT si.provider_id, si.spoken_name, si.proficiency,
         si.shift_range * bh.open_range AS open_range
  FROM shift_instances si
  CROSS JOIN params p
  JOIN LATERAL business_hours_for_date(p.tenant_id, si.on_date, p.tz) bh ON true
  WHERE si.shift_range && bh.open_range
),
-- 15-minute grid anchored to each open range's start.
candidates AS (
  SELECT o.provider_id, o.spoken_name, o.proficiency, o.open_range, g.start_ts,
         tstzrange(
           g.start_ts - make_interval(mins => svc.buffer_before_min),
           g.start_ts + make_interval(mins => svc.duration_min + svc.buffer_after_min),
           '[)'
         ) AS blocked_range,
         tstzrange(
           g.start_ts,
           g.start_ts + make_interval(mins => svc.duration_min),
           '[)'
         ) AS service_range
  FROM open_ranges o
  CROSS JOIN svc
  CROSS JOIN LATERAL generate_series(
    lower(o.open_range),
    upper(o.open_range) - make_interval(mins => svc.duration_min),
    interval '15 minutes'
  ) AS g(start_ts)
)
SELECT c.provider_id, c.spoken_name, c.proficiency, c.start_ts,
       lower(c.service_range) AS service_from, upper(c.service_range) AS service_to,
       lower(c.blocked_range) AS blocked_from, upper(c.blocked_range) AS blocked_to
FROM candidates c
CROSS JOIN params p
CROSS JOIN svc
WHERE c.start_ts >= p.now + make_interval(mins => svc.min_lead_time_min)
  AND c.start_ts <= p.now + make_interval(days => svc.max_advance_days)
  AND c.start_ts >= p.window_from
  AND c.start_ts <  p.window_to
  AND c.service_range <@ c.open_range          -- the whole service fits before closing
  AND NOT EXISTS (                             -- the subtraction: what is already taken
    SELECT 1 FROM calendar_occupancy occ
    WHERE occ.tenant_id = p.tenant_id
      AND occ.state = 'ACTIVE'
      AND occ.subject_type = 'PROVIDER'
      AND occ.subject_id = c.provider_id
      AND occ.blocked_range && c.blocked_range
  )
ORDER BY c.start_ts
LIMIT 200;
