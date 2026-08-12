"""The booking state machine, checked exhaustively (booking-write-path.md §4).

Every state pair is enumerated rather than sampled: there are 64 of them, the table is the
contract, and a typo in it is the kind of bug that only shows up when a real caller's
booking gets stuck.
"""

from __future__ import annotations

import itertools

import pytest

from grace_domain.booking.transitions import (
    ALL_STATES,
    TRANSITIONS,
    BookingState,
    IllegalTransition,
    assert_transition,
    can_transition,
    emissions_for,
    is_terminal,
)


def test_every_state_has_an_entry() -> None:
    """A state absent from the table would raise KeyError at runtime, mid-booking."""
    assert set(TRANSITIONS) == set(ALL_STATES)


@pytest.mark.parametrize(("origin", "target"), list(itertools.product(ALL_STATES, ALL_STATES)))
def test_transition_legality_matches_the_table(origin: BookingState, target: BookingState) -> None:
    expected = target in TRANSITIONS[origin]
    assert can_transition(origin, target) is expected
    if expected:
        assert_transition(origin, target)
    else:
        with pytest.raises(IllegalTransition):
            assert_transition(origin, target)


def test_terminal_states_are_dead_ends() -> None:
    """CANCELLED and EXPIRED never move again — a resurrected booking is a phantom."""
    state: BookingState
    for state in ("CANCELLED", "EXPIRED"):
        assert is_terminal(state)
        assert TRANSITIONS[state] == frozenset()


def test_cancellation_is_reachable_from_every_live_state() -> None:
    """A caller can always cancel. If some state trapped a booking, staff would have to
    edit the database to release the slot."""
    for state in ALL_STATES:
        if is_terminal(state):
            continue
        assert can_transition(state, "CANCELLED"), f"{state} cannot reach CANCELLED"


def test_no_state_transitions_to_itself() -> None:
    for state in ALL_STATES:
        assert state not in TRANSITIONS[state]


def test_draft_cannot_jump_straight_to_synced() -> None:
    """SYNCED means a real appointment exists in the booking system. Reaching it without
    passing CONFIRMED would mean writing to the salon's calendar before the deposit."""
    assert not can_transition("DRAFT", "SYNCED")
    assert not can_transition("DRAFT", "WRITING_TO_PMS")


def test_pms_write_is_emitted_on_confirmed_and_nowhere_else() -> None:
    """The PMS write must not fire before the deposit is satisfied."""
    emitting = [s for s in ALL_STATES if "pms.write_appointment" in emissions_for(s)]
    assert emitting == ["CONFIRMED"]


def test_needs_staff_emits_a_notification() -> None:
    """Track D's promise: automation gave up, so a human is told and the slot stays held."""
    assert "staff.notify" in emissions_for("NEEDS_STAFF")
