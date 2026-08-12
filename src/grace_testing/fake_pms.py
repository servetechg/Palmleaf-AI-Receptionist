"""A stateful in-memory PMS (provider-adapters.md §8).

Not a stub that returns constants — a real store with real pagination, so the sync worker
and the booking saga can be developed and tested with no Vagaro account and no network.

The point of the capability flags being constructor arguments: **AC-05.7** requires that
flipping ``write_appointments=True`` on this fake switches the booking saga onto the
native-write path with no other code change. If that ever stops being true, the
abstraction has leaked and the "Vagaro says yes" migration will not be the one-file change
the design promises.

Fidelity rule from the doc: when the real API surprises us, the surprise lands here *and*
in the adapter in the same change, with a test.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime

from grace_contracts.ports.errors import NotSupportedByProvider
from grace_contracts.ports.pms import (
    AvailabilityQuery,
    CreateAppointmentRequest,
    CreateCustomerRequest,
    Page,
    PmsAppointment,
    PmsCapabilities,
    PmsCustomer,
    PmsEmployee,
    PmsLocation,
    PmsService,
    PmsSlot,
    UpdateAppointmentRequest,
)

_DIGITS = str.maketrans("", "", " ()-.‑–")


def normalise_phone(raw: str, default_country: str = "1") -> str:
    """Best-effort E.164. The contract suite asserts lookups match regardless of format.

    Deliberately small: the fake exists to prove callers normalise *before* querying, not
    to be a phone-number library. A real adapter uses the same helper on the way out.
    """
    cleaned = raw.translate(_DIGITS).strip()
    if cleaned.startswith("+"):
        return cleaned
    digits = "".join(c for c in cleaned if c.isdigit())
    if len(digits) == 10:
        return f"+{default_country}{digits}"
    return f"+{digits}"


class FakePms:
    """In-memory `PmsPort`. Everything is a dict; nothing escapes the process."""

    def __init__(
        self,
        *,
        capabilities: PmsCapabilities | None = None,
        latency_s: float = 0.0,
        failure_rate: float = 0.0,
        page_size: int = 50,
        seed: int = 0,
    ) -> None:
        self._capabilities = capabilities or PmsCapabilities(
            read_appointments=True,
            read_customers=True,
            read_employees=True,
            read_services=True,
            webhooks=True,
        )
        self._latency_s = latency_s
        self._failure_rate = failure_rate
        self._page_size = page_size
        self._rng = random.Random(seed)

        self.appointments: dict[str, PmsAppointment] = {}
        self.customers: dict[str, PmsCustomer] = {}
        self.employees: dict[str, PmsEmployee] = {}
        self.services: dict[str, PmsService] = {}
        self.locations: dict[str, PmsLocation] = {}
        self._next_id = 1

    # ── test helpers ─────────────────────────────────────────────────────────────
    @property
    def capabilities(self) -> PmsCapabilities:
        return self._capabilities

    def set_capabilities(self, capabilities: PmsCapabilities) -> None:
        self._capabilities = capabilities

    def add_appointment(self, appointment: PmsAppointment) -> PmsAppointment:
        self.appointments[appointment.id] = appointment
        return appointment

    def add_customer(self, customer: PmsCustomer) -> PmsCustomer:
        self.customers[customer.id] = customer
        return customer

    def add_employee(self, employee: PmsEmployee) -> PmsEmployee:
        self.employees[employee.id] = employee
        return employee

    def add_service(self, service: PmsService) -> PmsService:
        self.services[service.id] = service
        return service

    def _mint_id(self, prefix: str) -> str:
        value = f"{prefix}-{self._next_id}"
        self._next_id += 1
        return value

    async def _tick(self) -> None:
        """Injected latency and failures, so retry/breaker logic has something to chew."""
        if self._latency_s:
            await asyncio.sleep(self._latency_s)
        if self._failure_rate and self._rng.random() < self._failure_rate:
            raise ConnectionError("FakePms: injected transport failure")

    def _paginate(self, items: list[object], cursor: str | None) -> tuple[list[object], str | None]:
        start = int(cursor) if cursor else 0
        window = items[start : start + self._page_size]
        nxt = start + self._page_size
        return window, (str(nxt) if nxt < len(items) else None)

    def _require(self, flag: bool, operation: str) -> None:
        if not flag:
            raise NotSupportedByProvider(operation, provider="FakePms")

    # ── reads ────────────────────────────────────────────────────────────────────
    async def list_appointments(
        self, *, from_time: datetime, to_time: datetime, cursor: str | None = None
    ) -> Page[PmsAppointment]:
        await self._tick()
        self._require(self._capabilities.read_appointments, "list_appointments")
        matching = sorted(
            (a for a in self.appointments.values() if from_time <= a.starts_at < to_time),
            key=lambda a: (a.starts_at, a.id),
        )
        window, nxt = self._paginate(list(matching), cursor)
        return Page[PmsAppointment](
            items=[a for a in window if isinstance(a, PmsAppointment)], next_cursor=nxt
        )

    async def get_appointment(self, appointment_id: str) -> PmsAppointment | None:
        await self._tick()
        self._require(self._capabilities.read_appointments, "get_appointment")
        return self.appointments.get(appointment_id)

    async def list_customers(
        self, *, updated_since: datetime | None = None, cursor: str | None = None
    ) -> Page[PmsCustomer]:
        await self._tick()
        self._require(self._capabilities.read_customers, "list_customers")
        ordered = sorted(self.customers.values(), key=lambda c: c.id)
        window, nxt = self._paginate(list(ordered), cursor)
        return Page[PmsCustomer](
            items=[c for c in window if isinstance(c, PmsCustomer)], next_cursor=nxt
        )

    async def find_customer_by_phone(self, phone_e164: str) -> PmsCustomer | None:
        await self._tick()
        self._require(self._capabilities.read_customers, "find_customer_by_phone")
        wanted = normalise_phone(phone_e164)
        for customer in self.customers.values():
            if customer.phone_e164 and normalise_phone(customer.phone_e164) == wanted:
                return customer
        return None

    async def list_employees(self) -> list[PmsEmployee]:
        await self._tick()
        self._require(self._capabilities.read_employees, "list_employees")
        return sorted(self.employees.values(), key=lambda e: e.id)

    async def list_services(self) -> list[PmsService]:
        await self._tick()
        self._require(self._capabilities.read_services, "list_services")
        return sorted(self.services.values(), key=lambda s: s.id)

    async def list_locations(self) -> list[PmsLocation]:
        await self._tick()
        return sorted(self.locations.values(), key=lambda loc: loc.id)

    # ── writes ───────────────────────────────────────────────────────────────────
    async def create_appointment(self, req: CreateAppointmentRequest) -> PmsAppointment:
        await self._tick()
        self._require(self._capabilities.write_appointments, "create_appointment")
        appointment = PmsAppointment(
            id=self._mint_id("appt"),
            starts_at=req.starts_at,
            ends_at=req.ends_at,
            status="Confirmed",
            customer_id=req.customer_id,
            employee_id=req.employee_id,
            service_id=req.service_id,
            booked_via="grace",
            updated_at=datetime.now(UTC),
        )
        self.appointments[appointment.id] = appointment
        return appointment

    async def update_appointment(
        self, appointment_id: str, req: UpdateAppointmentRequest
    ) -> PmsAppointment:
        await self._tick()
        self._require(self._capabilities.update_appointments, "update_appointment")
        current = self.appointments.get(appointment_id)
        if current is None:
            raise KeyError(appointment_id)
        updated = current.model_copy(
            update={k: v for k, v in req.model_dump().items() if v is not None}
        )
        self.appointments[appointment_id] = updated
        return updated

    async def cancel_appointment(self, appointment_id: str, reason: str) -> None:
        await self._tick()
        self._require(self._capabilities.cancel_appointments, "cancel_appointment")
        current = self.appointments.get(appointment_id)
        if current is not None:
            self.appointments[appointment_id] = current.model_copy(
                update={"status": "Cancelled", "raw": {**current.raw, "cancelReason": reason}}
            )

    async def create_customer(self, req: CreateCustomerRequest) -> PmsCustomer:
        await self._tick()
        self._require(self._capabilities.write_customers, "create_customer")
        customer = PmsCustomer(
            id=self._mint_id("cust"),
            phone_e164=normalise_phone(req.phone_e164),
            email=req.email,
            first_name=req.first_name,
            last_name=req.last_name,
        )
        self.customers[customer.id] = customer
        return customer

    async def search_availability(self, query: AvailabilityQuery) -> list[PmsSlot]:
        await self._tick()
        self._require(self._capabilities.search_availability, "search_availability")
        return []
