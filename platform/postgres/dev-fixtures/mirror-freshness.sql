-- LOCAL DEV FIXTURE — never run this against a hosted database.
--
-- The availability freshness gate (grace_domain/availability/freshness.py) refuses to speak
-- any slot unless BOTH hold:
--   1. sync_state has a `vagaro.appointments` row whose last_success_at is under 30 minutes old
--   2. appointments_mirror has at least one row for the tenant
--
-- Vagaro is not connected and the sync worker that would maintain both does not exist yet, so
-- on a fresh database every checkAvailability answers "I'm having trouble reaching the
-- schedule" — correct behaviour against an empty mirror, but it makes the booking path
-- impossible to demo or test.
--
-- ⚠️ The timestamp goes stale after 30 MINUTES. Re-run this before each test session:
--        make db-devfixture
--
-- Undo:  DELETE FROM appointments_mirror WHERE pms_appointment_id LIKE 'devfixture-%';
--        DELETE FROM sync_state WHERE source = 'vagaro.appointments';

WITH t AS (
    SELECT id FROM tenants WHERE slug = 'palmleaf'
)
INSERT INTO sync_state (tenant_id, source, last_success_at, last_attempt_at, consecutive_failures)
SELECT t.id, 'vagaro.appointments', now(), now(), 0 FROM t
ON CONFLICT (tenant_id, source) DO UPDATE
    SET last_success_at = now(), last_attempt_at = now(), consecutive_failures = 0;

-- One appointment early tomorrow, so the mirror is not empty. Placed at 08:00 local to
-- overlap as little of a test window as possible.
WITH t AS (
    SELECT id, timezone FROM tenants WHERE slug = 'palmleaf'
), p AS (
    SELECT id FROM providers WHERE tenant_id = (SELECT id FROM t) AND active ORDER BY id LIMIT 1
), s AS (
    SELECT id FROM services
    WHERE tenant_id = (SELECT id FROM t) AND code = 'massage_60'
)
INSERT INTO appointments_mirror (
    tenant_id, pms_appointment_id, provider_id, service_id,
    starts_at, ends_at, status, booked_via, pms_updated_at, last_synced_at, raw
)
SELECT
    t.id, 'devfixture-0001', p.id, s.id,
    ((current_date + 1) + time '08:00') AT TIME ZONE t.timezone,
    ((current_date + 1) + time '09:00') AT TIME ZONE t.timezone,
    'booked', 'dev-fixture', now(), now(),
    '{"note": "local dev fixture — not a real appointment"}'::jsonb
FROM t, p, s
ON CONFLICT (tenant_id, pms_appointment_id) DO UPDATE
    SET last_synced_at = now(), pms_updated_at = now();
