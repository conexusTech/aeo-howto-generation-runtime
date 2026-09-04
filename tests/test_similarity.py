"""HOW-4.4 — similarity measurement.

The criteria under test:

- a score and a nearest-neighbour reference are stored per article
- boilerplate is excluded, **verified by confirming two articles sharing only
  chrome score near zero**
- publication is never blocked and no alert is raised
- the comparison's duration and the number of articles compared are recorded
"""

from __future__ import annotations

import pytest

from app.howto_generation.contracts import CorpusArticle, Section
from app.howto_generation.similarity import (
    SHINGLE_SIZE,
    body_text,
    estimate_jaccard,
    exact_jaccard,
    measure,
    normalize,
    shingles,
    signature,
    strip_markdown,
)

CHROME = (
    "Book your appointment today. Call the shop or use the online form. "
    "We service all makes and models and stand behind every repair."
)

BODY_A = (
    "A timing belt drives the camshaft in step with the crankshaft. When it "
    "snaps on an interference engine the valves meet the pistons and the "
    "damage runs past the belt itself into the head."
)

BODY_B = (
    "Brake fluid absorbs water out of the air over time. Once the moisture "
    "content climbs the boiling point drops, and a long descent can put vapour "
    "in the line where hydraulic pressure ought to be."
)


class TestNormalization:
    def test_markdown_syntax_is_removed(self) -> None:
        text = "## Heading\n\n- a bullet\n> a quote\n**bold** and `code`"
        stripped = strip_markdown(text)
        assert "##" not in stripped
        assert ">" not in stripped
        assert "- a bullet" not in stripped
        assert "bullet" in stripped

    def test_link_text_survives_but_the_url_does_not(self) -> None:
        tokens = normalize("See [the service interval](https://example.com/specs).")
        assert "interval" in tokens
        assert not any("example" in t for t in tokens)

    def test_images_are_dropped_whole(self) -> None:
        # Alt text is separate data on the section; leaving it in the body would
        # count the same words twice.
        tokens = normalize("![a worn belt](/assets/belt.png) Text after.")
        assert "belt" not in tokens
        assert "text" in tokens

    def test_case_and_punctuation_do_not_affect_tokens(self) -> None:
        assert normalize("Timing-Belt, replaced!") == normalize("timing belt replaced")


class TestShingles:
    def test_shingles_are_five_words_long(self) -> None:
        tokens = "a b c d e f".split()
        result = shingles(tokens)
        assert result == {"a b c d e", "b c d e f"}
        assert all(len(s.split()) == SHINGLE_SIZE for s in result)

    def test_a_document_shorter_than_the_window_yields_one_shingle(self) -> None:
        # Otherwise two identical three-word documents score as completely
        # dissimilar, which is not a defensible thing for a duplication metric
        # to say about identical text.
        assert shingles(["a", "b", "c"]) == {"a b c"}
        assert exact_jaccard(shingles(["a", "b", "c"]), shingles(["a", "b", "c"])) == 1.0

    def test_an_empty_document_yields_no_shingles(self) -> None:
        assert shingles([]) == set()


class TestMinHash:
    def test_the_signature_is_deterministic_across_calls(self) -> None:
        # 🔴 The property the whole stored history depends on. Python randomises
        # `hash()` per process, so a MinHash built on it changes every run while
        # still returning plausible numbers in [0, 1] — a silent failure that
        # would turn the calibration data into noise.
        target = shingles(normalize(BODY_A))
        assert signature(target, 64) == signature(target, 64)

    def test_the_signature_does_not_depend_on_set_iteration_order(self) -> None:
        # Python set ordering varies with insertion history; the signature is a
        # minimum over the whole set and must not.
        forward = {"a b c d e", "f g h i j", "k l m n o"}
        backward = {"k l m n o", "f g h i j", "a b c d e"}
        assert signature(forward, 64) == signature(backward, 64)

    def test_the_estimate_tracks_exact_jaccard(self) -> None:
        # Bounds the estimator against ground truth rather than asserting an
        # exact value, which would only be asserting the seed.
        left = shingles(normalize(BODY_A + " " + BODY_B))
        right = shingles(normalize(BODY_A))
        estimated = estimate_jaccard(signature(left, 256), signature(right, 256))
        exact = exact_jaccard(left, right)
        assert abs(estimated - exact) < 0.10

    def test_identical_documents_score_one(self) -> None:
        target = shingles(normalize(BODY_A))
        assert estimate_jaccard(signature(target, 128), signature(target, 128)) == 1.0

    def test_two_empty_documents_score_zero_not_one(self) -> None:
        # Jaccard is undefined on two empty sets. Of the two available answers,
        # only 0.0 avoids reporting a data-loading bug as maximum duplication.
        assert exact_jaccard(set(), set()) == 0.0

    def test_mismatched_signature_lengths_are_an_error(self) -> None:
        with pytest.raises(ValueError):
            estimate_jaccard(signature(set(), 32), signature(set(), 64))


class TestChromeExclusion:
    """The named acceptance criterion, plus the control that proves it fires."""

    def test_two_articles_sharing_only_chrome_score_near_zero(self) -> None:
        left = f"{CHROME}\n\n{BODY_A}"
        right = f"{CHROME}\n\n{BODY_B}"
        result = measure(
            left,
            [CorpusArticle(article_id="a2", organization_id="org-2", body=right)],
            chrome_blocks=[CHROME],
        )
        assert result.score < 0.02

    def test_without_stripping_the_same_pair_scores_materially_higher(self) -> None:
        # The control. Without it the test above passes just as happily when
        # `chrome_blocks` does nothing at all, and a check that cannot fail
        # proves nothing.
        left = f"{CHROME}\n\n{BODY_A}"
        right = f"{CHROME}\n\n{BODY_B}"
        stripped = measure(
            left,
            [CorpusArticle(article_id="a2", organization_id="org-2", body=right)],
            chrome_blocks=[CHROME],
        ).score
        unstripped = measure(
            left,
            [CorpusArticle(article_id="a2", organization_id="org-2", body=right)],
        ).score
        assert unstripped > stripped
        assert unstripped > 0.15

    def test_renderer_chrome_cannot_reach_the_metric_at_all(self) -> None:
        # Nav, header and footer live in aeo-howto-web and are never part of an
        # article row, so the measurement only ever sees section text.
        sections = [
            Section(type="intro", position=1, heading="Why", body_md=BODY_A),
        ]
        assert "<nav" not in body_text(sections)
        assert BODY_A in body_text(sections)


class TestMeasurement:
    def test_a_near_duplicate_scores_high(self) -> None:
        near = BODY_A.replace("snaps", "breaks")
        result = measure(
            BODY_A, [CorpusArticle(article_id="a2", organization_id="org-2", body=near)]
        )
        assert result.score > 0.5

    def test_the_nearest_neighbour_is_the_one_reported(self) -> None:
        near = BODY_A.replace("snaps", "breaks")
        result = measure(
            BODY_A,
            [
                CorpusArticle(article_id="far", organization_id="org-3", body=BODY_B),
                CorpusArticle(article_id="near", organization_id="org-2", body=near),
            ],
        )
        assert result.nearest_article_id == "near"
        assert result.nearest_organization_id == "org-2"
        assert result.compared_count == 2

    def test_an_empty_corpus_reports_zero_comparisons(self) -> None:
        # And the score is 0.0 meaning UNMEASURED, not "perfectly distinct".
        # Consumers have to read `compared_count` before `score`.
        result = measure(BODY_A, [])
        assert result.compared_count == 0
        assert result.score == 0.0
        assert result.nearest_article_id is None

    def test_an_article_is_never_compared_against_itself(self) -> None:
        result = measure(
            BODY_A,
            [CorpusArticle(article_id="self", organization_id="org-1", body=BODY_A)],
            exclude_article_id="self",
        )
        assert result.compared_count == 0

    def test_duration_and_count_are_recorded(self) -> None:
        # The evidence HOW-4.4 asks for in place of a guessed corpus ceiling:
        # moving this off the publish path becomes a decision with numbers
        # behind it rather than a guess about the fiftieth shop.
        result = measure(
            BODY_A,
            [
                CorpusArticle(article_id=f"a{i}", organization_id="org-2", body=BODY_B)
                for i in range(5)
            ],
        )
        assert result.compared_count == 5
        assert result.duration_ms >= 0

    def test_the_score_stays_inside_the_stored_columns_bounds(self) -> None:
        # The gateway column is numeric(7,4) with a ratio CHECK; a score outside
        # [0, 1] is rejected at the database, which is a bad place to find out.
        for body in (BODY_A, BODY_B, "", CHROME):
            result = measure(
                body,
                [CorpusArticle(article_id="a", organization_id="o", body=BODY_A)],
            )
            assert 0.0 <= result.score <= 1.0

    def test_measurement_blocks_nothing_and_raises_nothing(self) -> None:
        # HOW-4.4 is recorded only. There is no threshold, no exception and no
        # alert anywhere in this module — the assertion is that a maximally
        # duplicate article still just returns a number.
        result = measure(
            BODY_A, [CorpusArticle(article_id="a", organization_id="o", body=BODY_A)]
        )
        assert result.score == 1.0
