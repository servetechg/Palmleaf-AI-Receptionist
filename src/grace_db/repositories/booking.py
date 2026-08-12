"""Creating a booking (booking-write-path.md §2, §4; availability-engine.md §6).

The whole write is one SQL statement in `sql/create_booking.sql`, so it is one transaction
by construction. That is worth stating plainly because an earlier reading of this design
assumed a multi-step application-side saga was unavoidable — it is not, and the single
statement is both safer and portable to anything that can run SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
CREATE_BOOKING = (_SQL_DIR / "create_booking.sql").read_text(encoding="utf-8")
RESURRECT_HOLD = (_SQL_DIR / "resurrect_hold.sql").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class BookingResult:
    id: str
    state: str
    starts_at: datetime
    provider_id: str
    #: "created" on the first call, "existing" when idempotency collapsed a repeat.
    outcome: str

    @property
    def was_repeat(self) -> bool:
        return self.outcome == "existing"


def create_booking(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    idempotency_key: str,
    public_slot_id: str,
    service_id: str,
    call_id: str | None,
    phone: str,
    first_name: str,
    last_name: str,
    price_cents: int,
    deposit_cents: int,
    is_member: bool,
    reservation_ttl_seconds: int,
) -> BookingResult | None:
    """Returns None when the hold is gone — expired, or taken by another caller.

    None is not an error: it is the honest outcome of two people wanting the same slot,
    and the handler turns it into "that just went, let me find you another".
    """
    # A hold that merely timed out is not a lost slot. Try to bring it back first — the
    # exclusion constraint decides whether the time is genuinely still free, so this
    # cannot resurrect something another caller has taken.
    with conn.cursor() as probe:
        probe.execute(
            "SELECT 1 FROM calendar_occupancy WHERE tenant_id = %s AND metadata->>'publicId' = %s"
            " AND state = 'ACTIVE' AND kind = 'HOLD'",
            (tenant_id, public_slot_id),
        )
        if probe.fetchone() is None:
            try:
                with conn.transaction():  # savepoint: a failed resurrection is not fatal
                    probe.execute(
                        RESURRECT_HOLD,
                        {
                            "tenant_id": tenant_id,
                            "public_slot_id": public_slot_id,
                            "call_id": call_id,
                            "reservation_ttl": reservation_ttl_seconds,
                        },
                    )
                    revived = probe.fetchone()
            except psycopg.errors.ExclusionViolation:
                revived = None  # genuinely resold while they deliberated
            if revived is not None:
                # Put it back to HOLD so the ordinary promotion path below claims it.
                probe.execute(
                    "UPDATE calendar_occupancy SET kind = 'HOLD' WHERE id = %s", (revived[0],)
                )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            CREATE_BOOKING,
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "public_slot_id": public_slot_id,
                "service_id": service_id,
                "call_id": call_id,
                "phone": phone,
                "first_name": first_name,
                "last_name": last_name,
                "price_cents": price_cents,
                "deposit_cents": deposit_cents,
                "is_member": is_member,
                "reservation_ttl": reservation_ttl_seconds,
            },
        )
        row = cur.fetchone()

    if row is None:
        return None

    return BookingResult(
        id=str(row["id"]),
        state=str(row["state"]),
        starts_at=row["starts_at"],
        provider_id=str(row["provider_id"]),
        outcome=str(row["outcome"]),
    )


@dataclass(frozen=True, slots=True)
class ExistingBooking:
    id: str
    starts_at: datetime
    state: str
    deposit_cents: int
    price_cents: int


def find_by_ref(
    conn: psycopg.Connection, *, tenant_id: str, booking_ref_value: str
) -> ExistingBooking | None:
    """Find a booking by the short reference Grace reads aloud.

    Only finds bookings **Grace made**. A Massagebook-era appointment, or one the front
    desk entered directly, is invisible here by design until the Vagaro mirror lands —
    which is why the handler promises a callback rather than claiming a cancellation it
    cannot perform.
    """
    from grace_domain.booking.slot_id import booking_ref as make_ref

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, starts_at, state::text AS state, deposit_cents, price_cents
            FROM bookings
            WHERE tenant_id = %s AND state NOT IN ('CANCELLED', 'EXPIRED')
            ORDER BY created_at DESC
            LIMIT 500
            """,
            (tenant_id,),
        )
        wanted = booking_ref_value.strip().lower()
        for row in cur.fetchall():
            if make_ref(str(row["id"])).lower() == wanted:
                return ExistingBooking(
                    id=str(row["id"]),
                    starts_at=row["starts_at"],
                    state=str(row["state"]),
                    deposit_cents=int(row["deposit_cents"]),
                    price_cents=int(row["price_cents"]),
                )
    return None


def cancel(conn: psycopg.Connection, *, booking_id: str, fee_cents: int, reason: str) -> None:
    """Cancel and release the slot, in one transaction.

    The state trigger requires the audit row, so it is written here rather than trusted to
    a caller — and the occupancy is released in the same breath, because a cancelled
    booking still holding its slot is how a therapist's day silently stays full.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO booking_events (tenant_id, booking_id, from_state, to_state, actor, reason)
            SELECT tenant_id, id, state, 'CANCELLED', 'grace', %s FROM bookings WHERE id = %s
            """,
            (reason, booking_id),
        )
        cur.execute(
            """
            UPDATE bookings
            SET state = 'CANCELLED', cancelled_at = now(), cancellation_reason = %s,
                change_fee_cents = %s, version = version + 1, state_changed_at = now(),
                updated_at = now()
            WHERE id = %s
            """,
            (reason, fee_cents, booking_id),
        )
        cur.execute(
            """
            UPDATE calendar_occupancy
            SET state = 'RELEASED', released_at = now(), release_reason = 'booking_cancelled'
            WHERE booking_id = %s AND state = 'ACTIVE'
            """,
            (booking_id,),
        )
