"""Does a generated article actually honour the literal-steps content model?

Product direction (2026-09-04): the template carries the PROCEDURE — steps
authored by someone who knows the trade. The generator rewrites how each step is
said for one shop, writes a fresh intro and conclusion, and invents nothing.

This script asks whether that happened, against a live generation. It is the
answer to "how do we know the model was met" that does not depend on somebody
reading two documents side by side and forming an impression.

    python scripts/check_content_model.py                    # local runtime on :8090
    python scripts/check_content_model.py --url http://host:8090/invocations

Exits non-zero if any check fails, so it can gate a run.

⚠️ It costs a real model call (~30-45s). That is the point: the property under
test is what the MODEL did, and no offline check can stand in for it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

# A template whose steps carry facts that are cheap to look for afterwards.
# Deliberately specific: a number, a part name, a list of parts. Vague steps
# would make "was the fact preserved" unanswerable.
TEMPLATE = {
    "id": "tpl-check",
    "service_key": "timing-belt",
    "vertical": "auto-repair",
    "title": "How to tell when a timing belt needs replacing",
    "description": "Signs a belt is due, and what replacing it involves.",
    "sections": [
        {
            "type": "intro",
            "position": 1,
            "heading": "Why this matters",
            "body_md": "Every shop using this template was handed this exact paragraph.",
            "image_asset_key": None,
            "image_alt": None,
        },
        {
            "type": "step",
            "position": 2,
            "heading": "Check the service interval",
            "body_md": (
                "Start with the manufacturer interval for the engine. "
                "Most fall between 60,000 and 100,000 miles."
            ),
            "image_asset_key": None,
            "image_alt": None,
        },
        {
            "type": "step",
            "position": 3,
            "heading": "Inspect the belt for cracking",
            "body_md": "Look for cracking, fraying or a glazed surface on the belt itself.",
            "image_asset_key": None,
            "image_alt": None,
        },
        {
            "type": "step",
            "position": 4,
            "heading": "Replace the tensioner and water pump together",
            "body_md": (
                "The tensioner, idler pulleys and often the water pump run off "
                "the same belt. Replace them in the same job."
            ),
            "image_asset_key": None,
            "image_alt": None,
        },
        {
            "type": "outro",
            "position": 5,
            "heading": "Book it in",
            "body_md": "Generic closing paragraph shared by every shop.",
            "image_asset_key": None,
            "image_alt": None,
        },
    ],
    "slots": [
        {"name": "shop_name", "description": "The shop", "required": True},
        {"name": "city", "description": "Where it is", "required": False},
        {"name": "price_band", "description": "Typical cost", "required": False},
    ],
}

CONTEXT = {
    "context_version": "check",
    "organization": {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Kirkwood Auto Care",
        "industry": "auto repair",
        "description": "Independent garage, mostly fleet and light commercial work.",
        "address": "412 Kirkwood Ave, Springfield, IL 62701, USA",
    },
    "geography": {"home_markets": ["Springfield"]},
}

#: Facts that appear inside the template's literal steps. Each must survive.
FACTS = [
    ("the 60,000-100,000 mile interval", lambda b: bool(re.search(r"60[,.]?000", b) and re.search(r"100[,.]?000", b))),
    ("cracking / fraying / glazing", lambda b: any(w in b for w in ("crack", "fray", "glaz"))),
    ("the tensioner", lambda b: "tensioner" in b),
    ("the water pump", lambda b: "water pump" in b),
    ("the idler pulleys", lambda b: "idler" in b),
]


def generate(url: str) -> dict:
    payload = {"operation": "generate", "template": TEMPLATE, "context": CONTEXT, "corpus": []}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8090/invocations")
    args = parser.parse_args()

    print(f"Generating against {args.url} — this is a real model call, ~30-45s\n")
    article = generate(args.url)

    if "error_code" in article:
        print(f"REFUSED: {article['error_code']} — {article.get('message', '')[:200]}")
        return 1

    usage = article.get("usage") or {}
    if not (usage.get("input_tokens") or 0):
        print("STOP: zero input tokens — this is the STUB, not a real generation.")
        print("      Unset HOWTO_GENERATION_USE_STUB_MODEL and try again.")
        return 1

    sections = article["sections"]
    steps = [s for s in sections if s["type"] in ("step", "tip")]
    template_steps = [s for s in TEMPLATE["sections"] if s["type"] == "step"]
    body = " ".join(s["body_md"] for s in sections).lower()

    print(f'Title: {article["title"]}')
    for s in sections:
        print(f'  [{s["type"]:5}] {s["heading"]}')
    print()

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f'  {"PASS" if ok else "FAIL"}  {label}{("  — " + detail) if detail and not ok else ""}')
        if not ok:
            failures.append(label)

    print("THE STEPS ARE PRESERVED")
    check(
        f"every step kept ({len(template_steps)} in, {len(steps)} out)",
        len(steps) >= len(template_steps),
        f"{len(template_steps) - len(steps)} lost",
    )
    print("\nTHE FACTS SURVIVED THE REWRITE")
    for label, probe in FACTS:
        check(label, probe(body))

    print("\nTHE SENTENCES WERE REWRITTEN, NOT COPIED")
    for section in template_steps:
        first = section["body_md"].split(".")[0].strip().lower()
        check(f'"{first[:44]}…" not reused verbatim', first not in body)

    print("\nTHE INTRO AND CONCLUSION ARE NEW")
    tmpl_intro = next(s for s in TEMPLATE["sections"] if s["type"] == "intro")["body_md"].lower()
    tmpl_outro = next(s for s in TEMPLATE["sections"] if s["type"] == "outro")["body_md"].lower()
    check("the template's intro paragraph is gone", tmpl_intro[:40] not in body)
    check("the template's outro paragraph is gone", tmpl_outro[:40] not in body)
    check("an intro was written", any(s["type"] == "intro" for s in sections))
    check("a conclusion was written", any(s["type"] == "outro" for s in sections))

    print("\nNOTHING WAS INVENTED")
    refused = list((article.get("slots") or {}).get("refused") or {})
    check("no price stated — price_band refused in code", "price_band" in refused)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {'; '.join(failures)}")
        return 1
    print("All checks passed — the content model holds for this generation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
