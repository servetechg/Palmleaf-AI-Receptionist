"""Grace tool contracts.

Pydantic models for the 13 Vapi function tools, plus the Vapi wire envelope. This package
is the single source that generates the tool definitions sent to Vapi, the prompt's tool
table, and the runtime validation used by the mock server (and later by Core API).

Zero dependencies beyond pydantic.
"""

from .tools.registry import (
    HAND_AUTHORED_TOOLS,
    TOOL_NAMES,
    TOOL_REGISTRY,
    TOTAL_TOOL_COUNT,
    ToolSpec,
    get_tool_spec,
)
from .vapi.envelope import (
    TransferDestination,
    TransferDestinationResponse,
    TransferFallbackPlan,
    TransferPlan,
    TransferPlanMode,
    VapiEventPayload,
    VapiServerMessageType,
    VapiToolCallsPayload,
    VapiToolResponse,
    VapiToolResult,
    parse_tool_arguments,
)

__all__ = [
    "HAND_AUTHORED_TOOLS",
    "TOOL_NAMES",
    "TOOL_REGISTRY",
    "TOTAL_TOOL_COUNT",
    "ToolSpec",
    "TransferDestination",
    "TransferDestinationResponse",
    "TransferFallbackPlan",
    "TransferPlan",
    "TransferPlanMode",
    "VapiEventPayload",
    "VapiServerMessageType",
    "VapiToolCallsPayload",
    "VapiToolResponse",
    "VapiToolResult",
    "get_tool_spec",
    "parse_tool_arguments",
]
