"""HOW-4.4 — lexical similarity measurement, recorded and never enforced.

The metric is fixed by the PRD and is not a free choice: **Jaccard similarity
over 5-word shingles via MinHash**, on body text with chrome stripped, against
the nearest neighbour.

**Lexical, deliberately — not semantic.** Two genuinely distinct articles about
the same repair are *supposed* to be semantically close; they are about the same
repair. An embedding metric would score good, differentiated content as
duplicate and would be at its most confident exactly when it was most wrong.
Word-level overlap is the signal, because word-level overlap is what a search
index collapses on.

This module blocks nothing and alerts nothing. It returns a number, a neighbour
reference, and the two figures HOW-4.4 asks for in place of a guessed corpus
ceiling: how many articles were compared, and how long it took.

Implemented in stdlib rather than on `datasketch`, and that is a decision rather
than an omission. The metric above is specified tightly enough that "whatever
the library does" is not an acceptable answer to "what does this score mean",
and the acceptance criteria ride on the exact behaviour. Forty lines of hashing
that we can point at beats a dependency we would have to characterise anyway.
"""

from __future__ import annotations

import hashlib
import re
import time

from app.howto_generation.contracts import CorpusArticle, SimilarityMeasurement

#: 5-word shingles, per HOW-4.4. Not tunable: the stored scores are only
#: comparable to each other while every one of them was computed the same way,
#: and V2 threshold calibration reads the whole history.
SHINGLE_SIZE = 5

#: Mersenne prime 2^61 - 1, the standard MinHash modulus.
_PRIME = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1

# --- Markdown furniture -----------------------------------------------------
# Order matters: images before links, or `![alt](url)` loses its `!` and becomes
# a link whose text is the alt.
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_BULLET = re.compile(r"^\s{0,3}([-*+]|\d+\.)\s+", re.MULTILINE)
_RULE = re.compile(r"^\s{0,3}([-*_])\s*(\1\s*){2,}$", re.MULTILINE)
_NON_WORD = re.compile(r"[^a-z0-9]+")


def strip_markdown(text: str) -> str:
    """Remove markdown syntax, keeping the words a reader would actually read.

    Syntax is shared by every document we generate, so leaving it in inflates
    the similarity of any two markdown files toward each other regardless of
    what they say. Link URLs go for the same reason and one stronger: a template
    linking to the same reference from every shop's article is furniture, and
    counting it would make articles look alike for a reason unrelated to prose.
    """
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)
    text = _RULE.sub(" ", text)
    text = _HEADING.sub(" ", text)
    text = _BLOCKQUOTE.sub(" ", text)
    text = _BULLET.sub(" ", text)
    return text


def normalize(text: str, chrome_blocks: list[str] | None = None) -> list[str]:
    """Body text to a comparable token list.

    Renderer chrome — nav, header, footer, breadcrumb, JSON-LD — is excluded by
    construction and not by this function: it lives in `aeo-howto-web` and is
    never part of an article row, so it cannot reach here. `chrome_blocks` is
    for the other kind: boilerplate a caller knows the TEMPLATE put into the
    body, identical across every shop using it, which would otherwise be counted
    as shop-to-shop similarity when it is really template-to-itself.
    """
    for block in chrome_blocks or []:
        normalized_block = block.strip()
        if normalized_block:
            text = text.replace(normalized_block, " ")
    text = strip_markdown(text)
    return [token for token in _NON_WORD.sub(" ", text.lower()).split() if token]


def shingles(tokens: list[str], size: int = SHINGLE_SIZE) -> set[str]:
    """Overlapping k-word shingles.

    A document shorter than `size` yields ONE shingle of everything it has,
    rather than none. The alternative scores two identical three-word documents
    as completely dissimilar, which is not a defensible thing for a
    duplication metric to say about identical text.
    """
    if not tokens:
        return set()
    if len(tokens) < size:
        return {" ".join(tokens)}
    return {
        " ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)
    }


def _stable_hash(value: str) -> int:
    """A 32-bit hash that is the same in every process, forever.

    🔴 **Do not replace this with `hash()`.** Python randomises string hashing
    per process unless `PYTHONHASHSEED` is set, so a MinHash built on it would
    produce a different signature on every run — and the failure is silent,
    because the scores still come back as plausible numbers in [0, 1]. Two
    articles compared today and re-compared tomorrow would disagree, and the
    stored history that V2 threshold calibration depends on would be noise
    wearing four decimal places.
    """
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & _MAX_HASH


def _permutation_params(num_perm: int) -> list[tuple[int, int]]:
    """Deterministic (a, b) coefficients for `(a*h + b) mod p`.

    Derived from blake2b of the index rather than from `random.Random(seed)`.
    Both are reproducible in practice, but the stdlib RNG's mapping from seed to
    output is an implementation detail of CPython and this one is a written-down
    function of the index — and these coefficients have to outlive several
    Python upgrades for the stored scores to stay comparable.
    """
    params: list[tuple[int, int]] = []
    for i in range(num_perm):
        a_digest = hashlib.blake2b(f"minhash-a-{i}".encode(), digest_size=8).digest()
        b_digest = hashlib.blake2b(f"minhash-b-{i}".encode(), digest_size=8).digest()
        a = (int.from_bytes(a_digest, "big") % (_PRIME - 1)) + 1  # a must be non-zero
        b = int.from_bytes(b_digest, "big") % _PRIME
        params.append((a, b))
    return params


def signature(shingle_set: set[str], num_perm: int = 256) -> tuple[int, ...]:
    """The MinHash signature: the minimum hash under each permutation.

    An empty set yields all-`_PRIME` sentinels, which compare equal to each
    other — handled explicitly in `estimate_jaccard` rather than being allowed
    to read as a perfect match.
    """
    params = _permutation_params(num_perm)
    if not shingle_set:
        return tuple(_PRIME for _ in range(num_perm))
    hashes = [_stable_hash(s) for s in shingle_set]
    return tuple(
        min(((a * h + b) % _PRIME) for h in hashes) for a, b in params
    )


def estimate_jaccard(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    """The MinHash estimate: the fraction of positions that agree.

    Accurate to roughly 1/sqrt(num_perm) — about 6% at the default 256. The
    tests bound it against `exact_jaccard` rather than asserting exact values,
    because asserting an estimator's exact output is asserting the seed.
    """
    if len(left) != len(right):
        raise ValueError("signatures must have the same permutation count")
    if not left:
        return 0.0
    return sum(1 for a, b in zip(left, right) if a == b) / len(left)


def exact_jaccard(left: set[str], right: set[str]) -> float:
    """Ground truth for the estimator. Not used in the measurement path.

    Two empty documents score 0.0, not 1.0. Jaccard is undefined on a pair of
    empty sets, and of the two available answers only one avoids reporting a
    data-loading bug as maximum duplication.
    """
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def measure(
    body: str,
    corpus: list[CorpusArticle],
    *,
    chrome_blocks: list[str] | None = None,
    num_perm: int = 256,
    exclude_article_id: str | None = None,
) -> SimilarityMeasurement:
    """Nearest-neighbour similarity against published siblings.

    An empty corpus returns `compared_count=0` with `score=0.0`, and those two
    have to be read together: the first article generated from a template has
    nothing to be similar to, and 0.0 there means UNMEASURED. Reporting it as
    "perfectly distinct" would tell a reviewer the opposite of the truth at
    exactly the moment they have least other information.
    """
    started = time.perf_counter()

    target = signature(shingles(normalize(body, chrome_blocks)), num_perm)

    best_score = 0.0
    best: CorpusArticle | None = None
    compared = 0

    for other in corpus:
        if exclude_article_id is not None and other.article_id == exclude_article_id:
            continue
        compared += 1
        other_signature = signature(
            shingles(normalize(other.body, chrome_blocks)), num_perm
        )
        score = estimate_jaccard(target, other_signature)
        if best is None or score > best_score:
            best_score = score
            best = other

    duration_ms = int(round((time.perf_counter() - started) * 1000))

    if compared == 0:
        return SimilarityMeasurement(
            score=0.0,
            nearest_article_id=None,
            nearest_organization_id=None,
            compared_count=0,
            duration_ms=duration_ms,
        )

    return SimilarityMeasurement(
        score=round(best_score, 4),
        nearest_article_id=best.article_id if best else None,
        nearest_organization_id=best.organization_id if best else None,
        compared_count=compared,
        duration_ms=duration_ms,
    )


def body_text(sections: list) -> str:
    """Join an article's sections into the text the metric runs on.

    Headings are included: a template whose headings all survive generation
    unchanged IS duplication, and dropping them would hide the cheapest
    available signal that generation only rewrote the paragraphs.
    """
    parts: list[str] = []
    for section in sections:
        heading = getattr(section, "heading", "") or ""
        body = getattr(section, "body_md", "") or ""
        parts.append(f"{heading}\n{body}")
    return "\n\n".join(parts)
