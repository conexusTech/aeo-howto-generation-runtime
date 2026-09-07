"""HOW-4.2 — localization slots.

Every test here maps to one of the three acceptance criteria:

- no slot renders a placeholder or an invented value
- a missing input omits the section rather than fabricating it
- pricing never appears without a source field
"""

from __future__ import annotations

import pytest

from app.howto_generation.contracts import TemplateSlot
from app.howto_generation.slots import (
    PRICING_SLOTS,
    derive_city,
    inputs_used,
    resolve_slots,
)


def slot(name: str, required: bool = False) -> TemplateSlot:
    return TemplateSlot(name=name, description=None, required=required)


CONTEXT = {
    "context_version": "2026-09-03T10:00:00Z",
    "organization": {
        "id": "org-1",
        "name": "Auto Care Guy",
        "industry": "auto repair",
        "address": "412 Kirkwood Ave, Springfield, IL 62701, USA",
        "website": "https://autocareguy.com",
        "founded_year": 1998,
    },
    "geography": {"home_markets": ["Springfield", "Chatham"]},
}


class TestResolvesFromOrgData:
    def test_shop_name_comes_from_the_organization_record(self) -> None:
        result = resolve_slots([slot("shop_name")], CONTEXT)
        assert result.resolved["shop_name"] == "Auto Care Guy"
        assert result.provenance["shop_name"] == "organization.name"

    def test_aliases_resolve_to_the_same_value(self) -> None:
        # A template author writing `company_name` and one writing `shop_name`
        # must get the same value; the alternative is one of them silently
        # getting nothing and the section vanishing for no visible reason.
        for alias in ("shop_name", "company_name", "business_name", "org_name"):
            result = resolve_slots([slot(alias)], CONTEXT)
            assert result.resolved[alias] == "Auto Care Guy"

    def test_service_area_reads_the_geography_blob(self) -> None:
        result = resolve_slots([slot("service_area")], CONTEXT)
        assert result.resolved["service_area"] == "Springfield, Chatham"
        assert result.provenance["service_area"] == "geography.home_markets"

    def test_service_area_deduplicates_while_keeping_order(self) -> None:
        context = {"geography": {"home_markets": ["Chatham", "Springfield", "Chatham"]}}
        result = resolve_slots([slot("service_area")], context)
        assert result.resolved["service_area"] == "Chatham, Springfield"

    def test_service_area_reads_markets_given_as_objects(self) -> None:
        # The geography blob is unvalidated passthrough on the gateway side, so
        # its interior shape has never been checked by anything.
        context = {"geography": {"home_markets": [{"name": "Springfield"}]}}
        result = resolve_slots([slot("service_area")], context)
        assert result.resolved["service_area"] == "Springfield"


class TestOmitsRatherThanFabricates:
    def test_a_missing_field_omits_the_slot(self) -> None:
        result = resolve_slots([slot("shop_name")], {"organization": {}})
        assert result.omitted == ["shop_name"]
        assert "shop_name" not in result.resolved

    def test_an_empty_string_is_not_a_value(self) -> None:
        result = resolve_slots([slot("shop_name")], {"organization": {"name": "   "}})
        assert result.omitted == ["shop_name"]

    def test_a_non_string_field_is_never_coerced(self) -> None:
        # `str(None)` is the literal "None", and this is how that reaches a
        # published article as copy.
        result = resolve_slots([slot("shop_name")], {"organization": {"name": None}})
        assert result.omitted == ["shop_name"]
        assert "None" not in result.resolved.values()

    def test_an_unrecognised_slot_is_omitted_not_guessed(self) -> None:
        result = resolve_slots([slot("warranty_terms")], CONTEXT)
        assert result.omitted == ["warranty_terms"]

    def test_a_slot_the_context_has_no_field_for_is_omitted(self) -> None:
        # CTAs are named as a slot by HOW-4.2 and the runtime-context payload
        # carries no CTA field at all, so every org omits this one.
        result = resolve_slots([slot("cta"), slot("phone")], CONTEXT)
        assert set(result.omitted) == {"cta", "phone"}

    def test_no_resolved_value_is_ever_blank(self) -> None:
        # The general form of the criterion: whatever comes back, nothing
        # resolved is a placeholder or an empty string.
        every_slot = [
            slot(name)
            for name in (
                "shop_name",
                "city",
                "service_area",
                "cta",
                "industry",
                "website",
                "warranty_terms",
            )
        ]
        result = resolve_slots(every_slot, CONTEXT)
        for name, value in result.resolved.items():
            assert value.strip(), f"{name} resolved to blank"
            assert "{{" not in value and "}}" not in value


class TestPricingIsRefused:
    def test_every_pricing_slot_is_refused(self) -> None:
        for name in sorted(PRICING_SLOTS):
            result = resolve_slots([slot(name)], CONTEXT)
            assert name in result.refused, name
            assert name not in result.resolved

    def test_pricing_is_refused_even_when_a_plausible_field_sits_nearby(self) -> None:
        # `pricing_model` is a BILLING model ("subscription"), not an amount.
        # It is the field somebody would reach for, so the refusal has to hold
        # with it present, not merely when the context is empty.
        context = {
            **CONTEXT,
            "products_services": [
                {"name": "Timing belt replacement", "pricing_model": "one-time"}
            ],
        }
        result = resolve_slots([slot("price_band")], context)
        assert "price_band" in result.refused
        assert "one-time" not in str(result.resolved)

    def test_a_refusal_says_why(self) -> None:
        result = resolve_slots([slot("pricing")], CONTEXT)
        assert "pricing" in result.refused["pricing"].lower()

    def test_a_required_pricing_slot_is_still_refused(self) -> None:
        # `required` is the template author's assertion, not an override. A
        # template that requires a price is a template that cannot be
        # materialized, which is the correct outcome and not this module's
        # problem to work around.
        result = resolve_slots([slot("price", required=True)], CONTEXT)
        assert "price" in result.refused


class TestDeriveCity:
    def test_a_well_formed_address_yields_the_city(self) -> None:
        assert derive_city("412 Kirkwood Ave, Springfield, IL 62701, USA") == "Springfield"

    def test_the_country_is_never_mistaken_for_the_city(self) -> None:
        assert derive_city("1 High St, Bath, Somerset, United Kingdom") != "United Kingdom"

    def test_a_bare_street_yields_nothing(self) -> None:
        assert derive_city("412 Kirkwood Ave") is None
        assert derive_city("Main Street") is None

    def test_a_business_name_is_never_returned_as_a_city(self) -> None:
        # The first component is discarded unread precisely for this case.
        assert derive_city("Acme Auto, 123 Main St") is None

    def test_an_ambiguous_address_yields_nothing(self) -> None:
        # Two plausible candidates means the format is not one we recognise,
        # and choosing between them would be a well-formed invented value.
        assert derive_city("123 Main St, Springfield, Chatham") is None

    def test_blank_input_yields_nothing(self) -> None:
        assert derive_city(None) is None
        assert derive_city("") is None
        assert derive_city("   ") is None

    def test_a_derived_value_is_marked_as_derived(self) -> None:
        # The provenance prefix is what lets a reviewer tell an inferred city
        # from one read out of a field.
        result = resolve_slots([slot("city")], CONTEXT)
        assert result.resolved["city"] == "Springfield"
        assert result.provenance["city"].startswith("derived:")


class TestAudit:
    def test_inputs_used_lists_only_what_was_read(self) -> None:
        result = resolve_slots([slot("shop_name"), slot("cta")], CONTEXT)
        assert inputs_used(result) == ["organization.name"]

    def test_inputs_used_is_sorted_and_deduplicated(self) -> None:
        result = resolve_slots(
            [slot("shop_name"), slot("company_name"), slot("website")], CONTEXT
        )
        used = inputs_used(result)
        assert used == sorted(used)
        assert len(used) == len(set(used))

class TestDeriveCityWorksFromTheRight:
    """🔴 Regression cover for three defects measured on real org data.

    `derive_city` used to discard the FIRST comma component unread, assuming a
    street or venue name. That is correct only when a street exists. Measured
    across every org holding a location (2026-09-07), two of three were wrong:

        "Colorado Springs, CO"  -> None        (the city, discarded as a street)
        "Widefield, Colorado"   -> "Colorado"  (the REGION, as the city)

    The second is the serious one: it publishes a wrong locality rather than
    omitting one, which the function's own docblock promised could not happen.
    """

    @pytest.mark.parametrize(
        "address,expected",
        [
            # Two components — no street. The first IS the city.
            ("Colorado Springs, CO", "Colorado Springs"),
            ("Grand Rapids, MI", "Grand Rapids"),
            # …and with the region spelled out rather than coded.
            ("Widefield, Colorado", "Widefield"),
            ("Nashville, Tennessee", "Nashville"),
            ("Toronto, Ontario", "Toronto"),
            # A trailing country is stripped like any other region marker.
            ("Springfield, IL, USA", "Springfield"),
            # Three-plus components — a street leads, as before.
            ("1124 Menzler Rd, Nashville, TN 37210", "Nashville"),
            ("123 Main St, Springfield, IL 62701, USA", "Springfield"),
        ],
    )
    def test_the_city_is_found(self, address: str, expected: str) -> None:
        assert derive_city(address) == expected

    @pytest.mark.parametrize(
        "address",
        [
            # CONTROLS. Omission is still correct where the format is genuinely
            # unreadable — a business name published as a city is worse than no
            # city, which is why the street/venue rule survives.
            "Acme Auto, 123 Main St",
            "Main Street",
            "",
            # Every component is a region: there is no locality to find.
            "Colorado, USA",
            "CO, USA",
        ],
    )
    def test_an_unreadable_address_still_yields_nothing(self, address: str) -> None:
        assert derive_city(address) is None

    def test_a_region_is_never_returned_as_a_city(self) -> None:
        # The invariant, asserted over every region name rather than a sample —
        # this is the class of bug, not one instance of it.
        from app.howto_generation.slots import _REGION_NAMES

        for region in sorted(_REGION_NAMES):
            got = derive_city(f"Somewhereville, {region.title()}")
            assert got == "Somewhereville", f"{region}: got {got!r}"

