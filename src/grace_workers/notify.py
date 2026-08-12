"""Deliver staff notifications from the outbox to n8n.

    python -m grace_workers.notify

A **separate process from the tool server**, deliberately. `grace_api`'s whole contract is
that it answers a caller and calls nothing outward — its own module docstring says so. The
import-linter would have permitted an httpx import there, but permitted is not the same as
right: outbound HTTP with retries belongs on the cold path, where a slow third party costs
nobody any silence.

At-least-once delivery, keyed on the outbox row id. `SKIP LOCKED` means a second copy of
this worker could run without double-sending, though one is correct at this volume.

Only `staff.notify` is claimed here. `pms.write_appointment` and friends are left alone for
the Vagaro worker — filtered in SQL rather than by convention, so a new event type cannot
be silently swallowed by the wrong consumer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("grace_workers.notify")

POLL_SECONDS = 5.0
BATCH = 10
EVENT_TYPE = "staff.notify"


#: Backoff per attempt, capped. A staff notification that has failed eight times is not
#: going to succeed on the ninth; it becomes DEAD and someone looks at it.
def backoff_seconds(attempts: int) -> int:
    return int(min(2 ** max(attempts, 0) * 2, 1800))


CLAIM = """
SELECT id, tenant_id, aggregate_id, payload, attempts, max_attempts
FROM outbox_events
WHERE status IN ('PENDING', 'FAILED')
  AND event_type = %s
  AND available_at <= now()
ORDER BY available_at, id
LIMIT %s
FOR UPDATE SKIP LOCKED
"""


async def deliver(client: httpx.AsyncClient, url: str, token: str, payload: dict[str, Any]) -> bool:
    try:
        response = await client.post(
            url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=10.0
        )
    except httpx.HTTPError as exc:
        log.warning("staff.notify transport error: %s", exc)
        return False
    if response.status_code // 100 == 2:
        return True
    log.warning("staff.notify rejected: %s %s", response.status_code, response.text[:200])
    return False


async def drain_once(
    conn: psycopg.Connection, client: httpx.AsyncClient, url: str, token: str
) -> int:
    """One pass. Each row is claimed, delivered, and settled inside one transaction."""
    delivered = 0
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CLAIM, (EVENT_TYPE, BATCH))
        rows = cur.fetchall()

        for row in rows:
            ok = await deliver(client, url, token, dict(row["payload"]))
            if ok:
                cur.execute(
                    "UPDATE outbox_events SET status = 'DONE', processed_at = now() WHERE id = %s",
                    (row["id"],),
                )
                delivered += 1
                continue

            attempts = int(row["attempts"]) + 1
            dead = attempts >= int(row["max_attempts"])
            cur.execute(
                """
                UPDATE outbox_events
                SET status = %s,
                    attempts = %s,
                    available_at = now() + make_interval(secs => %s),
                    last_error = %s
                WHERE id = %s
                """,
                (
                    "DEAD" if dead else "FAILED",
                    attempts,
                    0 if dead else backoff_seconds(attempts),
                    "delivery failed",
                    row["id"],
                ),
            )
            if dead:
                # Nobody was told something a human needed to know. That is worth an alarm,
                # not a log line — WF-00's error handler picks these up from n8n's side.
                log.error("outbox event %s is DEAD after %s attempts", row["id"], attempts)
    return delivered


async def run() -> int:
    url = os.environ.get("GRACE_N8N_ESCALATION_URL", "")
    token = os.environ.get("GRACE_N8N_INBOUND_TOKEN", "")
    dsn = os.environ.get("GRACE_DATABASE_URL", "")

    if not dsn:
        sys.exit("✗ GRACE_DATABASE_URL is not set")
    if not url or not token:
        # Refuse rather than silently pile up undelivered notifications: an escalation
        # nobody receives is worse than a worker that will not start.
        sys.exit(
            "✗ GRACE_N8N_ESCALATION_URL and GRACE_N8N_INBOUND_TOKEN must both be set —\n"
            "  without them staff notifications would queue forever with nobody told."
        )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("notify worker started — polling every %.0fs", POLL_SECONDS)

    async with httpx.AsyncClient() as client:
        while True:
            try:
                with psycopg.connect(dsn) as conn:
                    sent = await drain_once(conn, client, url, token)
                    if sent:
                        log.info("delivered %d staff notification(s)", sent)
            except psycopg.Error as exc:
                log.error("database error: %s", exc)
            await asyncio.sleep(POLL_SECONDS)


def main() -> int:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
