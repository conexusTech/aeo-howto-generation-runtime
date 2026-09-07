"""The model seam: parsing, and the import boundary.

`BedrockChatModel` is not exercised against a live endpoint here and never will
be — `FakeChatModel` stands in. What IS tested is the half that fails silently:
turning whatever the model handed back into sections we are willing to publish.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import contextlib
import logging

import pytest

from app.howto_generation.model import (
    _ARTICLE_TOOL,
    _SECTION_TYPES,
    _VALID_TYPES,
    FakeChatModel,
    GeneratedArticle,
    parse_article,
)
from app.howto_generation.prompt import PromptComposition


@contextlib.contextmanager
def caplog_at_error():
    """Capture ERROR records from this module's logger.

    `caplog` needs propagation, which pytest provides -- but a bare list of
    records is what these tests actually assert on, and naming it here keeps
    the assertions about the log CONTENT rather than about the fixture.
    """
    records: list[logging.LogRecord] = []

    class _Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    sink = _Sink(level=logging.ERROR)
    target = logging.getLogger("app.howto_generation.model")
    target.addHandler(sink)
    previous = target.level
    target.setLevel(logging.ERROR)
    try:
        yield records
    finally:
        target.removeHandler(sink)
        target.setLevel(previous)


def wire(sections: list[dict], title: str = "A title") -> dict:
    return {"title": title, "sections_json": json.dumps(sections)}


class TestImportBoundary:
    def test_importing_the_module_does_not_import_the_anthropic_sdk(self) -> None:
        # 🔴 The property that lets the entire suite run with no AWS, no
        # credentials and no network. If the SDK import ever moves to module
        # scope this fails, which is the whole point of writing it down: a
        # runtime whose logic can only be exercised against a live endpoint is
        # a runtime whose logic does not get exercised.
        #
        # Run in a SUBPROCESS deliberately. Inside this one, pytest has already
        # imported half the world and `anthropic` may be in `sys.modules`
        # because something else pulled it in — so an in-process assertion
        # would pass or fail for reasons unrelated to the module under test.
        probe = (
            "import sys; import app.howto_generation.model; "
            "print('anthropic' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
            check=True,
        )
        assert result.stdout.strip() == "False", (
            "importing app.howto_generation.model pulled in the anthropic SDK; "
            "the import must stay inside BedrockChatModel.__init__"
        )

    def test_the_probe_would_notice_an_eager_import(self) -> None:
        # The control for the test above. It asserts on a subprocess's stdout,
        # so it would pass just as happily against a probe that never imports
        # anything — this proves the probe reports True when the SDK really is
        # loaded, and therefore that False means something.
        probe = "import sys, anthropic; print('anthropic' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
            check=True,
        )
        assert result.stdout.strip() == "True"

    def test_constructing_the_fake_needs_nothing(self) -> None:
        assert FakeChatModel().generate(
            prompt=PromptComposition(stable="s", volatile="v")
        )


class TestParsing:
    def test_positions_are_assigned_from_array_order(self) -> None:
        # Positions are OURS, never the model's. A model asked for contiguous
        # 1-based positions will occasionally skip one or repeat one, and the
        # gateway's stored invariant is contiguity.
        article = parse_article(
            wire(
                [
                    {"type": "intro", "heading": "A", "body_md": "a"},
                    {"type": "step", "heading": "B", "body_md": "b"},
                    {"type": "outro", "heading": "C", "body_md": "c"},
                ]
            )
        )
        assert [s.position for s in article.sections] == [1, 2, 3]

    def test_positions_supplied_by_the_model_are_ignored(self) -> None:
        article = parse_article(
            wire(
                [
                    {"type": "intro", "heading": "A", "body_md": "a", "position": 9},
                    {"type": "step", "heading": "B", "body_md": "b", "position": 9},
                ]
            )
        )
        assert [s.position for s in article.sections] == [1, 2]

    def test_a_section_with_an_unknown_type_is_dropped_not_coerced(self) -> None:
        # The four types drive rendering. Quietly mapping an invented fifth onto
        # `step` publishes something in a shape nobody chose.
        article = parse_article(
            wire(
                [
                    {"type": "intro", "heading": "A", "body_md": "a"},
                    {"type": "sidebar", "heading": "B", "body_md": "b"},
                ]
            )
        )
        assert [s.heading for s in article.sections] == ["A"]

    def test_a_section_missing_a_body_is_dropped(self) -> None:
        article = parse_article(
            wire(
                [
                    {"type": "step", "heading": "A"},
                    {"type": "step", "heading": "B", "body_md": "b"},
                ]
            )
        )
        assert [s.heading for s in article.sections] == ["B"]

    def test_an_already_decoded_array_is_tolerated(self) -> None:
        # Some endpoints hand back a decoded array rather than a JSON string.
        article = parse_article(
            {
                "title": "T",
                "sections_json": [{"type": "step", "heading": "A", "body_md": "a"}],
            }
        )
        assert len(article.sections) == 1

    def test_image_fields_from_the_model_are_dropped(self) -> None:
        # ⚠️ **This test asserted the OPPOSITE until 2026-09-04**, under the
        # name `test_image_alt_survives_parsing`, reasoning that alt text gates
        # publication so losing it would strand an article. The reasoning was
        # sound about alt text and wrong about where it comes from: images are
        # attached by a human in the editor, which is the only place the asset
        # key can be checked against the org. Nothing the model emits here was
        # ever a real image.
        #
        # Carrying the fields through was a cross-tenant asset vector — see the
        # 🔴 in `parse_article`. The test is inverted rather than deleted so the
        # next reader meets the reasoning instead of repeating it.
        article = parse_article(
            wire(
                [
                    {
                        "type": "step",
                        "heading": "A",
                        "body_md": "a",
                        "image_asset_key": "organizations/o/howto/x.png",
                        "image_alt": "a worn belt",
                    }
                ]
            )
        )
        assert article.sections[0].image_alt is None
        assert article.sections[0].image_asset_key is None
        # Control: the section itself is kept, not dropped.
        assert article.sections[0].heading == "A"

    def test_an_empty_payload_yields_no_sections(self) -> None:
        assert parse_article({"title": "T", "sections_json": ""}).sections == []

    def test_a_missing_title_comes_back_blank_not_invented(self) -> None:
        # The runtime falls back to the template title, which is a decision
        # taken there and visibly, rather than a value made up here.
        assert parse_article(wire([], title="  ")).title == ""


class TestTheToolAsksForARealArray:
    """The 2026-09-07 regression, at the layer that caused it.

    The tool used to declare `sections_json` as a STRING holding a JSON-encoded
    array, so the model hand-escaped every quote, backslash and newline in the
    article body. Six generations parsed; the seventh died on
    `JSONDecodeError: Expecting ',' delimiter: line 1 column 3107` and reached
    the operator as "the generation runtime declined".

    These tests are about the SHAPE ASKED FOR, not only the parsing -- parsing a
    string correctly was never the problem, being handed one was.
    """

    def test_the_tool_declares_sections_as_an_array_not_a_string(self) -> None:
        # Reverting the schema to a string is the specific mistake this guards,
        # and it would leave every parse test below green because the fallback
        # path still reads a string. Only this assertion notices.
        props = _ARTICLE_TOOL["input_schema"]["properties"]
        assert "sections_json" not in props
        assert props["sections"]["type"] == "array"
        assert props["sections"]["items"]["type"] == "object"
        assert _ARTICLE_TOOL["input_schema"]["required"] == ["title", "sections"]

    def test_the_declared_types_are_the_types_we_accept_in_reading_order(self) -> None:
        # Two defects in one assertion: a type advertised but rejected (the
        # model obeys and we silently drop the section), and a type accepted but
        # never advertised. Order matters -- the model reads it as a sequence.
        enum = _ARTICLE_TOOL["input_schema"]["properties"]["sections"]["items"][
            "properties"
        ]["type"]["enum"]
        assert enum == ["intro", "step", "tip", "outro"]
        assert set(enum) == set(_VALID_TYPES)

    def test_the_tool_no_longer_asks_the_model_to_encode_json(self) -> None:
        # 🔴 The diff's own CAUSAL claim, and it shipped with no reader: with
        # the description reverted to "escape every quote, backslash and
        # newline yourself" and `body_md`'s note deleted, all 218 tests stayed
        # green. The schema would still say array while the instructions said
        # hand-encode -- and a model that obeys the prose lands back on the
        # string branch and reproduces 2026-09-07 exactly.
        description = _ARTICLE_TOOL["description"]
        assert "JSON-encoded" not in description
        assert "sections_json" not in description
        body_md = _ARTICLE_TOOL["input_schema"]["properties"]["sections"]["items"][
            "properties"
        ]["body_md"]
        assert "no escaping" in body_md["description"]

    def test_the_item_schema_pins_the_fields_a_section_must_carry(self) -> None:
        # `required` is load-bearing rather than decorative: a section arriving
        # without `heading` is SILENTLY DROPPED by the parse loop, so the
        # schema asking for it is what stops the model omitting it and losing a
        # section with no error anywhere. Both of these were unasserted --
        # popping `required` and flipping `additionalProperties` to True left
        # the whole suite green.
        items = _ARTICLE_TOOL["input_schema"]["properties"]["sections"]["items"]
        assert items["required"] == ["type", "heading", "body_md"]
        assert items["additionalProperties"] is False

    def test_a_native_array_parses_with_positions_from_its_order(self) -> None:
        article = parse_article(
            {
                "title": "T",
                "sections": [
                    {"type": "intro", "heading": "One", "body_md": "a"},
                    {"type": "step", "heading": "Two", "body_md": "b"},
                    {"type": "outro", "heading": "Three", "body_md": "c"},
                ],
            }
        )
        assert [(s.position, s.heading) for s in article.sections] == [
            (1, "One"),
            (2, "Two"),
            (3, "Three"),
        ]

    def test_a_tip_section_survives(self) -> None:
        # `tip` was in `_VALID_TYPES` and covered by NO test: a mutation
        # removing it left all 207 tests green on 2026-09-07. The renderer draws
        # it as the callout, so dropping it would lose content silently.
        article = parse_article(
            {
                "title": "T",
                "sections": [{"type": "tip", "heading": "H", "body_md": "b"}],
            }
        )
        assert [s.type for s in article.sections] == ["tip"]

    def test_a_body_with_hostile_characters_is_copied_through_untouched(self) -> None:
        # ⚠️ NOT the regression test, despite reading like one — retitled
        # after review said so, because a docstring claiming more than a test
        # proves is worse than a modest test.
        #
        # The array branch is `parsed = raw` and the body is copied verbatim,
        # so this is dict identity: no choice of characters can make it fail.
        # The escaping failure lived at the Mantle API boundary and NO unit
        # test in this repo can prove it fixed — the schema assertion above and
        # the live-endpoint check recorded in the capability are the real
        # guards. What this does earn: it pins that nothing later introduces
        # normalisation or re-escaping into the array path.
        quote, backslash, newline = chr(34), chr(92), chr(10)
        body = (
            "He said " + quote + "check it" + quote + " then ran "
            + backslash + backslash + "server" + newline + "on a second line"
        )
        # The probe must be hostile, or the round-trip below proves nothing.
        # Each of these is a character hand-escaped JSON gets wrong.
        assert quote in body
        assert backslash in body
        assert newline in body
        # Control: the same content, hand-encoded the way the old shape
        # required and mis-escaped the way the model mis-escaped it, is
        # STILL rejected -- so this test is about the array carrying it, not
        # about parse_article having become permissive.
        with pytest.raises(RuntimeError):
            parse_article(
                {
                    "title": "T",
                    "sections_json": (
                        "[{" + quote + "type" + quote + ": " + quote + "step"
                        + quote + ", " + quote + "body_md" + quote + ": "
                        + quote + body + quote + "}]"
                    ),
                }
            )
        article = parse_article(
            {
                "title": "T",
                "sections": [
                    {"type": "step", "heading": "H", "body_md": body},
                ],
            }
        )
        assert article.sections[0].body_md == body

    def test_an_array_section_with_an_unknown_type_is_still_dropped(self) -> None:
        # The parse-side allowlist is not redundant with the schema: Mantle
        # refuses `strict: true`, so `enum` is a hint the model may ignore.
        article = parse_article(
            {
                "title": "T",
                "sections": [
                    {"type": "sidebar", "heading": "X", "body_md": "x"},
                    {"type": "step", "heading": "Y", "body_md": "y"},
                ],
            }
        )
        assert [s.heading for s in article.sections] == ["Y"]

    def test_an_array_cannot_smuggle_an_image_asset_key_either(self) -> None:
        # The security control this repo already had, re-asserted on the new
        # shape. `additionalProperties: False` on the item schema does NOT
        # enforce it (see `strict: true` above), so the parse-side drop is what
        # actually holds -- and a shape change must not step around it.
        article = parse_article(
            {
                "title": "T",
                "sections": [
                    {
                        "type": "step",
                        "heading": "H",
                        "body_md": "b",
                        "image_asset_key": "organizations/other-org/howto/hero.png",
                        "image_alt": "not ours",
                    }
                ],
            }
        )
        assert article.sections[0].image_asset_key is None
        assert article.sections[0].image_alt is None
        # Control: the section itself survived, so the two assertions above are
        # about those fields and not about the section being dropped whole.
        assert article.sections[0].heading == "H"


class TestTheOldShapeStillReadsAndFailsLoudly:
    """`sections_json` stays readable for one release, because a payload in
    flight when this deploys must not parse as an empty article."""

    def test_a_non_list_sections_value_does_not_yield_a_silent_empty_article(
        self,
    ) -> None:
        # The model returning ONE section object instead of an array. The
        # schema cannot stop it (Mantle refuses `strict: true`), and the first
        # version of this fix answered with an empty article and no log --
        # a publishable page with no content, reported as a success.
        with pytest.raises(RuntimeError) as exc:
            parse_article(
                {
                    "title": "T",
                    "sections": {"type": "step", "heading": "H", "body_md": "b"},
                }
            )
        assert "not an array" in str(exc.value)

    def test_an_empty_sections_array_does_not_shadow_a_valid_legacy_payload(
        self,
    ) -> None:
        # Precedence was `if raw is None`, so an empty `sections` beside a good
        # `sections_json` silently won and produced no sections at all.
        article = parse_article(
            {
                "title": "T",
                "sections": [],
                "sections_json": json.dumps(
                    [{"type": "step", "heading": "Legacy", "body_md": "b"}]
                ),
            }
        )
        assert [s.heading for s in article.sections] == ["Legacy"]

    def test_a_legacy_json_string_still_parses(self) -> None:
        article = parse_article(
            wire([{"type": "step", "heading": "Legacy", "body_md": "b"}])
        )
        assert [s.heading for s in article.sections] == ["Legacy"]

    def test_the_array_wins_when_both_are_present(self) -> None:
        article = parse_article(
            {
                "title": "T",
                "sections": [{"type": "step", "heading": "New", "body_md": "n"}],
                "sections_json": json.dumps(
                    [{"type": "step", "heading": "Old", "body_md": "o"}]
                ),
            }
        )
        assert [s.heading for s in article.sections] == ["New"]

    def test_malformed_legacy_json_raises_rather_than_publishing_nothing(self) -> None:
        # Returning `[]` here would be worse than raising: an empty section list
        # is a publishable article with no content, and it reaches an operator
        # as a SUCCESS.
        broken = '[{\"type\": \"step\", \"heading\": \"H\", \"body_md\": \"he said \"hi\"\"}]'
        with pytest.raises(RuntimeError) as exc:
            parse_article({"title": "T", "sections_json": broken})
        # The character position is the whole diagnostic value; a message
        # without it sends the next person back to guessing.
        assert "char" in str(exc.value)

    def test_the_malformed_payload_is_logged_so_the_bad_character_is_findable(
        self, caplog
    ) -> None:
        # The 2026-09-07 failure logged a traceback but never the payload, so
        # "column 3107" named a character nobody could read back.
        broken = '[{\"type\": \"step\", \"heading\": \"H\", \"body_md\": \"bad \"quote\"\"}]'
        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError):
                parse_article({"title": "T", "sections_json": broken})
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "bad " in logged
        assert "quote" in logged


class TestTheDecodeLogIsActuallyDiagnostic:
    """What the runtime records when the legacy string shape fails to decode.

    Every test here was written from a security review of the first version of
    this fix, which logged `raw[:2000]`. Each one fails against that version.
    """

    #: A payload whose fault sits well past 2000 characters -- the shape of the
    #: real incident, which failed at char 3107.
    @staticmethod
    def _broken_far_into_the_payload() -> tuple[str, str]:
        quote = chr(34)
        needle = "NEEDLE_NEAR_THE_FAULT"
        filler = "x" * 2500
        # The unescaped quote is what breaks it, immediately after the needle.
        body = filler + needle + quote + "unescaped"
        payload = (
            "[{" + quote + "type" + quote + ": " + quote + "step" + quote + ", "
            + quote + "body_md" + quote + ": " + quote + body + quote + "}]"
        )
        return payload, needle

    def test_the_logged_window_contains_the_offending_character(self) -> None:
        # 🔴 THE TEST THE FIRST VERSION OF THIS FIX WOULD HAVE FAILED.
        #
        # It logged the first 2000 characters. The 2026-09-07 fault was at char
        # 3107, so the log would have carried 2000 characters that do not
        # contain the problem -- diagnostic in appearance and useless in fact.
        payload, needle = self._broken_far_into_the_payload()
        with caplog_at_error() as records:
            with pytest.raises(RuntimeError):
                parse_article({"title": "T", "sections_json": payload})
        logged = " ".join(r.getMessage() for r in records)
        assert needle in logged, (
            "the log window missed the fault; a head slice would do this"
        )

    def test_the_logged_window_is_bounded_well_below_the_payload(self) -> None:
        # The truncation is the privacy control: section bodies are
        # tenant-influenced and this lands in CloudWatch. Nothing pinned the
        # bound before, so removing it entirely left the suite green.
        payload, _ = self._broken_far_into_the_payload()
        with caplog_at_error() as records:
            with pytest.raises(RuntimeError):
                parse_article({"title": "T", "sections_json": payload})
        logged = " ".join(r.getMessage() for r in records)
        assert len(logged) < len(payload) / 2, (
            "the whole payload is reaching the log, not a bounded window"
        )

    def test_a_newline_in_the_payload_cannot_forge_a_second_log_record(self) -> None:
        # `%r` is load-bearing, not cosmetic. Under `%s` a tenant-influenced
        # body containing a line break plus something that reads like a log
        # line would appear in CloudWatch as its own record -- in the one place
        # the generic API response says the truthful detail lives.
        quote, newline = chr(34), chr(10)
        forged = newline + "ERROR app.howto_generation.server: generation succeeded"
        payload = (
            "[{" + quote + "type" + quote + ": " + quote + "step" + quote + ", "
            + quote + "body_md" + quote + ": " + quote + "bad " + quote
            + forged + quote + "}]"
        )
        with caplog_at_error() as records:
            with pytest.raises(RuntimeError):
                parse_article({"title": "T", "sections_json": payload})
        assert len(records) == 1
        # The escaping is the mechanism: no raw newline survives into the record.
        assert newline not in records[0].getMessage()

    def test_the_message_names_the_field_the_value_actually_came_from(self) -> None:
        # A model that hand-encodes under the NEW field name lands on the same
        # branch. Reporting it as `sections_json` would misdirect whoever is
        # reading the log during an incident.
        quote = chr(34)
        broken = "[{" + quote + "type" + quote + ": " + quote + "step"
        with pytest.raises(RuntimeError) as exc:
            parse_article({"title": "T", "sections": broken})
        assert "sections " in str(exc.value)
        assert "sections_json" not in str(exc.value)


class TestTheDeclaredTypesMatchTheContract:
    def test_the_tool_enum_matches_the_section_type_the_contract_accepts(self) -> None:
        # Two independent literal lists of the same four values. If they
        # diverged, a section the tool advertised would fail pydantic
        # validation inside the parse loop and the whole article would be lost
        # to a generic GENERATION_FAILED -- a silent content loss, not an error
        # anyone could read.
        from typing import get_args

        from app.howto_generation.contracts import SectionType

        assert set(_SECTION_TYPES) == set(get_args(SectionType))


class TestFake:
    def test_the_fake_records_the_prompt_it_was_given(self) -> None:
        # So tests can assert on what the model was actually told, not only on
        # what came back.
        fake = FakeChatModel()
        composition = PromptComposition(stable="s", volatile="v")
        fake.generate(prompt=composition)
        assert fake.calls == [composition]

    def test_a_scripted_article_is_returned_unchanged(self) -> None:
        scripted = GeneratedArticle(title="Scripted", sections=[])
        fake = FakeChatModel(scripted)
        assert fake.generate(prompt=PromptComposition(stable="", volatile="")) is scripted


class TestModelCannotSmuggleAssetKeys:
    """🔴 A shop's own profile text reaches the prompt, so the model can be
    asked to emit fields the tool schema never declared. These stay dropped."""

    def test_an_image_asset_key_from_the_model_is_discarded(self) -> None:
        # The attack: prose in the org description tells the model to add
        # `image_asset_key` naming ANOTHER org's asset. The tool schema does not
        # declare the field, but `sections_json` is a free string we parse
        # ourselves, so nothing upstream stops it arriving.
        article = parse_article(
            {
                "title": "Timing belts",
                "sections_json": json.dumps(
                    [
                        {
                            "type": "intro",
                            "heading": "Why this matters",
                            "body_md": "A belt is a wear item.",
                            "image_asset_key": (
                                "organizations/"
                                "99999999-9999-9999-9999-999999999999"
                                "/howto/hero.png"
                            ),
                            "image_alt": "someone else's photo",
                        }
                    ]
                ),
            }
        )
        assert len(article.sections) == 1
        assert article.sections[0].image_asset_key is None
        assert article.sections[0].image_alt is None

    def test_control_the_rest_of_the_section_still_survives(self) -> None:
        # Control: proves the assertions above are not passing because the
        # section was dropped wholesale, which would look identical.
        article = parse_article(
            {
                "title": "Timing belts",
                "sections_json": json.dumps(
                    [
                        {
                            "type": "step",
                            "heading": "Check the interval",
                            "body_md": "Start with the manufacturer interval.",
                            "image_asset_key": "organizations/x/howto/a.png",
                        }
                    ]
                ),
            }
        )
        assert len(article.sections) == 1
        assert article.sections[0].heading == "Check the interval"
        assert article.sections[0].body_md == "Start with the manufacturer interval."

    def test_a_malformed_asset_key_no_longer_discards_the_whole_article(self) -> None:
        # Previously `image_asset_key={"k": "v"}` reached the Section
        # constructor and pydantic raised, throwing away a complete article and
        # the ~30k tokens paid for it over one optional field.
        article = parse_article(
            {
                "title": "Timing belts",
                "sections_json": json.dumps(
                    [
                        {
                            "type": "intro",
                            "heading": "A",
                            "body_md": "B",
                            "image_asset_key": {"k": "v"},
                        },
                        {"type": "step", "heading": "C", "body_md": "D"},
                    ]
                ),
            }
        )
        assert [s.heading for s in article.sections] == ["A", "C"]
