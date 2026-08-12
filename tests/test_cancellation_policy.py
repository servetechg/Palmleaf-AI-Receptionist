"""The 48-hour rule — the one calculation that decides real money.

Invariant I4: never let the model compute this boundary. These tests are why that rule can
be kept — the arithmetic lives in one pure function with the edges pinned down.

The published policy (palmleafmassage.com, 8 August 2026): a change or cancellation inside
48 hours is charged the FULL session fee, and so is a no-show.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from grace_domain.booking.policy import CANCELLATION_WINDOW, evaluate_change

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
SESSION = 11500  # a 60-minute massage, $115 (palmleafmassage.com)


def at(offset: timedelta) -> datetime:
    return NOW + offset


def test_outside_the_window_is_free() -> None:
    d = evaluate_change(
        starts_at=at(timedelta(hours=49)), now=NOW, price_cents=SESSION, is_reschedule=False
    )
    assert d.fee_cents == 0
    assert d.reason == "outside_48h"
    assert "no charge" in d.spoken


def test_inside_the_window_forfeits_the_deposit() -> None:
    d = evaluate_change(
        starts_at=at(timedelta(hours=47)), now=NOW, price_cents=SESSION, is_reschedule=False
    )
    assert d.fee_cents == SESSION
    assert d.reason == "inside_48h"
    assert "115 dollars" in d.spoken and "full session fee" in d.spoken


def test_exactly_forty_eight_hours_is_free() -> None:
    """The boundary itself. A caller at exactly 48 hours has met the policy — charging
    them would be defensible to nobody, least of all at the front desk."""
    d = evaluate_change(
        starts_at=at(CANCELLATION_WINDOW), now=NOW, price_cents=SESSION, is_reschedule=False
    )
    assert d.fee_cents == 0
    assert d.reason == "outside_48h"


def test_one_second_inside_the_boundary_charges() -> None:
    d = evaluate_change(
        starts_at=at(CANCELLATION_WINDOW - timedelta(seconds=1)),
        now=NOW,
        price_cents=SESSION,
        is_reschedule=False,
    )
    assert d.fee_cents == SESSION


def test_no_deposit_means_nothing_to_forfeit() -> None:
    """A session with no price on file is a data fault, not a caller to bill."""
    d = evaluate_change(
        starts_at=at(timedelta(hours=2)), now=NOW, price_cents=0, is_reschedule=False
    )
    assert d.fee_cents == 0
    assert d.reason == "waived"


def test_unapproved_policy_never_quotes_a_fee() -> None:
    """GATE-02. Quoting a fee the client never signed off is the exact failure the
    approval gate exists to prevent."""
    d = evaluate_change(
        starts_at=at(timedelta(hours=1)),
        now=NOW,
        price_cents=SESSION,
        is_reschedule=False,
        policy_approved=False,
    )
    assert d.fee_cents == 0
    assert d.reason == "policy_unapproved"
    assert "someone" in d.spoken


@pytest.mark.parametrize("is_reschedule", [True, False])
def test_reschedule_and_cancel_share_the_same_boundary(is_reschedule: bool) -> None:
    """The client's policy names both in one sentence; they must not drift apart."""
    inside = evaluate_change(
        starts_at=at(timedelta(hours=10)),
        now=NOW,
        price_cents=SESSION,
        is_reschedule=is_reschedule,
    )
    outside = evaluate_change(
        starts_at=at(timedelta(days=5)),
        now=NOW,
        price_cents=SESSION,
        is_reschedule=is_reschedule,
    )
    assert inside.fee_cents == SESSION
    assert outside.fee_cents == 0


def test_spoken_fee_never_contains_digits_with_cents() -> None:
    """Everything here is read aloud. "$50.00" becomes "fifty dollars zero zero"."""
    d = evaluate_change(
        starts_at=at(timedelta(hours=1)), now=NOW, price_cents=SESSION, is_reschedule=False
    )
    assert "$" not in d.spoken
    assert ".00" not in d.spoken
