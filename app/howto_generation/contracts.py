"""The wire contract: what the gateway sends, what this runtime answers with.

snake_case throughout, matching the gateway's runtime-context endpoint
(`RuntimeContextDto` in aeo-backend) — that payload is already snake_case
precisely because Python consumes it, and a second convention here would mean a
transform layer whose only job is to undo a decision someone already made.

**Everything inbound is `extra="ignore"`.** The gateway's context DTO gains
fields regularly (`known_companies`, `pipeline` and `type` all arrived after the
first consumer shipped), and a runtime that rejects an unknown key turns every
additive gateway change into an outage in a repo nobody touched.

**The one exception is outbound.** `GenerationResponse` is `extra="forbid"`:
this runtime OWNS its response shape, so an unexpected key there is our own bug
and should fail loudly rather than reach a gateway that will ignore it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SectionType = Literal["intro", "step", "tip", "outro"]

_INBOUND = ConfigDict(extra="ignore")
_OUTBOUND = ConfigDict(extra="forbid")


class Section(BaseModel):
    """Mirrors `HowtoArticleSection` in aeo-backend. The gateway writes the
    rows; we only ever propose them, so this is a proposal shape rather than a
    persistence shape."""

    model_config = _INBOUND

    type: SectionType
    #: 1-based and contiguous when it leaves here. The gateway re-numbers on
    #: write anyway; matching its invariant means a diff between what we
    #: proposed and what was stored is a real difference rather than a
    #: numbering artefact.
    position: int
    heading: str
    body_md: str
    image_asset_key: str | None = None
    image_alt: str | None = None


class TemplateSlot(BaseModel):
    model_config = _INBOUND

    name: str
    description: str | None = None
    required: bool = False


class Template(BaseModel):
    """The library template being generated from — `howto_templates`, global and
    SU-managed. Sent whole rather than by id: this runtime has no database."""

    model_config = _INBOUND

    id: str | None = None
    service_key: str
    vertical: str
    title: str
    description: str | None = None
    sections: list[Section] = Field(default_factory=list)
    slots: list[TemplateSlot] = Field(default_factory=list)


class CorpusArticle(BaseModel):
    """One published sibling to compare against (HOW-4.4).

    WARNING: cross-tenant by design, and the only cross-tenant data in the
    payload. The nearest neighbour of a shop's article is another shop's
    article from the same template — that is the entire point of the
    measurement. The gateway assembles this list under SU context and sends
    body text only: no shop name, no host, no tenant id. `organization_id` is
    carried because the stored record needs a neighbour reference, and because
    a comparison against the org's OWN earlier article has to be excludable.
    """

    model_config = _INBOUND

    article_id: str
    organization_id: str
    #: Section bodies joined. Already free of renderer chrome by construction —
    #: nav, header and footer live in the renderer, never in an article row.
    body: str


#: The two jobs `POST /invocations` does. `article` is the default so every
#: request written before `section_copy` existed means exactly what it meant.
Task = Literal["article", "section_copy"]


class GenerationRequest(BaseModel):
    model_config = _INBOUND

    #: Only ever `article` here. A `section_copy` body is parsed as a
    #: `SectionCopyRequest` instead (the server dispatches on this field), so
    #: an article request can never be mistaken for one and vice versa.
    task: Literal["article"] = "article"
    operation: Literal["generate", "regenerate"] = "generate"
    template: Template
    #: The gateway's runtime-context payload, passed through verbatim. Read
    #: defensively in `context.py`; every field in it is optional in practice.
    context: dict[str, Any] = Field(default_factory=dict)

    # --- regenerate only ---------------------------------------------------
    #: The article as it stands now, human edits included.
    current_article: list[Section] | None = None
    #: What generation last produced for this article, before any human touched
    #: it. Without it an edit cannot be distinguished from generated copy — see
    #: `regenerate.py` for why that makes `discard` a refusal rather than a
    #: best effort.
    generated_baseline: list[Section] | None = None
    edit_policy: Literal["preserve", "discard"] = "preserve"

    # --- similarity --------------------------------------------------------
    corpus: list[CorpusArticle] = Field(default_factory=list)
    #: Text blocks the caller declares as furniture, removed before shingling.
    #: Empty is the normal case; see `similarity.py`.
    chrome_blocks: list[str] = Field(default_factory=list)


class SlotResolution(BaseModel):
    """What HOW-4.2 did with each slot, and why. The why is the point.

    A reviewer looking at an article with no pricing section needs to tell "the
    shop has no pricing on file" from "the generator dropped it", and those two
    produce identical output. This is the only place that distinction survives.
    """

    model_config = _OUTBOUND

    resolved: dict[str, str] = Field(default_factory=dict)
    #: name -> the context path the value came from, e.g. `organization.name`.
    #: A `derived:` prefix marks a value inferred rather than read (`slots.py`).
    provenance: dict[str, str] = Field(default_factory=dict)
    #: Declared by the template, no value available. The section is omitted.
    omitted: list[str] = Field(default_factory=list)
    #: Refused on principle even when something plausible sits nearby: pricing.
    refused: dict[str, str] = Field(default_factory=dict)


class SimilarityMeasurement(BaseModel):
    """HOW-4.4. Recorded only: this blocks nothing and alerts nothing."""

    model_config = _OUTBOUND

    #: Jaccard estimate in [0, 1] against the nearest neighbour.
    score: float
    nearest_article_id: str | None
    nearest_organization_id: str | None
    #: How many siblings this was compared against. `0` means the corpus was
    #: empty — the first article from a template — and a score of 0.0 then means
    #: UNMEASURED, not "perfectly distinct". Every consumer must branch on this
    #: before reading `score`.
    compared_count: int
    #: The evidence HOW-4.4 asks for in place of a guessed corpus ceiling.
    duration_ms: int


class RegenerationOutcome(BaseModel):
    """HOW-4.6. `mode` is stated, never inferred by the reader."""

    model_config = _OUTBOUND

    mode: Literal["preserve", "discard"]
    preserved_positions: list[int] = Field(default_factory=list)
    discarded_positions: list[int] = Field(default_factory=list)


class AuditRecord(BaseModel):
    """HOW-4.1: the exact inputs used are recorded for audit.

    Inputs, not a summary of them. `context_version` is the gateway's opaque
    token that changes whenever onboarding data changes, so it pins the org
    snapshot; `inputs_used` pins which fields of it were actually read. Together
    they answer "what did the generator see" without this runtime storing
    anything, which it cannot do.
    """

    model_config = _OUTBOUND

    template_id: str | None
    template_service_key: str
    template_vertical: str
    context_version: str | None
    organization_id: str | None
    model_id: str
    build_version: str | None = None
    #: Context paths read, sorted. The complement of this against the context is
    #: what was ignored — occasionally the more interesting half.
    inputs_used: list[str] = Field(default_factory=list)

    #: House-voice tells found in the copy this run produced, sorted. Empty is
    #: the ordinary case and the goal.
    #:
    #: 🔴 MEASURED, NEVER ENFORCED, and that is the same choice this runtime
    #: already made for similarity: a generation that reads slightly
    #: machine-written is worth flagging to the person reviewing it and is not
    #: worth refusing, because the alternative is refusing good articles over
    #: a word list. An operator sees the list; nothing here acts on it.
    #:
    #: Additive with a default, so a gateway that has not learned about this
    #: field stores it in `generation_audit` jsonb and ignores it.
    voice_tells: list[str] = Field(default_factory=list)


class TokenUsage(BaseModel):
    model_config = _OUTBOUND

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


class GenerationResponse(BaseModel):
    model_config = _OUTBOUND

    operation: Literal["generate", "regenerate"]
    title: str
    sections: list[Section]
    slots: SlotResolution
    similarity: SimilarityMeasurement | None = None
    regeneration: RegenerationOutcome | None = None
    audit: AuditRecord
    usage: TokenUsage = Field(default_factory=TokenUsage)


class ErrorResponse(BaseModel):
    """A refusal or a failure, as a body rather than an HTTP status.

    AgentCore surfaces a non-2xx as an invocation failure with the body often
    discarded, so a 400 carrying a good explanation reaches the gateway as "it
    broke". Every outcome this runtime can name is therefore a 200 with a typed
    body, and the gateway branches on `error_code`.
    """

    model_config = _OUTBOUND

    error_code: str
    message: str


# ===========================================================================
# task: "section_copy" — Meriwether Sites C4 (`section-copy-generation`)
#
# Copy for ONE section of an organization's own site, written for the
# questions that section is meant to win, from facts the record holds. The
# same rules as an article — facts only, prices only from the price list, a
# person's edits kept — but per FIELD rather than per article section, and the
# fact rules are re-checked in code after the model answers (`section_checks`).
# ===========================================================================

#: A text field is one string; `rich_text` is one string of markup the site
#: renders; a `list` is repeated items, each with its own named text fields.
SectionFieldKind = Literal["text", "rich_text", "list"]
QuestionVerdict = Literal["lost", "missing", "earned", "unmeasured"]


#: Where a field's copy comes from. `generated`: Meriwether writes it from
#: Share of Voice, the business, the page and the price list. `brand`: written
#: only from the organization's brand record (`SectionCopyRequest.brand`), and
#: left out when the record does not hold it. `manual` fields are a person's
#: alone and are never sent, so the value is refused rather than drafted.
#: Absent means `generated`, which is what every field meant before C20.
FieldSource = Literal["generated", "brand"]


class SectionItemField(BaseModel):
    """One field inside every item of a `list` field.

    An item field may itself be a `list` (FAQ groups -> questions, pricing
    plans -> features), with its own `item_fields`. That is the only level of
    nesting: a list inside a nested list is refused by `SectionTemplate`.
    """

    model_config = _INBOUND

    name: str
    max_length: int | None = Field(default=None, ge=1)
    kind: SectionFieldKind = "text"
    required: bool = False
    source: FieldSource = "generated"
    #: Only meaningful when `kind` is `list`.
    item_fields: list[SectionItemField] = Field(default_factory=list)


class SectionTemplateField(BaseModel):
    """One field of the site template's section, flattened by the gateway
    from the template's JSON Schema."""

    model_config = _INBOUND

    name: str
    max_length: int | None = Field(default=None, ge=1)
    kind: SectionFieldKind = "text"
    #: Only meaningful when `kind` is `list`.
    item_fields: list[SectionItemField] = Field(default_factory=list)
    required: bool = False
    #: A `brand` list field makes every value inside it a brand value.
    source: FieldSource = "generated"


def _check_item_fields(
    path: str, item_fields: list[SectionItemField], *, nested: bool
) -> None:
    """A list's item fields: present, uniquely named, and at most one level of
    list below them. `nested` is True for the item fields of a list that is
    itself inside a list item."""
    if not item_fields:
        raise ValueError(f"list field {path!r} declares no item_fields")
    names = [i.name for i in item_fields]
    if len(names) != len(set(names)):
        raise ValueError(f"item field names of {path!r} must be unique")
    for item in item_fields:
        if item.kind != "list":
            if item.item_fields:
                raise ValueError(
                    f"{path}.{item.name} declares item_fields but is not a list"
                )
            continue
        if nested:
            raise ValueError(
                f"{path}.{item.name} is a list inside a list inside a list item; "
                "a list item may hold only one level of list"
            )
        _check_item_fields(f"{path}.{item.name}", item.item_fields, nested=True)


class SectionLink(BaseModel):
    """Where a label field's link goes, so the label can say so.

    `field` names the label field: a template field when `item` is absent, or
    an item field of a list field when `item` is the 0-based index of the item.
    `target` is the title of the site page the link opens; None when the link
    leaves the site or the page is not known. A link naming a field the
    template does not declare is ignored, not refused.
    """

    model_config = _INBOUND

    field: str
    href: str
    target: str | None = None
    item: int | None = Field(default=None, ge=0)


class SectionTemplate(BaseModel):
    model_config = _INBOUND

    key: str
    name: str
    fields: list[SectionTemplateField] = Field(min_length=1)
    #: The links the section's label fields carry. Absent from an older gateway.
    links: list[SectionLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def _field_names_are_unique(self) -> SectionTemplate:
        # Fields are matched BY NAME everywhere downstream — the edit check, the
        # model's answer, the refusals — so two fields sharing a name would make
        # one of them unaddressable, and which one is an accident of ordering.
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("template field names must be unique")
        for field in self.fields:
            if field.kind == "list":
                _check_item_fields(field.name, field.item_fields, nested=False)
            elif field.item_fields:
                raise ValueError(
                    f"{field.name!r} declares item_fields but is not a list"
                )
        return self


class SectionPage(BaseModel):
    model_config = _INBOUND

    title: str
    page_type: str
    #: The page's address on the site, e.g. `/services/drain-cleaning`.
    address: str | None = None
    #: The live text of the page's OTHER sections, so the draft does not repeat
    #: them. Written by a person or an earlier accepted draft.
    other_sections_text: list[str] = Field(default_factory=list)


class TargetQuestion(BaseModel):
    """One question the section is meant to win, from Share of Voice."""

    model_config = _INBOUND

    #: The durable question id (`prompt_source_id` in the gateway).
    id: str
    text: str
    verdict: QuestionVerdict = "unmeasured"
    competitors: list[str] = Field(default_factory=list)
    top_cited_host: str | None = None


class PriceEntry(BaseModel):
    model_config = _INBOUND

    item: str
    price: str


class PricePolicy(BaseModel):
    """Whether this site allows prices in drafts, and the only ones it may use.

    Off unless the gateway says otherwise: a request that forgets the field
    gets the safe answer.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    allowed: bool = False
    #: Wire name `list`; `items` in Python so it does not shadow the builtin.
    items: list[PriceEntry] = Field(default_factory=list, alias="list")


class RejectedDraft(BaseModel):
    """A reason a person gave for rejecting an earlier draft of this same
    section or entry. The person's own words: shown to the model inside the
    data fence, never as an instruction."""

    model_config = _INBOUND

    reason: str
    at: str | None = None


class SectionCorpusDraft(BaseModel):
    """Another organization's draft from the same site template (similarity).

    Cross-tenant by design, like `CorpusArticle`: text only, no name, no host.
    """

    model_config = _INBOUND

    draft_id: str
    organization_id: str
    text: str


class SectionCopyRequest(BaseModel):
    model_config = _INBOUND

    task: Literal["section_copy"]
    #: What the copy is for: one section of a page, or one entry of a
    #: collection (a blog post, a case study), whose template is the
    #: collection's entry schema and whose page is the entry's own. Changes the
    #: prompt's wording only.
    subject: Literal["section", "entry"] = "section"
    template: SectionTemplate
    page: SectionPage
    questions: list[TargetQuestion] = Field(default_factory=list)
    #: The gateway's runtime-context payload, verbatim, as for articles.
    context: dict[str, Any] = Field(default_factory=dict)
    prices: PricePolicy = Field(default_factory=PricePolicy)
    #: The organization's brand record, from its brand onboarding: fact name ->
    #: value (a string, a number, or a list of them). The ONLY source for a
    #: `brand` field. Empty when absent, and then no brand field is drafted.
    brand: dict[str, Any] = Field(default_factory=dict)

    @field_validator("brand", mode="before")
    @classmethod
    def _no_brand_record_is_empty(cls, value: Any) -> Any:
        # `brand: null` is a gateway saying "no record", which is what empty means.
        return {} if value is None else value

    #: The section's live fields, a person's edits included. None on a first draft.
    current_fields: dict[str, Any] | None = None
    #: What drafting last produced for this section, before any person touched
    #: it. Required whenever `current_fields` is sent, for the reason
    #: `regenerate.py` gives: without it an edit and a draft are the same bytes.
    generated_baseline: dict[str, Any] | None = None
    edit_policy: Literal["preserve", "discard"] = "preserve"
    #: Why a person rejected earlier drafts of this section or entry, newest
    #: first. The gateway sends at most three; the prompt shows at most three.
    rejected: list[RejectedDraft] = Field(default_factory=list)

    corpus: list[SectionCorpusDraft] = Field(default_factory=list)


class FieldNote(BaseModel):
    model_config = _OUTBOUND

    #: Input ids the draft of this field drew on, as offered in the prompt —
    #: `question:<id>`, `price:<n>`, a fact name, `page.title`. Ids the model
    #: named that were never offered are dropped, not echoed.
    inputs_used: list[str] = Field(default_factory=list)


class SectionSimilarity(BaseModel):
    """`SimilarityMeasurement`, named for drafts. Recorded only, never enforced.

    `compared_count == 0` means UNMEASURED and `score` is then meaningless.
    """

    model_config = _OUTBOUND

    score: float
    nearest_draft_id: str | None
    nearest_organization_id: str | None
    compared_count: int
    duration_ms: int


class SectionCopyAudit(BaseModel):
    """`AuditRecord`'s fields, with the site template and the questions in
    place of the article template's service key and vertical."""

    model_config = _OUTBOUND

    template_key: str
    template_name: str
    question_ids: list[str] = Field(default_factory=list)
    context_version: str | None
    organization_id: str | None
    model_id: str
    build_version: str | None = None
    inputs_used: list[str] = Field(default_factory=list)
    #: The draft's notes for a person, over the copy THIS run drafted (not a
    #: person's preserved words). Measured, never enforced. Voice tells as for
    #: articles (`character:`, `phrase:`, `word:` — see
    #: `AuditRecord.voice_tells`), then `claim:<family> (<field>)` for a promise
    #: word no business input uses, then `disagreement:<line>` for each point
    #: the model found the record and the page disagree on. One list because it
    #: is the one the gateway already stores and shows.
    voice_tells: list[str] = Field(default_factory=list)


class SectionCopyResponse(BaseModel):
    model_config = _OUTBOUND

    task: Literal["section_copy"] = "section_copy"
    #: Field name -> a string (`text`, `rich_text`) or a list of items, each a
    #: name -> value mapping (`list`), where a value is a string or, for a list
    #: inside an item, a list of name -> string mappings. A field absent here was not drafted:
    #: it is in `refused` with the reason.
    fields: dict[str, Any] = Field(default_factory=dict)
    field_notes: dict[str, FieldNote] = Field(default_factory=dict)
    #: Field name -> why no draft is returned for it. A field the model drafted
    #: and a post-check removed lands here, as does one it never drafted.
    refused: dict[str, str] = Field(default_factory=dict)
    #: Fields a person edited, returned word for word (`preserve`).
    preserved_fields: list[str] = Field(default_factory=list)
    #: Fields a person edited that this run replaced (`discard`). Stated so the
    #: overwrite is never silent.
    discarded_fields: list[str] = Field(default_factory=list)
    edit_policy: Literal["preserve", "discard"]
    similarity: SectionSimilarity
    audit: SectionCopyAudit
    usage: TokenUsage = Field(default_factory=TokenUsage)
