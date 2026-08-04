"""Tools 12–14: the handoff path.

``transferToHuman`` is NOT here — it is a Vapi ``transferCall`` tool with no
``function`` property and therefore no schema. It is hand-authored at
``platform/vapi/tools/transferToHuman.json`` (doc 08 §7.1).
"""

from __future__ import annotations

from pydantic import Field

from .shared import EscalationReason, PhoneE164, ToolAck, ToolInput, ToolOutput, Urgency

# ── 12. takeMessage ───────────────────────────────────────────────────────────


class TakeMessageInput(ToolInput):
    caller_name: str = Field(min_length=1, max_length=80)
    callback_number: PhoneE164 = Field(
        description=(
            "Number to call back. Default to the number they are calling from unless they "
            "give a different one."
        )
    )
    subject: str = Field(
        min_length=1,
        max_length=120,
        description="One short line: what it is about. NEVER include health or medical detail.",
    )
    body: str = Field(
        default="",
        max_length=600,
        description="Any extra detail the caller gave. Again: no health or medical detail, ever.",
    )


class TaskRef(ToolOutput):
    task_id: str


class TakeMessageOutput(ToolAck):
    data: TaskRef | None = None


# ── 13. flagMedicalHold ───────────────────────────────────────────────────────


class FlagMedicalHoldInput(ToolInput):
    """Invariant I6: this records that a disclosure happened. It records NOTHING about
    what was disclosed. There is deliberately no free-text field — not even an optional
    one, because an optional field is one a model will eventually fill.

    ``bool`` rather than ``Literal[True]``: a single-value literal renders as a scalar
    ``const``, which Vapi rejects. The handler enforces the value.
    """

    disclosed: bool = Field(
        description=(
            "Always pass true. Call this the moment a caller mentions surgery, treatment, "
            "or any health matter. Do NOT ask what it is, and do NOT describe it anywhere."
        )
    )


class MedicalHoldData(ToolOutput):
    task_id: str
    booking_blocked: bool = True


class FlagMedicalHoldOutput(ToolAck):
    data: MedicalHoldData | None = None


# ── 14. flagEscalation ────────────────────────────────────────────────────────


class FlagEscalationInput(ToolInput):
    """Required companion to ``transferToHuman``.

    A ``transferCall`` tool takes no parameters (verified: ``CreateTransferCallToolDTO``
    has no ``function`` property), and the ``transfer-destination-request`` webhook
    payload carries no tool arguments — so this is the ONLY path by which whisper
    context and the staff_tasks row can be created.
    """

    reason: EscalationReason = Field(description="Why you are handing off. Pick the closest match.")
    urgency: Urgency = Field(
        default=Urgency.NORMAL,
        description="Use 'high' only if the caller is upset or the matter is time-critical.",
    )
    summary: str = Field(
        min_length=1,
        max_length=200,
        description=(
            'One sentence of context for the person picking up, e.g. "Caller wants to '
            'dispute a late-cancel fee." NEVER include medical, health, or diagnostic '
            'detail — say "a health matter" instead.'
        ),
    )


class EscalationData(ToolOutput):
    task_id: str
    whisper_primed: bool


class FlagEscalationOutput(ToolAck):
    data: EscalationData | None = None
