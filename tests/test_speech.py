"""Locks the doc 04 §5.2 speech conventions.

Every case here is something a caller would actually hear, and several are regressions
found by running the mock server.
"""

from __future__ import annotations

from grace_platform.vapi.mock_server.speech import (
    chicago_date,
    speak_date,
    speak_list,
    speak_price,
    speak_time,
)


class TestSpeakTime:
    def test_hour_alone_on_the_hour(self) -> None:
        assert speak_time(chicago_date("2026-08-04", 14, 0)) == "two"

    def test_minutes_past_ten(self) -> None:
        assert speak_time(chicago_date("2026-08-04", 14, 15)) == "two fifteen"
        assert speak_time(chicago_date("2026-08-04", 18, 30)) == "six thirty"
        assert speak_time(chicago_date("2026-08-04", 17, 45)) == "five forty-five"

    def test_oh_for_single_digit_minutes(self) -> None:
        assert speak_time(chicago_date("2026-08-04", 9, 5)) == "nine oh five"

    def test_noon_and_midnight_are_twelve_not_zero(self) -> None:
        assert speak_time(chicago_date("2026-08-04", 12, 0)) == "twelve"
        assert speak_time(chicago_date("2026-08-04", 0, 30)) == "twelve thirty"


class TestSpeakDate:
    def test_bare_date_is_chicago_not_utc(self) -> None:
        """Regression: parsing '2026-08-04' as UTC midnight renders as Aug 3 in Chicago.

        The mock server said "Monday the third" for a Tuesday before chicago_date existed.
        """
        assert speak_date("2026-08-04") == "Tuesday the fourth"

    def test_irregular_ordinals(self) -> None:
        assert speak_date("2026-08-01") == "Saturday the first"
        assert speak_date("2026-08-02") == "Sunday the second"
        assert speak_date("2026-08-03") == "Monday the third"
        assert speak_date("2026-08-05") == "Wednesday the fifth"
        assert speak_date("2026-08-09") == "Sunday the ninth"
        assert speak_date("2026-08-12") == "Wednesday the twelfth"

    def test_twenties_and_thirties(self) -> None:
        assert speak_date("2026-08-20") == "Thursday the twentieth"
        assert speak_date("2026-08-21") == "Friday the twenty-first"
        assert speak_date("2026-08-23") == "Sunday the twenty-third"
        assert speak_date("2026-08-31") == "Monday the thirty-first"


class TestSpeakPrice:
    def test_how_a_receptionist_says_a_price(self) -> None:
        assert speak_price(13500) == "one thirty-five"
        assert speak_price(18500) == "one eighty-five"
        assert speak_price(15000) == "one fifty"

    def test_teens_in_the_hundreds(self) -> None:
        """Regression: the tens table had no entry below 20, so 11500 was 'one 10-five'."""
        assert speak_price(11500) == "one fifteen"
        assert speak_price(11000) == "one ten"
        assert speak_price(11900) == "one nineteen"

    def test_two_digit_prices(self) -> None:
        assert speak_price(9900) == "ninety-nine"
        assert speak_price(4500) == "forty-five"
        assert speak_price(800) == "eight"

    def test_oh_for_single_digit_remainder(self) -> None:
        assert speak_price(10500) == "one oh five"
        assert speak_price(20000) == "two hundred"

    def test_cents_only_when_non_zero(self) -> None:
        assert speak_price(13550) == "one thirty-five fifty"
        assert speak_price(13500) == "one thirty-five"


class TestSpeakList:
    def test_never_more_than_three(self) -> None:
        assert speak_list(["a", "b", "c", "d", "e"]) == "a, b, or c"

    def test_joins_naturally(self) -> None:
        assert speak_list(["a"]) == "a"
        assert speak_list(["a", "b"]) == "a or b"
        assert speak_list([]) == ""
