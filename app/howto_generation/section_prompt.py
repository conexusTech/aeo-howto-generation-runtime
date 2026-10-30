"""The prompt for `task: "section_copy"` — one section of an organization's site.

Same posture as the article prompt (`prompt.py`), reused where it can be:

- the business's own words go in the stable half inside the same data fence
  (`_org_context_block`), and every other piece of tenant or third-party text —
  the page, its other sections, the questions, the price list — is fenced too;
- the facts come from the same slot resolver, so the model is told what the
  record holds AND what it does not (`_facts_block`);
- the voice rules are the same generated text the detector checks against.

⚠️ **This prompt is not the enforcement layer.** It asks for facts only and
prices only from the list; `section_checks.py` removes any field that does not
comply after the model answers. Read what follows as the part that shapes good
copy, not the part that prevents bad copy.

Every input the model may draw on is offered with an ID (`question:<id>`,
`price:<n>`, a fact name, `page.title`), and the model reports per field which
ids it used. Ids it names that were never offered are dropped in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.howto_generation import slots as slots_module
from app.howto_generation.contracts import (
    SectionCopyRequest,
    SectionTemplateField,
    SlotResolution,
    TemplateSlot,
)
from app.howto_generation.prompt import _facts_block, _fence, _org_context_block
from app.howto_generation.voice import voice_rules_for_prompt

#: The facts a section may state, by the slot names the resolver knows. Phone,
#: email and opening hours are declared so that they come back OMITTED — the
#: record has no field for them — and the prompt then names them as facts we do
#: not have, which is the instruction a model needs most on a contact section.
FACT_SLOTS: tuple[str, ...] = (
    "business_name",
    "industry",
    "city",
    "address",
    "service_area",
    "website",
    "founded_year",
    "phone",
    "email",
    "opening_hours",
)

_BASELINE = """\
You write the copy for one section of a business's own website.

WHAT THE SECTION IS FOR.
Each section is meant to be the page an answer engine cites when somebody asks
one of the QUESTIONS listed below. Write so that a reader, and an answer engine,
finds a direct, specific, quotable answer to those questions in this section,
in this business's own terms. Answer the question; do not restate it.

WHAT TRADE THIS BUSINESS IS IN, YOU WILL BE TOLD.
Take the register, the vocabulary and the examples from THE BUSINESS below, not
from any assumption about what kind of work this is.

FACTS: USE ONLY WHAT YOU ARE GIVEN.
Every fact about the business is listed under RESOLVED FACTS, in THE BUSINESS,
or in the price list if there is one. That is complete. If something is not
there (a phone number, an address, opening hours, a licence or registration
number, a warranty, a turnaround time, a certification, a price, a discount)
then we do not have it, and you write the copy without it. Do not invent,
estimate or hedge toward a plausible value.

This is checked after you answer. A field carrying a phone number, a licence
number, an address, opening hours or a price that we did not give you is
thrown away whole, so an invented detail costs the entire field.

COMPETITORS.
The questions may name competitors and the sites answer engines cite today.
They tell you what this section is up against. Never name a competitor in the
copy, and never compare this business with one by name.
"""

_BASELINE = _BASELINE + "\n" + voice_rules_for_prompt()

_VERDICTS = {
    "lost": "answer engines cite a competitor instead of this business",
    "missing": "answer engines mention nobody we track, this business included",
    "earned": "answer engines already cite this business; keep what earns it",
    "unmeasured": "not measured yet",
}


@dataclass(frozen=True)
class SectionCopyPrompt:
    """The composed prompt, split at the cache breakpoint, plus what the local
    stub needs to draft deterministically. No model is sent the stub fields."""

    stable: str
    volatile: str
    #: The fields the model is asked to draft (preserved fields excluded).
    fields_to_draft: tuple[SectionTemplateField, ...] = ()
    #: `(id, text)` of each target question, in request order.
    questions: tuple[tuple[str, str], ...] = ()
    page_title: str = ""
    #: Every input id offered to the model. The allowlist for `inputs_used`.
    input_ids: frozenset[str] = field(default_factory=frozenset)

    def split(self) -> tuple[str, str]:
        return self.stable, self.volatile


def resolve_facts(context: dict[str, Any]) -> SlotResolution:
    return slots_module.resolve_slots(
        [TemplateSlot(name=name) for name in FACT_SLOTS], context
    )


def _one_line(value: Any) -> str:
    """Collapse whitespace so no value can start a fresh line of instruction."""
    return " ".join(str(value).split()) if value is not None else ""


def _field_line(spec: SectionTemplateField) -> list[str]:
    limit = f", at most {spec.max_length} characters" if spec.max_length else ""
    need = "required" if spec.required else "optional"
    if spec.kind != "list":
        kind = "plain text" if spec.kind == "text" else "rich text (markdown)"
        return [f"- {spec.name}: {kind}{limit}, {need}"]
    lines = [f"- {spec.name}: a list of items, {need}. Each item has:"]
    for item in spec.item_fields:
        item_limit = f", at most {item.max_length} characters" if item.max_length else ""
        kind = "plain text" if item.kind == "text" else "rich text (markdown)"
        lines.append(f"    - {item.name}: {kind}{item_limit}")
    return lines


def _business_ids(context: dict[str, Any]) -> list[str]:
    """Ids for what `_org_context_block` shows beyond the resolved facts."""
    ids: list[str] = []
    organization = context.get("organization") or {}
    if isinstance(organization, dict):
        if isinstance(organization.get("description"), str) and organization[
            "description"
        ].strip():
            ids.append("organization.description")
    if isinstance(context.get("products_services"), list) and context["products_services"]:
        ids.append("products_services")
    if isinstance(context.get("personas"), list) and context["personas"]:
        ids.append("personas")
    if isinstance(context.get("voice_tone"), dict) and context["voice_tone"]:
        ids.append("voice_tone")
    return ids


def compose(
    request: SectionCopyRequest,
    *,
    facts: SlotResolution,
    fields_to_draft: list[SectionTemplateField],
    preserved: list[str],
) -> SectionCopyPrompt:
    """Build the prompt for one section.

    The business sits in the STABLE half, as for articles: one organization
    drafts many sections, so the organization is what repeats.
    """
    stable = "\n\n".join([_BASELINE, _org_context_block(request.context)])

    input_ids: set[str] = set(facts.resolved) | set(_business_ids(request.context))

    # --- the page and the questions, fenced: tenant and third-party text ----
    data: list[str] = ["THE PAGE"]
    data.append(f"- [page.title] Title: {_one_line(request.page.title)}")
    data.append(f"- Page type: {_one_line(request.page.page_type)}")
    input_ids.add("page.title")
    if request.page.address:
        data.append(f"- [page.address] Address on the site: {_one_line(request.page.address)}")
        input_ids.add("page.address")
    others = [t for t in request.page.other_sections_text if t and t.strip()]
    if others:
        data.append(
            "- [page.other_sections] What the page's other sections already say "
            "(do not repeat it):"
        )
        data.extend(f"    - {_one_line(t)[:1500]}" for t in others[:12])
        input_ids.add("page.other_sections")

    data.append("\nTHE QUESTIONS THIS SECTION IS MEANT TO WIN")
    if request.questions:
        for question in request.questions:
            qid = f"question:{_one_line(question.id)}"
            input_ids.add(qid)
            data.append(f"- [{qid}] {_one_line(question.text)}")
            data.append(f"    - Today: {_VERDICTS[question.verdict]}")
            if question.competitors:
                named = ", ".join(_one_line(c) for c in question.competitors[:10])
                data.append(f"    - Competitors answer engines name: {named}")
            if question.top_cited_host:
                data.append(
                    f"    - The source answer engines cite most: "
                    f"{_one_line(question.top_cited_host)}"
                )
    else:
        data.append("- (none given: write for the page's title)")

    if request.prices.allowed:
        data.append(
            "\nTHE PRICE LIST. The ONLY amounts you may write, each exactly as listed:"
        )
        if request.prices.items:
            for index, entry in enumerate(request.prices.items[:50], start=1):
                pid = f"price:{index}"
                input_ids.add(pid)
                data.append(
                    f"- [{pid}] {_one_line(entry.item)}: {_one_line(entry.price)}"
                )
        else:
            data.append("- (empty: write no amount at all)")

    task: list[str] = [
        "\n".join(_fence(data)),
        "",
        _facts_block(facts),
    ]
    if not request.prices.allowed:
        task.append(
            "\nFORBIDDEN. This site does not allow prices. Write no amount, price, "
            "rate, fee, discount or percentage off, in figures or in words."
        )

    task.append(f"\nTHE SECTION: {_one_line(request.template.name)}")
    task.append("Write these fields:")
    for spec in fields_to_draft:
        task.extend(_field_line(spec))
    if preserved:
        task.append(
            "\nThese fields were written by a person and are kept as they are; "
            "do not write them: " + ", ".join(preserved)
        )

    task.append(
        "\nINPUT IDS you may cite in `inputs_used`, and only these: "
        + ", ".join(sorted(input_ids))
    )
    task.append(
        "\nOUTPUT\nCall the `emit_section_copy` tool exactly once. One entry per "
        "field, by its exact name. A text field carries `text`; a list field "
        "carries `items`, each an object keyed by the item field names. Stay "
        "within every character limit. List in `inputs_used` the ids of the "
        "inputs each field draws on."
    )

    return SectionCopyPrompt(
        stable=stable,
        volatile="\n".join(task),
        fields_to_draft=tuple(fields_to_draft),
        questions=tuple((q.id, q.text) for q in request.questions),
        page_title=request.page.title,
        input_ids=frozenset(input_ids),
    )
