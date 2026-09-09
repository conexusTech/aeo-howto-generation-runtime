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

from pydantic import BaseModel, ConfigDict, Field

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


class GenerationRequest(BaseModel):
    model_config = _INBOUND

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
