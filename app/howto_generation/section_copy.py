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
   and the page disagree on (`disagreement:`). Recorded, never enforced. The
   notes ride in `audit.voice_tells`, the one list of notes the gateway
   already stores and shows.

Emit-only, as for articles: the gateway stores the draft, prices the usage and
writes the section when a person accepts it.
"""

from __future__ import annotations

import copy
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
    SectionSimilarity,
    SectionTemplateField,
    TokenUsage,
)
from app.howto_generation.model import ChatModel, DraftedSectionCopy
from app.howto_generation.runtime import _context_version, _organization_id
from app.howto_generation import slots as slots_module

_NOT_DRAFTED = "the model did not draft this field"

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


def _over_limit(text: str, limit: int | None) -> bool:
    return limit is not None and len(text) > limit


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
    string values, and an item left with nothing is dropped.
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
        if spec.kind == "list":
            raw_items = entry.get("items")
            if not isinstance(raw_items, list):
                continue
            items: list[dict[str, str]] = []
            problem: str | None = None
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                item: dict[str, str] = {}
                for item_spec in spec.item_fields:
                    value = raw.get(item_spec.name)
                    if isinstance(value, str) and value.strip():
                        if _over_limit(value, item_spec.max_length) and problem is None:
                            problem = (
                                f"item {len(items) + 1}'s {item_spec.name} is longer "
                                f"than the template's {item_spec.max_length} characters"
                            )
                        item[item_spec.name] = value
                if item:
                    # An item with something in it must hold every part the
                    # template requires: a question with no answer is not a
                    # complete list, and must not look like one.
                    for item_spec in spec.item_fields:
                        if item_spec.required and item_spec.name not in item and problem is None:
                            problem = (
                                f"item {len(items) + 1} is missing its required "
                                f"{item_spec.name}"
                            )
                    items.append(item)
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
            if _over_limit(value, spec.max_length):
                refused[name] = (
                    f"longer than the template's {spec.max_length} characters"
                )
                continue
            fields[name] = value

        cited = entry.get("inputs_used")
        used = (
            sorted({c for c in cited if isinstance(c, str) and c in offered_ids})
            if isinstance(cited, list)
            else []
        )
        notes[name] = FieldNote(inputs_used=used)

    for spec in fields_to_draft:
        if spec.name not in fields and spec.name not in refused:
            refused[spec.name] = _NOT_DRAFTED
    return fields, notes, refused


def post_check(
    fields: dict[str, Any],
    *,
    request: SectionCopyRequest,
    sources: Iterable[str],
) -> dict[str, str]:
    """TR-1 and TR-2, and the competitor rule, over every drafted field and
    every list item's fields.

    `sources` is every text a number may come from: what the prompt showed
    (`SectionCopyPrompt.source_texts`) plus the person's edited fields.

    Returns field name -> reason for each field that must be removed. A list is
    removed whole when any one of its items fails, since the list is one field.
    """
    listed = section_checks.listed_price_keys(e.price for e in request.prices.items)
    sourced = section_checks.sourced_numbers(sources)
    competitors = [c for q in request.questions for c in q.competitors]
    refused: dict[str, str] = {}
    for name, value in fields.items():
        if isinstance(value, list):
            for index, item in enumerate(value, start=1):
                for key, text in item.items():
                    reason = section_checks.refusal_reason(
                        text,
                        prices_allowed=request.prices.allowed,
                        listed=listed,
                        sourced=sourced,
                        competitors=competitors,
                    )
                    if reason is not None:
                        refused[name] = f"item {index}'s {key} {reason}"
                        break
                if name in refused:
                    break
        else:
            reason = section_checks.refusal_reason(
                value,
                prices_allowed=request.prices.allowed,
                listed=listed,
                sourced=sourced,
                competitors=competitors,
            )
            if reason is not None:
                refused[name] = reason
    return refused


def copy_text(fields: dict[str, Any]) -> str:
    """The copy as one text, in field order, for voice and similarity."""
    parts: list[str] = []
    for value in fields.values():
        if isinstance(value, list):
            parts.extend(" ".join(item.values()) for item in value)
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


def disagreement_notes(disagreements: Iterable[str]) -> list[str]:
    """`disagreement:<line>` per point the model reported, one line each,
    bounded, deduplicated, in the model's order."""
    lines: list[str] = []
    for raw in disagreements:
        if not isinstance(raw, str):
            continue
        line = " ".join(raw.split())[:MAX_DISAGREEMENT_CHARS].rstrip()
        if line and line not in lines:
            lines.append(line)
        if len(lines) == MAX_DISAGREEMENTS:
            break
    return [f"disagreement:{line}" for line in lines]


def _inputs_used(request: SectionCopyRequest, facts_provenance: list[str]) -> list[str]:
    paths = set(facts_provenance)
    organization = request.context.get("organization")
    if isinstance(organization, dict) and isinstance(organization.get("description"), str):
        paths.add("organization.description")
    for key in ("products_services", "personas", "voice_tone"):
        if request.context.get(key):
            paths.add(key)
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
    facts = section_prompt.resolve_facts(request.context)
    composition = section_prompt.compose(
        request,
        facts=facts,
        fields_to_draft=to_draft,
        preserved=preserved,
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

    sources = [*composition.source_texts, *edited_texts(request, edited)]
    for name, reason in post_check(fields, request=request, sources=sources).items():
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
        inputs_used=_inputs_used(request, slots_module.inputs_used(facts)),
        # Over what THIS run drafted and kept — not a person's preserved words,
        # which are not ours to flag, and not the prompt, which names every
        # banned character in order to forbid it. The claim and disagreement
        # notes ride here too, under their own prefixes: this is the list of
        # notes the gateway already stores and shows, and a field it does not
        # know would be dropped there.
        voice_tells=[
            *voice.find_tells(drafted_text),
            *notes_on_claims,
            *disagreement_notes(drafted.disagreements),
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
