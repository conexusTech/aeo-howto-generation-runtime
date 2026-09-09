"""One generation, end to end. The deterministic spine.

Order matters and is not arbitrary:

1. **Resolve slots first.** Everything downstream depends on knowing which facts
   exist, and the refusals have to be in hand before the prompt is written — a
   prompt composed before the pricing refusal is known is a prompt that never
   mentions it.
2. **Generate.** The only model call.
3. **Merge**, on a regeneration.
4. **Measure**, against the corpus.
5. **Record** what was read.

Steps 1, 3, 4 and 5 are pure functions over their inputs and are tested without
a model. Step 2 is behind `ChatModel` and is tested with a fake. There is no
path through this module that requires AWS.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.howto_generation import voice
from app.howto_generation import completeness
from app.howto_generation import prompt as prompt_module
from app.howto_generation import regenerate, similarity, slots
from app.howto_generation.contracts import (
    AuditRecord,
    ErrorResponse,
    GenerationRequest,
    GenerationResponse,
    Section,
    TokenUsage,
)
from app.howto_generation.model import ChatModel

logger = logging.getLogger(__name__)


def _organization_id(context: dict[str, Any]) -> str | None:
    organization = context.get("organization")
    if isinstance(organization, dict):
        value = organization.get("id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _context_version(context: dict[str, Any]) -> str | None:
    value = context.get("context_version")
    return value.strip() if isinstance(value, str) and value.strip() else None


def handle(
    request: GenerationRequest, *, model: ChatModel, settings: Settings
) -> GenerationResponse | ErrorResponse:
    """Produce one draft article, plus its measurement and its audit trail.

    Returns an `ErrorResponse` rather than raising for anything the gateway can
    act on. Only genuinely unexpected failures propagate, and the server turns
    those into a typed body too — see `server.py` for why nothing here answers
    with a non-2xx status.
    """
    resolution = slots.resolve_slots(request.template.slots, request.context)

    composition = prompt_module.compose(
        template=request.template,
        context=request.context,
        slots=resolution,
        regenerating=request.operation == "regenerate",
    )

    generated = model.generate(prompt=composition)

    if not generated.sections:
        # An article with no sections cannot be published and must not be
        # returned as though it could. This is a named outcome rather than an
        # exception because the gateway's response to it — retry, or surface to
        # an operator — is a decision it owns.
        return ErrorResponse(
            error_code="EMPTY_ARTICLE",
            message=(
                "the model returned no usable sections. Every section it "
                "produced was missing a heading or body, or carried a type "
                "outside intro/step/tip/outro."
            ),
        )

    # 🔴 Does the article actually cover its template?
    #
    # `parse_article` checks each section's SHAPE and never compares the result
    # to the template, so a generation that dropped a step — or stopped before
    # the conclusion — was indistinguishable from a correct one. A real Bedrock
    # run on 2026-09-07 returned intro + three steps and stopped; every other
    # content-model property held, which is precisely why it would have shipped.
    #
    # Checked on the FIRST pass only. A regeneration merges against the current
    # article under an edit policy, so its section set is legitimately not the
    # template's — asserting template coverage there would refuse valid edits.
    if request.operation != "regenerate":
        missing = completeness.shortfalls(
            template_sections=request.template.sections,
            generated_sections=generated.sections,
        )
        if missing:
            return ErrorResponse(
                error_code="INCOMPLETE_ARTICLE",
                message=completeness.describe(missing),
            )

    sections: list[Section] = generated.sections
    regeneration_outcome = None

    if request.operation == "regenerate":
        try:
            merged = regenerate.merge(
                regenerated=generated.sections,
                current=request.current_article,
                baseline=request.generated_baseline,
                policy=request.edit_policy,
            )
        except regenerate.RegenerationRefused as refusal:
            return ErrorResponse(
                error_code=refusal.error_code, message=refusal.message
            )
        sections = merged.sections
        regeneration_outcome = merged.outcome
    else:
        sections = [
            section.model_copy(update={"position": index})
            for index, section in enumerate(generated.sections, start=1)
        ]

    measurement = similarity.measure(
        similarity.body_text(sections),
        request.corpus,
        chrome_blocks=request.chrome_blocks,
        num_perm=settings.HOWTO_GENERATION_MINHASH_PERMUTATIONS,
    )

    audit = AuditRecord(
        template_id=request.template.id,
        template_service_key=request.template.service_key,
        template_vertical=request.template.vertical,
        context_version=_context_version(request.context),
        organization_id=_organization_id(request.context),
        model_id=settings.HOWTO_GENERATION_MODEL_ID,
        # Empty means unstamped, and the field is omitted rather than reported
        # as "unknown" — a deploy that forgot to stamp should look different
        # from one that stamped a placeholder.
        build_version=settings.HOWTO_GENERATION_BUILD_VERSION or None,
        inputs_used=slots.inputs_used(resolution),
        # Over the copy that is actually going out, headings included — not
        # over the prompt. The prompt LISTS the banned characters in order to
        # forbid them, so checking the prompt would report every one of them
        # forever. This repo's own notes call that shape out: an acceptance
        # criterion must not forbid its own proof.
        voice_tells=voice.find_tells(
            (generated.title or request.template.title)
            + " " + similarity.body_text(sections)
        ),
    )

    return GenerationResponse(
        operation=request.operation,
        title=generated.title or request.template.title,
        sections=sections,
        slots=resolution,
        similarity=measurement,
        regeneration=regeneration_outcome,
        audit=audit,
        usage=generated.usage or TokenUsage(),
    )
