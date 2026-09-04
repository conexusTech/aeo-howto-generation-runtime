"""HOW-4.6 — regeneration.

The criteria under test:

- the operation states which mode it ran in
- preserved edits survive verbatim
- human copy is never *silently* overwritten
"""

from __future__ import annotations

import pytest

from app.howto_generation.contracts import Section
from app.howto_generation.regenerate import (
    RegenerationRefused,
    find_human_edits,
    merge,
)


def section(position: int, heading: str, body: str, type_: str = "step") -> Section:
    return Section(type=type_, position=position, heading=heading, body_md=body)  # type: ignore[arg-type]


BASELINE = [
    section(1, "Why this matters", "Generated intro.", "intro"),
    section(2, "Check the interval", "Generated step one."),
    section(3, "Inspect the tensioner", "Generated step two."),
]

# The operator rewrote step one and left everything else alone.
CURRENT = [
    section(1, "Why this matters", "Generated intro.", "intro"),
    section(2, "Check the interval", "We always pull the cover first. — Dave"),
    section(3, "Inspect the tensioner", "Generated step two."),
]

REGENERATED = [
    section(1, "Why this matters", "Fresh intro.", "intro"),
    section(2, "Check the interval", "Fresh step one."),
    section(3, "Inspect the tensioner", "Fresh step two."),
]


class TestFindingEdits:
    def test_an_edited_section_is_detected(self) -> None:
        edits = find_human_edits(CURRENT, BASELINE)
        assert [s.heading for s in edits] == ["Check the interval"]

    def test_an_untouched_article_reports_no_edits(self) -> None:
        assert find_human_edits(BASELINE, BASELINE) == []

    def test_reordering_alone_is_not_an_edit(self) -> None:
        # Generation varies section order (HOW-4.3), so a positional match after
        # a re-order would report every section as edited — and a report where
        # everything is flagged is one nobody reads.
        reordered = [BASELINE[2], BASELINE[0], BASELINE[1]]
        assert find_human_edits(reordered, BASELINE) == []

    def test_a_section_with_no_counterpart_counts_as_human_added(self) -> None:
        added = [*BASELINE, section(4, "Our own tip", "Bring the vehicle in cold.")]
        edits = find_human_edits(added, BASELINE)
        assert [s.heading for s in edits] == ["Our own tip"]

    def test_an_alt_text_change_counts_as_an_edit(self) -> None:
        current = [
            BASELINE[0],
            BASELINE[1].model_copy(update={"image_alt": "a worn belt"}),
            BASELINE[2],
        ]
        assert len(find_human_edits(current, BASELINE)) == 1


class TestPreserve:
    def test_the_mode_is_stated(self) -> None:
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        assert result.outcome.mode == "preserve"

    def test_an_edited_section_survives_verbatim(self) -> None:
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        preserved = next(s for s in result.sections if s.heading == "Check the interval")
        assert preserved.body_md == "We always pull the cover first. — Dave"

    def test_unedited_sections_take_the_fresh_copy(self) -> None:
        # The point of regenerating. Preserve means preserve the EDITS, not
        # preserve the article.
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        fresh = next(s for s in result.sections if s.heading == "Why this matters")
        assert fresh.body_md == "Fresh intro."

    def test_an_edit_whose_heading_vanished_is_appended_not_dropped(self) -> None:
        # Losing human copy is the one unrecoverable outcome. An article with a
        # section in an odd place is a reviewer's five-second fix; an article
        # missing a paragraph somebody wrote is not recoverable from anything
        # this runtime returns.
        regenerated = [REGENERATED[0], REGENERATED[2]]
        result = merge(
            regenerated=regenerated,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        bodies = [s.body_md for s in result.sections]
        assert "We always pull the cover first. — Dave" in bodies

    def test_positions_come_back_contiguous_from_one(self) -> None:
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        assert [s.position for s in result.sections] == list(
            range(1, len(result.sections) + 1)
        )

    def test_the_preserved_positions_are_reported(self) -> None:
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        assert result.outcome.preserved_positions == [2]


class TestDiscard:
    def test_the_mode_is_stated(self) -> None:
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="discard",
        )
        assert result.outcome.mode == "discard"

    def test_the_edit_is_replaced_by_fresh_copy(self) -> None:
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="discard",
        )
        replaced = next(s for s in result.sections if s.heading == "Check the interval")
        assert replaced.body_md == "Fresh step one."

    def test_what_was_discarded_is_reported(self) -> None:
        # This is the difference between overwriting human copy and overwriting
        # it SILENTLY. Discarding is a legitimate outcome somebody asked for;
        # being unable to say it happened is not.
        result = merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="discard",
        )
        assert result.outcome.discarded_positions == [2]


class TestRefusals:
    def test_regeneration_without_a_baseline_is_refused(self) -> None:
        # In either mode. Without a baseline a human edit and a generated
        # paragraph are the same bytes: `discard` would overwrite human work
        # with no way to report it, and `preserve` would claim edits survived
        # while having no idea which ones they were.
        for policy in ("preserve", "discard"):
            with pytest.raises(RegenerationRefused) as caught:
                merge(
                    regenerated=REGENERATED,
                    current=CURRENT,
                    baseline=None,
                    policy=policy,
                )
            assert caught.value.error_code == "BASELINE_REQUIRED"

    def test_the_refusal_names_what_is_missing(self) -> None:
        with pytest.raises(RegenerationRefused) as caught:
            merge(
                regenerated=REGENERATED,
                current=CURRENT,
                baseline=None,
                policy="discard",
            )
        assert "generated_baseline" in caught.value.message

    def test_an_unknown_policy_is_refused(self) -> None:
        with pytest.raises(RegenerationRefused) as caught:
            merge(
                regenerated=REGENERATED,
                current=CURRENT,
                baseline=BASELINE,
                policy="merge_somehow",
            )
        assert caught.value.error_code == "INVALID_EDIT_POLICY"

    def test_a_first_generation_needs_no_baseline(self) -> None:
        # Nothing to merge and no edits to report.
        result = merge(
            regenerated=REGENERATED, current=None, baseline=None, policy="preserve"
        )
        assert [s.body_md for s in result.sections] == [
            "Fresh intro.",
            "Fresh step one.",
            "Fresh step two.",
        ]


class TestNoMutation:
    def test_the_inputs_are_not_modified(self) -> None:
        # `_renumber` assigns positions, and doing it in place would corrupt the
        # caller's baseline — which is also the object the audit trail describes.
        before = [s.model_copy(deep=True) for s in REGENERATED]
        merge(
            regenerated=REGENERATED,
            current=CURRENT,
            baseline=BASELINE,
            policy="preserve",
        )
        assert REGENERATED == before
