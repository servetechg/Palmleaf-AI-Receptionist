"""The PMS contract suite (provider-adapters.md §9).

Every assertion here is a promise the *port* makes, not a promise FakePms makes. When the
Vagaro adapter exists it is added to the parametrisation and must pass this file unchanged
— that is the whole point: the fake and the real adapter cannot drift in behaviour without
a red test.

No network, no database, no clock dependence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from grace_contracts.ports.errors import NotSupportedByProvider
from grace_contracts.ports.pms import (
    CreateAppointmentRequest,
    PmsAppointment,
    PmsCapabilities,
    PmsCustomer,
)
from grace_testing.fake_pms import FakePms, normalise_phone

NOW = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)

READ_ONLY = PmsCapabilities(
    read_appointments=True, read_customers=True, read_employees=True, read_services=True
)
FULL_WRITE = PmsCapabilities(
    read_appointments=True,
    read_customers=True,
    read_employees=True,
    read_services=True,
    write_appointments=True,
    update_appointments=True,
    cancel_appointments=True,
    write_customers=True,
)


def populated(capabilities: PmsCapabilities, *, appointments: int = 0) -> FakePms:
    pms = FakePms(capabilities=capabilities, page_size=10)
    for i in range(appointments):
        pms.add_appointment(
            PmsAppointment(
                id=f"appt-{i:03d}",
                starts_at=NOW + timedelta(hours=i),
                ends_at=NOW + timedelta(hours=i, minutes=60),
                status="Confirmed",
            )
        )
    return pms


# ── pagination ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pagination_visits_every_item_exactly_once() -> None:
    """A cursor loop must terminate and must not duplicate or skip."""
    pms = populated(READ_ONLY, appointments=25)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # bounded: a non-terminating cursor is a failure, not a hang
        page = await pms.list_appointments(
            from_time=NOW - timedelta(days=1), to_time=NOW + timedelta(days=30), cursor=cursor
        )
        seen.extend(a.id for a in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert cursor is None, "cursor never exhausted"
    assert len(seen) == 25
    assert len(set(seen)) == 25, "pagination returned duplicates"


@pytest.mark.asyncio
async def test_time_window_is_respected() -> None:
    pms = populated(READ_ONLY, appointments=10)
    page = await pms.list_appointments(from_time=NOW, to_time=NOW + timedelta(hours=3))
    assert [a.id for a in page.items] == ["appt-000", "appt-001", "appt-002"]


# ── absent records ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_appointment_returns_none_rather_than_raising() -> None:
    """Callers branch on None. A raise here would make every sync loop defensive."""
    pms = populated(READ_ONLY)
    assert await pms.get_appointment("does-not-exist") is None


# ── phone normalisation ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "spoken",
    ["+18475550123", "8475550123", "(847) 555-0123", "847-555-0123", "847.555.0123"],
)
@pytest.mark.asyncio
async def test_find_customer_by_phone_normalises_before_matching(spoken: str) -> None:
    """A caller ID arrives in many shapes; the port promises one lookup behaviour."""
    pms = populated(READ_ONLY)
    pms.add_customer(PmsCustomer(id="cust-1", phone_e164="+18475550123", first_name="Jordan"))
    found = await pms.find_customer_by_phone(spoken)
    assert found is not None and found.id == "cust-1"


def test_normalise_phone_adds_country_code_to_ten_digits() -> None:
    assert normalise_phone("8475550123") == "+18475550123"


# ── capability gating ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_raises_when_capability_is_false() -> None:
    """The read-only default is what Vagaro is assumed to be until discovery proves more."""
    pms = populated(READ_ONLY)
    with pytest.raises(NotSupportedByProvider):
        await pms.create_appointment(
            CreateAppointmentRequest(
                customer_id="c",
                employee_id="e",
                service_id="s",
                starts_at=NOW,
                ends_at=NOW + timedelta(hours=1),
            )
        )


@pytest.mark.asyncio
async def test_flipping_the_capability_flag_enables_the_write() -> None:
    """AC-05.7: the flag is the only thing standing between us and native writes."""
    pms = populated(READ_ONLY)
    pms.set_capabilities(FULL_WRITE)
    created = await pms.create_appointment(
        CreateAppointmentRequest(
            customer_id="c",
            employee_id="e",
            service_id="s",
            starts_at=NOW,
            ends_at=NOW + timedelta(hours=1),
        )
    )
    assert created.id in pms.appointments
    assert (await pms.get_appointment(created.id)) is not None


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_marks_rather_than_deletes() -> None:
    pms = populated(FULL_WRITE, appointments=1)
    await pms.cancel_appointment("appt-000", reason="caller changed their mind")
    await pms.cancel_appointment("appt-000", reason="caller changed their mind")
    appointment = await pms.get_appointment("appt-000")
    assert appointment is not None and appointment.status == "Cancelled"
