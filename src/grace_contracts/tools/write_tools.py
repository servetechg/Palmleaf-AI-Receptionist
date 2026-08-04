"""Tools 5–7: the booking write path.

All idempotent (I3), all emit outbox rows (I8), none carries a ``backoffPlan`` —
a retried booking is a real-world duplicate (doc 08 §4.1).
"""

from __future__ import annotations

from pydantic import Field

from .shared import (
    BookingRef,
    FeeReason,
    LocalDate,
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
