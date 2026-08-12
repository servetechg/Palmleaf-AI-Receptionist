"""The Vapi <-> Core API wire contract.

Shared by the mock server today and by Core API later, so both are provably speaking the
same protocol (03-vapi-layer §10).
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── inbound: tool calls ───────────────────────────────────────────────────────


class VapiFunctionCall(BaseModel):
    name: str
    # Vapi sends an object, but has historically sent a JSON string. Accept both — a
    # string here is a wire-level surprise, not a caller error, and must not 500.
    arguments: dict[str, Any] | str = Field(default_factory=dict)


class VapiToolCall(BaseModel):
    id: str
    type: str = "function"
    function: VapiFunctionCall


class VapiCustomer(BaseModel):
    number: str = ""


class VapiCall(BaseModel):
    id: str = ""
    assistant_id: str = Field(default="", alias="assistantId")
    phone_number_id: str = Field(default="", alias="phoneNumberId")
    customer: VapiCustomer | None = None

    model_config = {"populate_by_name": True}


class VapiToolCallsMessage(BaseModel):
    type: str = "tool-calls"
    tool_calls: list[VapiToolCall] = Field(alias="toolCalls", min_length=1)
    call: VapiCall | None = None

    model_config = {"populate_by_name": True}


class VapiToolCallsPayload(BaseModel):
    message: VapiToolCallsMessage
    call: VapiCall | None = None


class VapiToolResult(BaseModel):
    """``result`` is a spoken English sentence, never JSON: numbers in spoken form, at
    most three options, machine data only as an echo-able token like ``hold-7K2``."""

    tool_call_id: str = Field(serialization_alias="toolCallId")
    name: str = ""
    result: str


class VapiToolResponse(BaseModel):
    """ALWAYS this shape, even on error — an HTTP 500 gives the model nothing to say,
    which is dead air (reference/core-api §5.1 rule 4)."""

    results: list[VapiToolResult]


# ── inbound: server events (assistant-level webhook) ──────────────────────────


class VapiServerMessageType(StrEnum):
    END_OF_CALL_REPORT = "end-of-call-report"
    STATUS_UPDATE = "status-update"
    HANG = "hang"
    TOOL_CALLS = "tool-calls"
    TRANSFER_DESTINATION_REQUEST = "transfer-destination-request"


class VapiAnalysis(BaseModel):
    summary: str = ""
    structured_data: dict[str, Any] = Field(default_factory=dict, alias="structuredData")
    success_evaluation: str = Field(default="", alias="successEvaluation")

    model_config = {"populate_by_name": True}


class VapiArtifact(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    transcript: str = ""
    recording_url: str = Field(default="", alias="recordingUrl")

    model_config = {"populate_by_name": True}


class VapiEventMessage(BaseModel):
    type: VapiServerMessageType
    call: VapiCall | None = None
    ended_reason: str = Field(default="", alias="endedReason")
    analysis: VapiAnalysis | None = None
    artifact: VapiArtifact | None = None

    model_config = {"populate_by_name": True}


class VapiEventPayload(BaseModel):
    message: VapiEventMessage


# ── outbound: transfer destination ────────────────────────────────────────────


class TransferPlanMode(StrEnum):
    BLIND = "blind-transfer"
    BLIND_SUMMARY_SIP = "blind-transfer-add-summary-to-sip-header"
    WARM_SAY_MESSAGE = "warm-transfer-say-message"
    WARM_SAY_SUMMARY = "warm-transfer-say-summary"
    WARM_TWIML = "warm-transfer-twiml"
    WARM_WAIT_THEN_MESSAGE = "warm-transfer-wait-for-operator-to-speak-first-and-then-say-message"
    WARM_WAIT_THEN_SUMMARY = "warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary"
    WARM_EXPERIMENTAL = "warm-transfer-experimental"


class TransferFallbackPlan(BaseModel):
    message: str
    end_call_enabled: bool = Field(serialization_alias="endCallEnabled")


class TransferPlan(BaseModel):
    mode: TransferPlanMode
    message: str = ""
    sip_verb: Literal["refer", "bye", "dial"] = Field(
        default="refer", serialization_alias="sipVerb"
    )
    dial_timeout: int = Field(default=60, serialization_alias="dialTimeout")
    fallback_plan: TransferFallbackPlan | None = Field(
        default=None, serialization_alias="fallbackPlan"
    )


class TransferDestination(BaseModel):
    type: Literal["number"] = "number"
    number: str
    # '{{customer.number}}' preserves caller ID on transfer — resolves A-04 by config.
    caller_id: str = Field(default="", serialization_alias="callerId")
    message: str = ""
    transfer_plan: TransferPlan | None = Field(default=None, serialization_alias="transferPlan")


class TransferDestinationResponse(BaseModel):
    destination: TransferDestination


def parse_tool_arguments(raw: dict[str, Any] | str) -> dict[str, Any]:
    """Normalises the string-or-object ``arguments`` quirk into a plain dict."""
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
