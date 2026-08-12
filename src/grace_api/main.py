"""The tool server Vapi calls (core-api.md §1, §5, §9).

    make api-run          # uvicorn on :8080

What it does: serves the tool endpoint, stages inbound webhooks, and answers the internal
report endpoints the n8n workflows already call.

What it deliberately does NOT do: talk to Vagaro, Stripe, Twilio, Google or n8n; retry
anything; send messages. Those are cold-path jobs. This process has a caller waiting on the
line and its whole job is to answer inside the deadline.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import FastAPI, Header, Request, Response, status
from fastapi.responses import JSONResponse
from psycopg.types.json import Json

from grace_api.envelope import ToolResponse, VapiToolRequest, sentence
from grace_api.handlers import HANDLERS
from grace_db.repositories import availability as availability_repo

log = logging.getLogger("grace_api")

#: Total budget for a tool call. Losing the race fires a graceful sentence rather than
#: leaving the caller in silence (core-api.md §6.4).
DEADLINE_MS = int(os.environ.get("GRACE_TOOL_DEADLINE_MS", "2500"))

#: How far out each tool call pushes the caller's holds. Matches the tenant hold TTL —
#: the point is that the clock restarts while they are talking, not that it runs longer.
HOLD_REFRESH_SECONDS = 240

app = FastAPI(title="Grace Core API", docs_url=None, redoc_url=None)


def database_url() -> str:
    return os.environ.get("GRACE_DATABASE_URL", "")


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """One transaction per request. Handlers never commit on their own behalf."""
    with psycopg.connect(database_url()) as conn:
        yield conn
        conn.commit()


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/readyz")
def readyz() -> Response:
    """Ready means the database answers. Anything else is not this endpoint's business."""
    try:
        with psycopg.connect(database_url(), connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        return JSONResponse(
            {"ok": False, "reason": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    return JSONResponse({"ok": True})


@app.post("/vapi/tools")
async def vapi_tools(request: Request) -> Response:
    """Every function tool dispatches from here.

    Always HTTP 200 with a spoken sentence, including on failure: an error status gives
    the model nothing to say, and the caller hears dead air.
    """
    started = time.monotonic()
    try:
        payload = VapiToolRequest.model_validate(await request.json())
    except Exception:
        log.exception("unparseable tool request")
        return JSONResponse(ToolResponse(results=[]).to_payload())

    call_id = payload.vapi_call_id
    results = []

    for call in payload.message.tool_calls:
        name = call.function.name
        handler = HANDLERS.get(name)

        if handler is None:
            log.warning("unknown tool %s", name)
            results.append(sentence(call.id, "Let me get someone who can help with that."))
            continue

        elapsed_ms = (time.monotonic() - started) * 1000
        if elapsed_ms > DEADLINE_MS:
            # Out of budget before we even started this one. Say something honest.
            results.append(
                sentence(call.id, "I'm having trouble reaching the schedule. Let me get someone.")
            )
            continue

        try:
            with transaction() as conn:
                # A caller is listening: never wait longer on a lock than the voice budget
                # can absorb. A skipped slot is invisible; a stalled answer is not.
                conn.execute("SET LOCAL lock_timeout = '250ms'")
                # Every tool call is proof this conversation is still alive, so push the
                # caller's holds out. Deliberating slowly must not cost them their slot.
                if call_id:
                    availability_repo.refresh_holds_for_call(
                        conn, vapi_call_id=call_id, ttl_seconds=HOLD_REFRESH_SECONDS
                    )
                spoken = handler(conn, call.function.arguments, call_id)
        except Exception:
            # A handler fault must not silence the assistant.
            log.exception("tool %s failed", name)
            spoken = "I'm having trouble with that. Let me get someone who can help."

        results.append(sentence(call.id, spoken))

    return JSONResponse(ToolResponse(results=results).to_payload())


@app.post("/webhooks/vagaro")
async def vagaro_webhook(request: Request) -> Response:
    """ONE insert, then 200. core-api.md §9.1.

    Vagaro requires a 2xx within 20 seconds and retries 5 times over 15 minutes otherwise.
    So nothing is parsed deeply, nothing is looked up, and no other service is called before
    the acknowledgement — the sync worker does the real work afterwards.

    Dedupe uses Vagaro's own event id, which their documentation says exists precisely "to
    ensure that an event is not processed twice"; a payload hash is the fallback.
    """
    raw = await request.body()
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}

    dedupe_key = str(body.get("id") or "") or f"sha:{hash(raw)}"

    try:
        with transaction() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inbound_webhooks (source, dedupe_key, payload)
                VALUES ('vagaro', %s, %s)
                ON CONFLICT (source, dedupe_key) DO NOTHING
                """,
                (dedupe_key, Json(body)),
            )
    except psycopg.Error:
        log.exception("failed to stage vagaro webhook")
        # Still 200: a retry storm helps nobody, and the poller catches what we drop.
    return JSONResponse({"ok": True})


def _authorised(header: str | None) -> bool:
    expected = os.environ.get("GRACE_INTERNAL_API_TOKEN", "")
    return bool(expected) and header == f"Bearer {expected}"


@app.get("/internal/reports/calls")
def report_calls(window: str = "1h", authorization: str | None = Header(default=None)) -> Response:
    """What WF-11 fetches hourly. Actually authenticated — core-api.md flagged that the
    internal routes were specified as bearer-protected but registered unguarded."""
    if not _authorised(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    with transaction() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE outcome IS NOT NULL)            AS calls,
                   count(*) FILTER (WHERE outcome = 'BOOKED')             AS booked,
                   count(*) FILTER (WHERE outcome = 'TRANSFERRED')        AS escalated
            FROM calls
            WHERE started_at > now() - interval '1 hour'
            """
        )
        row = cur.fetchone() or (0, 0, 0)
        cur.execute("SELECT count(*) FROM staff_tasks WHERE status = 'OPEN'")
        open_row = cur.fetchone() or (0,)

    return JSONResponse(
        {
            "calls": row[0],
            "booked": row[1],
            "escalated": row[2],
            "openTasks": open_row[0],
            "summary": f"{row[0]} calls in the last hour, {row[1]} booked",
        }
    )


@app.get("/internal/reports/reconciliation")
def report_reconciliation(authorization: str | None = Header(default=None)) -> Response:
    """What WF-07 fetches nightly. Each check is a claim the mirror should satisfy."""
    if not _authorised(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    checks: list[dict[str, Any]] = []
    with transaction() as conn, conn.cursor() as cur:
        # Every future mirrored appointment must hold its slot, or a customer believes
        # they are booked into a time we would happily sell again.
        cur.execute(
            """
            SELECT count(*) FROM appointments_mirror m
            WHERE m.starts_at > now() AND m.status <> 'Cancelled'
              AND NOT EXISTS (
                SELECT 1 FROM calendar_occupancy o
                WHERE o.id = m.occupancy_id AND o.state = 'ACTIVE'
              )
            """
        )
        orphan_row = cur.fetchone() or (0,)
        checks.append({"name": "mirror rows hold their slot", "passed": orphan_row[0] == 0})

        cur.execute(
            "SELECT count(*) FROM calendar_occupancy "
            "WHERE state = 'ACTIVE' AND expires_at IS NOT NULL AND expires_at < now()"
        )
        stale_row = cur.fetchone() or (0,)
        checks.append({"name": "no holds past their expiry", "passed": stale_row[0] == 0})

        cur.execute("SELECT count(*) FROM outbox_events WHERE status = 'DEAD'")
        dead_row = cur.fetchone() or (0,)
        checks.append({"name": "no dead outbox events", "passed": dead_row[0] == 0})

    failed = [c for c in checks if not c["passed"]]
    return JSONResponse(
        {
            "ranAt": datetime.now(UTC).isoformat(),
            "checks": checks,
            "driftRecords": len(failed),
            "summary": (
                "reconciliation complete" if not failed else f"{len(failed)} check(s) failed"
            ),
        }
    )


@app.post("/internal/sweep/holds")
def sweep_holds(authorization: str | None = Header(default=None)) -> Response:
    """Expire holds past their TTL. availability-engine.md §8's 30-second sweeper, exposed
    as an endpoint so n8n can drive the schedule until a worker process exists."""
    if not _authorised(authorization):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    with transaction() as conn:
        expired = availability_repo.expire_stale_holds(conn)
    return JSONResponse({"expired": expired})
