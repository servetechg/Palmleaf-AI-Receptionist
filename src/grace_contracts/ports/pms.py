"""The PMS port — the only shape the rest of the system knows a booking system by.

provider-adapters.md §1, §3. **The domain does not know Vagaro exists.** Everything above
this file speaks to `PmsPort`; every line of Vagaro-specific code lives in
`grace_adapters.vagaro` behind it. That is what makes "Vagaro grants a write API" a
one-file change rather than a redesign, and what lets a second PMS ever be added.

Two rules that matter more than the signatures:

1. **Code never branches on the adapter's class.** It branches on
   ``pms.capabilities.write_appointments``. Vagaro's write story is unknown until the
   credentials arrive and discovery runs; the capability flag is how that uncertainty is
   carried without leaking into the domain.
2. **Reads here are for SYNC, not for answering a caller.** Invariant I1 forbids touching
   a third party on the synchronous voice path — in-call availability comes from the local
   mirror. Vagaro's 5,000-calls/month quota makes that architectural, not just a latency
   preference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class PmsCapabilities:
    """What this provider can actually do, as facts rather than assumptions.

    Every write defaults to False. A provider must prove it can write by setting the flag,
    which happens in one place per adapter (`capabilities.py`) from observed evidence —
    never from documentation or optimism.
    """

    read_appointments: bool = False
    read_customers: bool = False
    read_employees: bool = False
    read_services: bool = False
    write_appointments: bool = False
    update_appointments: bool = False
    cancel_appointments: bool = False
    write_customers: bool = False
    search_availability: bool = False
    idempotency_header: bool = False
    webhooks: bool = False


class Page[T](BaseModel):
    """One page of results plus the cursor for the next, if any.

    Vagaro's pagination convention is unconfirmed (GATE-03). The adapter implements cursor
    and offset behind this one shape and detects at runtime which it is dealing with, so
    callers loop on ``next_cursor`` regardless.
    """

    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = None


class PmsAppointment(BaseModel):
    id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    customer_id: str | None = None
    employee_id: str | None = None
    service_id: str | None = None
    service_name: str | None = None
    booked_via: str | None = None
    updated_at: datetime | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class PmsCustomer(BaseModel):
    id: str
    phone_e164: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    membership_active: bool = False
    visit_count: int = 0
    raw: dict[str, object] = Field(default_factory=dict)


class PmsEmployee(BaseModel):
    id: str
    display_name: str
    active: bool = True
    raw: dict[str, object] = Field(default_factory=dict)


class PmsService(BaseModel):
    id: str
    name: str
    duration_min: int | None = None
    price_cents: int | None = None
    category: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class PmsLocation(BaseModel):
    id: str
    name: str
    timezone: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class PmsSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    employee_id: str | None = None


class AvailabilityQuery(BaseModel):
    """Only used when ``capabilities.search_availability`` is True.

    Even then it is a *sync-time* helper, never the in-call path.
    """

    service_id: str
    from_time: datetime
    to_time: datetime
    employee_id: str | None = None


class CreateAppointmentRequest(BaseModel):
    customer_id: str
    employee_id: str
    service_id: str
    starts_at: datetime
    ends_at: datetime
    note: str | None = None
    idempotency_key: str | None = None


class UpdateAppointmentRequest(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    employee_id: str | None = None
    status: str | None = None


class CreateCustomerRequest(BaseModel):
    phone_e164: str
    first_name: str
    last_name: str | None = None
    email: str | None = None


class PmsPort(Protocol):
    """The interface. Implemented by `FakePms` and by the Vagaro adapter."""

    @property
    def capabilities(self) -> PmsCapabilities: ...

    # ── reads ────────────────────────────────────────────────────────────────────
    async def list_appointments(
        self, *, from_time: datetime, to_time: datetime, cursor: str | None = None
    ) -> Page[PmsAppointment]: ...

    async def get_appointment(self, appointment_id: str) -> PmsAppointment | None:
        """Returns None when absent. Never raises for a missing record."""
        ...

    async def list_customers(
        self, *, updated_since: datetime | None = None, cursor: str | None = None
    ) -> Page[PmsCustomer]: ...

    async def find_customer_by_phone(self, phone_e164: str) -> PmsCustomer | None:
        """Normalises to E.164 before querying — callers may pass anything spoken."""
        ...

    async def list_employees(self) -> list[PmsEmployee]: ...

    async def list_services(self) -> list[PmsService]: ...

    async def list_locations(self) -> list[PmsLocation]: ...

    # ── writes: every one may raise NotSupportedByProvider ───────────────────────
    async def create_appointment(self, req: CreateAppointmentRequest) -> PmsAppointment: ...

    async def update_appointment(
        self, appointment_id: str, req: UpdateAppointmentRequest
    ) -> PmsAppointment: ...

    async def cancel_appointment(self, appointment_id: str, reason: str) -> None: ...

    async def create_customer(self, req: CreateCustomerRequest) -> PmsCustomer: ...

    async def search_availability(self, query: AvailabilityQuery) -> list[PmsSlot]: ...
