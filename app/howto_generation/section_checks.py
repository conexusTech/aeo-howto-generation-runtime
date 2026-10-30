"""Post-checks on drafted section copy — TR-1 (prices) and TR-2 (unsourced numbers),
plus one that only NOTES: a claim about how the business works (same day,
guaranteed, licensed, insured...) that no business input makes. See the end of
this module.

The prompt ASKS the model to use only the facts it is given. This module is what
holds when the model does not comply: it reads every drafted field after the
model has answered and reports each number that should not be there. The caller
removes the whole field and says why. A prompt instruction is a request; this is
the rule.

Two checks:

**Prices (TR-1).** Any currency amount when the site does not allow prices; when
it does, any amount whose value is not on the organization's own price list.

**Unsourced numbers (TR-2).** A phone number, a licence or registration number,
a street or postal number, or opening hours, that the same detector does not
also find in the INPUTS — the context the model was shown, the page, the
questions, the price list and the section's current fields.

"Appears in the inputs" means: the same pattern, run over the inputs, yields the
same canonical value. Not a substring search, because a bare `27` is a substring
of almost any input and would wave through `27 Main Street`.

The patterns, and what each is for
----------------------------------

Prices (`find_prices`):

==================  ==========================================  ================
name                matches                                     example
==================  ==========================================  ================
``symbol_before``   a currency symbol or code, then an amount   ``$120``, ``USD 120``, ``€1.200,50``
``symbol_after``    an amount, then a symbol, code or word      ``120€``, ``120 dollars``, ``45 cents``
``number_words``    a number word, then a currency word         ``twenty dollars``
``percent_off``     a percentage discount                       ``20% off``, ``save 15%``
==================  ==========================================  ================

A range (``$100-$200``, ``$100 to 200``) yields both ends. An amount in words
cannot be compared with a list, so it is refused even when prices are allowed.

Everything is NFKC-normalised first (fullwidth ``＄40`` is ``$40``) and every
Unicode dash read as ``-``. Markers and ISO codes match in any case, before or
after the amount, joined by nothing, a space or a hyphen: ``usd 40``, ``Usd40``,
``40-dollar``, ``99¢``, ``₤40``, ``1299 kr``, ``Rs. 500``, ``$.99``. A magnitude
(``k``, ``M``, ``thousand``, ``million``, ``bn``) scales the amount before it is
compared, so ``$40k`` is not the listed ``$40``. ``percent_off`` is this module's
rule for a percentage discount and reads ``%``, ``percent`` and ``per cent``
alike; a percentage that is not a discount (``50 percent of our work``) is not a
price.

⚠️ Bare ``pounds`` counts as money, so ``lose 10 pounds`` is refused. That is the
safe direction: a refused field is a person's thirty-second fix, a price on a
site that does not allow them is a false statement.

Unsourced numbers (`find_unsourced`):

==================  ==========================================  ================
category            matches                                     example
==================  ==========================================  ================
``phone``           7 to 15 digits, groups of up to 8           ``(555) 123-4567``,
                    split by space, dot or dash (any            ``+44 20 7946 0958``,
                    Unicode dash), optional ``+`` code,         ``07700 900123``,
                    or one unbroken run of 7 to 15 digits       ``5551234567``
``licence``         a licence/registration keyword then an id;   ``Lic. #123456``,
                    ``#`` then 3+ digits; 1-4 capitals then      ``#4471``,
                    4+ digits                                    ``ROC123456``, ``ISO9001``
``address``         a number then a street suffix; a suite or    ``412 Kirkwood Ave``,
                    unit number; a PO box; a US ZIP after a      ``Suite 200``, ``PO Box 9``,
                    state code; a UK postcode                    ``IL 62701``, ``SW1A 1AA``
``hours``           a clock time with am/pm; a 24-hour time;     ``9am``, ``17:30``,
                    ``24/7``; ``24 hours``; ``N days a week``    ``24/7``, ``7 days a week``
==================  ==========================================  ================

Phone excludes an ISO date (``2026-10-30``), a dotted or slashed date
(``30.10.2026``) and a year range (``2019-2026``), which have the same shape.

How "sourced" is decided, per category:

- **phone** — digits only; an unbroken run in the inputs sources a phone only
  at 10+ digits (``ref 5551234`` is not a phone); equal, or equal but for a country code of up to
  three digits (a trunk ``0`` ignored) when the national number has 10+ digits.
  A 7-digit local number never sources a draft that adds an area code to it.
- **licence** — the identifier's digits equal a digit run in the inputs.
- **address** — ``412 Kirkwood Ave`` keys as ``412 kirkwood``, and the inputs
  offer every ``<number> <word>`` pair they contain, so ``Avenue`` against
  ``Ave`` still matches; a suite as ``suite 200``; a ZIP or PO box by number; a
  UK postcode without its space.
- **hours** — a 24-hour time: ``9am``, ``9 a.m.``, ``9:00 AM`` and ``9:00`` are
  all ``9:00``; ``5pm``, ``5:00 PM`` and ``17:00`` are all ``17:00``.

Every pattern is tested, with a sourced control beside it, in
`tests/test_section_checks.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

#: An amount: `120`, `1,200`, `1.200,50`, `120.00`, `1.5`, `.99`.
_NUM = r"(?:\d+(?:[,.]\d{3})*(?:[.,]\d{1,2})?|\.\d{1,2})"

#: A magnitude after an amount: `40k`, `40M`, `1.5 million`, `2bn`. Letters stand
#: against the digits; words may be spaced or hyphenated.
_MAG = r"(?:[\s-]?(?:thousand|million|billion|mil)|(?:k|mm|m|bn))(?![a-z])"
_MAGNITUDE: dict[str, int] = {
    "k": 10**3, "thousand": 10**3,
    "m": 10**6, "mm": 10**6, "mil": 10**6, "million": 10**6,
    "bn": 10**9, "billion": 10**9,
}

#: Currency marker -> the group it compares within. `$`, `USD`, `dollars` are
#: one group so `USD 120` in a draft matches `$120` on the list.
_CURRENCY_GROUPS: dict[str, str] = {
    "$": "$", "us$": "$", "c$": "$", "a$": "$", "nz$": "$", "hk$": "$",
    "usd": "$", "cad": "$", "aud": "$", "nzd": "$", "hkd": "$", "sgd": "$",
    "mxn": "$", "dollar": "$", "dollars": "$", "buck": "$", "bucks": "$",
    "cent": "$/100", "cents": "$/100", "¢": "$/100",
    "£": "£", "₤": "£", "gbp": "£", "pound": "£", "pounds": "£", "quid": "£",
    "pence": "£/100",
    "€": "€", "eur": "€", "euro": "€", "euros": "€",
    "¥": "¥", "jpy": "¥", "cny": "¥",
    "₹": "₹", "inr": "₹", "rs": "₹",
    "r$": "R$", "chf": "CHF", "zar": "ZAR", "₩": "₩", "₽": "₽",
    "kr": "kr", "sek": "kr", "nok": "kr", "dkk": "kr",
}

_SYMBOL = r"(?:US\$|C\$|A\$|NZ\$|HK\$|R\$|\$|£|₤|€|¥|₹|₩|₽|¢)"
_CODE = (
    r"(?:USD|EUR|GBP|CAD|AUD|NZD|HKD|SGD|MXN|JPY|CNY|INR|CHF|ZAR|SEK|NOK|DKK|PLN|"
    r"AED|BRL|KRW|THB)"
)
#: Markers that are words rather than symbols or ISO codes.
_KR_RS = r"(?:kr|rs\.?)"
_WORD = r"(?:dollars?|bucks?|euros?|pounds?|quid|cents?|pence)"
#: What may join a marker to its amount: nothing, a space or a hyphen.
_JOIN = r"[\s-]?"
_RANGE = r"\s?(?:-|to)\s?"
_NUMBER_WORDS = (
    r"(?:a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|few|several|couple of)"
)

_PRICE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "symbol_before",
        re.compile(
            rf"(?P<cur>{_SYMBOL}|\b{_CODE}|\b{_KR_RS}){_JOIN}"
            rf"(?P<a>{_NUM})(?P<ma>{_MAG})?"
            rf"(?:{_RANGE}(?:{_SYMBOL}|{_CODE})?{_JOIN}(?P<b>{_NUM})(?P<mb>{_MAG})?)?",
            re.IGNORECASE,
        ),
    ),
    (
        "symbol_after",
        re.compile(
            rf"(?<![\w.,$£₤€])(?:(?P<a>{_NUM})(?P<ma>{_MAG})?{_RANGE})?"
            rf"(?P<b>{_NUM})(?P<mb>{_MAG})?{_JOIN}"
            rf"(?P<cur>{_SYMBOL}|{_CODE}\b|{_WORD}\b|{_KR_RS}\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "number_words",
        re.compile(
            rf"\b{_NUMBER_WORDS}[\s-]+"
            r"(?:hundred[\s-]+|thousand[\s-]+)?(?P<cur>dollars|bucks|euros|pounds|quid)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "percent_off",
        re.compile(
            rf"(?:\b(?:save|saving|discount of|reduction of)\s+(?P<a>{_NUM})\s?"
            rf"(?:%|per\s?cent|pct))"
            rf"|(?:(?<![\w.,])(?P<b>{_NUM})\s?(?:%|per\s?cent|pct)\s?"
            rf"(?:off|discount|cheaper|less)\b)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    """One number a check found. `key` is what sourcing compares."""

    category: str
    pattern: str
    text: str
    key: str


def _amount(raw: str) -> Decimal | None:
    """`1,200.50` / `1.200,50` / `120,50` / `120` -> a Decimal, or None."""
    text = raw.strip()
    separators = [c for c in text if c in ",."]
    if not separators:
        digits = text
    else:
        last = max(text.rfind(","), text.rfind("."))
        tail = text[last + 1 :]
        if len(set(separators)) == 1 and len(tail) == 3:
            digits = text.replace(",", "").replace(".", "")  # thousands only
        else:
            digits = (
                text[:last].replace(",", "").replace(".", "") + "." + tail
            )
    try:
        return Decimal(digits).normalize()
    except InvalidOperation:
        return None


#: Every dash-like character, read as a plain hyphen once NFKC has run.
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-")


def normalise(text: str) -> str:
    """NFKC, then every Unicode dash as `-`.

    Fullwidth `＄40` becomes `$40`, a non-breaking hyphen or en dash in a phone
    number becomes the hyphen the patterns expect, and non-breaking spaces
    become spaces. Run over drafts AND inputs, so the two compare alike.
    """
    return unicodedata.normalize("NFKC", text).translate(_DASHES)


def _scaled(raw: str | None, magnitude: str | None) -> Decimal | None:
    """An amount with its `k` / `million` / `bn` applied."""
    value = _amount(raw) if raw else None
    if value is None or not magnitude:
        return value
    return (value * _MAGNITUDE[magnitude.strip(" -").lower()]).normalize()


def _group(marker: str | None) -> str | None:
    if marker is None:
        return None
    key = marker.strip().lower().rstrip(".")
    return _CURRENCY_GROUPS.get(key, key.upper())


def _price_key(group: str | None, value: Decimal | None) -> str:
    """`$|120`. A `/100` group (cents, pence) is converted to its base unit."""
    if group is not None and group.endswith("/100") and value is not None:
        group = group[: -len("/100")]
        value = (value / 100).normalize()
    # Fixed-point text, so `120`, `120.00` and `1.2E+2` are all `120`.
    shown = format(value.normalize(), "f") if value is not None else "?"
    return f"{group or '?'}|{shown}"


def find_prices(text: str) -> list[Finding]:
    """Every currency amount in `text`. A range yields both ends."""
    text = normalise(text)
    findings: list[Finding] = []
    for name, pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groupdict()
            if name == "percent_off":
                for raw in (groups.get("a"), groups.get("b")):
                    if raw:
                        findings.append(
                            Finding("price", name, match.group(0), _price_key("%", _amount(raw)))
                        )
                continue
            group = _group(groups.get("cur"))
            if name == "number_words":
                # A value in words cannot be compared with a list.
                findings.append(Finding("price", name, match.group(0), f"{group}|words"))
                continue
            ma, mb = groups.get("ma"), groups.get("mb")
            # `$40-50k` is forty thousand to fifty thousand: the closing
            # magnitude reaches the opening amount when it has none of its own.
            if groups.get("a") and groups.get("b") and not ma:
                ma = mb
            for raw, magnitude in ((groups.get("a"), ma), (groups.get("b"), mb)):
                if raw:
                    findings.append(
                        Finding(
                            "price", name, match.group(0),
                            _price_key(group, _scaled(raw, magnitude)),
                        )
                    )
    return findings


def listed_price_keys(prices: Iterable[str]) -> set[str]:
    """The keys the organization's price list offers.

    A listed price with no currency marker (`120`) keys as `?|120` and matches
    an amount of that value in any currency — the list did not say, so the
    draft's marker cannot contradict it.
    """
    keys: set[str] = set()
    for price in prices:
        found = [f.key for f in find_prices(price)]
        if found:
            keys.update(found)
            continue
        for found_amount in re.finditer(
            rf"(?P<n>{_NUM})(?P<m>{_MAG})?", normalise(price), re.IGNORECASE
        ):
            keys.add(
                _price_key(None, _scaled(found_amount.group("n"), found_amount.group("m")))
            )
    return keys


def price_is_listed(key: str, listed: set[str]) -> bool:
    if key in listed:
        return True
    _, _, value = key.partition("|")
    if value in ("?", "words"):
        return False
    return f"?|{value}" in listed and not key.startswith("%|")


# --- unsourced numbers (TR-2) ---------------------------------------------

_PHONE = re.compile(
    r"(?<![\w$£€.,/#])"
    r"(?:\+\s?\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?"
    r"\d{1,8}(?:(?:\s*[.-]\s*|\s)\d{1,8}){1,5}(?![\w%/])"
    r"|(?<![\w$£€.,/#])\+?\d{7,15}(?![\w%/])"
)
_NOT_A_PHONE = (
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),  # ISO date
    re.compile(r"^\d{1,2}[.-]\d{1,2}[.-]\d{2,4}$"),  # 30.10.2026
    re.compile(r"^(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}$"),  # 2019-2026
)

_LICENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "licence_keyword",
        re.compile(
            r"\b(?:licen[cs]e[ds]?|lic\.|registration|reg\.|permit|"
            r"certificate|cert\.|accreditation|bond|policy)"
            r"\s*(?:no\.?|number|num\.?|#|:)?\s*#?\s*"
            r"(?P<id>[A-Za-z]{0,4}-?\d[\dA-Za-z-]{2,})",
            re.IGNORECASE,
        ),
    ),
    (
        "licence_acronym",
        re.compile(
            r"\b(?:ABN|ACN|EIN|VAT|NMLS|CSLB|USDOT|DOT|MC)\s*(?:no\.?|#|:)?\s*"
            r"(?P<id>\d[\d\s-]{2,}\d)"
        ),
    ),
    ("licence_hash", re.compile(r"#\s?(?P<id>\d{3,})\b")),
    ("licence_code", re.compile(r"\b(?P<id>[A-Z]{1,4}-?\d{4,}[A-Z0-9]*)\b")),
)

_STREET_SUFFIX = (
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|"
    r"Court|Ct|Place|Pl|Highway|Hwy|Parkway|Pkwy|Terrace|Close|Crescent|"
    r"Square|Sq|Row|Circle|Cir|Trail|Pike)"
)
_ADDRESS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "street",
        re.compile(
            r"\b(?P<num>\d{1,6}[A-Za-z]?)(?:-\d{1,6})?\s+"
            r"(?P<name>(?:[A-Z0-9][\w'.-]*\s+){0,3}?)"
            rf"(?P<suffix>{_STREET_SUFFIX})\b\.?"
        ),
    ),
    (
        "suite",
        re.compile(
            r"\b(?P<kw>Suite|Ste\.?|Unit|Apt\.?|Apartment|Floor|Bldg\.?|Building)"
            r"\s*#?\s*(?P<num>\d+[A-Za-z]?)\b"
        ),
    ),
    ("po_box", re.compile(r"\bP\.?\s?O\.?\s?Box\s+(?P<num>\d+)", re.IGNORECASE)),
    ("zip", re.compile(r"\b[A-Z]{2}\s+(?P<num>\d{5}(?:-\d{4})?)\b")),
    ("uk_postcode", re.compile(r"\b(?P<num>[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b")),
)

_HOURS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ampm",
        re.compile(
            r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s?(?P<ap>[ap])\.?m\.?(?![a-z])",
            re.IGNORECASE,
        ),
    ),
    (
        "clock",
        re.compile(
            r"\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)\b(?!\s?[ap]\.?m)",
            re.IGNORECASE,
        ),
    ),
    ("always_open", re.compile(r"\b24\s?/\s?7\b")),
    ("all_day", re.compile(r"\b24[\s-]hours?\b", re.IGNORECASE)),
    ("days_a_week", re.compile(r"\b(?P<d>[1-7])\s+days\s+a\s+week\b", re.IGNORECASE)),
)

_CATEGORY_LABEL = {
    "phone": "a phone number",
    "licence": "a licence or registration number",
    "address": "a street or postal number",
    "hours": "opening hours",
}


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _phones(text: str) -> list[Finding]:
    text = normalise(text)
    out: list[Finding] = []
    for match in _PHONE.finditer(text):
        span = match.group(0).strip()
        digits = _digits(span)
        if not 7 <= len(digits) <= 15:
            continue
        if any(p.match(span) for p in _NOT_A_PHONE):
            continue
        out.append(Finding("phone", "phone", span, digits))
    return out


def _licences(text: str) -> list[Finding]:
    text = normalise(text)
    out: list[Finding] = []
    for name, pattern in _LICENCE_PATTERNS:
        for match in pattern.finditer(text):
            digits = _digits(match.group("id"))
            if len(digits) < 3:
                continue
            out.append(Finding("licence", name, match.group(0), digits))
    return out


def _address_key(name: str, match: re.Match[str]) -> str:
    num = match.group("num")
    if name == "street":
        words = match.group("name").split()
        follow = words[0] if words else match.group("suffix")
        return f"{num.lower()} {follow.lower().rstrip('.')}"
    if name == "suite":
        kw = match.group("kw").lower().rstrip(".")
        return f"{kw} {num.lower()}"
    if name == "uk_postcode":
        return num.replace(" ", "").upper()
    return _digits(num)


def _addresses(text: str) -> list[Finding]:
    text = normalise(text)
    return [
        Finding("address", name, match.group(0), _address_key(name, match))
        for name, pattern in _ADDRESS_PATTERNS
        for match in pattern.finditer(text)
    ]


def _hours_key(name: str, match: re.Match[str]) -> str:
    """A time as 24-hour `H:MM`, so `5pm`, `5:00 PM` and `17:00` are one key."""
    if name == "ampm":
        hour = int(match.group("h")) % 12
        if match.group("ap").lower() == "p":
            hour += 12
        return f"{hour}:{match.group('m') or '00'}"
    if name == "clock":
        return f"{int(match.group('h'))}:{match.group('m')}"
    if name == "always_open":
        return "24/7"
    if name == "all_day":
        return "24 hours"
    return f"{match.group('d')} days a week"


def _hours(text: str) -> list[Finding]:
    text = normalise(text)
    return [
        Finding("hours", name, match.group(0), _hours_key(name, match))
        for name, pattern in _HOURS_PATTERNS
        for match in pattern.finditer(text)
    ]


def find_numbers(text: str) -> list[Finding]:
    """Every phone, licence, address and hours number in `text`."""
    return _phones(text) + _licences(text) + _addresses(text) + _hours(text)


@dataclass(frozen=True)
class SourcedNumbers:
    """What the inputs offer, per category, built once per request."""

    phones: frozenset[str]
    digit_runs: frozenset[str]
    address: frozenset[str]
    hours: frozenset[str]


def sourced_numbers(inputs: Iterable[str]) -> SourcedNumbers:
    """Run the detectors over the inputs. Each input is scanned on its own, so
    numbers in two different inputs never join into one."""
    phones: set[str] = set()
    runs: set[str] = set()
    address: set[str] = set()
    hours: set[str] = set()
    for text in inputs:
        if not text:
            continue
        text = normalise(text)
        # A formatted number is a phone number at any length. An UNBROKEN run
        # sources a phone only when it is a full national number (10+ digits):
        # `ref 5551234` is a reference, and must not source `Call 555-1234`.
        phones.update(
            f.key
            for f in _phones(text)
            if len(f.key) >= 10 or not f.text.lstrip("+").isdigit()
        )
        runs.update(re.findall(r"\d{3,}", text))
        runs.update(f.key for f in _licences(text))
        address.update(f.key for f in _addresses(text))
        # Every `<number> <word>` pair, so `412 Kirkwood Avenue` in a draft is
        # sourced by `412 Kirkwood Ave` in the record.
        address.update(
            f"{n.lower()} {w.lower()}"
            for n, w in re.findall(r"\b(\d{1,6}[A-Za-z]?)\s+([A-Za-z][\w'-]*)", text)
        )
        hours.update(f.key for f in _hours(text))
    return SourcedNumbers(
        phones=frozenset(phones),
        digit_runs=frozenset(runs),
        address=frozenset(address),
        hours=frozenset(hours),
    )


def _is_sourced(finding: Finding, sourced: SourcedNumbers) -> bool:
    if finding.category == "phone":
        for known in sourced.phones:
            if known == finding.key:
                return True
            # A country code in one and not the other: the longer may carry up
            # to three extra leading digits, with a national trunk `0` dropped.
            # The shorter must be a full national number (10+ digits), or a
            # 7-digit local number would source a draft with an INVENTED area
            # code in front of it.
            shorter, longer = sorted(
                (known.lstrip("0"), finding.key.lstrip("0")), key=len
            )
            if (
                len(shorter) >= 10
                and len(longer) - len(shorter) <= 3
                and longer.endswith(shorter)
            ):
                return True
        return False
    if finding.category == "licence":
        return finding.key in sourced.digit_runs
    if finding.category == "address":
        return finding.key in sourced.address or (
            finding.pattern in ("zip", "po_box") and finding.key in sourced.digit_runs
        )
    if finding.category == "hours":
        return finding.key in sourced.hours
    return False


def find_unsourced(text: str, sourced: SourcedNumbers) -> list[Finding]:
    return [f for f in find_numbers(text) if not _is_sourced(f, sourced)]


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 40 else text[:37] + "..."


def competitor_named(text: str, competitors: Iterable[str]) -> str | None:
    """The first competitor `text` names, or None.

    Case-insensitive, after NFKC, as a whole word or phrase: `Ace` is in
    `Call Ace today` and not in `space`. Whitespace inside a name is flexible.
    """
    folded = " ".join(normalise(text).casefold().split())
    for name in competitors:
        needle = " ".join(normalise(name).casefold().split())
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", folded):
            return name
    return None


def refusal_reason(
    text: str,
    *,
    prices_allowed: bool,
    listed: set[str],
    sourced: SourcedNumbers,
    competitors: Iterable[str] = (),
) -> str | None:
    """Why this text cannot be returned, or None when it can.

    The first finding wins; one reason is enough to remove the field.
    """
    for finding in find_prices(text):
        if not prices_allowed:
            return (
                f'contains a price ("{_quote(finding.text)}") and this site does '
                "not allow prices in drafts"
            )
        if not price_is_listed(finding.key, listed):
            return (
                f'contains a price ("{_quote(finding.text)}") that is not on the '
                "organization's price list"
            )
    for finding in find_unsourced(text, sourced):
        return (
            f"contains {_CATEGORY_LABEL[finding.category]} "
            f'("{_quote(finding.text)}") that the organization\'s record does not hold'
        )
    named = competitor_named(text, competitors)
    if named is not None:
        return (
            f'names a competitor ("{_quote(named)}"); section copy never names or '
            "compares with one"
        )
    return None


# --- claims about how the business works: a NOTE, never a refusal ------------
#
# Found by the first real-model run (2026-10-31): drafts were well written and
# number-clean, and still told readers how the business operates — "a same-day
# job, not something that sits in a general queue" — when nothing the model was
# shown said so. Most such sentences have no fixed vocabulary, so the PROMPT is
# what addresses them. A few terms do: each below is a promise a reader acts on,
# and none is ordinary filler copy, so a draft using one that no input uses is
# worth a person's look. It is reported, never refused: unlike an invented phone
# number, "guaranteed" can be true of the business and simply missing from the
# record, and a person reviewing the draft is who knows.
#
# Clock times, `24/7` and `24 hours` are NOT here: the hours detector above
# already refuses them when unsourced. `around the clock` is here because it
# says the same thing with no digit for that detector to see.
#
# Matched by FAMILY, so `guaranteed` in a draft is sourced by `guarantee` in the
# record; whole words only, so `uninsured` is not `insured`.

CLAIM_FAMILIES: tuple[tuple[str, str], ...] = (
    ("accredited", r"accredited"),
    ("around the clock", r"a?round[\s-]the[\s-]clock"),
    ("bonded", r"bonded"),
    ("certified", r"certified"),
    ("guarantee", r"guarantee(?:s|d|ing)?"),
    ("insured", r"insured"),
    ("licensed", r"licen[cs]ed"),
    ("next day", r"next[\s-]day"),
    # `same day-to-day work` is not a timing claim.
    ("same day", r"same[\s-]day(?![\s-]to[\s-]day)"),
    ("warranty", r"warrant(?:y|ies|ied)"),
)

_CLAIM_PATTERNS = tuple(
    (label, re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", re.IGNORECASE))
    for label, pattern in CLAIM_FAMILIES
)


def claim_families(text: str) -> list[str]:
    """Every claim family `text` uses, in `CLAIM_FAMILIES` order, once each."""
    if not text:
        return []
    folded = normalise(text)
    return [label for label, pattern in _CLAIM_PATTERNS if pattern.search(folded)]


def sourced_claims(inputs: Iterable[str]) -> frozenset[str]:
    """The claim families any input uses."""
    return frozenset(label for text in inputs for label in claim_families(text))


def unsourced_claims(text: str, sourced: frozenset[str]) -> list[str]:
    """The claim families `text` uses that no input does."""
    return [label for label in claim_families(text) if label not in sourced]
