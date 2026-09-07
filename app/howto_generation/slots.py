"""HOW-4.2 — localization slots, resolved from org data only.

The acceptance criteria are three sentences and each one is a refusal:

- no slot renders a placeholder or an invented value
- a missing input omits the section rather than fabricating it
- pricing never appears without a source field

All three are enforced **here, in code**, not in the prompt. A prompt
instruction is a request; the model complies most of the time, and "most of the
time" is indistinguishable from "always" until the day it is not. The generated
copy never sees a slot this module refused to resolve, so there is nothing for a
model to substitute even if it wanted to.

The mechanical half of this slice already exists in the gateway:
`aeo-backend/src/backend/howto/howto-slots.ts` substitutes `{{slot}}` and drops
any section referencing an unresolved one. What lives here is the half it cannot
do — deciding **which values are legitimately available** from an org's runtime
context, and which are not available at any price.
"""

from __future__ import annotations

import re

from typing import Any

from app.howto_generation.contracts import SlotResolution, TemplateSlot

#: Slots whose value would be a price. Refused unconditionally.
#:
#: The org runtime context has no pricing field. `products_services[].pricing_model`
#: is the nearest thing and it is a BILLING MODEL ("subscription", "one-time"),
#: not an amount or a band — reading it as a price is precisely the fabrication
#: the criterion forbids, and it is plausible enough that someone would.
#:
#: When onboarding grows a real pricing-band field, delete a name from this set
#: and add a resolver. Until then this is a closed door rather than a missing
#: resolver, because the two behave identically and only one of them says why.
PRICING_SLOTS = frozenset(
    {
        "price",
        "prices",
        "pricing",
        "price_band",
        "price_bands",
        "pricing_band",
        "pricing_bands",
        "price_range",
        "cost",
        "costs",
        "typical_cost",
        "estimated_cost",
        "rate",
        "rates",
        "hourly_rate",
        "labour_rate",
        "labor_rate",
    }
)

_PRICING_REFUSAL = (
    "no pricing source field exists in the org runtime context; HOW-4.2 forbids "
    "pricing without one. `products_services[].pricing_model` is a billing model, "
    "not an amount, and is not a substitute."
)

#: Slots the templates ask for that the gateway's context genuinely does not
#: carry. Distinguished from "this org has not filled it in" because the fix is
#: different: an onboarding field has to exist before any org can supply one.
#:
#: `cta` is the live example. HOW-4.2 names CTAs as a slot; the runtime-context
#: payload has no CTA field of any kind (verified against `RuntimeContextDto`,
#: 2026-09-03). Every org therefore omits it, which is correct behaviour and a
#: product gap at the same time.
CONTEXT_GAP_SLOTS: dict[str, str] = {
    "cta": "the org runtime context carries no CTA field",
    "ctas": "the org runtime context carries no CTA field",
    "cta_text": "the org runtime context carries no CTA field",
    "call_to_action": "the org runtime context carries no CTA field",
    "phone": "the org runtime context carries no phone field",
    "phone_number": "the org runtime context carries no phone field",
    "email": "the org runtime context carries no contact-email field",
    "hours": "the org runtime context carries no opening-hours field",
    "opening_hours": "the org runtime context carries no opening-hours field",
}

#: Country tokens that must never be mistaken for a city when parsing an address.
_COUNTRY_TOKENS = frozenset(
    {
        "usa",
        "us",
        "u.s.",
        "u.s.a.",
        "united states",
        "united states of america",
        "canada",
        "uk",
        "u.k.",
        "united kingdom",
        "england",
        "scotland",
        "wales",
        "australia",
        "ireland",
        "new zealand",
    }
)


#: US states and Canadian provinces, by full name. Needed because a
#: two-component address may end in either a code ("Grand Rapids, MI") or a
#: name ("Widefield, Colorado"), and only by recognising both can the CITY be
#: told apart from the region beside it.
#:
#: 🔴 Before this existed, `"Widefield, Colorado"` derived the city as
#: **"Colorado"** — the region, published as the locality. The docblock on
#: `derive_city` claimed its failures were "silent omissions rather than wrong
#: copy"; for that format the claim was false.
_REGION_NAMES = frozenset(
    {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming", "district of columbia",
        # Canadian provinces and territories.
        "alberta", "british columbia", "manitoba", "new brunswick",
        "newfoundland and labrador", "nova scotia", "ontario",
        "prince edward island", "quebec", "saskatchewan",
        "northwest territories", "nunavut", "yukon",
    }
)

#: A region code or name optionally trailed by a postal code — "TN 37210",
#: "IL 62701", "ON K1A 0B1". Matched as a unit so a state-plus-ZIP component
#: is recognised as a region marker rather than mistaken for a street.
_REGION_WITH_POSTAL = re.compile(
    r"^(?P<region>[A-Za-z][A-Za-z .]*?)\s+[A-Za-z0-9][A-Za-z0-9 -]*\d[A-Za-z0-9 -]*$"
)


def _is_region_marker(part: str) -> bool:
    """Is this component a state, province or country rather than a city?

    Deliberately narrow. Anything it does not recognise is left in place and
    handled by the street/venue rule, because treating an unknown component as
    a region is how a city gets discarded.
    """
    text = part.strip()
    lowered = text.lower()
    if lowered in _COUNTRY_TOKENS or lowered in _REGION_NAMES:
        return True
    if len(text) == 2 and text.isalpha() and text.isupper():
        return True  # a state or province code
    match = _REGION_WITH_POSTAL.match(text)
    if match is not None:
        region = match.group("region").strip().lower()
        return (
            region in _REGION_NAMES
            or (len(region) == 2 and region.isalpha())
        )
    return False


def _text(value: Any) -> str | None:
    """A non-blank string, or nothing. Numbers are deliberately NOT coerced.

    An onboarding blob can hold anything; `str(value)` on an unexpected type is
    how `{'city': None}` becomes the literal copy "None" in a published article.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _looks_like_city(part: str) -> bool:
    """A conservative filter over one comma-separated address component."""
    if any(ch.isdigit() for ch in part):
        return False  # "IL 62701", "62701", "123 Main St"
    if not any(ch.isalpha() for ch in part):
        return False
    if not 2 <= len(part) <= 40:
        return False
    if part.lower() in _COUNTRY_TOKENS:
        return False
    if len(part) == 2 and part.isupper():
        return False  # a state or province code
    return True


def derive_city(address: str | None) -> str | None:
    """Best-effort city from a free-text address, or nothing.

    ⚠️ **This is inference, and it is the only inference in this module.** The
    org record has no structured city column — `organization.address` is one
    free-text line from the company-profile step — so the choice is between
    inferring a city and shipping articles with no locality at all, which
    removes most of what "localization slots" means. The value is marked
    `derived:` in provenance so a reviewer can see it was not read from a field.

    The rule works from the RIGHT, which is the fix. Region and country
    components are stripped off the end first; whatever survives is the address
    proper, and only then is a leading street or venue name discarded.

    🔴 It used to work from the left — discard the first component unread, then
    look for exactly one city-shaped component among the rest. That is correct
    only when a street component exists, and produced three defects on real
    data (measured across every org with geography, 2026-09-07):

        "Colorado Springs, CO"    -> None        (city discarded as a street)
        "Grand Rapids, MI"        -> None        (same)
        "Widefield, Colorado"     -> "Colorado"  (the REGION as the city)
        "Nashville, Tennessee"    -> "Tennessee" (same)
        "Springfield, IL, USA"    -> None

    Two of those publish a wrong locality rather than omitting one, which the
    old docblock explicitly promised could not happen. Two of the three orgs
    holding a location were affected.

    Still errs toward omission where the format is genuinely unreadable:
    `"Acme Auto, 123 Main St"` and `"Main Street"` yield nothing, because a
    business name published as a city is worse than no city.

    The real fix remains a structured locality field in onboarding; this is the
    honest approximation until there is one.
    """
    if not address or not address.strip():
        return None

    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return None  # a single line is a street, not an address we can read

    # Strip region and country components off the end. What remains is the
    # address proper — street and locality, in that order.
    while len(parts) > 1 and _is_region_marker(parts[-1]):
        parts.pop()
    if _is_region_marker(parts[-1]):
        return None  # every component was a region; there is no locality here

    if len(parts) == 1:
        # No street component survived, so this component IS the locality —
        # the "City, ST" and "City, State" shapes.
        return parts[0] if _looks_like_city(parts[0]) else None

    # A street or venue leads; exactly one of the rest must look like a city.
    # Two candidates means a format we do not recognise, and a coin flip
    # between them is a fabricated value that happens to be well-formed.
    candidates = [p for p in parts[1:] if _looks_like_city(p)]
    if len(candidates) != 1:
        return None
    return candidates[0]


def _market_names(value: Any) -> list[str]:
    """Flatten a geography blob entry into plain market names.

    The blob is `Record<string, unknown>` passthrough on the gateway side, so
    its interior has never been validated by anything. Every shape below has
    been seen in onboarding data or is one step away from a shape that has.
    """
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        for key in ("name", "label", "market", "city", "region", "value"):
            found = _text(value.get(key))
            if found:
                return [found]
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_market_names(item))
        return out
    return []


def _service_area(context: dict[str, Any]) -> str | None:
    """Home markets from the `geography` blob.

    ⚠️ The roadmap recorded service area as ABSENT from the runtime-context
    payload. Measured against `RuntimeContextDto` on 2026-09-03 that is not
    quite right: `geography` is present and documented as the
    `geographic_strategy` blob (home/secondary/excluded). What is true is that
    it is an unvalidated passthrough object, so it is present without being
    reliable — read defensively, omit on anything unrecognised.
    """
    geography = context.get("geography")
    if not isinstance(geography, dict):
        return None
    for key in (
        "home_markets",
        "home_market",
        "home",
        "primary_markets",
        "primary",
        "markets",
    ):
        names = _market_names(geography.get(key))
        if names:
            # Deduplicate while keeping declared order: a repeated market in the
            # blob should not become a repeated phrase in the copy.
            seen: dict[str, None] = {}
            for name in names:
                seen.setdefault(name, None)
            return ", ".join(seen)
    return None


#: Canonical slot name -> (context path, extractor). Aliases share a resolver so
#: a template author writing `company_name` and one writing `shop_name` get the
#: same value rather than one of them silently getting nothing.
_RESOLVERS: dict[str, tuple[str, Any]] = {}


def _register(names: tuple[str, ...], path: str, fn: Any) -> None:
    for name in names:
        _RESOLVERS[name] = (path, fn)


_register(
    ("shop_name", "company_name", "business_name", "org_name", "organization_name"),
    "organization.name",
    lambda ctx: _text((ctx.get("organization") or {}).get("name")),
)
_register(
    ("city", "town", "locality"),
    "derived:organization.address",
    lambda ctx: derive_city(_text((ctx.get("organization") or {}).get("address"))),
)
_register(
    ("address", "location", "full_address"),
    "organization.address",
    lambda ctx: _text((ctx.get("organization") or {}).get("address")),
)
_register(
    ("service_area", "service_areas", "coverage_area", "home_markets"),
    "geography.home_markets",
    _service_area,
)
_register(
    ("industry", "vertical", "sector"),
    "organization.industry",
    lambda ctx: _text((ctx.get("organization") or {}).get("industry")),
)
_register(
    ("website", "site_url", "web_address"),
    "organization.website",
    lambda ctx: _text((ctx.get("organization") or {}).get("website")),
)
_register(
    ("founded_year", "established"),
    "organization.founded_year",
    lambda ctx: (
        str((ctx.get("organization") or {}).get("founded_year"))
        if isinstance((ctx.get("organization") or {}).get("founded_year"), int)
        else None
    ),
)


def resolve_slots(
    slots: list[TemplateSlot], context: dict[str, Any]
) -> SlotResolution:
    """Resolve every declared slot, recording why each one landed where it did.

    Nothing is ever filled with a placeholder, an empty string or a plausible
    guess. A slot either has a value traceable to a context path, or it appears
    in `omitted` / `refused` and the section referencing it is dropped
    downstream by the gateway's existing materializer.
    """
    result = SlotResolution()

    for slot in slots:
        name = slot.name.strip().lower()

        if name in PRICING_SLOTS:
            result.refused[slot.name] = _PRICING_REFUSAL
            continue

        if name in CONTEXT_GAP_SLOTS:
            result.omitted.append(slot.name)
            continue

        resolver = _RESOLVERS.get(name)
        if resolver is None:
            # An unrecognised slot is omitted, never guessed at. Templates are
            # SU-authored and the library is small, so a new slot name is a
            # deliberate act that should come with a resolver; silently
            # inventing one here is how a template starts quietly shipping
            # sections nobody specified.
            result.omitted.append(slot.name)
            continue

        path, extract = resolver
        value = extract(context)
        if value is None:
            result.omitted.append(slot.name)
            continue

        result.resolved[slot.name] = value
        result.provenance[slot.name] = path

    return result


def inputs_used(resolution: SlotResolution) -> list[str]:
    """The context paths that actually contributed, sorted — HOW-4.1's audit.

    Derived from provenance rather than from the resolver table, so it lists
    what was read on THIS request rather than what could have been.
    """
    return sorted(set(resolution.provenance.values()))
