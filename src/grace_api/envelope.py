"""The Vapi tool-call envelope (core-api.md §4.1, §5.1).

Five rules, every one learned from a live failure somewhere:

1. **One endpoint, batched calls.** Vapi may send more than one tool call per request, so
   the response is a list matched by `toolCallId`.
2. **`result` is a spoken English sentence, never JSON.** The model reads it aloud.
3. **Numbers in spoken form** — "five fifteen", not "17:15".
4. **Errors return a sentence with HTTP 200.** A 500 gives the model nothing to say and
   the caller hears silence.
5. **A missing or mismatched `toolCallId` makes the assistant go mute** — the single most
   common failure in this integration, so it is asserted rather than assumed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCallFunction(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str
    function: ToolCallFunction


class VapiMessage(BaseModel):
    tool_calls: list[ToolCall] = Field(default_factory=list, alias="toolCalls")
    call: dict[str, Any] = Field(default_factory=dict)
    assistant: dict[str, Any] = Field(default_factory=dict)
    phone_number: dict[str, Any] = Field(default_factory=dict, alias="phoneNumber")

    model_config = {"populate_by_name": True, "extra": "allow"}


class VapiToolRequest(BaseModel):
    message: VapiMessage

    model_config = {"extra": "allow"}

    @property
    def vapi_call_id(self) -> str | None:
        value = self.message.call.get("id")
        return str(value) if value else None

    @property
    def caller_number(self) -> str | None:
        customer = self.message.call.get("customer") or {}
        value = customer.get("number") if isinstance(customer, dict) else None
        return str(value) if value else None

    @property
    def assistant_id(self) -> str | None:
        value = self.message.assistant.get("id")
        return str(value) if value else None


class ToolResult(BaseModel):
    tool_call_id: str = Field(serialization_alias="toolCallId")
    result: str


class ToolResponse(BaseModel):
    results: list[ToolResult]

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


def sentence(tool_call_id: str, spoken: str) -> ToolResult:
    return ToolResult(tool_call_id=tool_call_id, result=spoken)
