"""Spoken-English formatters (doc 04 §5.2).

These move into the Core API formatters package unchanged when it lands — the phrasing
work is not throwaway. All pure functions, all unit-testable.

Timezone rule: a bare ``YYYY-MM-DD`` from the model means a **Chicago** calendar date, not
UTC. Parsing it as UTC yields the *previous* day in Chicago — an off-by-one that had Grace
confidently saying the wrong weekday. Always go through :func:`chicago_date`.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")

UNITS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)  # fmt: skip

TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _under_hundred(n: int, hyphen: bool) -> str:
    """0–99 in words. ``hyphen`` joins tens and units the way prices read: 'thirty-five'."""
    if n < 20:
        return UNITS[n]
    tens, unit = TENS[n // 10], n % 10
    if unit == 0:
        return tens
    return f"{tens}-{UNITS[unit]}" if hyphen else f"{tens} {UNITS[unit]}"


def chicago_date(ymd: str, hour: int = 12, minute: int = 0) -> datetime:
    """Builds a Chicago wall-clock datetime. ``zoneinfo`` handles CST/CDT itself."""
    y, m, d = (int(p) for p in ymd.split("-"))
    return datetime(y, m, d, hour, minute, tzinfo=TZ)


def _as_chicago(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(TZ)
    if len(value) == 10 and value.count("-") == 2:
        return chicago_date(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)


def speak_time(value: str | datetime) -> str:
    """'2:15 PM' → 'two fifteen'. Never '14:15'."""
    dt = _as_chicago(value)
    hour12 = dt.hour % 12 or 12
    minute = dt.minute
    h = UNITS[hour12]
    if minute == 0:
        return h
    if minute < 10:
        return f"{h} oh {UNITS[minute]}"
    # Hyphenated, matching speak_price — TTS renders both identically, so pick one and be
    # consistent rather than having two conventions in the same sentence.
    return f"{h} {_under_hundred(minute, hyphen=True)}"


_ORDINAL_IRREGULAR = {
    1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth",
    12: "twelfth", 20: "twentieth", 30: "thirtieth",
}  # fmt: skip


def _ordinal(n: int) -> str:
    if n in _ORDINAL_IRREGULAR:
        return _ORDINAL_IRREGULAR[n]
    if n < 20:
        return f"{UNITS[n]}th"
    tens, unit = (n // 10) * 10, n % 10
    if unit == 0:
        return _ORDINAL_IRREGULAR.get(tens, f"{TENS[tens // 10]}th")
    return f"{TENS[tens // 10]}-{_ORDINAL_IRREGULAR.get(unit, f'{UNITS[unit]}th')}"


def speak_date(value: str | datetime) -> str:
    """'2026-08-04' → 'Tuesday the fourth'."""
    dt = _as_chicago(value)
    return f"{dt.strftime('%A')} the {_ordinal(dt.day)}"


def speak_price(cents: int) -> str:
    """13500 → 'one thirty-five'. 11500 → 'one fifteen'. 9900 → 'ninety-nine'."""
    dollars, rem = divmod(cents, 100)

    if dollars < 100:
        spoken = _under_hundred(dollars, hyphen=True)
    else:
        hundreds, rest = divmod(dollars, 100)
        h = UNITS[hundreds]
        if rest == 0:
            spoken = f"{h} hundred"
        elif rest < 10:
            spoken = f"{h} oh {UNITS[rest]}"
        else:
            # "one thirty-five", not "one hundred and thirty-five" — how a price is said.
            spoken = f"{h} {_under_hundred(rest, hyphen=True)}"

    return spoken if rem == 0 else f"{spoken} {_under_hundred(rem, hyphen=True)}"


def speak_list(items: list[str]) -> str:
    """Joins at most three options the way a person would say them."""
    three = items[:3]
    if not three:
        return ""
    if len(three) == 1:
        return three[0]
    if len(three) == 2:
        return f"{three[0]} or {three[1]}"
    return f"{three[0]}, {three[1]}, or {three[2]}"
