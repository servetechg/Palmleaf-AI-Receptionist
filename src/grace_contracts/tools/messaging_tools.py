"""Tools 8–10: async messaging.

Vapi marks async tools resolved immediately and never delivers the response to the
model (03-vapi-layer §4.2) — so the caller-facing acknowledgement MUST come from the tool's
``request-start`` message, never from ``result``.

All three are gated on GATE-09 (A2P 10DLC). Until the campaign is verified the handler
falls back to email and says so; it never silently drops the message.
"""

from __future__ import annotations

from enum import StrEnum

from .shared import BookingRef, ToolAck, ToolInput, ToolOutput


class SendChannel(StrEnum):
    SMS = "sms"
    EMAIL = "email"
    NONE = "none"


class DegradedReason(StrEnum):
    TENDLC_PENDING = "10dlc_pending"
    OPTED_OUT = "opted_out"
    NO_CONTACT_METHOD = "no_contact_method"
    NONE = "none"


class SendData(ToolOutput):
    queued: bool
    channel: SendChannel
    degraded_reason: DegradedReason = DegradedReason.NONE


class SendResult(ToolAck):
    data: SendData | None = None


class SendIntakeFormInput(ToolInput):
    booking_ref: BookingRef


class SendDepositLinkInput(ToolInput):
    booking_ref: BookingRef


class SendBookingConfirmationInput(ToolInput):
    booking_ref: BookingRef


SendIntakeFormOutput = SendResult
SendDepositLinkOutput = SendResult
SendBookingConfirmationOutput = SendResult
