"""HOW-4.6 — regeneration, preserving or discarding human edits by explicit choice.

Three acceptance criteria, and the third governs the other two:

- the operation states which mode it ran in
- preserved edits survive verbatim
- **human copy is never silently overwritten**

"Silently" is the load-bearing word. Overwriting a human edit is a legitimate
outcome — it is what `discard` means, and somebody asked for it. What is not
legitimate is overwriting one without being able to say that it happened, which
is the state this module refuses to enter.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.howto_generation.contracts import RegenerationOutcome, Section


class RegenerationRefused(Exception):
    """A refusal, not a failure. Carries a code the gateway branches on."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class MergeResult:
    sections: list[Section]
    outcome: RegenerationOutcome


def _edit_key(section: Section) -> tuple[str, str, str | None, str | None]:
    """Everything about a section a human could have changed.

    Position is excluded on purpose: re-ordering sections is something
    generation does (HOW-4.3 varies ordering), so including it would report
    every section as edited the first time the order moved, and a report where
    everything is flagged is one nobody reads.
    """
    return (
        section.heading,
        section.body_md,
        section.image_asset_key,
        section.image_alt,
    )


def find_human_edits(
    current: list[Section], baseline: list[Section]
) -> list[Section]:
    """Sections of `current` a human changed since generation produced `baseline`.

    Matched by heading first, position second. Heading is the more stable
    identity of the two — generation may re-order sections, and a positional
    match after a re-order compares a step against an unrelated step and calls
    both of them edited.

    A section present in `current` with no counterpart in `baseline` at all is
    treated as human-added, which is the safe reading: the alternative is to
    assume generation produced it and let a later `discard` delete something a
    person wrote by hand.
    """
    by_heading = {s.heading: s for s in baseline}
    by_position = {s.position: s for s in baseline}

    edited: list[Section] = []
    for section in current:
        original = by_heading.get(section.heading) or by_position.get(section.position)
        if original is None or _edit_key(original) != _edit_key(section):
            edited.append(section)
    return edited


def merge(
    *,
    regenerated: list[Section],
    current: list[Section] | None,
    baseline: list[Section] | None,
    policy: str,
) -> MergeResult:
    """Combine freshly generated sections with what is already there.

    A first generation (`current` is None) has nothing to merge and no edits to
    report; anything else needs a baseline.

    🔴 **`generated_baseline` is required, in BOTH modes, and this is the one
    place this runtime refuses to proceed.** Without it, a human edit and a
    generated paragraph are the same bytes:

    - in `discard`, that means overwriting human copy with no way to say which
      copy was human — the exact thing the third criterion forbids;
    - in `preserve`, it means claiming edits survived verbatim while having no
      idea which ones they were, which is worse than failing, because it
      reports success.

    The gateway supplies the baseline. It is a real cross-repo dependency and
    it is recorded as one: `howto_articles.published_snapshot` is NULL on
    published rows today (measured 2026-09-03), so something has to retain what
    generation produced before regeneration can run at all.
    """
    if policy not in ("preserve", "discard"):
        raise RegenerationRefused(
            "INVALID_EDIT_POLICY",
            f"edit policy must be 'preserve' or 'discard', got {policy!r}",
        )

    if current is None:
        return MergeResult(
            sections=_renumber(regenerated),
            outcome=RegenerationOutcome(mode=policy),  # type: ignore[arg-type]
        )

    if baseline is None:
        raise RegenerationRefused(
            "BASELINE_REQUIRED",
            "regeneration needs `generated_baseline` — what generation last "
            "produced, before any human edit. Without it a human edit is "
            "indistinguishable from generated copy, so `discard` would "
            "overwrite human work without being able to report it and "
            "`preserve` would claim edits survived without knowing which ones.",
        )

    edited = find_human_edits(current, baseline)
    edited_by_heading = {s.heading: s for s in edited}

    if policy == "discard":
        # The regenerated article stands. The edits are reported so the
        # operation states what it threw away rather than merely which mode it
        # ran in — a mode name alone does not tell a reviewer what was lost.
        return MergeResult(
            sections=_renumber(regenerated),
            outcome=RegenerationOutcome(
                mode="discard",
                discarded_positions=sorted(s.position for s in edited),
            ),
        )

    merged: list[Section] = []
    preserved_headings: set[str] = set()

    for section in regenerated:
        human = edited_by_heading.get(section.heading)
        if human is not None:
            # Verbatim. Not merged, not re-flowed, not re-numbered until the
            # final pass — the criterion says survive verbatim and a helpful
            # tidy-up here is exactly the silent change it forbids.
            merged.append(human.model_copy(deep=True))
            preserved_headings.add(section.heading)
        else:
            merged.append(section.model_copy(deep=True))

    # An edited section whose heading no longer appears in the regenerated
    # article is APPENDED rather than dropped. Losing human copy is the one
    # unrecoverable outcome here, and an article with a section in an odd place
    # is a reviewer's five-second fix; an article missing a paragraph somebody
    # wrote is not recoverable from anything this runtime returns.
    for section in edited:
        if section.heading not in preserved_headings:
            merged.append(section.model_copy(deep=True))
            preserved_headings.add(section.heading)

    return MergeResult(
        sections=_renumber(merged),
        outcome=RegenerationOutcome(
            mode="preserve",
            preserved_positions=sorted(s.position for s in edited),
        ),
    )


def _renumber(sections: list[Section]) -> list[Section]:
    """Contiguous from 1, matching the gateway's stored invariant."""
    out: list[Section] = []
    for index, section in enumerate(sections, start=1):
        copy = section.model_copy(deep=True)
        copy.position = index
        out.append(copy)
    return out
