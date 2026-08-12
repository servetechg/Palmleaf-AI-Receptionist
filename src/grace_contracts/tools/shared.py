"""Shared primitives for tool schemas.

Every ``description=`` here is read by the model on every turn — it is prompt real
estate, not documentation (02-python-and-repo §4, 03-vapi-layer §4.3). Write for a new receptionist,
not an API consumer.

Two hard rules for tool INPUT models, both learned from live 400s (03-vapi-layer §4.1):

1. **Never use ``X | None``** on an input field. Pydantic renders an optional-with-
   constraints field as ``anyOf``, which Vapi rejects. Use a plain type with a
   default instead, or omit the field.
2. **Never use ``Literal[...]`` with a single value.** It renders as a scalar
   ``const``, which Vapi also rejects. Use the plain type and enforce the value in
   the handler — which is where I4 wants it anyway.

``generate_tools.py`` enforces both statically, so neither can reach a deploy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# ── field aliases ─────────────────────────────────────────────────────────────

LocalDate = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Local date in YYYY-MM-DD. Today or later. Never guess a year the caller did not say.",
    ),
]

PublicSlotId = Annotated[
    str,
    Field(
        pattern=r"^[Hh][Oo][Ll][Dd]-[0-9A-Za-z]{3,6}$",
        description="Slot id exactly as checkAvailability returned it, e.g. hold-7K2. Never invent one.",
    ),
]

BookingRef = Annotated[
    str,
    Field(
        pattern=r"^[Bb][Kk]-[0-9A-Za-z]{4,8}$",
        description="Booking reference exactly as it was given to you, e.g. bk-3QR9.",
    ),
]

PhoneE164 = Annotated[
    str,
    Field(
        pattern=r"^\+[1-9]\d{7,14}$",
        description="Phone number in E.164 format, e.g. +18475550123",
    ),
]


# ── enums ─────────────────────────────────────────────────────────────────────


class TimePreference(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    ANY = "any"


class ContactPreference(StrEnum):
    """Where the caller wants their confirmation, intake form and any payment link.

    ``BOTH`` is not greedy defaulting — a deposit link that misses costs a booking, so a
    caller who offers both addresses gets both. What is never allowed is guessing: the
    handler refuses a channel it has no address for rather than silently downgrading.
    """

    SMS = "sms"
    EMAIL = "email"
    BOTH = "both"


class EscalationReason(StrEnum):
    """Closed set, never free text — this value is persisted, and an LLM-authored
    free-text field summarising a transcript is a PHI route (I6, 03-vapi-layer §3.4)."""

    ASKED_FOR_PERSON = "asked_for_person"
    FRUSTRATED = "frustrated"
    COMPLAINT = "complaint"
    REFUND = "refund"
    GIFT_CERTIFICATE = "gift_certificate"
    MEDICAL = "medical"
    RECORDING_OBJECTION = "recording_objection"
    NO_TOOL = "no_tool"
    REPEATED_FAILURE = "repeated_failure"


class Urgency(StrEnum):
    NORMAL = "normal"
    HIGH = "high"


class FeeReason(StrEnum):
    """Machine-readable reason from the pure 48h engine (01-architecture ADR-0011)."""

    INSIDE_48H = "inside_48h"
    OUTSIDE_48H = "outside_48h"
    WAIVED = "waived"
    POLICY_UNAPPROVED = "policy_unapproved"


# ── base models ───────────────────────────────────────────────────────────────


class ToolInput(BaseModel):
    """Base for every tool input.

    ``extra="forbid"`` is the equivalent of zod's ``.strict()`` and renders as
    ``additionalProperties: false``. A model inventing a parameter must be a loud
    validation error, never a silently ignored field.
    """

    model_config = ConfigDict(extra="forbid")


class ToolOutput(BaseModel):
    """Base for tool outputs. These never reach Vapi, so the constraints that apply
    to inputs (no ``anyOf``, no scalar ``const``) do not apply here."""


class ToolAck(ToolOutput):
    """Every write tool returns this. The router turns ``spoken`` into the Vapi
    ``result`` string (reference/core-api §5.1).

    Subclasses declare their own typed ``data`` field. The base deliberately does not,
    so a subclass narrowing it to a concrete model is not a type error.
    """

    spoken: str = Field(min_length=1)
