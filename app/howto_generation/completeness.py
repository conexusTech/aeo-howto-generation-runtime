"""Does the generated article actually cover the template it was built from?

The content model (PO, 2026-09-04) is that the TEMPLATE carries the procedure:
the model keeps every step, in order, with its facts intact, and writes a fresh
intro and conclusion for this shop. `prompt.py` says all of that in words.

Nothing checked it. `parse_article` validates the SHAPE of each section — type
in the enum, heading and body are strings — and never compares the result to
the template. So a generation that silently dropped a step, or stopped before
writing the conclusion, was indistinguishable from a correct one.

That is not hypothetical: a real Bedrock run on 2026-09-07 returned an intro
and three steps and simply stopped, with no conclusion. Every other
content-model property held on the same run, which is exactly why it would have
shipped — the article looked finished.

**The requirement is derived from the template, never hardcoded.** A template
with no `outro` must not be forced to produce one; a template with six steps
must not come back with five. That is the difference between checking the
content model and inventing a house style.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Protocol


class _Sectioned(Protocol):
    """Anything carrying a `type` — template sections and generated ones alike."""

    type: str


#: Section types the model must REPRODUCE one-for-one, because they are the
#: procedure. A missing step is missing instructions.
PROCEDURE_TYPES = ("step", "tip")

#: Section types the model must REPLACE — one in, one out, but rewritten. It
#: may not carry the template's own text over (the prompt forbids that, and
#: `check_content_model.py` verifies it); it may not skip them either.
NARRATIVE_TYPES = ("intro", "outro")

_HUMAN = {
    "step": "step",
    "tip": "tip",
    "intro": "introduction",
    "outro": "conclusion",
}


@dataclass(frozen=True)
class Shortfall:
    """One section type the generation under-delivered on."""

    section_type: str
    expected: int
    produced: int

    def describe(self) -> str:
        noun = _HUMAN[self.section_type]
        if self.expected == 1 and self.produced == 0:
            return f"no {noun} was written"
        return (
            f"{self.produced} of {self.expected} "
            f"{noun}{'s' if self.expected != 1 else ''} were written"
        )


def _counts(sections: Iterable[_Sectioned]) -> Counter[str]:
    return Counter(section.type for section in sections)


def shortfalls(
    *,
    template_sections: Iterable[_Sectioned],
    generated_sections: Iterable[_Sectioned],
) -> list[Shortfall]:
    """Every section type the generation produced FEWER of than the template.

    Only shortfalls. A generation that adds a `tip` the template did not have
    is not a defect — the prompt allows the model to add guidance, and the
    procedure is still intact. Only losing content breaks the model.
    """
    expected = _counts(template_sections)
    produced = _counts(generated_sections)

    found: list[Shortfall] = []
    for section_type in (*PROCEDURE_TYPES, *NARRATIVE_TYPES):
        want = expected.get(section_type, 0)
        got = produced.get(section_type, 0)
        if want > 0 and got < want:
            found.append(
                Shortfall(section_type=section_type, expected=want, produced=got)
            )
    return found


def describe(found: list[Shortfall]) -> str:
    """A message naming what is missing, for the gateway to surface verbatim."""
    parts = [item.describe() for item in found]
    if len(parts) == 1:
        detail = parts[0]
    else:
        detail = f"{', '.join(parts[:-1])} and {parts[-1]}"
    return (
        f"the generated article does not cover its template: {detail}. "
        "The template carries the procedure, so a missing step is missing "
        "instructions, and a missing introduction or conclusion is the part "
        "that makes the article this shop's. Regenerate rather than publish."
    )
