"""Tools 5–7: the booking write path.

All idempotent (I3), all emit outbox rows (I8), none carries a ``backoffPlan`` —
a retried booking is a real-world duplicate (03-vapi-layer §4.1).
"""

from __future__ import annotations

from pydantic import Field

from .shared import (
    BookingRef,
    ContactPreference,
    FeeReason,
    LocalDate,
    PhoneE164,
    PublicSlotId,
    TimePreference,
    ToolAck,
    ToolInput,
    ToolOutput,
)

# ── 5. createBooking ──────────────────────────────────────────────────────────


class CreateBookingInput(ToolInput):
    slot_id: PublicSlotId
    first_name: str = Field(
        min_length=1,
        max_length=60,
        description="Caller first name as they said it. Do not ask for a surname unless they offer one.",
    )
    last_name: str = Field(default="", max_length=60)
    # The gate is enforced server-side, not by the prompt alone (I4). The handler
    # rejects the booking unless this is explicitly true, so a model that skips the
    # screening question cannot book.
    booked_for_name: str = Field(
        default="",
        max_length=60,
        description=(
            "First name of the person the appointment is FOR, when it isn't the caller "
            "(e.g. booking for a partner). Leave empty when the caller books for themselves."
        ),
    )

    medical_screen_passed: bool = Field(
        description=(
            "Set true ONLY after asking the screening question and hearing a clear no. "
            "If they said yes, are unsure, or you did not ask, set false and call "
            "flagMedicalHold instead of booking."
        )
    )
    notes: str = Field(
        default="",
        max_length=280,
        description=(
            'Scheduling preferences only, e.g. "prefers a quieter room". '
            "NEVER any health, medical, or diagnostic detail."
        ),
    )

    # ── where the confirmation, intake form and payment link actually go ──
    #
    # Before these existed the handler read a `phone` key the schema never offered, so every
    # booking stored the placeholder +10000000000 and no confirmation could ever reach the
    # customer. A booking without a reachable contact is not a booking.
    phone: PhoneE164 = Field(
        description=(
            "The caller's mobile number, ONLY as they spoke it aloud on this call. On a web "
            "call there is no caller ID, so you must ask. Never use a number from anywhere "
            "else and never guess one."
        )
    )
    # Same server-side gate as medical_screen_passed (I4): the prompt is told to read the
    # number back, and this makes it so regardless of whether the model remembered to.
    phone_confirmed: bool = Field(
        description=(
            "Set true ONLY after you have read the number back digit by digit and the caller "
            "confirmed it. If you did not read it back, set false."
        )
    )
    email: str = Field(
        default="",
        max_length=254,
        description=(
            "Email address, if they gave one. Spell it back before using it. Leave empty if "
            "they did not offer one — never invent or assume an address."
        ),
    )
    contact_preference: ContactPreference = Field(
        default=ContactPreference.SMS,
        description=(
            "Where they want their confirmation and any payment link. Ask if unsure. Use "
            "'both' only when they actually gave both a number and an email."
        ),
    )


class CreateBookingData(ToolOutput):
    booking_ref: BookingRef
    confirmed: bool
    deposit_required: bool


class CreateBookingOutput(ToolAck):
    data: CreateBookingData | None = None


# ── 6. rescheduleAppointment ──────────────────────────────────────────────────


class RescheduleAppointmentInput(ToolInput):
    booking_ref: BookingRef
    new_date: LocalDate
    new_time_preference: TimePreference = Field(
        default=TimePreference.ANY,
        description="Rough time of day they want instead. Use 'any' if they did not say.",
    )
    fee_acknowledged: bool = Field(
        default=False,
        description=(
            "Set true only after you have stated the change fee and the caller agreed. "
            "Never assume agreement."
        ),
    )


class RescheduleData(ToolOutput):
    booking_ref: BookingRef
    fee_cents: int
    fee_reason: FeeReason
    rescheduled: bool


class RescheduleAppointmentOutput(ToolAck):
    data: RescheduleData | None = None


# ── 7. cancelAppointment ──────────────────────────────────────────────────────


class CancelAppointmentInput(ToolInput):
    booking_ref: BookingRef
    fee_acknowledged: bool = Field(
        default=False,
        description="Set true only after stating the cancellation fee and hearing the caller accept it.",
    )


class CancelData(ToolOutput):
    booking_ref: BookingRef
    fee_cents: int
    fee_reason: FeeReason
    cancelled: bool


class CancelAppointmentOutput(ToolAck):
    data: CancelData | None = None
