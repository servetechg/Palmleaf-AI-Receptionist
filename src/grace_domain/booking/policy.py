"""Cancellation and change fees — pure, so the money rule is testable.

booking-write-path.md §6, and invariant I4: **never let the model compute the 48-hour
boundary.** A language model asked "is Thursday within 48 hours of Tuesday" will usually be
right, and usually is not a standard for someone's money.

**The published policy wins.** palmleafmassage.com (8 August 2026) states that a change or
cancellation inside 48 hours "are considered a late cancellation and are subject to the
full session fee (100% of the scheduled service)", and that no-shows are charged the same.
The onboarding questionnaire gave two different answers — one said full charge, one said
the Room Reservation Deposit is forfeited — so the website, which the caller has already
read, is what Grace quotes.

⚠️ Confirm with PalmLeaf before the first real cancellation: on a sixty-minute session this
is the difference between a fifty-dollar deposit and a hundred and fifteen dollar fee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

#: The client's window. Lives here, not in a prompt, and not in the model's head.
CANCELLATION_WINDOW = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class FeeDecision:
    fee_cents: int
    reason: str  # inside_48h | outside_48h | waived | policy_unapproved
    spoken: str

    @property
    def charged(self) -> bool:
        return self.fee_cents > 0


def evaluate_change(
    *,
    starts_at: datetime,
    now: datetime,
    price_cents: int,
    is_reschedule: bool,
    policy_approved: bool = True,
) -> FeeDecision:
    """What this change costs. One function, one rule, both paths tested.

    An unapproved policy returns a fee of zero AND a reason that tells the handler to hand
    over — quoting a fee the client never signed off is exactly the failure the approval
    gate exists to prevent.
    """
    if not policy_approved:
        return FeeDecision(
            fee_cents=0,
            reason="policy_unapproved",
            spoken="Let me get someone who can confirm that for you.",
        )

    word = "moving" if is_reschedule else "cancelling"

    if starts_at - now >= CANCELLATION_WINDOW:
        return FeeDecision(
            fee_cents=0,
            reason="outside_48h",
            spoken=f"That's more than forty-eight hours away, so there's no charge for {word} it.",
        )

    if price_cents <= 0:
        # Inside the window but the session has no price on file. Inventing a charge is
        # worse than collecting none — and a zero-priced service is a data fault to fix,
        # not a caller to bill.
        return FeeDecision(
            fee_cents=0,
            reason="waived",
            spoken=f"That's inside forty-eight hours, but there's nothing to charge for {word} it.",
        )

    dollars = price_cents // 100
    return FeeDecision(
        fee_cents=price_cents,
        reason="inside_48h",
        spoken=(
            f"That's inside forty-eight hours, so it's charged at the full session fee — "
            f"{dollars} dollars. Would you like me to go ahead?"
        ),
    )
