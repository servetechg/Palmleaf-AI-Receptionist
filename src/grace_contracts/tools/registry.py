"""THE registry.

One entry per function tool; everything downstream derives from it — ``generate_tools``,
the prompt's TOOLS table, the mock server's dispatch, and eventually Core API's router.
Adding a tool means adding a row here and nothing else.

``transferToHuman`` and ``endCall`` are absent by design: they are Vapi tool *types* with
no parameters and therefore no Pydantic source (03-vapi-layer §7.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

from .escalation_tools import (
    FlagEscalationInput,
    FlagEscalationOutput,
    FlagMedicalHoldInput,
    FlagMedicalHoldOutput,
    TakeMessageInput,
    TakeMessageOutput,
)
from .messaging_tools import (
    SendBookingConfirmationInput,
    SendBookingConfirmationOutput,
    SendDepositLinkInput,
    SendDepositLinkOutput,
    SendIntakeFormInput,
    SendIntakeFormOutput,
)
from .read_tools import (
    CheckAvailabilityInput,
    CheckAvailabilityOutput,
    GetBusinessInfoInput,
    GetBusinessInfoOutput,
    GetServicesAndPricingInput,
    GetServicesAndPricingOutput,
    LookupCustomerInput,
    LookupCustomerOutput,
)
from .write_tools import (
    CancelAppointmentInput,
    CancelAppointmentOutput,
    CreateBookingInput,
    CreateBookingOutput,
    RescheduleAppointmentInput,
    RescheduleAppointmentOutput,
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    """Tool name as the model sees it."""

    description: str
    """Read by the model on every turn — prompt real estate. Written as an instruction to
    a new receptionist, including what NOT to do with the tool (03-vapi-layer §4.3)."""

    input_model: type[BaseModel]
    output_model: type[BaseModel]

    budget_ms: int | None
    """p95 latency TARGET, from 03-vapi-layer §4. NOT a deadline — the deadline is
    GRACE_TOOL_DEADLINE_MS. Racing a handler against this fires the fallback on ~5% of
    healthy calls (01-architecture ADR-0012). ``None`` for async tools."""

    is_async: bool
    """Vapi ``async: true`` — resolved immediately, response never reaches the model."""

    is_write: bool
    """Writes state; must be idempotent on ``{call_id}:{tool_call_id}`` (I3)."""

    request_start: str = ""
    """Spoken while the tool runs. Required for async tools — their result is never spoken."""

    request_failed: str = ""
    """Spoken if the tool errors. Must never invent a fact (GROUNDING rule)."""

    acked_by_next_tool: bool = field(default=False)
    """Async tool that deliberately says nothing, because the tool the prompt requires
    immediately after it does the speaking. Without this the validator would force a
    filler phrase and the caller would hear two acknowledgements in a row."""


TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="getBusinessInfo",
        description=(
            "Answer any factual question about the business — hours, address, parking, contact, what "
            "we offer, policies, memberships, or our team. Call it even when you think you remember t"
            "he answer; you don't. If it returns no approved answer, say the front desk will confirm "
            "and offer a callback or transfer — never improvise."
        ),
        input_model=GetBusinessInfoInput,
        output_model=GetBusinessInfoOutput,
        budget_ms=150,
        is_async=False,
        is_write=False,
    ),
    ToolSpec(
        name="lookupCustomer",
        description=(
            "Look up the caller by the number they're calling from — do it early in every call, silen"
            "tly. It tells you their name, whether they're a member, and whether they already have an"
            " upcoming booking (vital when someone calls back after being cut off). It never tells yo"
            "u prices — getServicesAndPricing does that. Never ask a caller for a different number to"
            " look up."
        ),
        input_model=LookupCustomerInput,
        output_model=LookupCustomerOutput,
        budget_ms=250,
        is_async=False,
        is_write=False,
    ),
    ToolSpec(
        name="getServicesAndPricing",
        description=(
            "Get real services, durations, and prices before you mention ANY of them. Pass the caller"
            "'s own words as the query. Never state a price or duration this tool did not return in t"
            "his call; never estimate; never say 'usually about'. If it says the catalogue is unappro"
            "ved, tell the caller the front desk will confirm the exact price, and offer a callback."
        ),
        input_model=GetServicesAndPricingInput,
        output_model=GetServicesAndPricingOutput,
        budget_ms=200,
        is_async=False,
        is_write=False,
        request_failed="I'm having trouble pulling up our pricing right now.",
    ),
    ToolSpec(
        name="checkAvailability",
        description=(
            "Find real open times — call it whenever the caller names a day, a time, or asks what's a"
            "vailable, and again every time their preference changes. Offer ONLY times it returned, a"
            "t most three, phrased exactly as given. Vague asks ('sometime next week') pick the first"
            " plausible date and call it; you can call again for other days. If they asked for a ther"
            "apist by name, pass the name in providerPreference and trust the tool's verdict on wheth"
            "er that person exists."
        ),
        input_model=CheckAvailabilityInput,
        output_model=CheckAvailabilityOutput,
        budget_ms=400,
        is_async=False,
        is_write=False,
        request_start="Let me check the schedule.",
        request_failed="I'm having trouble reaching the schedule right now.",
    ),
    ToolSpec(
        name="createBooking",
        description=(
            "Book the chosen slot — only after the caller picked a specific time you offered AND you "
            "asked the screening question this call. Pass slotId exactly as checkAvailability gave it"
            ", and bookedForName when the appointment is for someone other than the caller. If anythi"
            "ng medical came up, do not call this — flagMedicalHold, then hand over."
        ),
        input_model=CreateBookingInput,
        output_model=CreateBookingOutput,
        budget_ms=600,
        is_async=False,
        is_write=True,
        request_start="Let me get that booked for you.",
        request_failed="I'm having trouble completing that booking.",
    ),
    ToolSpec(
        name="rescheduleAppointment",
        description=(
            "Move an existing appointment Grace can see. The tool decides whether a change fee applie"
            "s — you never do, and you never waive one. State any fee it returns in full BEFORE confi"
            "rming, and set feeAcknowledged only after the caller clearly agrees. If it can't find th"
            "e appointment, don't insist — take a message for the front desk instead."
        ),
        input_model=RescheduleAppointmentInput,
        output_model=RescheduleAppointmentOutput,
        budget_ms=700,
        is_async=False,
        is_write=True,
        request_start="Let me look at that for you.",
        request_failed="I'm having trouble changing that appointment.",
    ),
    ToolSpec(
        name="cancelAppointment",
        description=(
            "Cancel an existing appointment Grace can see. The tool decides the cancellation fee — yo"
            "u never do, never waive, never negotiate. State the fee before confirming, and set feeAc"
            "knowledged only on a clear yes. If the caller disputes the fee, or the booking can't be "
            "found, hand over or take a message — never claim a cancellation you couldn't complete."
        ),
        input_model=CancelAppointmentInput,
        output_model=CancelAppointmentOutput,
        budget_ms=600,
        is_async=False,
        is_write=True,
        request_start="Let me pull that up.",
        request_failed="I'm having trouble cancelling that appointment.",
    ),
    ToolSpec(
        name="sendIntakeForm",
        description=(
            "Have the front desk text their intake form after booking. Call this once, right after a "
            "successful booking. Do not read the link aloud."
        ),
        input_model=SendIntakeFormInput,
        output_model=SendIntakeFormOutput,
        budget_ms=None,
        is_async=True,
        is_write=True,
        request_start="I'm texting your intake form over now.",
    ),
    ToolSpec(
        name="sendDepositLink",
        description=(
            "Text a secure payment link for the deposit. Use this whenever money needs "
            "collecting — never take card details by voice. Do not read the link aloud."
        ),
        input_model=SendDepositLinkInput,
        output_model=SendDepositLinkOutput,
        budget_ms=None,
        is_async=True,
        is_write=True,
        request_start="I'm sending a secure payment link to your phone now.",
    ),
    ToolSpec(
        name="sendBookingConfirmation",
        description=(
            "Text the booking confirmation. Call this after booking, rescheduling, or "
            "cancelling so the caller has it in writing."
        ),
        input_model=SendBookingConfirmationInput,
        output_model=SendBookingConfirmationOutput,
        budget_ms=None,
        is_async=True,
        is_write=True,
        request_start="I'm sending your confirmation by text.",
    ),
    ToolSpec(
        name="takeMessage",
        description=(
            "Take a message when nobody can pick up, when the caller prefers a callback, or when a to"
            "ol has failed twice. Capture name, callback number, and a one-line subject; promise the "
            "manager will call back as soon as possible. Never write health or medical detail into an"
            "y field — say 'a health matter'."
        ),
        input_model=TakeMessageInput,
        output_model=TakeMessageOutput,
        budget_ms=300,
        is_async=False,
        is_write=True,
        request_start="Let me take that down.",
    ),
    ToolSpec(
        name="flagMedicalHold",
        description=(
            "Call this the instant a caller mentions their own surgery, condition, "
            "medication, pregnancy, or treatment — even in passing. "
            "Call this the instant a caller mentions surgery, an injury, a condition, "
            "medication, pregnancy, or any treatment — even in passing. It blocks the booking "
            "so a qualified person can follow up. Do NOT ask what the condition is, do NOT "
            "repeat it back, and do NOT record it anywhere. After calling this, escalate."
        ),
        input_model=FlagMedicalHoldInput,
        output_model=FlagMedicalHoldOutput,
        budget_ms=300,
        is_async=False,
        is_write=True,
    ),
    ToolSpec(
        name="flagEscalation",
        description=(
            "Prime the human handoff — call this immediately before transferToHuman, every single tim"
            "e, and also when arranging a manager callback for an upset caller. The summary is what t"
            "he person picking up sees; one plain sentence, never any medical or health detail — writ"
            "e 'a health matter' instead."
        ),
        input_model=FlagEscalationInput,
        output_model=FlagEscalationOutput,
        budget_ms=None,
        is_async=True,
        is_write=True,
        # Silent on purpose: transferToHuman fires immediately after and speaks
        # "Of course — let me get someone for you." Two acknowledgements would be worse.
        acked_by_next_tool=True,
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(t.name for t in TOOL_REGISTRY)

_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOL_REGISTRY}


def get_tool_spec(name: str) -> ToolSpec | None:
    return _BY_NAME.get(name)


HAND_AUTHORED_TOOLS: tuple[str, ...] = ("transferToHuman", "endCall")
"""Vapi tool *types* with no schema source. ``generate_tools`` must not produce them and
the drift check must not treat them as orphans.

``endCall`` used to be the assistant flag ``endCallFunctionEnabled``. That property no
longer exists on ``CreateAssistantDTO`` — verified 2026-08-03 — and hanging up is now an
explicit ``type: "endCall"`` tool."""

TOTAL_TOOL_COUNT: int = len(TOOL_REGISTRY) + len(HAND_AUTHORED_TOOLS)
