"""TR-1 and TR-2: the post-checks on drafted section copy, one case per pattern.

Each pattern is proven both ways: it FIRES on a number the inputs do not hold,
and a sourced control beside it does NOT fire. A detector tested only for
firing would pass if it fired on everything.
"""

from __future__ import annotations

import pytest

from app.howto_generation import section_checks as checks

NO_INPUTS = checks.sourced_numbers([])


def reason(text: str, *, allowed: bool = False, listed: list[str] | None = None,
           inputs: list[str] | None = None) -> str | None:
    return checks.refusal_reason(
        text,
        prices_allowed=allowed,
        listed=checks.listed_price_keys(listed or []),
        sourced=checks.sourced_numbers(inputs or []),
    )


# --- TR-1: prices ----------------------------------------------------------

PRICE_CASES = [
    ("symbol_before", "Drain cleaning from $120."),
    ("symbol_before", "Call-out USD 120 flat."),
    ("symbol_before", "Only €1.200,50 for the full job."),
    ("symbol_before", "A visit is £85."),
    ("symbol_after", "A visit costs 120€."),
    ("symbol_after", "A visit costs 120 dollars."),
    ("symbol_after", "Just 45 cents a day."),
    ("symbol_after", "A visit costs 120 EUR."),
    ("number_words", "It costs twenty dollars."),
    ("percent_off", "Book now for 20% off."),
    ("percent_off", "Save 15% on your first visit."),
]


class TestPricesWhenTheSiteDoesNotAllowThem:
    @pytest.mark.parametrize(("pattern", "text"), PRICE_CASES)
    def test_every_currency_pattern_is_found(self, pattern: str, text: str) -> None:
        found = checks.find_prices(text)
        assert [f.pattern for f in found] == [pattern], text

    @pytest.mark.parametrize(("pattern", "text"), PRICE_CASES)
    def test_every_currency_pattern_refuses_the_field(self, pattern: str, text: str) -> None:
        why = reason(text, allowed=False)
        assert why is not None and "does not allow prices" in why

    def test_a_listed_price_is_still_refused_when_prices_are_off(self) -> None:
        assert reason("From $120.", allowed=False, listed=["$120"]) is not None

    def test_a_range_yields_both_ends(self) -> None:
        keys = [f.key for f in checks.find_prices("$100-$200")]
        assert keys == ["$|100", "$|200"]
        keys = [f.key for f in checks.find_prices("$100 to 200")]
        assert keys == ["$|100", "$|200"]

    def test_CONTROL_copy_with_no_amount_passes(self) -> None:
        assert reason("We clear blocked drains the same day.", allowed=False) is None

    def test_CONTROL_a_bare_count_is_not_a_price(self) -> None:
        assert checks.find_prices("Over 300 customers served.") == []


class TestPricesWhenTheSiteAllowsThem:
    @pytest.mark.parametrize(
        ("text", "listed"),
        [
            ("From $120.", ["$120"]),
            ("From $120.", ["$120.00"]),
            ("From USD 120.", ["$120"]),
            ("From 120 dollars.", ["$120"]),
            ("From $1,200.", ["$1200"]),
            ("From $120.", ["120"]),  # the list gave no currency
            ("Book now for 20% off.", ["20% off first visit"]),
            ("Just 45 cents a day.", ["$0.45"]),
        ],
    )
    def test_a_listed_price_passes(self, text: str, listed: list[str]) -> None:
        assert reason(text, allowed=True, listed=listed) is None

    @pytest.mark.parametrize(
        ("text", "listed"),
        [
            ("From $99.", ["$120"]),
            ("From €120.", ["$120"]),  # same value, different currency
            ("From $100-$200.", ["$100"]),  # one end of the range unlisted
            ("Book now for 25% off.", ["20% off"]),
            ("It costs twenty dollars.", ["$20"]),  # words cannot be compared
            ("From $120.", []),
        ],
    )
    def test_an_unlisted_price_is_refused(self, text: str, listed: list[str]) -> None:
        why = reason(text, allowed=True, listed=listed)
        assert why is not None and "not on the organization's price list" in why

    def test_a_price_in_the_context_does_not_make_it_listed(self) -> None:
        # Only the price list sources a price — a figure in the description
        # is not one the organization chose to publish.
        why = reason("From $99.", allowed=True, listed=["$120"], inputs=["from $99"])
        assert why is not None


# --- TR-2: unsourced numbers ------------------------------------------------

NUMBER_CASES = [
    # (category, pattern, draft text, an input that sources it)
    ("phone", "phone", "Call (555) 123-4567 today.", "Phone: 555-123-4567"),
    ("phone", "phone", "Call +44 20 7946 0958.", "+44 20 7946 0958"),
    ("phone", "phone", "Call 5551234567.", "555.123.4567"),
    ("licence", "licence_keyword", "Lic. #123456 holder.", "License 123456"),
    ("licence", "licence_keyword", "Registration no. 88123.", "registration 88123"),
    ("licence", "licence_acronym", "ABN 12 345 678 901.", "ABN 12345678901"),
    ("licence", "licence_hash", "Contractor #4471.", "contractor 4471"),
    ("licence", "licence_code", "Certified ROC123456.", "ROC 123456"),
    ("address", "street", "Visit us at 12 Main Street.", "12 Main St, Springfield"),
    ("address", "suite", "Find us in Suite 200.", "Suite 200, 4 Elm Rd"),
    ("address", "po_box", "Write to PO Box 77.", "P.O. Box 77"),
    ("address", "zip", "Serving Springfield, IL 62704.", "Springfield, IL 62704"),
    ("address", "uk_postcode", "Find us at SW1A 1AA.", "London SW1A1AA"),
    ("hours", "ampm", "Open from 8am.", "Hours: 8:00 AM to 6 PM"),
    ("hours", "clock", "Open until 17:30.", "closes 17:30"),
    ("hours", "always_open", "We answer 24/7.", "available 24/7"),
    ("hours", "all_day", "A 24-hour line.", "24 hours a day"),
    ("hours", "days_a_week", "Open 7 days a week.", "open 7 days a week"),
]


class TestUnsourcedNumbers:
    @pytest.mark.parametrize(("category", "pattern", "text", "source"), NUMBER_CASES)
    def test_each_pattern_is_found(self, category, pattern, text, source) -> None:
        found = checks.find_numbers(text)
        assert (category, pattern) in [(f.category, f.pattern) for f in found], found

    @pytest.mark.parametrize(("category", "pattern", "text", "source"), NUMBER_CASES)
    def test_each_pattern_refuses_when_the_inputs_do_not_hold_it(
        self, category, pattern, text, source
    ) -> None:
        why = reason(text, allowed=False)
        assert why is not None and "record does not hold" in why

    @pytest.mark.parametrize(("category", "pattern", "text", "source"), NUMBER_CASES)
    def test_CONTROL_each_pattern_passes_when_the_inputs_hold_it(
        self, category, pattern, text, source
    ) -> None:
        assert reason(text, allowed=False, inputs=[source]) is None

    @pytest.mark.parametrize(
        "text",
        [
            "Updated 2026-10-30.",
            "Updated 30.10.2026.",
            "Serving the city 2019-2026.",
            "Over 25 years and 300 customers.",
            "Step 1 is the inspection.",
        ],
    )
    def test_dates_years_and_counts_are_not_flagged(self, text: str) -> None:
        assert checks.find_numbers(text) == []

    def test_a_number_inside_a_bigger_input_number_is_not_sourced(self) -> None:
        # `27` is a substring of the ZIP 62701; equality, not substring, decides.
        why = reason("Visit 27 Main Street.", inputs=["Springfield, IL 62701"])
        assert why is not None

    def test_a_different_phone_is_not_sourced_by_the_real_one(self) -> None:
        assert reason("Call (555) 999-0000.", inputs=["555-123-4567"]) is not None

    def test_a_local_number_does_not_source_an_invented_area_code(self) -> None:
        assert reason("Call (555) 123-4567.", inputs=["call 123-4567"]) is not None

    def test_CONTROL_a_country_code_and_trunk_zero_still_match(self) -> None:
        assert reason("Call 1-555-123-4567.", inputs=["(555) 123-4567"]) is None
        assert reason("Call 020 7946 0958.", inputs=["+44 20 7946 0958"]) is None

    def test_a_different_time_is_not_sourced(self) -> None:
        assert reason("Open from 7am.", inputs=["Hours: 8am to 6pm"]) is not None

    def test_inputs_are_scanned_one_at_a_time(self) -> None:
        # Two separate inputs `555` and `1234567` must not join into a phone.
        why = reason("Call 555 123 4567.", inputs=["555", "123 4567"])
        assert why is not None


# --- review round: currency formats, magnitude, phones, hours ----------------

CURRENCY_FORMATS_MISSED_BEFORE = [
    "a 40-dollar call-out fee",
    "a 40-euro fee",
    "40k dollars",
    "1.5 million dollars",
    "usd 40",
    "eur 40",
    "Usd40",
    "99¢",
    "＄40",  # fullwidth dollar sign
    "₤40",
    "1299 kr",
    "Rs. 500",
    "$.99",
]


class TestCurrencyFormatsWithPricesOff:
    @pytest.mark.parametrize("text", CURRENCY_FORMATS_MISSED_BEFORE)
    def test_each_format_refuses_the_field(self, text: str) -> None:
        why = reason(f"Our rate: {text}.", allowed=False)
        assert why is not None and "does not allow prices" in why, text

    @pytest.mark.parametrize("text", CURRENCY_FORMATS_MISSED_BEFORE)
    def test_each_format_refuses_the_field_standing_alone(self, text: str) -> None:
        assert reason(text, allowed=False) is not None, text

    @pytest.mark.parametrize(
        "text",
        [
            "open 7 days",
            "since 1998",
            "24/7",
            "2 locations",
            "We try 5 different methods.",
            "Over 25 years and 300 customers.",
            "50 percent of our work is repeat business.",
        ],
    )
    def test_CONTROL_these_are_not_prices(self, text: str) -> None:
        # About prices only: `24/7` is still an hours claim, checked elsewhere.
        assert checks.find_prices(text) == [], text

    @pytest.mark.parametrize(
        "text", ["50 percent off", "Save 15 percent today", "20 per cent off", "50％ off"]
    )
    def test_a_percentage_discount_is_a_price_by_the_modules_own_rule(self, text: str) -> None:
        # `percent_off` is a rule of this module (`20% off`, `save 15%`); the
        # spelled-out forms are the same discount and are refused with it.
        assert [f.pattern for f in checks.find_prices(text)] == ["percent_off"], text
        assert reason(text, allowed=False) is not None


class TestMagnitudeWithPricesOn:
    LISTED = ["$40"]

    @pytest.mark.parametrize(
        "text", ["From $40k.", "From $40M.", "From $40 million.", "From $40 thousand.",
                 "From 40k dollars.", "From $40bn."]
    )
    def test_a_scaled_amount_is_not_the_listed_one(self, text: str) -> None:
        why = reason(text, allowed=True, listed=self.LISTED)
        assert why is not None and "not on the organization's price list" in why, text

    @pytest.mark.parametrize("text", ["From $40.", "From 40 dollars.", "From USD 40."])
    def test_CONTROL_the_listed_amount_passes(self, text: str) -> None:
        assert reason(text, allowed=True, listed=self.LISTED) is None, text

    def test_a_listed_scaled_price_matches_its_scaled_draft(self) -> None:
        assert reason("From $40k.", allowed=True, listed=["$40k"]) is None
        assert reason("From $40.", allowed=True, listed=["$40k"]) is not None


class TestPhoneSeparators:
    @pytest.mark.parametrize(
        "text",
        [
            "Call 555–123–4567",  # en dash
            "Call 555‑123‑4567",  # U+2011 non-breaking hyphen
            "Call 555 - 123 - 4567",
            "Text 07700 900123",
        ],
    )
    def test_refused_when_the_inputs_do_not_hold_it(self, text: str) -> None:
        why = reason(text, allowed=False)
        assert why is not None and "a phone number" in why, text

    @pytest.mark.parametrize(
        "text",
        [
            "Call 555–123–4567",
            "Call 555‑123‑4567",
            "Call 555 - 123 - 4567",
            "Text 07700 900123",
        ],
    )
    def test_CONTROL_allowed_when_the_inputs_hold_the_same_number(self, text: str) -> None:
        inputs = [text.split(" ", 1)[1]]
        assert reason(text, allowed=False, inputs=inputs) is None, text

    def test_CONTROL_the_same_number_in_a_different_dash_style_is_the_same_number(self) -> None:
        assert reason("Call 555–123–4567", inputs=["555-123-4567"]) is None
        assert reason("Call 555 - 123 - 4567", inputs=["(555) 123-4567"]) is None

    def test_a_bare_run_of_seven_digits_does_not_source_a_formatted_phone(self) -> None:
        # `ref 5551234` is a reference number, not a phone the record holds.
        assert reason("Call 555-1234", inputs=["ref 5551234"]) is not None

    def test_CONTROL_a_full_unbroken_national_number_still_sources(self) -> None:
        assert reason("Call 555-123-4567", inputs=["5551234567"]) is None


class TestHoursAreKeyedAcrossClocks:
    @pytest.mark.parametrize(
        ("draft", "source"),
        [
            ("Open from 9:00.", "Hours: 9:00 AM to 5:00 PM"),
            ("Closes at 17:00.", "Hours: 9:00 AM to 5:00 PM"),
            ("Open from 9am.", "opens 9:00"),
            ("Closes at 5pm.", "closes 17:00"),
            ("Open from 12:00 PM.", "lunch 12:00"),
        ],
    )
    def test_the_same_time_in_either_form_is_sourced(self, draft: str, source: str) -> None:
        assert reason(draft, inputs=[source]) is None

    @pytest.mark.parametrize(
        ("draft", "source"),
        [
            ("Open from 9:00 PM.", "Hours: 9:00 AM to 5:00 PM"),
            ("Closes at 5:00.", "Hours: 9:00 AM to 5:00 PM"),
            ("Closes at 17:30.", "Hours: 9:00 AM to 5:00 PM"),
        ],
    )
    def test_a_different_time_is_not(self, draft: str, source: str) -> None:
        assert reason(draft, inputs=[source]) is not None
