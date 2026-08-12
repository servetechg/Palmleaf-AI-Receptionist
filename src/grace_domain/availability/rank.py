"""Choosing which three slots Grace offers (availability-engine.md §4).

Pure: no I/O, no clock, no database. The SQL returns up to 200 candidates; *which three a
caller hears* is a product decision, and product decisions belong somewhere they can be
unit-tested and argued about without a database.

The commercially interesting signal is calendar packing. A naive "earliest first" engine
fragments the day into unbookable 20-minute gaps and measurably reduces sellable hours;
preferring a slot that leaves no orphan gap is a one-function change with real revenue
impact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

TimePreference = Literal["morning", "afternoon", "evening", "any"]

#: Weights, highest wins. availability-engine.md §4's table, verbatim.
W_REQUESTED_PROVIDER = 200
W_TIME_PREFERENCE = 100
W_PREFERRED_PROVIDER = 60
W_EARLIER_MAX = 30
W_PROFICIENCY_MAX = 20
W_NO_ORPHAN_GAP = 25
W_FIRST_OF_DAY_PENALTY = -10

#: Two offered slots closer than this from the same provider is a bad menu, not a choice.
DIVERSITY_WINDOW = timedelta(minutes=45)

#: Nothing shorter than this can be sold, so a gap under it is orphaned.
SHORTEST_SERVICE_MIN = 60


@dataclass(frozen=True, slots=True)
class Candidate:
    """One free slot as the SQL returned it."""

    provider_id: str
    provider_name: str
    starts_at: datetime
    ends_at: datetime
    proficiency: int = 3


@dataclass(frozen=True, slots=True)
class RankOptions:
    timezone: str = "UTC"
    time_preference: TimePreference = "any"
    requested_provider_name: str | None = None
    preferred_provider_id: str | None = None
    max_slots: int = 3


@dataclass(frozen=True, slots=True)
class RankedSlot:
    candidate: Candidate
    score: int


def _matches_preference(when: datetime, preference: TimePreference, tz: str = "UTC") -> bool:
    """Morning/afternoon/evening are LOCAL to the business, not to UTC."""
    if preference == "any":
        return False  # no preference stated means no bonus, not a bonus for everything
    hour = when.astimezone(ZoneInfo(tz)).hour
    if preference == "morning":
        return hour < 12
    if preference == "afternoon":
        return 12 <= hour < 17
    return hour >= 17


def _leaves_no_orphan_gap(candidate: Candidate, same_provider: list[Candidate]) -> bool:
    """True when this slot butts against another candidate, packing the day.

    Approximate by design: the exact neighbour set is whatever the query returned, which
    is enough to prefer contiguity without a second round-trip.
    """
    for other in same_provider:
        if other is candidate:
            continue
        if other.starts_at == candidate.ends_at or other.ends_at == candidate.starts_at:
            return True
    return False


def score_candidate(
    candidate: Candidate, options: RankOptions, same_provider: list[Candidate]
) -> int:
    score = 0

    if (
        options.requested_provider_name
        and candidate.provider_name.casefold() == options.requested_provider_name.casefold()
    ):
        score += W_REQUESTED_PROVIDER

    if _matches_preference(candidate.starts_at, options.time_preference, options.timezone):
        score += W_TIME_PREFERENCE

    if options.preferred_provider_id and candidate.provider_id == options.preferred_provider_id:
        score += W_PREFERRED_PROVIDER

    # Earlier in the day is generally better: full marks at opening, zero by late evening.
    local = candidate.starts_at.astimezone(ZoneInfo(options.timezone))
    minutes_into_day = local.hour * 60 + local.minute
    span = 12 * 60
    earliness = max(0.0, 1.0 - (max(0, minutes_into_day - 9 * 60) / span))
    score += int(W_EARLIER_MAX * earliness)

    score += int(W_PROFICIENCY_MAX * (max(1, min(5, candidate.proficiency)) - 1) / 4)

    if _leaves_no_orphan_gap(candidate, same_provider):
        score += W_NO_ORPHAN_GAP

    earliest_for_provider = min((c.starts_at for c in same_provider), default=candidate.starts_at)
    if candidate.starts_at == earliest_for_provider and len(same_provider) > 1:
        score += W_FIRST_OF_DAY_PENALTY

    return score


def rank_slots(candidates: list[Candidate], options: RankOptions) -> list[RankedSlot]:
    """Score, sort, then diversify. Returns at most ``options.max_slots``.

    Diversification runs *after* scoring rather than as part of it: three slots from one
    provider inside 45 minutes is a bad menu even when all three score well, and that is a
    property of the set, not of any single slot.
    """
    by_provider: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        by_provider.setdefault(candidate.provider_id, []).append(candidate)

    scored = [
        RankedSlot(candidate=c, score=score_candidate(c, options, by_provider[c.provider_id]))
        for c in candidates
    ]
    # Ties break on the earlier slot, so the order is total and the output deterministic.
    scored.sort(key=lambda s: (-s.score, s.candidate.starts_at, s.candidate.provider_id))

    chosen: list[RankedSlot] = []
    for slot in scored:
        if len(chosen) >= options.max_slots:
            break
        # Spread across TIME first, providers second (§4). Two therapists at the identical
        # hour gives the caller no choice of when — only of whom — and burns an offer slot.
        same_time = any(picked.candidate.starts_at == slot.candidate.starts_at for picked in chosen)
        too_close = any(
            picked.candidate.provider_id == slot.candidate.provider_id
            and abs(picked.candidate.starts_at - slot.candidate.starts_at) < DIVERSITY_WINDOW
            for picked in chosen
        )
        if not same_time and not too_close:
            chosen.append(slot)

    # Deliberately NO padding pass. A thin day returns two slots, or one, and that is the
    # correct answer — back-filling with a slot diversification just rejected would undo
    # the rule in the name of hitting a count, and "nine, nine fifteen, nine thirty with
    # Maria" is a worse menu than "nine with Maria, or two with James".
    return chosen
