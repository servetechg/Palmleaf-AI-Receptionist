-- 0016 — business_hours_for_date(). availability-engine.md §3.
--
-- Returns the effective open range for one date: the weekly template, with a
-- SPECIAL_HOURS exception overriding it, and nothing at all when the business is closed
-- that day. Kept in SQL so the free-slot query stays a single statement — the moment this
-- moves into Python it becomes an N+1 and the p95 target goes with it.
CREATE OR REPLACE FUNCTION business_hours_for_date(p_tenant uuid, p_date date, p_tz text)
RETURNS TABLE (open_range tstzrange)
LANGUAGE sql STABLE AS $$
  WITH special AS (
    SELECT se.opens_at, se.closes_at
    FROM schedule_exceptions se
    WHERE se.tenant_id = p_tenant
      AND se.on_date = p_date
      AND se.kind = 'SPECIAL_HOURS'
    LIMIT 1
  ),
  closed AS (
    SELECT 1
    FROM schedule_exceptions se
    WHERE se.tenant_id = p_tenant
      AND se.on_date = p_date
      AND se.kind IN ('CLOSED','HOLIDAY')
      AND se.provider_id IS NULL          -- whole-business closure only
    LIMIT 1
  ),
  template AS (
    SELECT bh.opens_at, bh.closes_at
    FROM business_hours bh
    WHERE bh.tenant_id = p_tenant
      AND bh.day_of_week = EXTRACT(DOW FROM p_date)::smallint
      AND bh.effective_from <= p_date
      AND (bh.effective_to IS NULL OR bh.effective_to >= p_date)
    LIMIT 1
  ),
  effective AS (
    SELECT * FROM special
    UNION ALL
    SELECT * FROM template WHERE NOT EXISTS (SELECT 1 FROM special)
  )
  SELECT tstzrange(
           ((p_date + e.opens_at)  AT TIME ZONE p_tz),
           ((p_date + e.closes_at) AT TIME ZONE p_tz),
           '[)'
         )
  FROM effective e
  WHERE NOT EXISTS (SELECT 1 FROM closed);
$$;
