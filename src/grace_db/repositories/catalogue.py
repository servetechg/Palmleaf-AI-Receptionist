"""Reading tenant, services and customers — all approval-gated (data-model.md §4, §7).

Every read that Grace might *speak* filters on `approved_at IS NOT NULL`. That is the
mechanism behind GATE-04: an unapproved service is invisible to her, so she cannot quote a
price the client never signed off. Sign-off is then one UPDATE per row, not a release.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    slug: str
    timezone: str
    settings: dict[str, Any]

    @property
    def hold_ttl_seconds(self) -> int:
        return int(self.settings.get("holdTtlSeconds", 240))

    @property
    def max_slots_offered(self) -> int:
        return int(self.settings.get("maxSlotsOffered", 3))

    @property
    def kill_switch(self) -> bool:
        return bool(self.settings.get("killSwitch", False))

    @property
    def speak_provider_names(self) -> bool:
        """False until the client gives us real therapist names (C3).

        Defaults to False deliberately: the failure of saying an internal placeholder or
        an invented name out loud is worse than offering a time on its own.
        """
        return bool(self.settings.get("speakProviderNames", False))


@dataclass(frozen=True, slots=True)
class Service:
    id: str
    code: str
    spoken_name: str
    duration_min: int
    buffer_before_min: int
    buffer_after_min: int
    price_nonmember_cents: int
    price_member_cents: int | None
    deposit_cents: int
    approved: bool


@dataclass(frozen=True, slots=True)
class Customer:
    id: str
    phone_e164: str
    first_name: str | None
    membership_active: bool
    visit_count: int
    medical_hold: bool


def get_tenant_by_slug(conn: psycopg.Connection, slug: str) -> Tenant | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, slug, timezone, settings FROM tenants WHERE slug = %s AND status = 'ACTIVE'",
            (slug,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Tenant(
        id=str(row["id"]),
        slug=row["slug"],
        timezone=row["timezone"],
        settings=row["settings"] or {},
    )


def get_tenant_by_channel(conn: psycopg.Connection, kind: str, external_id: str) -> Tenant | None:
    """Resolve a tenant from a Vapi assistant or phone-number id. No hardcoded ids in code."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT t.id, t.slug, t.timezone, t.settings
            FROM tenant_channels tc
            JOIN tenants t ON t.id = tc.tenant_id
            WHERE tc.kind = %s AND tc.external_id = %s AND tc.active AND t.status = 'ACTIVE'
            """,
            (kind, external_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Tenant(
        id=str(row["id"]),
        slug=row["slug"],
        timezone=row["timezone"],
        settings=row["settings"] or {},
    )


def _service_from_row(row: dict[str, Any]) -> Service:
    return Service(
        id=str(row["id"]),
        code=row["code"],
        spoken_name=row["spoken_name"],
        duration_min=row["duration_min"],
        buffer_before_min=row["buffer_before_min"],
        buffer_after_min=row["buffer_after_min"],
        price_nonmember_cents=row["price_nonmember_cents"],
        price_member_cents=row["price_member_cents"],
        deposit_cents=row["deposit_cents"],
        approved=row["approved_at"] is not None,
    )


def find_service_by_code(conn: psycopg.Connection, tenant_id: str, code: str) -> Service | None:
    """Returns the row even when unapproved, so the caller can say *why* it declined.

    "Let me get someone who can confirm that" is a better answer than "I don't know that
    service" when the service exists and merely lacks a signature.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, code, spoken_name, duration_min, buffer_before_min, buffer_after_min,
                   price_nonmember_cents, price_member_cents, deposit_cents, approved_at
            FROM services
            WHERE tenant_id = %s AND code = %s AND active AND bookable_by_ai
            """,
            (tenant_id, code),
        )
        row = cur.fetchone()
    return _service_from_row(row) if row else None


def search_services(conn: psycopg.Connection, tenant_id: str, query: str) -> list[Service]:
    """Approved services only — this feeds what Grace says out loud."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, code, spoken_name, duration_min, buffer_before_min, buffer_after_min,
                   price_nonmember_cents, price_member_cents, deposit_cents, approved_at
            FROM services
            WHERE tenant_id = %s AND active AND bookable_by_ai AND approved_at IS NOT NULL
              AND (%s = '' OR spoken_name ILIKE '%%' || %s || '%%'
                   OR display_name ILIKE '%%' || %s || '%%'
                   OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a ILIKE '%%' || %s || '%%'))
            ORDER BY duration_min
            LIMIT 3
            """,
            (tenant_id, query, query, query, query),
        )
        return [_service_from_row(r) for r in cur.fetchall()]


def any_service_awaiting_approval(conn: psycopg.Connection, tenant_id: str) -> bool:
    """True when the catalogue exists but is unsigned — the GATE-04 state.

    Lets a handler distinguish "we do not offer that" from "we cannot quote that yet",
    which are very different things to say to a caller.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM services
                WHERE tenant_id = %s AND active AND bookable_by_ai AND approved_at IS NULL
            )
            """,
            (tenant_id,),
        )
        row = cur.fetchone()
        return bool(row[0]) if row else False


def find_customer_by_phone(
    conn: psycopg.Connection, tenant_id: str, phone_e164: str
) -> Customer | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, phone_e164, first_name, membership_active, visit_count, medical_hold
            FROM customers WHERE tenant_id = %s AND phone_e164 = %s
            """,
            (tenant_id, phone_e164),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Customer(
        id=str(row["id"]),
        phone_e164=row["phone_e164"],
        first_name=row["first_name"],
        membership_active=row["membership_active"],
        visit_count=row["visit_count"],
        medical_hold=row["medical_hold"],
    )


def provider_exists(conn: psycopg.Connection, tenant_id: str, spoken_name: str) -> bool:
    """Does anyone by roughly this name actually work here?

    Fuzzy on purpose — a caller says "Maria" and the record reads "Maria Alvarez", and a
    transcript is never exact. Uses the trigram index on `spoken_name`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM providers
                WHERE tenant_id = %s AND active
                  AND (spoken_name ILIKE %s OR display_name ILIKE %s
                       OR similarity(spoken_name, %s) > 0.4)
            )
            """,
            (tenant_id, f"%{spoken_name}%", f"%{spoken_name}%", spoken_name),
        )
        row = cur.fetchone()
        return bool(row[0]) if row else False


def next_booking_for_customer(
    conn: psycopg.Connection, tenant_id: str, customer_id: str
) -> datetime | None:
    """When this customer's next live appointment starts, if they have one."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT starts_at FROM bookings
            WHERE tenant_id = %s AND customer_id = %s
              AND starts_at > now()
              AND state NOT IN ('CANCELLED', 'EXPIRED')
            ORDER BY starts_at
            LIMIT 1
            """,
            (tenant_id, customer_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_knowledge(conn: psycopg.Connection, tenant_id: str, key: str) -> str | None:
    """Approved knowledge entries only (GATE-05); unapproved reads as absent."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT answer_spoken FROM knowledge_entries
            WHERE tenant_id = %s AND key = %s AND active AND approved_at IS NOT NULL
            """,
            (tenant_id, key),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
