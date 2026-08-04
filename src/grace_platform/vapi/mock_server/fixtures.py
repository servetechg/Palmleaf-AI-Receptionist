"""Canned tool responses for local development.

Each returns a SPOKEN SENTENCE — the same contract Core API will honour (doc 04 §5.1):
numbers in spoken form, at most three options, machine data only as an echo-able token.

The clock is frozen via GRACE_MOCK_NOW so dates are reproducible, which is what makes
voice simulations deterministic.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from .speech import chicago_date, speak_date, speak_list, speak_price, speak_time


def now() -> datetime:
    override = os.environ.get("GRACE_MOCK_NOW")
    return (
        datetime.fromisoformat(override.replace("Z", "+00:00")) if override else datetime.now(UTC)
    )


class Service(NamedTuple):
    code: str
    name: str
    price: int
    member: int


SERVICES = (
    Service("massage_60", "60-minute massage", 13500, 11500),
    Service("massage_90", "90-minute massage", 18500, 16000),
    Service("deep_tissue_60", "60-minute deep tissue", 15000, 13000),
)

PROVIDERS = ("Maria", "James")

BUSINESS_INFO = {
    "hours": "We are open Monday through Saturday, nine in the morning until seven in the evening, and closed Sundays.",
    "location": "We are on Dundee Road in Buffalo Grove, just past the Town Center, with parking right out front.",
    "parking": "There is free parking directly in front of the building.",
    "contact": "The best way is right here on this line, or by text to the same number.",
    "services_overview": "We offer therapeutic massage, deep tissue, acupuncture, and cryotherapy.",
    "policies": "Changes and cancellations are free up to forty-eight hours before your appointment.",
    "memberships": "Members get a reduced rate on every service and priority booking.",
}

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _hash(s: str) -> int:
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _slot_id(seed: str) -> str:
    h = _hash(seed)
    return "hold-" + "".join(_ALPHABET[(h >> (i * 5)) % len(_ALPHABET)] for i in range(3))


_bookings: dict[str, dict[str, Any]] = {}


def reset() -> None:
    _bookings.clear()


def get_business_info(a: dict[str, Any], _call: str) -> str:
    return BUSINESS_INFO[a["topic"]]


def lookup_customer(a: dict[str, Any], _call: str) -> str:
    # Even hash → a known member, so both branches are reachable deterministically.
    if _hash(a["phone"]) % 2 == 0:
        return "That number matches Jordan, who has been in four times and is a member."
    return "I do not see that number on file yet."


def get_services_and_pricing(a: dict[str, Any], _call: str) -> str:
    q = a["query"].lower()
    matches = [s for s in SERVICES if q in s.name.lower()] or list(SERVICES)
    member = bool(a.get("isMember"))
    phrases = [
        f"the {s.name} at {speak_price(s.member if member else s.price)}" for s in matches[:3]
    ]
    return f"We have {speak_list(phrases)}."


def check_availability(a: dict[str, Any], call_id: str) -> str:
    pref = a.get("timePreference", "any")
    start = 9 if pref == "morning" else 17 if pref == "evening" else 13
    date = a["preferredDate"]

    slots: list[tuple[datetime, str]] = [
        (chicago_date(date, start + i, 30 if i == 1 else 15), PROVIDERS[i % len(PROVIDERS)])
        for i in range(3)
    ]

    wanted = str(a.get("providerPreference") or "").lower()
    filtered = [s for s in slots if s[1].lower() == wanted] if wanted else slots
    offer = (filtered or slots)[:3]

    phrases = [f"{speak_time(starts)} with {provider}" for starts, provider in offer]
    prefix = (
        f"{a['providerPreference']} isn't available then, but I have "
        if wanted and not filtered
        else "I have "
    )
    return f"{prefix}{speak_list(phrases)} on {speak_date(date)}. Which works?"


def create_booking(a: dict[str, Any], call_id: str) -> str:
    # Server-side medical gate: the prompt is not the only thing enforcing this (I4).
    if not a.get("medicalScreenPassed"):
        return "Before I book, I'd like one of our team to go over a couple of health questions with you."
    ref = "bk-" + _slot_id(f"{call_id}:{a['slotId']}")[5:] + "9"
    starts = now() + timedelta(days=1)
    _bookings[ref.lower()] = {"ref": ref, "starts": starts}
    return (
        f"You're all set, {a['firstName']} — {speak_date(starts)} at {speak_time(starts)} "
        f"with Maria. I'll text you a confirmation."
    )


def reschedule_appointment(a: dict[str, Any], _call: str) -> str:
    if a["bookingRef"].lower() not in _bookings:
        return "I can't find that appointment — let me get someone who can look it up properly."
    starts = chicago_date(a["newDate"], 18, 30)
    return (
        f"Done — I've moved you to {speak_date(starts)} at {speak_time(starts)}. "
        f"There's no charge for that change."
    )


def cancel_appointment(a: dict[str, Any], _call: str) -> str:
    if _bookings.pop(a["bookingRef"].lower(), None) is None:
        return "I can't find that appointment — let me get someone who can look it up properly."
    return (
        "That's cancelled for you. Since it's more than forty-eight hours away, there's no charge."
    )


def take_message(a: dict[str, Any], _call: str) -> str:
    return (
        f"Got it — I've passed that to the team and someone will call you back about "
        f"{a['subject'].lower()}."
    )


def flag_medical_hold(_a: dict[str, Any], _call: str) -> str:
    return (
        "Thanks for telling me — I'd like one of our team to go over that with you before we book."
    )


Fixture = Callable[[dict[str, Any], str], str]

# Async tools: Vapi never delivers these to the model, so the string is for logs only.
FIXTURES: dict[str, Fixture] = {
    "getBusinessInfo": get_business_info,
    "lookupCustomer": lookup_customer,
    "getServicesAndPricing": get_services_and_pricing,
    "checkAvailability": check_availability,
    "createBooking": create_booking,
    "rescheduleAppointment": reschedule_appointment,
    "cancelAppointment": cancel_appointment,
    "sendIntakeForm": lambda _a, _c: "intake form queued",
    "sendDepositLink": lambda _a, _c: "deposit link queued",
    "sendBookingConfirmation": lambda _a, _c: "confirmation queued",
    "takeMessage": take_message,
    "flagMedicalHold": flag_medical_hold,
    "flagEscalation": lambda _a, _c: "escalation logged",
}
