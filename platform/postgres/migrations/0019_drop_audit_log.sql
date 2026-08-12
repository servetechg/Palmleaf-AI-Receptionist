-- 0019 — remove audit_log. Nothing writes it (verified 2026-08-08: zero references in
-- src/), and the paths that need auditing already have purpose-built records:
-- booking_events for booking state, tool_invocations for what Grace did on a call,
-- staff_tasks for operator actions. A generic before/after log for a 2-therapist salon
-- is speculative surface area.
DROP TABLE IF EXISTS audit_log;
