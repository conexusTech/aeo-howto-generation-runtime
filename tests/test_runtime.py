"""The deterministic spine, end to end with a fake model.

HOW-4.1's criteria live here: produces a complete draft, is re-runnable, and
**the exact inputs used are recorded for audit**.
"""

from __future__ import annotations

from app.config import Settings
from app.howto_generation import runtime
from app.howto_generation.contracts import (
    CorpusArticle,
    ErrorResponse,
    GenerationRequest,
    GenerationResponse,
    Section,
    Template,
    TemplateSlot,
)
from app.howto_generation.model import FakeChatModel, GeneratedArticle

SETTINGS = Settings(
    HOWTO_GENERATION_MODEL_ID="anthropic.claude-sonnet-5",
    HOWTO_GENERATION_BUILD_VERSION="",
)

CONTEXT = {
    "context_version": "2026-09-03T10:00:00Z",
    "organization": {
        "id": "org-1",
        "name": "Auto Care Guy",
        "address": "412 Kirkwood Ave, Springfield, IL 62701, USA",
    },
}

TEMPLATE = Template(
    id="tpl-1",
    service_key="timing-belt",
    vertical="auto-repair",
    title="How to replace a timing belt",
    sections=[],
    slots=[
        TemplateSlot(name="shop_name", description=None, required=True),
        TemplateSlot(name="city", description=None, required=False),
        TemplateSlot(name="price_band", description=None, required=False),
        TemplateSlot(name="cta", description=None, required=False),
    ],
)


def request(**overrides) -> GenerationRequest:
    payload = {"operation": "generate", "template": TEMPLATE, "context": CONTEXT}
    payload.update(overrides)
    return GenerationRequest(**payload)


def run(req: GenerationRequest, model=None):
    return runtime.handle(
        req, model=model or FakeChatModel(), settings=SETTINGS
    )


class TestProducesADraft:
    def test_a_complete_draft_comes_back(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.sections
        assert result.title

    def test_positions_are_contiguous_from_one(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert [s.position for s in result.sections] == list(
            range(1, len(result.sections) + 1)
        )

    def test_it_is_rerunnable(self) -> None:
        # HOW-4.1 says re-runnable. With a deterministic model the whole
        # pipeline is a pure function of its inputs, so two runs agree on
        # everything except timing.
        first = run(request())
        second = run(request())
        assert isinstance(first, GenerationResponse)
        assert isinstance(second, GenerationResponse)
        assert first.sections == second.sections
        assert first.slots == second.slots

    def test_the_template_title_is_the_fallback_when_the_model_gives_none(self) -> None:
        model = FakeChatModel(
            GeneratedArticle(
                title="",
                sections=[
                    Section(type="intro", position=1, heading="H", body_md="B")
                ],
            )
        )
        result = run(request(), model)
        assert isinstance(result, GenerationResponse)
        assert result.title == TEMPLATE.title

    def test_an_article_with_no_usable_sections_is_a_named_refusal(self) -> None:
        # Not an exception. An empty article cannot be published and must not
        # be returned as though it could; whether to retry is the gateway's
        # decision to make.
        model = FakeChatModel(GeneratedArticle(title="T", sections=[]))
        result = run(request(), model)
        assert isinstance(result, ErrorResponse)
        assert result.error_code == "EMPTY_ARTICLE"


class TestSlotsFlowThrough:
    def test_resolved_refused_and_omitted_all_reach_the_response(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.slots.resolved["shop_name"] == "Auto Care Guy"
        assert result.slots.resolved["city"] == "Springfield"
        assert "price_band" in result.slots.refused
        assert "cta" in result.slots.omitted

    def test_the_refusal_reaches_the_prompt_the_model_saw(self) -> None:
        # The chain that matters: a refusal recorded in the response but absent
        # from the prompt would let the model write a price anyway.
        model = FakeChatModel()
        run(request(), model)
        _, volatile = model.calls[0].split()
        assert "price_band" in volatile
        assert "FORBIDDEN" in volatile


class TestAudit:
    def test_the_audit_records_the_context_version(self) -> None:
        # The gateway's opaque token changes whenever onboarding data changes,
        # so it pins the org snapshot generation actually saw.
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.audit.context_version == "2026-09-03T10:00:00Z"

    def test_the_audit_records_which_fields_were_read(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.audit.inputs_used == [
            "derived:organization.address",
            "organization.name",
        ]

    def test_the_audit_records_the_template_and_the_model(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.audit.template_id == "tpl-1"
        assert result.audit.template_service_key == "timing-belt"
        assert result.audit.model_id == "anthropic.claude-sonnet-5"
        assert result.audit.organization_id == "org-1"

    def test_an_unstamped_build_is_omitted_rather_than_reported_unknown(self) -> None:
        # A deploy that forgot to stamp should look different from one that
        # stamped a placeholder.
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.audit.build_version is None

    def test_a_stamped_build_is_reported(self) -> None:
        settings = Settings(HOWTO_GENERATION_BUILD_VERSION="abc1234")
        result = runtime.handle(request(), model=FakeChatModel(), settings=settings)
        assert isinstance(result, GenerationResponse)
        assert result.audit.build_version == "abc1234"


class TestSimilarityIsMeasured:
    def test_an_empty_corpus_reports_zero_comparisons(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.similarity is not None
        assert result.similarity.compared_count == 0

    def test_a_populated_corpus_produces_a_neighbour(self) -> None:
        result = run(
            request(
                corpus=[
                    CorpusArticle(
                        article_id="a2",
                        organization_id="org-2",
                        body="A timing belt failure is not a repair you schedule.",
                    )
                ]
            )
        )
        assert isinstance(result, GenerationResponse)
        assert result.similarity is not None
        assert result.similarity.compared_count == 1
        assert result.similarity.nearest_article_id == "a2"

    def test_measurement_never_blocks_the_draft(self) -> None:
        # HOW-4.4 is recorded only. An article identical to a sibling still
        # comes back as a draft.
        model = FakeChatModel()
        identical = model.generate(prompt=None)  # type: ignore[arg-type]
        body = "\n\n".join(f"{s.heading}\n{s.body_md}" for s in identical.sections)
        result = run(
            request(
                corpus=[
                    CorpusArticle(article_id="a", organization_id="o", body=body)
                ]
            )
        )
        assert isinstance(result, GenerationResponse)
        assert result.similarity is not None
        assert result.similarity.score > 0.9
        assert result.sections


class TestRegeneration:
    def test_a_regeneration_without_a_baseline_is_refused(self) -> None:
        result = run(
            request(
                operation="regenerate",
                current_article=[
                    Section(type="intro", position=1, heading="H", body_md="B")
                ],
                generated_baseline=None,
                edit_policy="discard",
            )
        )
        assert isinstance(result, ErrorResponse)
        assert result.error_code == "BASELINE_REQUIRED"

    def test_a_regeneration_reports_its_mode(self) -> None:
        baseline = [Section(type="intro", position=1, heading="Why this matters", body_md="old")]
        result = run(
            request(
                operation="regenerate",
                current_article=baseline,
                generated_baseline=baseline,
                edit_policy="preserve",
            )
        )
        assert isinstance(result, GenerationResponse)
        assert result.regeneration is not None
        assert result.regeneration.mode == "preserve"

    def test_a_first_generation_carries_no_regeneration_block(self) -> None:
        result = run(request())
        assert isinstance(result, GenerationResponse)
        assert result.regeneration is None
