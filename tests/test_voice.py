"""The house voice rules: the detector, the prompt, and the audit.

⚠️ This file necessarily CONTAINS the characters and phrases it forbids —
that is what a detector test is. The rule is enforced on generated articles,
never on this repo's own source, because an acceptance criterion that forbade
its own proof would be unsatisfiable. This repo's notes record that exact
failure shape.
"""

from __future__ import annotations

import re

from app.config import get_settings
from app.howto_generation import runtime, voice
from app.howto_generation.contracts import GenerationRequest, Section
from app.howto_generation.model import FakeChatModel, GeneratedArticle
from app.howto_generation.prompt import _BASELINE

EM_DASH = chr(0x2014)
CURLY_APOSTROPHE = chr(0x2019)


class TestTheDetectorFires:
    def test_it_finds_a_banned_character(self) -> None:
        found = voice.find_tells("Servicing matters" + EM_DASH + " a lot.")
        assert any(t.startswith("character:") for t in found)

    def test_it_finds_a_phrase(self) -> None:
        found = voice.find_tells("It is important to note that this helps.")
        assert "phrase:it is important to note" in found

    def test_it_finds_a_word(self) -> None:
        assert "word:crucial" in voice.find_tells("This step is crucial.")

    def test_a_curly_apostrophe_does_not_hide_a_phrase(self) -> None:
        # 🔴 Found by probing the detector, not by reading it. `PHRASE_TELLS`
        # holds STRAIGHT apostrophes, so `Let's dive in` typed with a curly one
        # matched no phrase at all — only the character rule fired, which
        # reported the punctuation and quietly missed the signposting.
        curly = "Let" + CURLY_APOSTROPHE + "s dive in."
        straight = "Let's dive in."
        phrases_of = lambda t: [x for x in voice.find_tells(t) if x.startswith("phrase")]
        assert phrases_of(curly) == phrases_of(straight)
        assert "phrase:let's dive in" in phrases_of(curly)

    def test_clean_prose_produces_nothing(self) -> None:
        # Without this, every assertion above would also pass for a detector
        # that returned every tell for every input.
        assert voice.find_tells("Book a visit and we will take a look.") == []


class TestItDoesNotFlagRealTradeVocabulary:
    """🔴 The constraint that shaped this module.

    This runtime serves every trade. The house AI-tell list flags abstract
    metaphor nouns, and every one of them is literal vocabulary for some
    business we generate for. A check that fires on correct copy for a real
    customer is worse than no check, because people learn to ignore it.
    """

    def test_words_that_are_real_tools_parts_and_materials_pass(self) -> None:
        copy = (
            "Check the wiring harness behind the panel. Use a ratchet, not "
            "pliers. The substrate under the tile has to be dry, the flywheel "
            "needs inspecting, and the landscape crew will sweep the surface "
            "before the tapestry goes back on the wall."
        )
        assert voice.find_tells(copy) == []

    def test_an_elevator_company_can_write_elevator(self) -> None:
        # `elevate` is a tell; `elevator` is a machine.
        #
        # ⚠️ This does NOT prove the word-boundary logic, and an earlier
        # version of this test claimed it did. `elevator` never contained
        # `elevate` as a substring (`elevat-or` vs `elevat-e`), so it passed
        # whether the lookarounds existed or not — my own mutation check
        # caught that. It is kept as a plain behavioural fact. The boundary
        # logic is proven directly below.
        assert voice.find_tells("The elevator car stops at each floor.") == []
        assert "word:elevate" in voice.find_tells("This will elevate your home.")

    def test_the_word_pattern_is_boundary_matched_not_substring(self) -> None:
        """🔴 What the lookarounds actually buy, tested on its own.

        No word on today's list is a substring of an innocent word — every
        near-miss (`delved`, `crucially`, `myriads`) is an inflection of the
        tell itself and should be flagged. So the boundaries protect the NEXT
        word somebody adds, and these are the two that have already cost this
        repo real time: `tire` inside `entire`, `car` inside `carry`.

        Tested against the pattern builder rather than the tell list, because
        the point is that adding either word later stays safe.
        """
        tire = voice._word_pattern("tire")
        assert tire.search("the entire run of guttering") is None
        assert tire.search("check the tire pressure") is not None
        assert tire.search("two flat tires") is not None

        car = voice._word_pattern("car")
        assert car.search("we carry the parts") is None
        assert car.search("a strong character") is None
        assert car.search("bring the car in") is not None

    def test_the_exclusions_are_recorded_with_the_word_that_forced_each(self) -> None:
        # So the next person can see these were decisions, not oversights.
        assert len(voice.NOT_AUTOMATED) >= 5
        for rule, why in voice.NOT_AUTOMATED:
            assert rule and why


class TestThePromptNamesWhatWeCheck:
    """The instruction and the check must not drift apart.

    The previous change in this repo shipped tool instructions whose only
    reader was a human: reverting the prose left all 218 tests green while the
    schema said the opposite. The prompt text here is GENERATED from the same
    lists the detector scans, so these assertions hold by construction — and
    they fail loudly if anyone hand-writes the block instead.
    """

    def test_every_banned_word_appears_in_the_prompt(self) -> None:
        block = voice.voice_rules_for_prompt()
        missing = [w for w in voice.WORD_TELLS if w not in block]
        assert missing == []

    def test_every_banned_phrase_appears_in_the_prompt(self) -> None:
        block = voice.voice_rules_for_prompt()
        missing = [p for p in voice.PHRASE_TELLS if p not in block]
        assert missing == []

    def test_the_baseline_carries_the_voice_section_and_the_self_review(self) -> None:
        assert "WRITE LIKE A PERSON" in _BASELINE
        assert "NEVER use these characters" in _BASELINE
        # The PO asked for the copy to be reviewed, not merely constrained.
        assert "REVIEW YOUR OWN COPY" in _BASELINE

    def test_the_prompt_does_not_leak_one_trades_vocabulary(self) -> None:
        # 🔴 `NOT_AUTOMATED`'s examples are concrete trade nouns. An earlier
        # draft interpolated them into the prompt, which drops mechanical
        # vocabulary into the baseline EVERY business shares, including a
        # dental practice's. `tests/test_industry_neutral.py` does not catch
        # this because its word list is automotive-specific and these words
        # are not on it.
        leaks = (
            "harness",
            "ratchet",
            "flywheel",
            "substrate",
            "upholster",
            "landscaper",
            "tapestry",
        )
        present = [w for w in leaks if re.search(r"(?<![a-z])" + w, _BASELINE, re.I)]
        assert present == []

    def test_control_the_leak_check_can_see_those_words(self) -> None:
        # Otherwise the assertion above passes for a probe that sees nothing.
        leaks = ("harness", "flywheel")
        sample = "inspect the harness and the flywheel"
        found = [w for w in leaks if re.search(r"(?<![a-z])" + w, sample, re.I)]
        assert found == ["harness", "flywheel"]


def _request() -> GenerationRequest:
    return GenerationRequest(
        template={
            "service_key": "annual-service",
            "vertical": "generic-services",
            "title": "What an annual service covers",
        },
        context={"business_name": "Halloran and Sons", "city": "Grand Rapids"},
    )


def _article(title: str, body: str) -> GeneratedArticle:
    return GeneratedArticle(
        title=title,
        sections=[
            Section(type="intro", position=1, heading="Why this matters", body_md=body)
        ],
    )


class TestTheAuditRecordsTellsAndBlocksNothing:
    def test_clean_copy_records_an_empty_list(self) -> None:
        result = runtime.handle(
            _request(),
            model=FakeChatModel(_article("An annual service", "We check the seals.")),
            settings=get_settings(),
        )
        assert result.audit.voice_tells == []

    def test_machine_written_copy_is_recorded(self) -> None:
        dirty = "It is important to note that this step is crucial."
        result = runtime.handle(
            _request(),
            model=FakeChatModel(_article("An annual service", dirty)),
            settings=get_settings(),
        )
        assert "word:crucial" in result.audit.voice_tells
        assert "phrase:it is important to note" in result.audit.voice_tells

    def test_a_tell_in_the_TITLE_is_recorded_too(self) -> None:
        # The title is copy a customer reads, and it is not part of the body
        # text similarity works over — so reusing that text alone would have
        # left titles unchecked.
        result = runtime.handle(
            _request(),
            model=FakeChatModel(_article("A crucial guide", "We check the seals.")),
            settings=get_settings(),
        )
        assert "word:crucial" in result.audit.voice_tells

    def test_tells_do_not_refuse_the_generation(self) -> None:
        # 🔴 MEASURED, NEVER ENFORCED — the same choice this runtime already
        # made for similarity. Refusing an article over a word list would
        # throw away good work; the operator reviewing the draft sees the list
        # instead.
        dirty = "In today's fast-paced world, experts believe this is crucial."
        result = runtime.handle(
            _request(),
            model=FakeChatModel(_article("An annual service", dirty)),
            settings=get_settings(),
        )
        assert not hasattr(result, "error_code")
        assert len(result.audit.voice_tells) >= 3
        # Control: the article itself still came through intact.
        assert result.sections and result.sections[0].body_md == dirty
