"""`task: "section_copy"` — one section of an organization's site, end to end.

```
edits  ->  facts  ->  compose  ->  MODEL  ->  normalize  ->  post-checks  ->  merge  ->  measure  ->  audit
TR-3                                          allowlist       TR-1, TR-2      TR-3
```

1. **Find the person's edits first** (field-level preserve, TR-3). A field whose
   current value differs from what drafting last produced is a person's, and
   under `preserve` it is not even asked of the model.
2. **Resolve the facts** with the article's slot resolver, so the prompt names
   what the record holds and what it does not.
3. **Draft.** The only model call, skipped when every field is preserved.
4. **Normalize.** Only template field names, only the declared item keys, only
   strings, only within the template's character limits, and `inputs_used` only
   from ids the prompt offered.
5. **Post-check** every drafted field and every list item's fields: a price the
   site does not allow or the list does not hold, a phone, licence, address
   or hours number the inputs do not hold, or the name of a competitor, removes
   the WHOLE field and records why (`section_checks.py`). The prompt asks; this
   enforces. The inputs are what the prompt showed plus the person's edits.
6. **Merge** the person's fields back in, word for word.
7. **Measure** voice tells and similarity, and **note** a claim term no
   business input uses (`claim:`) and each point the model found the record
   and the page disagree on (`disagreement:`), unless the line names a
   catch-all value the record holds ("Other"). Recorded, never enforced. The
   notes ride in `audit.voice_tells`, the one list of notes the gateway
   already stores and shows.

Emit-only, as for articles: the gateway stores the draft, prices the usage and
writes the section when a person accepts it.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable

from app.config import Settings
from app.howto_generation import section_checks, section_prompt, similarity, voice
from app.howto_generation.contracts import (
    CorpusArticle,
    ErrorResponse,
    FieldNote,
    SectionCopyAudit,
    SectionCopyRequest,
    SectionCopyResponse,
    SectionItemField,
    SectionSimilarity,
    SectionTemplateField,
    TokenUsage,
)
from app.howto_generation.model import ChatModel, DraftedSectionCopy
from app.howto_generation.runtime import _context_version, _organization_id
from app.howto_generation import slots as slots_module

_NOT_DRAFTED = "the model did not draft this field"
#: A brand field the model left out, as the prompt tells it to when the brand
#: record does not hold what the field asks for.
BRAND_LEFT_OUT = "left out: the brand record does not hold it"
#: A brand field the model wrote while citing nothing from the brand record.
BRAND_UNCITED = (
    "a brand field is written only from the brand record, and this draft cites "
    "nothing from it"
)
#: A brand field, or a field with a required brand part at any depth, when
#: the request carries no brand record at all.
BRAND_EMPTY = "a brand field, and this request carries no brand record to write it from"


def _has_required_brand_part(
    item_fields: list[SectionItemField], *, brand: bool = False
) -> bool:
    """Whether a list's items need a brand part they can never have without a
    brand record: a required item field that is brand, or sits in a brand
    list, at any depth."""
    for item in item_fields:
        item_brand = brand or item.source == "brand"
        if item.required and item_brand:
            return True
        if item.kind == "list" and _has_required_brand_part(
            item.item_fields, brand=item_brand
        ):
            return True
    return False


def needs_brand_record(spec: SectionTemplateField) -> bool:
    """Whether a field cannot be drafted at all without a brand record."""
    if spec.source == "brand":
        return True
    return spec.kind == "list" and _has_required_brand_part(spec.item_fields)

#: Bounds on the model's own disagreement lines, which are untrusted text that
#: reaches a person's screen. The gateway cuts a note at 200 characters.
MAX_DISAGREEMENTS = 3
MAX_DISAGREEMENT_CHARS = 150
_MAX_NOTE_FIELD_CHARS = 60


class SectionCopyRefused(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def find_edited_fields(
    current: dict[str, Any] | None, baseline: dict[str, Any] | None
) -> list[str]:
    """Fields a person changed since drafting produced `baseline`, by NAME.

    Matched by field name, never by position. A list field is compared as a
    whole value, so an edit to one item, a re-ordered item or a removed item
    all make the whole list the person's. A field in `current` that `baseline`
    never had is treated as the person's, the safe reading: the alternative lets
    a later `discard` delete something somebody wrote. A field `baseline` had
    and `current` no longer has was DELETED by the person, which is an edit too:
    `preserve` keeps it deleted, `discard` redrafts it.

    🔴 `baseline` is required whenever `current` is given, in both modes, for
    the reason `regenerate.py` gives for articles.
    """
    if current is None:
        return []
    if baseline is None:
        raise SectionCopyRefused(
            "BASELINE_REQUIRED",
            "a section draft with `current_fields` needs `generated_baseline`: "
            "what drafting last produced, before any person's edit. Without it "
            "an edit is indistinguishable from drafted copy, so `discard` would "
            "overwrite a person's words without being able to say so and "
            "`preserve` would claim to keep edits without knowing which.",
        )
    changed = {
        name
        for name, value in current.items()
        if name not in baseline or baseline[name] != value
    }
    return sorted(changed | {name for name in baseline if name not in current})


def _strings(value: Any) -> list[str]:
    """Every string (and number, as text) inside a JSON-shaped value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def edited_texts(request: SectionCopyRequest, edited: list[str]) -> list[str]:
    """The person's own words in the fields they edited: a source for a number,
    because a person wrote it. Unedited `current_fields` are the model's earlier
    output and not a source; neither is the baseline.
    """
    current = request.current_fields or {}
    return [text for name in edited if name in current for text in _strings(current[name])]


_TOP_HEADING = re.compile(r"^#(?=[ \t])", re.MULTILINE)


def _demote_top_headings(text: str) -> str:
    """A `# ` heading is the page's own title, which the site renders itself and
    the template's markdown does not: demote every one to `## `, which it does.
    """
    return _TOP_HEADING.sub("##", text)


def _over_limit(text: str, limit: int | None) -> bool:
    return limit is not None and len(text) > limit


def _normalize_items(
    raw_items: list[Any],
    item_specs: list[SectionItemField],
    *,
    brand: bool,
    cites_brand: bool,
    where: str = "",
) -> tuple[list[dict[str, Any]], str | None]:
    """A list's items, allowlisted against its item fields, one level of list
    deep. Returns `(items, problem)`: the first reason the list cannot stand,
    or None.

    `brand` is True inside a `brand` list field. A brand value is kept only
    when the field's entry cites a brand id (`cites_brand`); otherwise it is
    left out of every item, as the prompt says the model should have done, and
    an item that then lacks a required part is a problem like any other.
    """
    items: list[dict[str, Any]] = []
    problem: str | None = None
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {}
        label = f"{where}item {len(items) + 1}"
        for item_spec in item_specs:
            item_brand = brand or item_spec.source == "brand"
            if item_brand and not cites_brand:
                continue
            value = raw.get(item_spec.name)
            if item_spec.kind == "list":
                if value is None:
                    continue
                if not isinstance(value, list):
                    if problem is None:
                        problem = f"{label}'s {item_spec.name} is not a list"
                    continue
                nested, nested_problem = _normalize_items(
                    value,
                    item_spec.item_fields,
                    brand=item_brand,
                    cites_brand=cites_brand,
                    where=f"{label}'s {item_spec.name} ",
                )
                if nested_problem is not None and problem is None:
                    problem = nested_problem
                if nested:
                    item[item_spec.name] = nested
                continue
            if isinstance(value, str) and value.strip():
                if item_spec.kind == "rich_text":
                    value = _demote_top_headings(value)
                if _over_limit(value, item_spec.max_length) and problem is None:
                    problem = (
                        f"{label}'s {item_spec.name} is longer "
                        f"than the template's {item_spec.max_length} characters"
                    )
                item[item_spec.name] = value
        if item:
            # An item with something in it must hold every part the template
            # requires: a question with no answer is not a complete list, and
            # must not look like one. The same at the nested level.
            for item_spec in item_specs:
                if item_spec.required and item_spec.name not in item and problem is None:
                    problem = f"{label} is missing its required {item_spec.name}"
            items.append(item)
    return items, problem


def normalize(
    drafted: DraftedSectionCopy,
    *,
    fields_to_draft: list[SectionTemplateField],
    offered_ids: frozenset[str],
) -> tuple[dict[str, Any], dict[str, FieldNote], dict[str, str]]:
    """Allowlist the model's answer against the template.

    Returns `(fields, notes, refused)`. A field the model named that the
    template does not declare is dropped unread; the first entry for a name
    wins. Values must be strings; a list item keeps only declared keys with
    string values (or, for a list inside an item, a list of such items), and
    an item left with nothing is dropped. A `brand` field whose entry cites no
    `brand:` id is refused; a brand item field's values are then left out.
    """
    specs = {spec.name: spec for spec in fields_to_draft}
    fields: dict[str, Any] = {}
    notes: dict[str, FieldNote] = {}
    refused: dict[str, str] = {}

    for entry in drafted.fields:
        name = entry.get("name")
        if not isinstance(name, str) or name not in specs or name in fields or name in refused:
            continue
        spec = specs[name]
        brand = spec.source == "brand"

        cited = entry.get("inputs_used")
        used = (
            sorted({c for c in cited if isinstance(c, str) and c in offered_ids})
            if isinstance(cited, list)
            else []
        )
        cites_brand = any(u.startswith("brand:") for u in used)

        if spec.kind == "list":
            raw_items = entry.get("items")
            if not isinstance(raw_items, list) or not raw_items:
                continue
            # Before the items are read: they would all be brand values, all
            # left out, and the list would read as never written.
            if brand and not cites_brand:
                refused[name] = BRAND_UNCITED
                continue
            items, problem = _normalize_items(
                raw_items, spec.item_fields, brand=brand, cites_brand=cites_brand
            )
            if not items:
                continue
            if problem is not None:
                refused[name] = problem
                continue
            fields[name] = items
        else:
            value = entry.get("text")
            if not isinstance(value, str) or not value.strip():
                continue
            if brand and not cites_brand:
                refused[name] = BRAND_UNCITED
                continue
            if spec.kind == "rich_text":
                value = _demote_top_headings(value)
            if _over_limit(value, spec.max_length):
                refused[name] = (
                    f"longer than the template's {spec.max_length} characters"
                )
                continue
            fields[name] = value

        notes[name] = FieldNote(inputs_used=used)

    for spec in fields_to_draft:
        if spec.name not in fields and spec.name not in refused:
            refused[spec.name] = BRAND_LEFT_OUT if spec.source == "brand" else _NOT_DRAFTED
    return fields, notes, refused


def _texts_with_source(
    value: Any,
    item_specs: list[SectionItemField],
    *,
    brand: bool,
    where: str = "",
) -> Iterable[tuple[str, str, bool]]:
    """`(label, text, brand)` for every text inside a list field's items, at
    every level, in order. `label` names the item and part for a reason."""
    if not isinstance(value, list):
        return
    by_name = {spec.name: spec for spec in item_specs}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        for key, inner in item.items():
            spec = by_name.get(key)
            item_brand = brand or (spec is not None and spec.source == "brand")
            if isinstance(inner, str):
                yield f"{where}item {index}'s {key}", inner, item_brand
            elif isinstance(inner, list):
                yield from _texts_with_source(
                    inner,
                    spec.item_fields if spec is not None else [],
                    brand=item_brand,
                    where=f"{where}item {index}'s {key} ",
                )


def post_check(
    fields: dict[str, Any],
    *,
    request: SectionCopyRequest,
    sources: Iterable[str],
    brand_sources: Iterable[str] = (),
) -> dict[str, str]:
    """TR-1 and TR-2, and the competitor rule, over every drafted field and
    every list item's fields, a list inside an item included.

    `sources` is every text a number may come from: what the prompt showed
    (`SectionCopyPrompt.source_texts`) plus the person's edited fields. A
    `brand` value's number may come only from `brand_sources`, the brand
    record as the prompt showed it (`SectionCopyPrompt.brand_source_texts`):
    a brand field is written from the brand record and nothing else.

    Returns field name -> reason for each field that must be removed. A list is
    removed whole when any one of its items fails, since the list is one field.
    """
    listed = section_checks.listed_price_keys(e.price for e in request.prices.items)
    sourced = section_checks.sourced_numbers(sources)
    brand_sourced = section_checks.sourced_numbers(brand_sources)
    competitors = [c for q in request.questions for c in q.competitors]
    specs = {spec.name: spec for spec in request.template.fields}

    def reason_for(text: str, brand: bool) -> str | None:
        return section_checks.refusal_reason(
            text,
            prices_allowed=request.prices.allowed,
            listed=listed,
            sourced=brand_sourced if brand else sourced,
            competitors=competitors,
        )

    refused: dict[str, str] = {}
    for name, value in fields.items():
        spec = specs.get(name)
        brand = spec is not None and spec.source == "brand"
        if isinstance(value, list):
            item_specs = spec.item_fields if spec is not None else []
            for label, text, text_brand in _texts_with_source(
                value, item_specs, brand=brand
            ):
                reason = reason_for(text, text_brand)
                if reason is not None:
                    refused[name] = f"{label} {reason}"
                    break
        else:
            reason = reason_for(value, brand)
            if reason is not None:
                refused[name] = reason
    return refused


def copy_text(fields: dict[str, Any]) -> str:
    """The copy as one text, in field order, for voice and similarity."""
    parts: list[str] = []
    for value in fields.values():
        if isinstance(value, list):
            parts.extend(" ".join(_strings(item)) for item in value)
        elif isinstance(value, str):
            parts.append(value)
    return "\n\n".join(parts)


def claim_notes(fields: dict[str, Any], *, sources: Iterable[str]) -> list[str]:
    """`claim:<family> (<field>)` for each claim family a drafted field uses
    that no business input does. A note for a person, never a refusal.

    `sources` is what the prompt showed about the business
    (`SectionCopyPrompt.claim_source_texts`) plus the person's edited fields;
    the questions are not in it.
    """
    sourced = section_checks.sourced_claims(sources)
    notes: list[str] = []
    for name, value in fields.items():
        families: set[str] = set()
        for text in _strings(value):
            families.update(section_checks.unsourced_claims(text, sourced))
        label = " ".join(name.split())[:_MAX_NOTE_FIELD_CHARS]
        notes.extend(f"claim:{family} ({label})" for family in sorted(families))
    return notes


def _bounded(line: str) -> str:
    """A line at most MAX_DISAGREEMENT_CHARS long, cut at a word and marked
    with an ellipsis, so a long point never ends mid-thought."""
    if len(line) <= MAX_DISAGREEMENT_CHARS:
        return line
    cut = line[: MAX_DISAGREEMENT_CHARS - 1]
    space = cut.rfind(" ")
    if space > MAX_DISAGREEMENT_CHARS // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


#: Record values that say nothing about what a business does. Compared after
#: trimming and lowercasing; a record holding one cannot disagree with a page.
CATCH_ALL_VALUES = frozenset(
    {
        "other", "others", "n/a", "na", "none", "general", "misc",
        "miscellaneous", "unknown", "unspecified", "not specified", "various",
    }
)
_QUOTES = "\"'\u2018\u2019\u201c\u201d"


def catch_all_record_values(context: dict[str, Any]) -> list[str]:
    """The organization record's values that are catch-alls ("Other", "N/A"),
    exactly as the record writes them. Blank values are not here: a line cannot
    name nothing, so the prompt alone carries that half of the rule."""
    organization = context.get("organization")
    if not isinstance(organization, dict):
        return []
    return sorted(
        {
            value.strip()
            for value in organization.values()
            if isinstance(value, str) and value.strip().lower() in CATCH_ALL_VALUES
        }
    )


def names_catch_all(line: str, values: Iterable[str]) -> bool:
    """Whether a disagreement line names one of the record's catch-all values.

    Named means quoted, in any case (`"other"`), or written exactly as the
    record writes it in the middle of a sentence, when that spelling has a
    capital letter (`as Other`, `N/A`). Prose never trips it: lowercase
    `other` is a word, and a capital at the start of a sentence is grammar.
    """
    for value in values:
        quoted = re.compile(
            rf"[{_QUOTES}]\s*{re.escape(value)}\s*[{_QUOTES}]", re.IGNORECASE
        )
        if quoted.search(line):
            return True
        if not any(ch.isupper() for ch in value):
            continue
        for match in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", line):
            before = line[: match.start()].rstrip()
            if before and before[-1] not in ".!?":
                return True
    return False


def disagreement_notes(
    disagreements: Iterable[str], *, catch_alls: Iterable[str] = ()
) -> list[str]:
    """`disagreement:<line>` per point the model reported, one line each,
    bounded, deduplicated, in the model's order.

    A line naming one of the record's catch-all values (`catch_alls`, from
    `catch_all_record_values`) is dropped: "Other" says nothing about what the
    business does, so it cannot disagree with a page, and the prompt says so.
    """
    values = list(catch_alls)
    lines: list[str] = []
    for raw in disagreements:
        if not isinstance(raw, str):
            continue
        if values and names_catch_all(" ".join(raw.split()), values):
            continue
        line = _bounded(" ".join(raw.split()))
        if line and line not in lines:
            lines.append(line)
        if len(lines) == MAX_DISAGREEMENTS:
            break
    return [f"disagreement:{line}" for line in lines]


def _inputs_used(
    request: SectionCopyRequest,
    facts_provenance: list[str],
    notes: dict[str, FieldNote],
) -> list[str]:
    paths = set(facts_provenance)
    organization = request.context.get("organization")
    if isinstance(organization, dict) and isinstance(organization.get("description"), str):
        paths.add("organization.description")
    for key in ("products_services", "personas", "voice_tone"):
        if request.context.get(key):
            paths.add(key)
    # Brand facts only as cited by a field this run kept: the record can hold
    # thirty facts, and listing them all would claim the draft drew on each.
    paths.update(
        used for note in notes.values() for used in note.inputs_used
        if used.startswith("brand:")
    )
    return sorted(paths)


def handle(
    request: SectionCopyRequest, *, model: ChatModel, settings: Settings
) -> SectionCopyResponse | ErrorResponse:
    """Draft one section's copy, with its refusals, notes, measurement and audit."""
    try:
        edited = find_edited_fields(request.current_fields, request.generated_baseline)
    except SectionCopyRefused as refusal:
        return ErrorResponse(error_code=refusal.error_code, message=refusal.message)

    preserved = edited if request.edit_policy == "preserve" else []

    to_draft = [f for f in request.template.fields if f.name not in preserved]
    brand = section_prompt.brand_facts(request.brand)
    # A brand field with no brand record has nothing to be written from, and
    # neither has a list whose items require a brand part: neither is asked of
    # the model, and each says why.
    refused_up_front: dict[str, str] = {}
    if not brand:
        refused_up_front = {f.name: BRAND_EMPTY for f in to_draft if needs_brand_record(f)}
        to_draft = [f for f in to_draft if f.name not in refused_up_front]
    facts = section_prompt.resolve_facts(request.context)
    composition = section_prompt.compose(
        request,
        facts=facts,
        fields_to_draft=to_draft,
        preserved=preserved,
        brand=brand,
    )

    if to_draft:
        drafted = model.draft_section_copy(prompt=composition)
    else:
        # Every field is a person's: there is nothing to ask a model for, and
        # nothing to pay for.
        drafted = DraftedSectionCopy()

    fields, notes, refused = normalize(
        drafted, fields_to_draft=to_draft, offered_ids=composition.input_ids
    )
    refused.update(refused_up_front)

    sources = [*composition.source_texts, *edited_texts(request, edited)]
    for name, reason in post_check(
        fields,
        request=request,
        sources=sources,
        brand_sources=composition.brand_source_texts,
    ).items():
        fields.pop(name, None)
        notes.pop(name, None)
        refused[name] = reason

    drafted_text = copy_text(fields)
    # Over the fields THIS run drafted and kept, before a person's preserved
    # words are merged back: those are theirs, and a source rather than a claim.
    notes_on_claims = claim_notes(
        fields,
        sources=[*composition.claim_source_texts, *edited_texts(request, edited)],
    )

    # `discard`: a person's field this draft actually replaces, named so the
    # overwrite is never silent. One the post-checks removed is not replaced.
    discarded = [] if request.edit_policy == "preserve" else [
        name for name in edited if name in fields
    ]

    # The person's fields go back word for word — a deep copy of exactly what
    # was sent, never re-flowed. Includes an edited field the template no
    # longer declares: dropping it would lose a person's words silently.
    current = request.current_fields or {}
    for name in preserved:
        # A field the person DELETED stays deleted: it is preserved by being
        # absent, not by a value.
        if name in current:
            fields[name] = copy.deepcopy(current[name])

    # Template order first, then any preserved field the template lacks.
    order = [f.name for f in request.template.fields]
    ordered = {name: fields[name] for name in order if name in fields}
    ordered.update({name: value for name, value in fields.items() if name not in ordered})

    corpus = [
        CorpusArticle(article_id=d.draft_id, organization_id=d.organization_id, body=d.text)
        for d in request.corpus
    ]
    measured = similarity.measure(
        copy_text(ordered),
        corpus,
        num_perm=settings.HOWTO_GENERATION_MINHASH_PERMUTATIONS,
    )

    audit = SectionCopyAudit(
        template_key=request.template.key,
        template_name=request.template.name,
        question_ids=[q.id for q in request.questions],
        context_version=_context_version(request.context),
        organization_id=_organization_id(request.context),
        model_id=settings.HOWTO_GENERATION_MODEL_ID,
        build_version=settings.HOWTO_GENERATION_BUILD_VERSION or None,
        inputs_used=_inputs_used(request, slots_module.inputs_used(facts), notes),
        # Over what THIS run drafted and kept — not a person's preserved words,
        # which are not ours to flag, and not the prompt, which names every
        # banned character in order to forbid it. The claim and disagreement
        # notes ride here too, under their own prefixes: this is the list of
        # notes the gateway already stores and shows, and a field it does not
        # know would be dropped there.
        voice_tells=[
            *voice.find_tells(drafted_text),
            *notes_on_claims,
            *disagreement_notes(
                drafted.disagreements,
                catch_alls=catch_all_record_values(request.context),
            ),
        ],
    )

    return SectionCopyResponse(
        fields=ordered,
        field_notes=notes,
        refused=dict(sorted(refused.items())),
        preserved_fields=sorted(preserved),
        discarded_fields=sorted(discarded),
        edit_policy=request.edit_policy,
        similarity=SectionSimilarity(
            score=measured.score,
            nearest_draft_id=measured.nearest_article_id,
            nearest_organization_id=measured.nearest_organization_id,
            compared_count=measured.compared_count,
            duration_ms=measured.duration_ms,
        ),
        audit=audit,
        usage=drafted.usage or TokenUsage(),
    )
