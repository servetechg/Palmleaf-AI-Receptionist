"""Outbound customer messages — queued on the hot path, sent on the cold path.

The split is invariant I1. A caller is on the line, so this module writes rows and returns;
it never opens a socket to Twilio or an SMTP server. `grace_workers.messenger` drains the
queue afterwards, where a slow third party costs nobody any silence.

Two writes per message, in the caller's transaction: a `messages` row (what was promised)
and an `outbox_events` row (how it actually gets sent). Both or neither — a promise with no
delivery job is exactly the broken promise this module exists to stop.

**Consent (GATE-09 / 10DLC).** `sms_opt_out_at` is checked here rather than trusted to a
caller-facing prompt, because an opt-out that only the prompt respects is not an opt-out.
A customer who opted out of SMS but gave an email still gets their booking confirmation —
the message degrades to the other channel instead of vanishing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Json

#: Deliberately permissive. This rejects the shapes a speech-to-text engine actually
#: produces for a spoken address ("john at gmail", "j o h n@", a trailing full stop) without
#: pretending to implement RFC 5322 — the real test of an address is whether mail to it
#: lands, and that answer comes back from the messenger worker, not from a regex.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def looks_like_email(raw: str) -> bool:
    """Cheap sanity check on a spoken address. Never used to claim an address is real."""
    value = raw.strip().rstrip(".").casefold()
    return bool(value) and len(value) <= 254 and _EMAIL.match(value) is not None


@dataclass(frozen=True, slots=True)
class Queued:
    """What was actually queued, so the handler can speak the truth about it."""

    sms: bool
    email: bool
    degraded_reason: str  # matches contracts DegradedReason

    @property
    def any_queued(self) -> bool:
        return self.sms or self.email


_INSERT_MESSAGE = """
INSERT INTO messages (
    tenant_id, customer_id, booking_id, call_id, channel, template_key,
    to_address, body_rendered, status
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'QUEUED')
RETURNING id
"""

_INSERT_OUTBOX = """
INSERT INTO outbox_events (tenant_id, aggregate_type, aggregate_id, event_type, payload)
VALUES (%s, 'message', %s, 'message.send', %s)
"""


def _queue_one(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    customer_id: str | None,
    booking_id: str | None,
    call_id: str | None,
    channel: str,
    template_key: str,
    to_address: str,
    body: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_MESSAGE,
            (
                tenant_id,
                customer_id,
                booking_id,
                call_id,
                channel,
                template_key,
                to_address,
                body,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        message_id = row[0]
        cur.execute(
            _INSERT_OUTBOX,
            (
                tenant_id,
                message_id,
                Json({"messageId": str(message_id), "channel": channel}),
            ),
        )


def sms_opted_out(conn: psycopg.Connection, customer_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sms_opt_out_at IS NOT NULL FROM customers WHERE id = %s", (customer_id,)
        )
        row = cur.fetchone()
    return bool(row[0]) if row else False


def customer_for_booking(conn: psycopg.Connection, booking_id: str) -> str | None:
    """Who to send a booking's message to. ``None`` when the booking has no customer."""
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM bookings WHERE id = %s", (booking_id,))
        row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def contact_for(conn: psycopg.Connection, customer_id: str) -> tuple[str, str]:
    """``(phone, email)`` as stored. Either may be empty."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(phone_e164, ''), coalesce(email::text, '') FROM customers WHERE id = %s",
            (customer_id,),
        )
        row = cur.fetchone()
    return (str(row[0]), str(row[1])) if row else ("", "")


def queue_message(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    customer_id: str,
    booking_id: str | None,
    call_id: str | None,
    template_key: str,
    body: str,
    preference: str,
) -> Queued:
    """Queue one message across whichever channels the caller asked for and we can reach.

    Returns what was queued rather than a bare bool: the handler has to tell the caller
    where to look, and "I've texted you" when only an email went out is the kind of small
    lie that turns into a missed appointment.
    """
    phone, email = contact_for(conn, customer_id)
    want_sms = preference in ("sms", "both")
    want_email = preference in ("email", "both")

    # A placeholder number is not a contact. It is what the old schema wrote when nobody
    # asked for one, and texting it would silently drop the message.
    if phone in ("", "+10000000000"):
        want_sms = False

    opted_out = bool(want_sms and sms_opted_out(conn, customer_id))
    if opted_out:
        want_sms = False
        # Their booking confirmation still has to reach them somehow.
        want_email = want_email or bool(email)

    if want_email and not looks_like_email(email):
        want_email = False

    if want_sms:
        _queue_one(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            booking_id=booking_id,
            call_id=call_id,
            channel="SMS",
            template_key=template_key,
            to_address=phone,
            body=body,
        )
    if want_email:
        _queue_one(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            booking_id=booking_id,
            call_id=call_id,
            channel="EMAIL",
            template_key=template_key,
            to_address=email,
            body=body,
        )

    if want_sms or want_email:
        reason = "opted_out" if opted_out else "none"
    elif opted_out:
        reason = "opted_out"
    else:
        reason = "no_contact_method"
    return Queued(sms=want_sms, email=want_email, degraded_reason=reason)


def set_contact(
    conn: psycopg.Connection, *, customer_id: str, phone: str = "", email: str = ""
) -> None:
    """Record what the caller gave us. Empty values never overwrite something real."""
    with conn.cursor() as cur:
        if phone and phone != "+10000000000":
            cur.execute(
                "UPDATE customers SET phone_e164 = %s, updated_at = now() WHERE id = %s",
                (phone, customer_id),
            )
        if email and looks_like_email(email):
            cur.execute(
                "UPDATE customers SET email = %s, updated_at = now() WHERE id = %s",
                (email.strip().rstrip("."), customer_id),
            )
