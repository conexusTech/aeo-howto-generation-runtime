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
   site does not allow or the list does not hold, or a phone, licence, address
   or hours number the inputs do not hold, removes the WHOLE field and records
   why (`section_checks.py`). The prompt asks; this enforces.
6. **Merge** the person's fields back in, word for word.
7. **Measure** voice tells and similarity. Recorded, never enforced.

Emit-only, as for articles: the gateway stores the draft, prices the usage and
writes the section when a person accepts it.
"""

from __future__ import annotations

import copy
from typing import Any

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

#: Context keys never shown to the model (`prompt._org_context_block` excludes
#: them for the same reason), and so never accepted as the source of a number:
#: another product's prospect lists are not this organization's record.
_UNSHOWN_CONTEXT_KEYS = frozenset(
    {
        "pipeline",
        "known_companies",
        "scoring_strategy",
        "lead_scoring",
        "discovery_project_signals",
    }
)

_NOT_DRAFTED = "the model did not draft this field"


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
    a later `discard` delete something somebody wrote.

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
    return sorted(
        name
        for name, value in current.items()
        if name not in baseline or baseline[name] != value
    )


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


def source_texts(request: SectionCopyRequest) -> list[str]:
    """The inputs a number may come from: the context the model was shown, the
    page, the questions, the price list and the section's current fields.

    Not `generated_baseline` — that is the model's own earlier output, and a
    number is not sourced by having been drafted before.
    """
    texts: list[str] = []
    for key, value in request.context.items():
        if key not in _UNSHOWN_CONTEXT_KEYS:
            texts.extend(_strings(value))
    texts.append(request.page.title)
    texts.append(request.page.page_type)
    if request.page.address:
        texts.append(request.page.address)
    texts.extend(request.page.other_sections_text)
    for question in request.questions:
        texts.append(question.text)
        texts.extend(question.competitors)
        if question.top_cited_host:
            texts.append(question.top_cited_host)
    for entry in request.prices.items:
        texts.extend([entry.item, entry.price])
    if request.current_fields:
        texts.extend(_strings(request.current_fields))
    return texts


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
            too_long: str | None = None
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                item: dict[str, str] = {}
                for item_spec in spec.item_fields:
                    value = raw.get(item_spec.name)
                    if isinstance(value, str) and value.strip():
                        if _over_limit(value, item_spec.max_length) and too_long is None:
                            too_long = (
                                f"item {len(items) + 1}'s {item_spec.name} is longer "
                                f"than the template's {item_spec.max_length} characters"
                            )
                        item[item_spec.name] = value
                if item:
                    items.append(item)
            if not items:
                continue
            if too_long is not None:
                refused[name] = too_long
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
) -> dict[str, str]:
    """TR-1 and TR-2 over every drafted field and every list item's fields.

    Returns field name -> reason for each field that must be removed. A list is
    removed whole when any one of its items fails, since the list is one field.
    """
    listed = section_checks.listed_price_keys(e.price for e in request.prices.items)
    sourced = section_checks.sourced_numbers(source_texts(request))
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

    for name, reason in post_check(fields, request=request).items():
        fields.pop(name, None)
        notes.pop(name, None)
        refused[name] = reason

    drafted_text = copy_text(fields)

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
        # banned character in order to forbid it.
        voice_tells=voice.find_tells(drafted_text),
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
