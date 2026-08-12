"""Call records (data-model.md §10).

Exists to resolve **Vapi's** call id — an opaque string on their side — to **our** call
row's uuid. Everything that references a call internally (`calendar_occupancy.call_id`,
`staff_tasks.call_id`, `bookings.call_id`) points at ours, not theirs.

Conflating the two is easy and quiet: it only surfaces when Postgres rejects the string as
a uuid, which happened the first time a hold was placed against a live tool call.
"""

from __future__ import annotations

from datetime import UTC, datetime

import psycopg


def ensure_call(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    vapi_call_id: str,
    from_phone: str | None = None,
) -> str:
    """Return our uuid for this Vapi call, creating the row on first sight.

    Idempotent on `(tenant_id, vapi_call_id)`: a call makes many tool requests and every
    one of them lands here.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO calls (tenant_id, vapi_call_id, from_phone, started_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, vapi_call_id) DO UPDATE
              SET from_phone = COALESCE(calls.from_phone, EXCLUDED.from_phone)
            RETURNING id
            """,
            (tenant_id, vapi_call_id, from_phone, datetime.now(UTC)),
        )
        row = cur.fetchone()
        assert row is not None
        return str(row[0])


def record_tool_invocation(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    call_id: str | None,
    vapi_call_id: str | None,
    tool_call_id: str,
    tool_name: str,
    latency_ms: int,
    status: str,
) -> None:
    """One row per tool call, for latency and failure reporting.

    Arguments are deliberately NOT stored: they can carry what a caller said, and this
    table is not where that belongs (I6).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tool_invocations
              (tenant_id, call_id, vapi_call_id, tool_call_id, tool_name, latency_ms, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (tenant_id, call_id, vapi_call_id, tool_call_id, tool_name, latency_ms, status),
        )
