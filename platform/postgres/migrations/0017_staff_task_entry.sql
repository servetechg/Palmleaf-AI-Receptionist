-- 0017 — a task type for "Grace booked this; someone must enter it in Vagaro".
--
-- Until GATE-01 answers whether Vagaro exposes appointment writes, the shipping path is
-- booking-write-path.md's Track D: we hold the slot, the caller is told they are booked,
-- and staff transcribe it. That is NOT a failure, so it must not be filed as
-- BOOKING_WRITE_FAILED — an operator triaging a queue needs the difference to be obvious.
ALTER TYPE staff_task_type ADD VALUE IF NOT EXISTS 'BOOKING_NEEDS_ENTRY';
