-- 0018 — who the appointment is actually for.
--
-- A caller booking for their partner is ordinary in a salon, and the phone number is the
-- account. Without this column the only place a name could live was the customer record,
-- so booking for someone else silently renamed the account holder — Ana books for Marco,
-- and Ana's file now says Marco.
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS booked_for_name text;
COMMENT ON COLUMN bookings.booked_for_name IS
  'Name given for THIS appointment. May differ from the customer on the account.';
