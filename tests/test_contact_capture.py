"""Contact capture and channel honesty — the gates that stop invented and unreachable contacts.

Two live failures drive these tests, both from 2026-08-10:

* a web call with no caller ID produced a callback task for `+18479614800`, a number nobody
  had spoken — the model filled the gap rather than asking;
* every booking stored the placeholder `+10000000000`, because the handler read a `phone`
  key that `createBooking`'s schema never offered, so no confirmation could ever arrive.

The rule both express: a contact detail is only usable if a human said it and heard it read
back. Everything else is "we don't have one", never a plausible guess.
"""

from __future__ import annotations

import pytest

from grace_api.handlers import PLACEHOLDER_PHONE, speak_digits
from grace_db.repositories.messaging import Queued, looks_like_email


class TestDigitReadback:
    """A number is only confirmed if the caller can actually check it."""

    def test_digits_are_spoken_individually(self) -> None:
        # "+18475551234" as a number is unverifiable by ear; as digits it is checkable.
        assert speak_digits("+18475551234") == "1 8 4, 7 5 5, 5 1 2, 3 4"

    def test_formatting_characters_are_ignored(self) -> None:
        assert speak_digits("(847) 555-1234") == speak_digits("8475551234")

    def test_empty_number_produces_nothing_to_read_back(self) -> None:
        assert speak_digits("") == ""


class TestEmailSanity:
    """Spoken addresses arrive mangled; obvious rubbish must not be queued."""

    @pytest.mark.parametrize(
        "address",
        ["dana@example.com", "d.ana+tag@mail.co.uk", "DANA@EXAMPLE.COM", "dana@example.com."],
    )
    def test_plausible_addresses_pass(self, address: str) -> None:
        assert looks_like_email(address)

    @pytest.mark.parametrize(
        "address",
        [
            "",
            "   ",
            "dana at example dot com",  # what a transcriber returns for a spoken address
            "dana@example",  # no TLD
            "dana@",
            "@example.com",
            "dana example.com",
            "two words@example.com",
        ],
    )
    def test_rubbish_is_rejected(self, address: str) -> None:
        assert not looks_like_email(address)


class TestQueuedHonesty:
    """What Grace says must match what was actually queued."""

    def test_nothing_queued_is_not_success(self) -> None:
        queued = Queued(sms=False, email=False, degraded_reason="no_contact_method")
        assert not queued.any_queued

    @pytest.mark.parametrize(
        ("sms", "email"),
        [(True, False), (False, True), (True, True)],
    )
    def test_any_channel_counts_as_queued(self, sms: bool, email: bool) -> None:
        assert Queued(sms=sms, email=email, degraded_reason="none").any_queued


def test_placeholder_is_never_a_real_contact() -> None:
    """The old default. If this is ever treated as reachable, confirmations vanish silently."""
    assert PLACEHOLDER_PHONE == "+10000000000"
