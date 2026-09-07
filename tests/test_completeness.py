"""The generated article must cover the template it was built from.

Regression cover for a defect a real Bedrock run produced on 2026-09-07: intro
plus three steps, no conclusion. Every other content-model property held on the
same run, so the article looked finished and would have published.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.howto_generation import completeness


@dataclass(frozen=True)
class S:
    """Minimal stand-in — `shortfalls` only ever reads `.type`."""

    type: str


def sections(*types: str) -> list[S]:
    return [S(type=t) for t in types]


TEMPLATE = sections("intro", "step", "step", "tip", "outro")


def types_of(found: list[completeness.Shortfall]) -> set[str]:
    return {item.section_type for item in found}


class TestCoversTemplate:
    def test_an_identical_shape_is_complete(self) -> None:
        assert (
            completeness.shortfalls(
                template_sections=TEMPLATE, generated_sections=TEMPLATE
            )
            == []
        )

    def test_the_observed_failure_is_caught(self) -> None:
        """intro + steps, no conclusion — exactly what the live model returned."""
        found = completeness.shortfalls(
            template_sections=TEMPLATE,
            generated_sections=sections("intro", "step", "step", "tip"),
        )
        assert types_of(found) == {"outro"}
        assert "no conclusion was written" in completeness.describe(found)

    def test_a_dropped_step_is_caught(self) -> None:
        """The bigger hole the same gap left open: missing instructions."""
        found = completeness.shortfalls(
            template_sections=TEMPLATE,
            generated_sections=sections("intro", "step", "tip", "outro"),
        )
        assert types_of(found) == {"step"}
        assert "1 of 2 steps were written" in completeness.describe(found)

    def test_several_shortfalls_are_all_reported(self) -> None:
        found = completeness.shortfalls(
            template_sections=TEMPLATE, generated_sections=sections("step")
        )
        assert types_of(found) == {"intro", "step", "tip", "outro"}


class TestDerivedFromTheTemplate:
    """The requirement comes from the template, never from a house rule."""

    def test_a_template_with_no_conclusion_does_not_demand_one(self) -> None:
        # CONTROL for the whole design. A blanket "always require an outro"
        # would fail here, and would be inventing a style rather than checking
        # the content model.
        template = sections("intro", "step")
        assert (
            completeness.shortfalls(
                template_sections=template,
                generated_sections=sections("intro", "step"),
            )
            == []
        )

    def test_a_template_with_six_steps_demands_six(self) -> None:
        template = sections(*(["step"] * 6))
        found = completeness.shortfalls(
            template_sections=template, generated_sections=sections(*(["step"] * 5))
        )
        assert types_of(found) == {"step"}

    def test_adding_a_tip_is_not_a_shortfall(self) -> None:
        # The prompt lets the model add guidance. Only LOSING content breaks
        # the model, so extra sections must not be refused.
        found = completeness.shortfalls(
            template_sections=TEMPLATE,
            generated_sections=sections(
                "intro", "step", "step", "tip", "tip", "tip", "outro"
            ),
        )
        assert found == []

    def test_an_empty_template_demands_nothing(self) -> None:
        assert (
            completeness.shortfalls(
                template_sections=[], generated_sections=sections("intro")
            )
            == []
        )


class TestMessage:
    @pytest.mark.parametrize(
        "generated,expected_phrase",
        [
            (sections("intro", "step", "step", "tip"), "no conclusion was written"),
            (sections("step", "step", "tip", "outro"), "no introduction was written"),
        ],
    )
    def test_names_what_is_missing(
        self, generated: list[S], expected_phrase: str
    ) -> None:
        message = completeness.describe(
            completeness.shortfalls(
                template_sections=TEMPLATE, generated_sections=generated
            )
        )
        assert expected_phrase in message
        # The message reaches a human through the gateway, so it has to say what
        # to do — "malformed output" tells a reviewer nothing actionable.
        assert "Regenerate rather than publish" in message
