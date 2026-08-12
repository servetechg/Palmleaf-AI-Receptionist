-- 0015 — the booking state-change trigger. booking-write-path.md §4.
--
-- There is exactly one legal way to change bookings.state: through the transition
-- function, which also writes a booking_events row in the SAME transaction. This trigger
-- makes that structural rather than a convention — an UPDATE that changes state without
-- its audit row is rejected by the database, so no code path can quietly skip the trail.
CREATE OR REPLACE FUNCTION bookings_require_event() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  event_count integer;
BEGIN
  IF NEW.state IS DISTINCT FROM OLD.state THEN
    SELECT count(*) INTO event_count
    FROM booking_events
    WHERE booking_id = NEW.id
      AND to_state = NEW.state
      AND from_state IS NOT DISTINCT FROM OLD.state;

    IF event_count = 0 THEN
      RAISE EXCEPTION
        'booking % changed state %->% with no booking_events row in this transaction',
        NEW.id, OLD.state, NEW.state
        USING HINT = 'Use the transition function; never UPDATE bookings.state directly.';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

-- CONSTRAINT TRIGGER, deferred to commit: the transition function inserts the event and
-- updates the row in either order within one transaction, and both are visible by commit.
CREATE CONSTRAINT TRIGGER bookings_state_audit
  AFTER UPDATE ON bookings
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION bookings_require_event();
