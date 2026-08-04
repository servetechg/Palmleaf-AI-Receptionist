"""THE registry.

One entry per function tool; everything downstream derives from it — ``generate_tools``,
the prompt's TOOLS table, the mock server's dispatch, and eventually Core API's router.
Adding a tool means adding a row here and nothing else.

``transferToHuman`` and ``endCall`` are absent by design: they are Vapi tool *types* with
no parameters and therefore no Pydantic source (doc 08 §7.1).
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
    a new receptionist, including what NOT to do with the tool (doc 08 §4.3)."""

    input_model: type[BaseModel]
    output_model: type[BaseModel]

    budget_ms: int | None
    """p95 latency TARGET, from doc 08 §4. NOT a deadline — the deadline is
    GRACE_TOOL_DEADLINE_MS. Racing a handler against this fires the fallback on ~5% of
    healthy calls (doc 01 ADR-0012). ``None`` for async tools."""

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
            "Answer a factual question about the business — hours, address, parking, how to "
            "reach us, what we offer, policies, or memberships. Call this instead of answering "
            "from memory; you do not know these facts. If the tool says it has no approved "
            "answer, do not improvise — escalate."
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
            "Look up the caller by the number they are calling from, so you can greet them by "
            "name and know if they are a member. Call this early. It tells you IF they are a "
            "member but NOT what members pay — always call getServicesAndPricing for any price."
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
            "Get services, durations and prices. Call this before stating ANY price or service "
            "length. Never quote a price this tool did not return, and never estimate or say "
            '"usually about". If it reports the catalogue is unapproved, say you will have '
            "someone confirm the price and escalate."
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
            "Find open appointment times. Call this whenever the caller asks about availability, "
            "mentions a day or time they'd like, or after they choose a service. NEVER guess or "
            "state a time this tool did not return. If the caller says something vague like "
            "'sometime next week', pick the first date of that range and call this — you can "
            "call it again for other days."
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
            "Book the appointment. Call this only after the caller has chosen a specific time "
            "you offered AND you have asked the medical screening question. Pass the slot id "
            "exactly as checkAvailability gave it. If they disclosed anything medical, do not "
            "call this — call flagMedicalHold and escalate."
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
            "Move an existing appointment to a new day or time. The tool decides whether a "
            "change fee applies — you do not. State the fee it returns, in full, before "
            "confirming, and only set feeAcknowledged once the caller has agreed."
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
            "Cancel an existing appointment. The tool decides whether a cancellation fee "
            "applies — you do not, and you must never waive one. State the fee it returns "
            "before confirming. If the caller disputes it, escalate rather than arguing."
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
            "Text the caller their intake form after booking. Call this once, right after a "
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
            "Take a message for the team when nobody can be reached or the caller prefers a "
            "callback. Capture their name, callback number, and a one-line subject. Never "
            "record health or medical detail."
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
            "Call this IMMEDIATELY BEFORE transferToHuman, every single time. It creates the "
            "staff task and gives the person picking up the context they need — without it "
            "they answer blind. Summarise in one sentence, and never put medical or health "
            'detail in the summary; say "a health matter" instead.'
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
