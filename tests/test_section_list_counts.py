"""`faq-groups-draft-meets-its-minimum` — a drafted list holds as many items as
its template requires, at every level. Ground truth (production, 2026-11-06):
drafting the FAQ groups section wrote two questions per group against a
minimum of three, because no list count reached the runtime: the template's
`minItems`/`maxItems` were not part of a field, the prompt said only "a list
of items", and nothing checked the count. No model is called here.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.howto_generation.contracts import SectionCopyRequest
from app.howto_generation.model import (
    DraftedSectionCopy,
    FakeChatModel,
    stub_section_copy,
)
from tests.test_section_copy import flat, payload, prompt_for, run

#: Template set 2.0.0's FAQ groups, as the gateway flattens it.
FAQ_GROUPS = {
    "key": "faq_groups",
    "name": "FAQ groups",
    "fields": [
        {"name": "heading", "max_length": 70, "kind": "text", "required": False},
        {
            "name": "groups",
            "kind": "list",
            "required": True,
            "min_items": 1,
            "max_items": 6,
            "item_fields": [
                {"name": "heading", "max_length": 70, "kind": "text"},
                {
                    "name": "items",
                    "kind": "list",
                    "required": True,
                    "min_items": 3,
                    "max_items": 15,
                    "item_fields": [
                        {"name": "question", "max_length": 120, "kind": "text", "required": True},
                        {"name": "answer", "max_length": 600, "kind": "rich_text", "required": True},
                    ],
                },
            ],
        },
    ],
}


def qa(n: int) -> list[dict[str, str]]:
    return [{"question": f"Question {i}?", "answer": f"Answer {i}."} for i in range(1, n + 1)]


def drafted_groups(*per_group: int) -> FakeChatModel:
    return FakeChatModel(
        section_copy=DraftedSectionCopy(
            fields=[
                {"name": "heading", "text": "Questions", "inputs_used": ["page.title"]},
                {
                    "name": "groups",
                    "items": [
                        {"heading": f"Group {g}", "items": qa(n)}
                        for g, n in enumerate(per_group, start=1)
                    ],
                    "inputs_used": ["page.title"],
                },
            ]
        )
    )


def draft(model: FakeChatModel, **overrides: Any):
    body = payload(**{"template": FAQ_GROUPS, **overrides})
    return run(SectionCopyRequest.model_validate(body), model)


class TestTheContract:
    def test_counts_are_read_at_both_levels(self) -> None:
        req = SectionCopyRequest.model_validate(payload(template=FAQ_GROUPS))
        groups = req.template.fields[1]
        assert (groups.min_items, groups.max_items) == (1, 6)
        items = groups.item_fields[1]
        assert (items.min_items, items.max_items) == (3, 15)

    def test_an_older_gateway_sends_no_counts(self) -> None:
        req = SectionCopyRequest.model_validate(payload())
        faqs = next(f for f in req.template.fields if f.kind == "list")
        assert faqs.min_items is None and faqs.max_items is None

    @pytest.mark.parametrize("bad", [{"min_items": -1}, {"max_items": 0}])
    def test_an_impossible_count_is_refused(self, bad: dict[str, int]) -> None:
        template = {**FAQ_GROUPS, "fields": [{**FAQ_GROUPS["fields"][1], **bad}]}
        with pytest.raises(ValueError):
            SectionCopyRequest.model_validate(payload(template=template))


class TestThePrompt:
    def test_each_list_says_how_many_items_it_takes(self) -> None:
        p = prompt_for(template=FAQ_GROUPS)
        assert (
            "- groups: a list of at least 1 and at most 6 items, required. Each item has:"
            in p.volatile
        )
        assert (
            "    - items: a list of at least 3 and at most 15 items, required. "
            "Each item has:" in p.volatile
        )

    def test_the_rule_is_in_the_stable_half(self) -> None:
        stable = flat(prompt_for(template=FAQ_GROUPS).stable)
        assert (
            "When a list says how many items it takes, write at least that many "
            "and no more, in every item that holds one"
        ) in stable

    def test_one_bound_alone_is_said_alone(self) -> None:
        template = {
            **FAQ_GROUPS,
            "fields": [{**FAQ_GROUPS["fields"][1], "min_items": None, "max_items": 4}],
        }
        assert "- groups: a list of at most 4 items, required." in prompt_for(template=template).volatile

    def test_CONTROL_no_counts_reads_as_before(self) -> None:
        assert "- faqs: a list of items, optional. Each item has:" in prompt_for().volatile


class TestTheDraftIsChecked:
    def test_three_questions_a_group_is_kept(self) -> None:
        response = draft(drafted_groups(3, 4))
        assert [len(g["items"]) for g in response.fields["groups"]] == [3, 4]
        assert "groups" not in response.refused

    def test_two_questions_in_a_group_refuse_the_groups_and_say_why(self) -> None:
        # What production drafted: two a group against a minimum of three.
        response = draft(drafted_groups(3, 2))
        assert "groups" not in response.fields
        assert response.refused["groups"] == (
            "item 2's items has 2 items; the template needs at least 3"
        )
        # The rest of the section is still drafted.
        assert response.fields["heading"] == "Questions"

    def test_too_few_groups_refuse_the_field(self) -> None:
        template = {
            **FAQ_GROUPS,
            "fields": [FAQ_GROUPS["fields"][0], {**FAQ_GROUPS["fields"][1], "min_items": 3}],
        }
        response = draft(drafted_groups(3, 3), template=template)
        assert response.refused["groups"] == "has 2 items; the template needs at least 3"

    def test_too_many_are_cut_to_the_maximum_at_both_levels(self) -> None:
        response = draft(drafted_groups(16, 3, 3, 3, 3, 3, 3, 3))
        groups = response.fields["groups"]
        assert len(groups) == 6
        assert len(groups[0]["items"]) == 15
        assert groups[0]["items"][-1]["question"] == "Question 15?"

    def test_CONTROL_without_counts_two_questions_are_kept(self) -> None:
        loose = {
            **FAQ_GROUPS,
            "fields": [
                FAQ_GROUPS["fields"][0],
                {
                    **FAQ_GROUPS["fields"][1],
                    "min_items": None,
                    "max_items": None,
                    "item_fields": [
                        FAQ_GROUPS["fields"][1]["item_fields"][0],
                        {
                            **FAQ_GROUPS["fields"][1]["item_fields"][1],
                            "min_items": None,
                            "max_items": None,
                        },
                    ],
                },
            ],
        }
        response = draft(drafted_groups(2), template=loose)
        assert len(response.fields["groups"][0]["items"]) == 2


class TestTheStub:
    def test_the_local_stub_writes_each_list_s_minimum(self) -> None:
        model = FakeChatModel()
        run(SectionCopyRequest.model_validate(payload(template=FAQ_GROUPS)), model)
        stub = stub_section_copy(model.section_calls[0])
        groups = next(f for f in stub.fields if f["name"] == "groups")
        assert 1 <= len(groups["items"]) <= 6
        assert all(len(g["items"]) >= 3 for g in groups["items"])

    def test_the_stub_draft_passes_its_own_checks(self) -> None:
        # FakeChatModel with no script is the local stub the server runs.
        response = draft(FakeChatModel())
        assert "groups" in response.fields, response.refused
