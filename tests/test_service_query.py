"""Open-ended service questions must reach the whole catalogue (handlers.normalise_service_query).

Regression cover for a live call on 2026-08-10: asked "can you tell me about your services?",
the model sent ``query="services"``, which matched no service and made Grace say "I don't have
that one on our list" — the entire catalogue reported as not offered, followed by an escalation.

The two directions matter equally. An open-ended ask must collapse to the empty query that
``search_services`` treats as "list everything"; a specific ask must KEEP its words, so that a
service we genuinely do not offer still gets an honest no rather than the massage menu.
"""

from __future__ import annotations

import pytest

from grace_api.handlers import normalise_service_query


@pytest.mark.parametrize(
    "raw",
    [
        "services",
        "Services",
        "service",
        "pricing",
        "prices",
        "what do you offer",
        "tell me about your services",
        "can you tell me about your services?",
        "what treatments do you have",
        "what are your options",
        "everything",
        "",
        "   ",
        None,
    ],
)
def test_open_ended_asks_collapse_to_the_whole_catalogue(raw: object) -> None:
    assert normalise_service_query(raw) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("deep tissue", "deep tissue"),
        ("Deep Tissue", "deep tissue"),
        ("acupuncture", "acupuncture"),
        ("prenatal", "prenatal"),
        # Catalogue-wide nouns drop out, the service word survives.
        ("what massage services do you offer", "massage"),
        ("how much for a deep tissue massage", "deep tissue massage"),
    ],
)
def test_specific_asks_keep_the_words_that_name_a_service(raw: str, expected: str) -> None:
    assert normalise_service_query(raw) == expected


def test_a_service_we_do_not_offer_is_still_a_specific_query() -> None:
    """The grounding rule (I2) depends on this staying non-empty.

    If "acupuncture" normalised to "", Grace would answer a question about a service we do
    not provide with the full massage menu — inventing an offer by omission.
    """
    assert normalise_service_query("do you do acupuncture") == "acupuncture"
