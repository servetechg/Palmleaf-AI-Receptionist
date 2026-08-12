"""Ranking, freshness and slot ids — the pure half of the availability engine."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from grace_domain.availability.freshness import (
    DEFAULT_MAX_AGE,
    Freshness,
    evaluate,
)
from grace_domain.availability.rank import Candidate, RankOptions, rank_slots
from grace_domain.booking.slot_id import booking_ref, idempotency_key, public_slot_id

DAY = datetime(2026, 9, 1, tzinfo=UTC)


def slot(hour: int, provider: str = "p1", name: str = "Maria", prof: int = 3) -> Candidate:
    starts = DAY.replace(hour=hour)
    return Candidate(
        provider_id=provider,
        provider_name=name,
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
        proficiency=prof,
    )


# ── ranking ──────────────────────────────────────────────────────────────────────


def test_requested_provider_outranks_everything_else() -> None:
    """Asking for someone by name is the strongest signal a caller can give."""
    ranked = rank_slots(
        [slot(9, "p1", "Maria"), slot(17, "p2", "James")],
        RankOptions(requested_provider_name="James", max_slots=1),
    )
    assert ranked[0].candidate.provider_name == "James"


def test_time_preference_is_honoured() -> None:
    ranked = rank_slots(
        [slot(9, "p1", "Maria"), slot(18, "p2", "James")],
        RankOptions(time_preference="evening", max_slots=1),
    )
    assert ranked[0].candidate.starts_at.hour == 18


def test_never_three_slots_from_one_provider_inside_45_minutes() -> None:
    """Three near-identical times from one therapist is a bad menu, however it scores."""
    crowded = [
        Candidate("p1", "Maria", DAY.replace(hour=9), DAY.replace(hour=10)),
        Candidate("p1", "Maria", DAY.replace(hour=9, minute=15), DAY.replace(hour=10, minute=15)),
        Candidate("p1", "Maria", DAY.replace(hour=9, minute=30), DAY.replace(hour=10, minute=30)),
        Candidate("p2", "James", DAY.replace(hour=14), DAY.replace(hour=15)),
    ]
    ranked = rank_slots(crowded, RankOptions(max_slots=3))
    starts = [r.candidate.starts_at for r in ranked if r.candidate.provider_id == "p1"]
    for a, b in itertools.pairwise(starts):
        assert abs(b - a) >= timedelta(minutes=45)


def test_returns_at_most_max_slots_and_is_deterministic() -> None:
    candidates = [slot(h, f"p{h % 2}", "Maria" if h % 2 else "James") for h in range(9, 18)]
    first = rank_slots(candidates, RankOptions(max_slots=3))
    second = rank_slots(candidates, RankOptions(max_slots=3))
    assert len(first) == 3
    assert [r.candidate.starts_at for r in first] == [r.candidate.starts_at for r in second]


def test_thin_day_returns_what_exists_rather_than_padding() -> None:
    ranked = rank_slots([slot(9)], RankOptions(max_slots=3))
    assert len(ranked) == 1


# ── freshness gate ───────────────────────────────────────────────────────────────


def test_never_synced_is_not_usable() -> None:
    """The dangerous case: no sync has ever run, so the calendar looks entirely free."""
    verdict = evaluate(None, now=DAY)
    assert not verdict.usable
    assert "never synced" in (verdict.reason or "")


def test_stale_mirror_is_not_usable() -> None:
    verdict = evaluate(DAY - DEFAULT_MAX_AGE - timedelta(minutes=1), now=DAY)
    assert not verdict.usable
    assert "past the" in (verdict.reason or "")


def test_fresh_mirror_is_usable() -> None:
    verdict = evaluate(DAY - timedelta(minutes=5), now=DAY)
    assert verdict.usable and verdict.reason is None


def test_empty_mirror_is_refused_even_when_recently_synced() -> None:
    """A fresh sync that returned nothing looks identical to a free calendar."""
    verdict = evaluate(DAY - timedelta(minutes=1), now=DAY, mirror_has_rows=False)
    assert not verdict.usable
    assert "empty" in (verdict.reason or "")


def test_fallback_sentence_never_invents_availability() -> None:
    spoken = Freshness(usable=False).spoken_fallback
    assert "trouble reaching the schedule" in spoken
    assert "someone" in spoken


# ── public ids ───────────────────────────────────────────────────────────────────


def test_slot_ids_are_deterministic_and_contract_shaped() -> None:
    import re

    generated = public_slot_id("3f7c1a5e-0000-4000-8000-000000000001")
    assert generated == public_slot_id("3f7c1a5e-0000-4000-8000-000000000001")
    assert re.match(r"^[Hh][Oo][Ll][Dd]-[0-9A-Za-z]{3,6}$", generated)


def test_booking_refs_match_the_contract_pattern() -> None:
    import re

    assert re.match(r"^[Bb][Kk]-[0-9A-Za-z]{4,8}$", booking_ref("a-booking-id"))


def test_slot_ids_avoid_characters_that_are_misheard() -> None:
    """I, L, O and U are dropped precisely because a caller repeating an id gets them wrong."""
    for seed in range(200):
        body = public_slot_id(f"id-{seed}").removeprefix("hold-")
        assert not (set(body) & set("ILOU"))


def test_idempotency_key_collapses_a_repeated_booking_for_the_same_slot() -> None:
    """Invariant I3: a Vapi retry and a chatty model are the same problem to the database."""
    assert idempotency_key("call-1", "hold-7K2") == idempotency_key("call-1", "hold-7K2")
    assert idempotency_key("call-1", "hold-7K2") != idempotency_key("call-1", "hold-9AB")
