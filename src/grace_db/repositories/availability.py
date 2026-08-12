"""Reading free slots and placing holds (availability-engine.md §3, §5).

Every function here takes a live connection and does its work inside the caller's
transaction. Nothing opens its own — the booking path needs several of these to succeed or
fail together, and a repository that commits on its own behalf makes that impossible.

**No third party is reachable from this module.** Availability is answered from the local
mirror, which is invariant I1 and also the only way to stay inside Vagaro's 5,000-call
monthly quota.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from grace_domain.availability.freshness import (
    APPOINTMENT_SYNC_SOURCE,
    Freshness,
    evaluate,
)
from grace_domain.availability.rank import Candidate
from grace_domain.booking.slot_id import public_slot_id

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
FIND_FREE_SLOTS = (_SQL_DIR / "find_free_slots.sql").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class HeldSlot:
    occupancy_id: str
    public_id: str
    provider_id: str
    provider_name: str
    starts_at: datetime
    ends_at: datetime


def check_freshness(conn: psycopg.Connection, tenant_id: str, *, now: datetime) -> Freshness:
    """Is the mirror recent enough to answer from? See freshness.py for why this exists."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_success_at FROM sync_state WHERE tenant_id = %s AND source = %s",
            (tenant_id, APPOINTMENT_SYNC_SOURCE),
        )
        row = cur.fetchone()
        last_success = row[0] if row else None

        # An empty mirror looks exactly like a free calendar, so it is checked separately
        # from the timestamp rather than inferred from it.
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM appointments_mirror WHERE tenant_id = %s)",
            (tenant_id,),
        )
        has_rows_row = cur.fetchone()
        has_rows = bool(has_rows_row[0]) if has_rows_row else False

    return evaluate(last_success, now=now, mirror_has_rows=has_rows)


def find_free_slots(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    service_id: str,
    window_from: datetime,
    window_to: datetime,
    now: datetime,
    timezone: str,
    provider_id: str | None = None,
) -> list[Candidate]:
    """Candidate slots, already filtered by the approval gate and existing occupancy."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            FIND_FREE_SLOTS,
            {
                "tenant_id": tenant_id,
                "service_id": service_id,
                "window_from": window_from,
                "window_to": window_to,
                "provider_filter": provider_id,
                "now": now,
                "tz": timezone,
            },
        )
        rows: list[dict[str, Any]] = cur.fetchall()

    return [
        Candidate(
            provider_id=str(r["provider_id"]),
            provider_name=str(r["spoken_name"]),
            starts_at=r["service_from"],
            ends_at=r["service_to"],
            proficiency=int(r["proficiency"]),
        )
        for r in rows
    ]


def place_holds(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    call_id: str | None,
    candidates: list[Candidate],
    service_id: str,
    buffer_before_min: int,
    buffer_after_min: int,
    ttl_seconds: int,
) -> list[HeldSlot]:
    """Hold every slot we are about to offer. availability-engine.md §5.

    Holds go on ALL THREE offered slots deliberately — over-holding for up to four minutes
    beats offering a caller a time that vanishes while they think about it.

    **Insertion order is a LOCKING decision; speech order is a PRODUCT decision.** They are
    deliberately decoupled here. Inserting in ranking order caused a real deadlock: ranking
    depends on the caller's stated preference, so two callers insert overlapping ranges in
    different orders, each waits on the other's uncommitted row, and Postgres kills one —
    which reached a caller as "I'm having trouble".

    Sorting by (provider_id, starts_at) removes that class entirely rather than making it
    rarer. Conflicts only exist within one provider, and if every transaction takes ranges
    for a provider in ascending start order, a wait cycle cannot form: whichever row landed
    second was disjoint from the first, so a cycle would require a range to start before a
    range it already sits after. The returned list is re-sorted back into ranking order, so
    what Grace says is unchanged.

    **Each hold gets its own savepoint**, and the catch is broad on purpose. A lost slot
    (23P01), a deadlock victim (40P01) and a lock timeout (55P03) all mean the same thing
    to a caller: offer the other two. None of them should cost the whole call.
    """
    held: list[HeldSlot] = []
    rank_position = {(c.provider_id, c.starts_at): i for i, c in enumerate(candidates)}

    for candidate in sorted(candidates, key=lambda c: (c.provider_id, c.starts_at)):
        blocked_from = candidate.starts_at - timedelta(minutes=buffer_before_min)
        blocked_to = candidate.ends_at + timedelta(minutes=buffer_after_min)
        try:
            with conn.transaction():  # savepoint — this candidate only
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO calendar_occupancy
                          (tenant_id, subject_type, subject_id, blocked_range, service_range,
                           kind, state, source, call_id, expires_at)
                        VALUES (%s, 'PROVIDER', %s,
                                tstzrange(%s, %s, '[)'), tstzrange(%s, %s, '[)'),
                                'HOLD', 'ACTIVE', 'GRACE', %s,
                                now() + make_interval(secs => %s))
                        RETURNING id
                        """,
                        (
                            tenant_id,
                            candidate.provider_id,
                            blocked_from,
                            blocked_to,
                            candidate.starts_at,
                            candidate.ends_at,
                            call_id,
                            ttl_seconds,
                        ),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    occupancy_id = str(row[0])

                    public = public_slot_id(occupancy_id)
                    cur.execute(
                        """
                        UPDATE calendar_occupancy
                        SET metadata = jsonb_set(metadata, '{publicId}', to_jsonb(%s::text))
                        WHERE id = %s
                        """,
                        (public, occupancy_id),
                    )
        except (
            psycopg.errors.ExclusionViolation,  # 23P01 — someone else has it. Expected.
            psycopg.errors.DeadlockDetected,  # 40P01 — we were the victim; skip, don't crash.
            psycopg.errors.LockNotAvailable,  # 55P03 — waited too long; a caller is listening.
        ):
            # Rolling back to the savepoint releases this subtransaction's locks, which
            # also unblocks whoever was waiting on us.
            continue

        held.append(
            HeldSlot(
                occupancy_id=occupancy_id,
                public_id=public,
                provider_id=candidate.provider_id,
                provider_name=candidate.provider_name,
                starts_at=candidate.starts_at,
                ends_at=candidate.ends_at,
            )
        )

    # Back into ranking order — the caller hears the best slot first, not the earliest.
    held.sort(key=lambda h: rank_position.get((h.provider_id, h.starts_at), 999))
    return held


def refresh_holds_for_call(conn: psycopg.Connection, *, vapi_call_id: str, ttl_seconds: int) -> int:
    """Keep a caller's holds alive while they are still talking.

    The hold TTL exists to stop an abandoned call locking slots forever, but it also
    quietly punishes a caller who simply takes their time: deliberate past four minutes and
    the slot you were offered is gone. Every tool call in a conversation is proof the
    conversation is alive, so every tool call pushes the expiry out.

    `greatest()` so this can only ever extend a hold, never shorten one. Changing
    `expires_at` does not touch the exclusion constraint's key columns, so this cannot
    conflict with anything.

    Takes VAPI's call id and joins to find ours. The two are different identifiers — a
    string from them, a uuid of ours — and passing one where the other is expected has
    already caused one production-shaped failure. Joining here means no caller has to
    remember which is which.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE calendar_occupancy o
            SET expires_at = greatest(o.expires_at, now() + make_interval(secs => %s)),
                updated_at = now()
            FROM calls c
            WHERE c.id = o.call_id
              AND c.vapi_call_id = %s
              AND o.kind = 'HOLD'
              AND o.state = 'ACTIVE'
            """,
            (ttl_seconds, vapi_call_id),
        )
        return cur.rowcount


def release_superseded_holds(conn: psycopg.Connection, *, call_id: str) -> int:
    """Free a caller's previous holds when they ask for different times.

    "None of those work, what about Friday?" means the first three slots are dead to this
    caller. Keeping them held until the timer expires denies them to the next caller for
    no reason at all — the decision has already been made, it was just a no.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE calendar_occupancy
            SET state = 'RELEASED', released_at = now(), release_reason = 'superseded',
                updated_at = now()
            WHERE call_id = %s AND kind = 'HOLD' AND state = 'ACTIVE'
            """,
            (call_id,),
        )
        return cur.rowcount


def release_holds_for_call(conn: psycopg.Connection, *, call_id: str) -> int:
    """Free anything still held when a call ends. Soft-released: never DELETE.

    A released hold is evidence in a dispute — "we offered them 3pm and they declined" is
    a thing you want to be able to show.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE calendar_occupancy
            SET state = 'RELEASED', released_at = now(), release_reason = 'call_ended'
            WHERE call_id = %s AND kind = 'HOLD' AND state = 'ACTIVE'
            """,
            (call_id,),
        )
        return cur.rowcount


def expire_stale_holds(conn: psycopg.Connection) -> int:
    """The 30-second sweeper (availability-engine.md §8)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE calendar_occupancy
            SET state = 'EXPIRED', released_at = now(), release_reason = 'ttl'
            WHERE state = 'ACTIVE' AND expires_at IS NOT NULL AND expires_at < now()
            """
        )
        return cur.rowcount
