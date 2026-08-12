"""Staff tasks and their notifications (booking-write-path.md §3, data-model.md §13).

Every path here does two writes in the caller's transaction: a `staff_tasks` row (what a
human must do) and an `outbox_events` row (how they find out). Both or neither — a task
nobody is told about is the same as no task at all.

**Nothing here stores health detail.** `flagMedicalHold` takes no free text from the call
on purpose: the fact that a follow-up is needed is operational, the reason is medical, and
invariant I6 says the second one does not get written down.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Json

#: The partial unique indexes on staff_tasks dedupe OPEN tasks per (call, type), so a
#: model that fires the same tool twice in one call produces one task, not two.
_INSERT_TASK = """
INSERT INTO staff_tasks (tenant_id, type, priority, title, body, payload, call_id, customer_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
RETURNING id
"""

_INSERT_OUTBOX = """
INSERT INTO outbox_events (tenant_id, aggregate_type, aggregate_id, event_type, payload)
VALUES (%s, 'staff_task', %s, 'staff.notify', %s)
"""


def _create(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    task_type: str,
    priority: int,
    title: str,
    body: str | None,
    call_id: str | None,
    payload: dict[str, object],
    customer_id: str | None = None,
) -> str | None:
    """Returns the new task id, or None when an identical OPEN task already exists."""
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_TASK,
            (tenant_id, task_type, priority, title, body, Json(payload), call_id, customer_id),
        )
        row = cur.fetchone()
        if row is None:
            return None  # deduped — the human already has this one
        task_id = str(row[0])

        cur.execute(
            _INSERT_OUTBOX,
            (
                tenant_id,
                task_id,
                Json({"taskId": task_id, "type": task_type, "priority": priority, "title": title}),
            ),
        )
    return task_id


def flag_escalation(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    call_id: str | None,
    reason: str,
    summary: str,
    urgent: bool,
) -> str | None:
    """A human is needed. Priority 1 pages immediately; 2 is same-day.

    The summary is what the person picking up sees before they speak, which is the whole
    point of calling this *before* the transfer — otherwise they answer blind.
    """
    return _create(
        conn,
        tenant_id=tenant_id,
        task_type="ESCALATION",
        priority=1 if urgent else 2,
        title=summary[:120] or "Caller asked for a person",
        body=None,
        call_id=call_id,
        payload={"reason": reason, "urgent": urgent},
    )


def flag_medical_hold(
    conn: psycopg.Connection, *, tenant_id: str, call_id: str | None
) -> str | None:
    """A caller disclosed something medical. Records THAT, never WHAT.

    Fixed title, no body, no payload detail — invariant I6. The team calls them back and
    handles clearance, which is the client's own stated process.
    """
    return _create(
        conn,
        tenant_id=tenant_id,
        task_type="MEDICAL_HOLD",
        priority=2,
        title="Medical follow-up needed",
        body=None,
        call_id=call_id,
        payload={},
    )


def take_message(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    call_id: str | None,
    subject: str,
    callback_number: str,
    caller_name: str,
) -> str | None:
    """A callback request. Subject only — the prompt forbids health detail here."""
    return _create(
        conn,
        tenant_id=tenant_id,
        task_type="MESSAGE",
        priority=2,
        title=f"Call back {caller_name}".strip()[:120] or "Call back",
        body=subject[:280],
        call_id=call_id,
        payload={"callbackNumber": callback_number},
    )


def has_medical_hold(conn: psycopg.Connection, *, call_id: str) -> bool:
    """Did anything medical come up on THIS call?

    Checked inside booking: once a caller discloses a condition, no later tool argument
    can talk the system back into booking them. The prompt is told not to; this makes it
    so regardless (invariant I4, belt over the model's braces).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM staff_tasks
                WHERE call_id = %s AND type = 'MEDICAL_HOLD'
            )
            """,
            (call_id,),
        )
        row = cur.fetchone()
        return bool(row[0]) if row else False
