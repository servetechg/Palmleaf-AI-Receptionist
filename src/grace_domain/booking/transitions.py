"""The booking state machine (booking-write-path.md §4).

There is exactly ONE legal way to change `bookings.state`, and this module is it. The
transition function asserts legality, bumps the optimistic-concurrency version, writes the
audit row, and emits that transition's outbox events — all in the caller's transaction.

Two enforcement layers sit under this, deliberately:

* the database trigger from migration 0015, which rejects a state change with no matching
  `booking_events` row by commit;
* `import-linter`, which stops a handler reaching past the domain to write state directly.

This file is the *pure* half: the table and the legality check, with no I/O, so the rules
can be property-tested exhaustively. The persistence half lives in the repository.
"""

from __future__ import annotations

from typing import Literal, get_args

BookingState = Literal[
    "DRAFT",
    "PENDING_DEPOSIT",
    "CONFIRMED",
    "WRITING_TO_PMS",
    "SYNCED",
    "NEEDS_STAFF",
    "CANCELLED",
    "EXPIRED",
]

ALL_STATES: tuple[BookingState, ...] = get_args(BookingState)

#: Implemented literally from booking-write-path.md §4. Anything absent is illegal.
TRANSITIONS: dict[BookingState, frozenset[BookingState]] = {
    "DRAFT": frozenset({"PENDING_DEPOSIT", "CONFIRMED", "CANCELLED"}),
    "PENDING_DEPOSIT": frozenset({"CONFIRMED", "EXPIRED", "CANCELLED"}),
    "CONFIRMED": frozenset({"WRITING_TO_PMS", "SYNCED", "NEEDS_STAFF", "CANCELLED"}),
    "WRITING_TO_PMS": frozenset({"SYNCED", "NEEDS_STAFF", "CANCELLED"}),
    "NEEDS_STAFF": frozenset({"SYNCED", "CANCELLED"}),
    "SYNCED": frozenset({"CANCELLED"}),
    "CANCELLED": frozenset(),
    "EXPIRED": frozenset(),
}

TERMINAL: frozenset[BookingState] = frozenset({"CANCELLED", "EXPIRED"})

#: What each arrival emits. booking-write-path.md §4.3.
#:
#: The PMS write fires on CONFIRMED — after any deposit is satisfied — and never earlier.
#: Booking someone into the salon's calendar before they have paid the deposit they were
#: told about is a real-world mess, not just a state-machine detail.
EMISSIONS: dict[BookingState, tuple[str, ...]] = {
    "DRAFT": ("calendar.create_event", "sms.send:booking_confirmation"),
    "PENDING_DEPOSIT": ("payments.create_deposit_link", "sms.send:deposit_link"),
    "CONFIRMED": ("sms.send:booking_confirmed", "pms.write_appointment", "calendar.update_event"),
    "WRITING_TO_PMS": (),
    "SYNCED": ("calendar.update_event",),
    "NEEDS_STAFF": ("staff.notify",),
    "CANCELLED": ("calendar.delete_event", "pms.cancel_appointment", "sms.send:cancellation"),
    "EXPIRED": ("calendar.delete_event", "sms.send:slot_released", "staff.notify"),
}


class IllegalTransition(Exception):
    """A state change the machine forbids. Never caught — it is a bug, not a condition."""

    def __init__(self, from_state: BookingState, to_state: BookingState) -> None:
        allowed = ", ".join(sorted(TRANSITIONS[from_state])) or "(terminal)"
        super().__init__(f"{from_state} → {to_state} is not legal; allowed: {allowed}")
        self.from_state = from_state
        self.to_state = to_state


def can_transition(from_state: BookingState, to_state: BookingState) -> bool:
    return to_state in TRANSITIONS[from_state]


def assert_transition(from_state: BookingState, to_state: BookingState) -> None:
    if not can_transition(from_state, to_state):
        raise IllegalTransition(from_state, to_state)


def emissions_for(to_state: BookingState) -> tuple[str, ...]:
    """Outbox event types this arrival must enqueue, in the caller's transaction."""
    return EMISSIONS[to_state]


def is_terminal(state: BookingState) -> bool:
    return state in TERMINAL
