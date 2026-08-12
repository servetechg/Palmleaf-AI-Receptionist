"""Send queued customer messages — SMS via Twilio, email via SMTP.

    python -m grace_workers.messenger

**A separate process from the tool server, deliberately** — the same reasoning as
`notify.py`. `grace_api` queues a row and returns inside the caller's deadline; reaching
Twilio or an SMTP server takes as long as it takes, and a caller must never wait on it.
`import-linter` enforces that grace_api cannot import this module's dependencies.

At-least-once delivery keyed on the outbox row, with `SKIP LOCKED` so a second copy is
safe. A message that has failed its attempts becomes DEAD and a human looks at it — it is
never silently dropped, because a customer was told it was on its way.

**Credentials are optional by design.** With none configured the worker runs, reports what
it *would* have sent, and leaves the rows QUEUED rather than marking them sent. That way a
missing credential never turns into a customer who was told they'd been texted.
"""

from __future__ import annotations

import logging
import os
import smtplib
import sys
import time
from email.message import EmailMessage
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("grace_workers.messenger")

POLL_SECONDS = 5.0
BATCH = 10
EVENT_TYPE = "message.send"

TWILIO_SEND_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def backoff_seconds(attempts: int) -> int:
    """Same curve as notify.py — capped at half an hour."""
    return int(min(2 ** max(attempts, 0) * 2, 1800))


CLAIM = """
SELECT o.id, o.tenant_id, o.aggregate_id, o.attempts, o.max_attempts,
       m.channel::text AS channel, m.to_address, m.body_rendered
FROM outbox_events o
JOIN messages m ON m.id = o.aggregate_id
WHERE o.status IN ('PENDING', 'FAILED')
  AND o.event_type = %s
  AND o.available_at <= now()
ORDER BY o.available_at, o.id
LIMIT %s
FOR UPDATE OF o SKIP LOCKED
"""


class Credentials:
    """What is configured right now. Read once per tick so a fix takes effect on restart."""

    def __init__(self) -> None:
        self.twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
        self.smtp_host = os.environ.get("SMTP_HOST", "").strip()
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587") or 587)
        self.smtp_user = os.environ.get("SMTP_USERNAME", "").strip()
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
        self.smtp_from = os.environ.get("SMTP_FROM", "").strip()
        self.subject = os.environ.get("GRACE_EMAIL_SUBJECT", "PalmLeaf Massage & Wellness")

    @property
    def sms_ready(self) -> bool:
        return bool(self.twilio_sid and self.twilio_token and self.twilio_from)

    @property
    def email_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


def send_sms(creds: Credentials, to_address: str, body: str) -> str:
    """Returns the provider message id. Raises on failure so the row is retried."""
    response = httpx.post(
        TWILIO_SEND_URL.format(sid=creds.twilio_sid),
        auth=(creds.twilio_sid, creds.twilio_token),
        data={"To": to_address, "From": creds.twilio_from, "Body": body},
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json().get("sid", ""))


def send_email(creds: Credentials, to_address: str, body: str) -> str:
    message = EmailMessage()
    message["Subject"] = creds.subject
    message["From"] = creds.smtp_from
    message["To"] = to_address
    message.set_content(body)

    with smtplib.SMTP(creds.smtp_host, creds.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if creds.smtp_user:
            smtp.login(creds.smtp_user, creds.smtp_password)
        smtp.send_message(message)
    return ""


def _mark_sent(conn: psycopg.Connection, outbox_id: str, message_id: str, provider_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE messages SET status='SENT', sent_at=now(), provider_message_id=%s WHERE id=%s",
            (provider_id or None, message_id),
        )
        cur.execute(
            "UPDATE outbox_events SET status='PROCESSED', processed_at=now() WHERE id=%s",
            (outbox_id,),
        )


def _mark_failed(conn: psycopg.Connection, row: dict[str, Any], error: str) -> None:
    attempts = int(row["attempts"]) + 1
    dead = attempts >= int(row["max_attempts"])
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE outbox_events
            SET status = %s, attempts = %s, last_error = %s,
                available_at = now() + make_interval(secs => %s)
            WHERE id = %s
            """,
            (
                "DEAD" if dead else "FAILED",
                attempts,
                error[:500],
                backoff_seconds(attempts),
                row["id"],
            ),
        )
        if dead:
            # A customer was told this was coming. Someone has to know it never arrived.
            cur.execute(
                "UPDATE messages SET status='FAILED', error_code=%s WHERE id=%s",
                (error[:100], row["aggregate_id"]),
            )


def tick(conn: psycopg.Connection, creds: Credentials) -> int:
    """One pass. Returns how many messages were sent."""
    sent = 0
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLAIM, (EVENT_TYPE, BATCH))
        rows: list[dict[str, Any]] = cur.fetchall()

    for row in rows:
        channel = str(row["channel"])
        ready = creds.sms_ready if channel == "SMS" else creds.email_ready
        if not ready:
            # Leave it QUEUED. Reporting it as sent would be the exact broken promise this
            # worker exists to prevent.
            log.warning(
                "%s not configured — leaving message %s queued for %s",
                channel,
                row["aggregate_id"],
                row["to_address"],
            )
            continue
        try:
            provider_id = (
                send_sms(creds, str(row["to_address"]), str(row["body_rendered"]))
                if channel == "SMS"
                else send_email(creds, str(row["to_address"]), str(row["body_rendered"]))
            )
            _mark_sent(conn, str(row["id"]), str(row["aggregate_id"]), provider_id)
            sent += 1
            log.info("sent %s to %s", channel, row["to_address"])
        # Any failure here is a retry, not a crash: one bad address must not stop the queue.
        except Exception as exc:
            _mark_failed(conn, row, f"{type(exc).__name__}: {exc}")
            log.warning("send failed for %s: %s", row["aggregate_id"], exc)
    conn.commit()
    return sent


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database_url = os.environ.get("GRACE_DATABASE_URL", "")
    if not database_url:
        sys.exit("✗ GRACE_DATABASE_URL is not set")

    creds = Credentials()
    if not creds.sms_ready:
        log.warning("SMS disabled — set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER")
    if not creds.email_ready:
        log.warning("Email disabled — set SMTP_HOST and SMTP_FROM")

    log.info("messenger started, polling every %ss", POLL_SECONDS)
    while True:
        try:
            with psycopg.connect(database_url) as conn:
                tick(conn, creds)
        except psycopg.Error as exc:
            log.error("database error: %s", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
