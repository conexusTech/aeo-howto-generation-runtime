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

from app.howto_generation.model import FakeChatModel, GeneratedArticle, parse_article
from app.howto_generation.prompt import PromptComposition


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
