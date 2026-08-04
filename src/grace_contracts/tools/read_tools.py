"""Tools 1–4: the read path.

No side effects, no idempotency key, safe to retry — these are the only tools that
carry a ``backoffPlan`` (doc 08 §4).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .shared import LocalDate, PhoneE164, PublicSlotId, TimePreference, ToolInput, ToolOutput

# ── 1. getBusinessInfo ────────────────────────────────────────────────────────


class BusinessTopic(StrEnum):
    HOURS = "hours"
    LOCATION = "location"
    PARKING = "parking"
    CONTACT = "contact"
    SERVICES_OVERVIEW = "services_overview"
    POLICIES = "policies"
    MEMBERSHIPS = "memberships"


class GetBusinessInfoInput(ToolInput):
    topic: BusinessTopic = Field(
        description=(
            "What the caller asked about. Pick the closest match. If nothing fits, "
            "do NOT call this — escalate instead."
        )
    )


class GetBusinessInfoOutput(ToolOutput):
    answer: str = Field(description="Already phrased for speech.")
    approved: bool = Field(
        description="False when no approved entry exists — the model must escalate, never improvise."
    )


# ── 2. lookupCustomer ─────────────────────────────────────────────────────────


class LookupCustomerInput(ToolInput):
    phone: PhoneE164 = Field(
        description=(
            "The caller's own number from caller ID. You may NOT look up any other number — "
            "asking a caller for someone else's number and querying it is not permitted."
        )
    )


class LookupCustomerOutput(ToolOutput):
    found: bool
    first_name: str = ""
    is_member: bool = False
    visit_count: int = 0
    has_upcoming_booking: bool = False


# ── 3. getServicesAndPricing ──────────────────────────────────────────────────


class GetServicesAndPricingInput(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "What the caller asked for, in their words, e.g. '60 minute massage' or "
            "'deep tissue'. Pass it through verbatim."
        ),
    )
    is_member: bool = Field(
        default=False,
        description="Set true only if lookupCustomer already confirmed membership. Never assume.",
    )


class ServiceOption(ToolOutput):
    service_code: str
    name: str
    duration_minutes: int
    price_cents: int
    member_price_cents: int
    deposit_required: bool


class GetServicesAndPricingOutput(ToolOutput):
    services: list[ServiceOption] = Field(max_length=3)
    approved: bool = Field(
        description="False when the catalogue is unapproved (GATE-04) — Grace must not quote a price."
    )


# ── 4. checkAvailability ──────────────────────────────────────────────────────


class CheckAvailabilityInput(ToolInput):
    service_code: str = Field(
        min_length=1,
        description="Service code, e.g. massage_60. Call getServicesAndPricing first to get it.",
    )
    preferred_date: LocalDate
    time_preference: TimePreference = Field(
        default=TimePreference.ANY,
        description="Rough time of day the caller asked for. Use 'any' if they did not say.",
    )
    # Empty string, not None: an optional-with-constraints field renders as `anyOf`,
    # which Vapi rejects. See the note in shared.py.
    provider_preference: str = Field(
        default="",
        description="Provider name if the caller asked for someone specific. Leave empty if not.",
    )
    party_size: int = Field(default=1, ge=1, le=4, description="Number of people. Almost always 1.")


class AvailableSlot(ToolOutput):
    slot_id: PublicSlotId
    starts_at: str
    provider_id: str
    provider_name: str
    price_cents: int
    hold_expires_at: str


class CheckAvailabilityOutput(ToolOutput):
    # Hard cap of 3: the prompt forbids reading more than three options aloud.
    slots: list[AvailableSlot] = Field(max_length=3)
    alternatives_available: bool
