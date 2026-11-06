# Log

## 2026-11-04

### Update

`task: "section_copy"` follows each field's copy source (`copy-source-on-every-field`, Meriwether Sites C20,
runtime half): every field and item field carries `source` `generated` (the default when absent) or `brand`,
and the request carries the organization's brand record as `brand`. A brand field is written only from that
record, shown fenced with `brand:<key>` ids: left out when the record lacks it, refused when it cites no brand
id, never asked when there is no record, and its numbers sourced by the record alone. A list item may hold one
level of list (FAQ groups and their questions), with the same limits, required parts, price, number,
competitor and edit rules as a top-level field; deeper nesting is refused. The stub drafts both. After
review: that a brand field's wording comes from the record is a prompt rule, and only its numbers are checked
against the record in code; a list needing a brand part is refused up front with no record; brand ids are
distinct when keys clash; keys are never number sources; the audit lists only cited brand ids. See
[section copy](/lib/section-copy.md).

## 2026-10-31

### Update

`task: "section_copy"` after its second real-model run (`section-copy-generation`): a button label had been
rewritten to promise a page the button does not open, a record industry of "Other" was reported as
disagreeing with a plumbing page, and reasons a person gave for rejecting earlier drafts never reached the
model. The request now accepts `template.links` (where each label goes, shown inside the fence and pointed at
from the label's field line, with the rule that a label says where it goes), `rejected` (the person's reasons,
newest first, inside the fence; sources for numbers and claims, never for a price) and `subject`
(`section` / `entry`, wording only: collection entries are drafted too). All three are optional. A
disagreement line naming a catch-all value the record holds ("Other", "N/A") is dropped. No note was added for
labels: whether a label describes its destination is meaning, not vocabulary. Four scenarios and checks added.
See [section copy](/lib/section-copy.md).

## 2026-10-30

### Update

The requirements for `task: "section_copy"` are written down (Meriwether Sites C4, documentation only):
`capabilities/section-copy-generation` (12 scenarios) with `qa/section-copy-generation`, every check
automated in `tests/test_section_copy.py` or `tests/test_section_checks.py` against a fake model. Nothing in
them has met a real model. Concept linked from the index: [section copy](/lib/section-copy.md).

### Update

`task: "section_copy"` on `POST /invocations` (Meriwether Sites C4,
`section-copy-generation`, T-1): copy for one site section, written for its
target questions from the record's facts. Prices, phone, licence, address and
hours numbers are re-checked in code after the model answers and the field is
refused whole when one is not in the inputs or (prices) not allowed or not on
the price list; a person's edited fields are kept word for word by name, a list
as a whole; voice tells and similarity are measured, never enforced; the stub
drafts deterministically from the inputs. Requests without `task` are articles,
unchanged. See [section copy](/lib/section-copy.md).

### Learning — a 7-digit local number sourced an invented area code

The first cut of the phone rule accepted a draft number when one digit string
ended with the other, to allow for a country code. A test written to prove the
inputs are scanned one at a time failed for a different reason: `123 4567` in
the record sourced `555 123 4567` in a draft, so the model could add an area
code nobody gave it and pass. The rule now allows at most three extra leading
digits and only against a full national number of ten or more.

## 2026-10-21

### Learning — a stub of fixed shape cannot pass a check derived from the template

The unscripted stub wrote one intro and one step whatever it was asked for, and
the completeness check refuses any article with fewer sections of a type than
its template. So every real template came back `INCOMPLETE_ARTICLE` locally,
and nothing after "Generate" in the portal could be exercised without a paid
Bedrock call. Found in browser verification of the portal's section editor. The
stub now mirrors the template: one placeholder section per template section, of
the same type and in the same order, with text that still reads as canned. The
shape reaches it on the prompt composition, as a field no model is ever sent.

## 2026-09-07

### Learning — a tool schema that makes the MODEL do the escaping is a latent parse failure

`emit_article` declared `sections_json` as a **string containing a JSON-encoded
array**, so every quote, backslash and newline in the article body had to be
escaped by the model. It worked six times and failed on the seventh with
`JSONDecodeError: Expecting ',' delimiter: line 1 column 3107` — from a clean
`stop_reason=tool_use` at 2029 of 32000 tokens. Nothing was truncated and
nothing was refused; the model wrote a correct article and mis-escaped one
character of its own envelope.

Two things made it expensive to read from outside:

- `server.py` maps every exception to `GENERATION_FAILED` and deliberately
  withholds the detail, so the operator was told **the runtime declined**. It
  had not declined. "Declined" and "crashed while parsing its own output" want
  different responses, and the API cannot tell them apart.
- The traceback was logged and the **payload was not**, so "column 3107" named
  a character nobody could read back.

⚠️ **Do not assume the endpoint accepts a nested array schema.** The comment
above the tool records that Mantle refuses `output_config.format` and
`strict: true`; an array schema could plausibly have been refused as well, and
deploying on that assumption would have broken generation outright rather than
fixing it. It was probed against the live endpoint before the change was
written: accepted, and `sections` arrives decoded with quotes, backslashes and
newlines intact.

⚠️ **The schema remains a HINT.** Because `strict: true` is refused,
`additionalProperties: False` on the item schema enforces nothing. Every
parse-side allowlist stays load-bearing — the unknown-type drop, and the
`image_asset_key` / `image_alt` drop that stops a shop's own profile text
inducing the model to publish a competitor's asset.

### Learning — a mutation check that does not apply reports a false green

Three of the mutation checks written for this change were themselves wrong, and
each looked like a pass:

- a `$`-anchored regex against a **CRLF** file matched nothing, and the gate
  reported exit 0 for an unmutated tree;
- multi-line anchors written with `\n` against the same CRLF file matched
  nothing;
- one mutation left `) from exc` dangling after an assignment, so the module
  stopped importing and pytest reported a **collection error** — non-zero, and
  worthless, because a syntax error reddens every test in the file including
  ones that assert nothing about the mutated behaviour.

The habit that catches all three: assert the file actually changed, assert the
module still imports, and require the failure to be a **failure** rather than
an error.

### Update

`okf/capabilities/howto-article-generation.md` — three scenarios added.
`okf/qa/howto-article-generation.md` — thirteen checks added.

## 2026-09-03

- **Update** — Repo created and built: `app/howto_generation/` (contracts, slot
  resolution, similarity, regeneration, prompt composition, the model seam, the
  pipeline, the server), 127 tests, a `gate` entry point, a CI workflow, a
  Dockerfile pinned to arm64, and this bundle. Concepts added: `service`,
  `endpoints/invocations`, `endpoints/ping`, `lib/slot-resolution`,
  `lib/similarity`, `lib/regeneration`, `lib/generation-pipeline`,
  `lib/prompt-composition`, `lib/model-seam`, `business/emit-only`,
  `business/differentiation`, `integrations/bedrock-claude`,
  `integrations/gateway`, `playbooks/run-locally`, plus
  `capabilities/howto-article-generation` and its QA checklist.

- **Learning** — **`aeo-agent-service` was named as the owner of HOW-4 and has
  no how-to code at all.** The four files matching "howto" there are the SoV
  question taxonomy — a question *type* alongside category, brand and
  comparison — which is a coincidental string match. It is also not in the call
  path: the gateway invokes AgentCore runtimes directly
  (`skill-builder-sessions/agui/agentcore-runtime.client.ts` is the precedent).
  The roadmap's repo-owner line was wrong and has been corrected.

- **Learning** — **The roadmap recorded service area as absent from the runtime
  context; it is present but unvalidated.** `geography` is documented on the
  gateway's DTO as the geographic-strategy blob. What is true is that it is
  passthrough `Record<string, unknown>` — present without being reliable — so it
  is read defensively with several shapes tolerated and omitted on anything
  unrecognised. CTAs, by contrast, are genuinely absent: no field of any kind,
  for any org.

- **Learning** — **There is no pricing field anywhere in the org runtime
  context, and the nearest thing is a trap.**
  `products_services[].pricing_model` is a billing model, not an amount. It is
  plausible enough that an implementation would reach for it, so pricing slots
  are refused in code rather than merely left unresolved — and the refusal is
  named to the model, because withholding is not the same as forbidding.

- **Learning** — **A MinHash built on Python's `hash()` fails silently and
  totally.** String hashing is randomised per process, so signatures differ on
  every run while the scores still come back as plausible numbers between zero
  and one. Nothing downstream can detect it; the stored history that a future
  threshold would be calibrated against becomes noise wearing four decimal
  places. `blake2b` throughout, and a check asserts determinism.

- **Learning** — **A chrome-stripping check needs its control or it proves
  nothing.** "Two articles sharing only chrome score near zero" passes just as
  happily against a stripper that does nothing, because two different bodies
  score near zero anyway. The control measures the same pair without declaring
  the chrome and requires a materially higher score — that is what makes the
  first check meaningful.

- **Learning** — **An import-boundary assertion has to run in a subprocess.**
  The first version of the lazy-import check was `assert "anthropic" not in
  sys.modules or True`, which cannot fail. Inside pytest the SDK may already be
  loaded by something unrelated, so the honest check runs a probe in a
  subprocess — plus a second probe that imports the SDK deliberately, proving
  the first one reports something.

- **Note** — **Nothing here has run against Bedrock.** `BedrockChatModel` is
  covered only for its parsing; the endpoint behaviour it encodes was measured
  on `aeo-skill-builder-runtime`, not here. Live verification is an AWS
  operation and is deliberately outside this change.

- **Note** — **Regeneration has an unsatisfied dependency on the gateway.**
  `howto_articles.published_snapshot` is NULL on published rows (measured
  2026-09-03), so nothing currently retains what generation produced. Until it
  does, every regeneration refuses with `BASELINE_REQUIRED` — correctly, but it
  means HOW-4.6 cannot complete end to end yet.

## 2026-09-04 (deployment)

- **Update** — Deployed to AgentCore: runtime `aeo_howto_generation-53Kml72pdB`, image `aeo-groundtruth/howto-generation` (arm64, digest-pinned), role `AmazonBedrockAgentCoreAEOHowtoGenerationRole`. `scripts/provision.py` is idempotent with `--check` and `--skip-push`.

- **Learning** — 🔴 **`bedrock-mantle` is a different service namespace from `bedrock`.** `AnthropicBedrockMantle` calls `bedrock-mantle:CreateInference` on a **project** resource, not `bedrock:InvokeModel` on a foundation model, so a role holding only the `bedrock:*` grant is denied 403 at the first generation — after the deploy reported success and the container started cleanly. ⚠️ The sibling runtime's role already carried this under the name `InvokeViaMantleWhichIsADifferentService`, i.e. it had been paid for once. Reading its provisioning script was not enough; the answer was in its **live IAM policy**. When copying a runtime, diff the IAM too.

- **Learning** — **The SDK refuses a non-streaming call whose `max_tokens` could exceed 10 minutes**, and 32000 trips it (the sibling's 16000 does not). Fixed by streaming from Bedrock internally — the runtime still answers the gateway with one JSON body. **Not** by shrinking the budget: the sibling documented 8000 killing a turn, and thinking shares this allowance, so cutting it trades a hard failure for a silent truncation that is indistinguishable from a short article by the time a reviewer sees it.

- **Note** — **First real evidence for HOW-4.3.** Two shops, one template, measured against each other: a fleet-focused shop in Springfield produced 7 sections on duty cycles and servicing calendars; a retail garage in Chatham produced 6 on "can this wait" and pre-purchase inspections. **Lexical similarity 0.0 at `compared_count: 1`** — distinct, not unmeasured. The criterion remains a human judgement over ten shops, so this is evidence rather than proof, but it is the strongest available and it was not obtainable before the deploy.

- **Note** — **Local runs still use the stub.** `aeo-backend/.env` keeps `HOWTO_GENERATION_RUNTIME_URL`, not the ARN, so local generation stays free. The ARN wins when set — switch deliberately, because every local generation then costs a real model call.

## 2026-09-09

### Learning — a good AI-tell list cannot be applied wholesale by a multi-trade generator

The house list flags abstract metaphor nouns: substrate, harness, scaffolding,
ratchet, wedge, flywheel, bedrock, vector, surface, primitive, tapestry,
landscape. **Every one of those is literal vocabulary for some business this
runtime generates for** — a wiring harness, a hand ratchet, flooring substrate,
an upholsterer's tapestry, a landscaper's whole trade. Automating them would
fire on correct copy for a real customer, and a check with that false-positive
rate teaches people to ignore it.

They stay in the prompt, where the model has the trade in front of it, and out
of the detector. `voice.NOT_AUTOMATED` records each exclusion with the word
that forced it.

⚠️ **The exclusion list itself must not reach the prompt.** An earlier draft
interpolated its examples, which drops mechanical vocabulary into the baseline
EVERY business shares, including a dental practice's. `test_industry_neutral.py`
does not catch that: its word list is automotive-specific and these words are
not on it.

### Learning — a curly apostrophe hid a phrase from its own detector

`PHRASE_TELLS` holds straight apostrophes, so `Let's dive in` typed with a
curly one matched no phrase. The character rule fired and reported the
punctuation, so the output looked like a detection — while the signposting it
was actually there to catch went unreported. Found by probing the detector, not
by reading it. Punctuation is folded before phrase matching now.

### Learning — my own boundary test could not fail, and a mutation check said so

`test_an_elevator_company_can_write_elevator` claimed to prove word-boundary
matching. It could not: `elevator` never contained `elevate` as a substring
(`elevat-or` vs `elevat-e`), so it passed with or without the lookarounds.
Replacing the pattern with a bare substring match left it green.

On today's list the boundaries protect nothing — every near-miss (`delved`,
`crucially`, `myriads`) is an inflection of the tell itself and should be
flagged. They protect the NEXT word added, so the test now exercises
`_word_pattern` directly with `tire` inside `entire` and `car` inside `carry`.

### Learning — the prompt cannot be checked against its own rules

The voice section LISTS the banned characters in order to forbid them, so it
contains all six. Any check asserting "the prompt carries no banned character"
is unsatisfiable. The rule is enforced on generated articles only.

### Update

`okf/capabilities/howto-article-generation.md` — three scenarios added.
`okf/qa/howto-article-generation.md` — twelve checks added.

## 2026-09-09

### Update

Deployed to AgentCore: runtime `aeo_howto_generation-53Kml72pdB`, **version 7**,
`HOWTO_GENERATION_BUILD_VERSION=19744a2@3e4a5b688417`, image digest-pinned and
READY. The pinned digest was compared against the one the push reported, rather
than assumed equal.

QA ran first: all 77 checks in `okf/qa/howto-article-generation.md` are automated
with a node id and none are `Manual`. Every id was proven to **resolve** with
`--collect-only` before being run — with a deliberately fake id as the control,
which collected nothing — and all 77 pass.

### Learning

**The workspace's record of what was deployed was wrong by two versions, and that
mis-sizes a deploy rather than merely being untidy.** `CLAUDE.md` said version 4 at
`34c48ab`; `get-agent-runtime` said version 6 at `4cea731`, updated two days
earlier. Sized from the note, this deploy looked like 11 commits and ~3,300 lines
across 20 files; the real delta was **2 commits** — one of them documentation only.
Everything downstream of that number would have been wrong: the review scope, the
risk call, the roadmap note. **Size a deploy by reading the runtime, never the
file that describes it.** The same line also claimed "two rows are Deployed" while
its own column said four.

**`provision.py` rewrites the role policy on every run, so the `bedrock-mantle`
grant has to be re-verified after each deploy, not once.** The documented trap is
that a missing `bedrock-mantle:CreateInference` fails **403 at the first
generation** — after the deploy reports success and the container starts cleanly.
So a deploy that ends green is not evidence the grant survived. Read it back off
the live role: `aws iam get-role-policy` showed all eight `bedrock-mantle` actions
present alongside the four `bedrock:` ones.

**This repo's `gate` runs two of its five steps.** `lint`, `typecheck` and `build`
each print "no toolchain in this repo; not checked" and pass. So "gate green" here
means 245 tests and `okf:check` — no static analysis of any kind ran over the 836
new lines. That is honest (it says so out loud) but it is not what the workspace
rule promises, and it is worth a row rather than a silent assumption.

2026-10-30 — Section copy review fixes on `15dd64e` (Meriwether Sites C4): the currency check now NFKC-normalises and matches markers and codes in any case, either side of the amount, with scale words (`$40k`, `1.5 million dollars`, `99¢`, `1299 kr`, `Rs. 500`, `$.99`), and `percent` reads like `%`; magnitudes scale before the price-list comparison; phones accept any Unicode dash, spaced separators and groups to 8 digits; a competitor's name refuses the field; sources are exactly what the prompt shows (collected in `compose`) plus the person's edits, and a bare 7-digit run no longer sources a phone; item-level `required` refuses a list; a field deleted from `current_fields` counts as edited; hours compare as 24-hour times; preserved field names are made safe outside the fence; the prompt caps questions at 12 and 300 characters. `okf/.DS_Store` removed and ignored. Measured: 515 tests; break-proofs for the currency, competitor and sources fixes each went red and were restored.

2026-10-31 — Section copy: claims and disagreements (`section-copy-generation`, Meriwether Sites C4). The first real-model run (Sonnet 5 via Bedrock) found drafts that were well written, price-free and kept edits, but invented how the business operates ("a same-day job, not something that sits in a general queue"), and, where the record's industry and the page's own sections disagreed, one field told readers "a burst pipe is not ours to fix" against the customer's own page. The prompt now limits claims about how the business works to what THE BUSINESS, the resolved facts, THE PAGE or the price list says, says the questions are not facts, gives a not-allowed and a write-instead example (trade-neutral), forbids saying the business does not do something unless an input says so, and on a record/page disagreement asserts neither version and reports it in the tool's new optional `disagreements`. In code, two NOTES and no refusals: `claim:<family> (<field>)` for ten promise-word families no business input uses (questions, competitors and cited hosts excluded from the sources via `claim_source_texts`; clock times and `24/7` stay with the hours refusal), and `disagreement:<line>`, bounded to three lines of 150 characters. Both ride in `audit.voice_tells` because the gateway rebuilds `field_notes` and `audit` key by key and would drop anything new. Updated: `capabilities/section-copy-generation`, `qa/section-copy-generation`, `lib/section-copy`, `endpoints/invocations`.

### Learning

**A question is not a fact about the business, and the number checks had been treating it as one for good reason that does not carry over.** A question's text sources a number because a model may legitimately echo it; it must not source a claim, because "who offers a guarantee" is a searcher's wish, not this business's promise. So claims have their own, narrower source list, collected in `compose` beside the existing one. Break-proof: letting question text into it took `test_a_question_is_not_a_source_for_a_claim` red, and nothing else.
- A disagreement note longer than 150 characters is cut at a word and ends with an ellipsis, never mid-thought (found reading the first real one on 2026-10-31).

2026-11-06 — Section copy: a business with several stores is drafted as serving every place (`drafting-names-every-store`, runtime half). Ground truth: Bramblewood Dental (Raleigh main, Cary, Durham; profile "Raleigh, NC") was drafted "Dental Care for Raleigh" and "Visit Bramblewood Dental in Raleigh" above a map of the Durham office, because the only place the request carried was `context.organization.address` (the profile's location), which `resolve_facts` turned into `city: Raleigh` and `address: Raleigh, NC` (`slots.py` city/address resolvers, `section_prompt.FACT_SLOTS`). The request now takes `places` (every live store, the main first, and the one store the subject is about); with any store the two profile facts are dropped, the towns are shown in the fence under WHERE THE BUSINESS IS, and the task tells the model to name every place (or a regional phrase true of all) or, for a one-store section or store page, that store's town only. The stable half gains the same rule, so the cached prefix changes once. Break-proof: resolving the profile facts despite `places` took four tests in `tests/test_section_places.py` red; restored. Updated: `lib/section-copy`, `endpoints/invocations`, `capabilities/section-copy-generation` (`scg-places`), `qa/section-copy-generation`.

2026-11-06 — Section copy: a drafted list meets its template's counts (`faq-groups-draft-meets-its-minimum`, runtime half). Checked first: no earlier commit covers it — `37829e9` made a list inside a list item draftable and checked, but no count reached the runtime at all: `SectionTemplateField` / `SectionItemField` had no `min_items` / `max_items`, `_field_line` and `_item_lines` printed only "a list of items", `_normalize_items` never counted, and the stub wrote two nested items (`questions[:2]`) — exactly the two-a-group production saw. Now the field carries `min_items` / `max_items`, the prompt states them, a list over its most is cut, one under its least refuses the field with a reason naming the place, and the stub pads to the least. Break-proof: skipping the least check took two tests in `tests/test_section_list_counts.py` red; restored. Updated: `lib/section-copy`, `endpoints/invocations`, `capabilities/section-copy-generation` (`scg-list-counts`), `qa/section-copy-generation`.

2026-11-06 — Review follow-ups to `drafting-names-every-store` (runtime half): `places.each_store_page` — a section of the stores' own pages' layout naming no store, which the site renders with each page's own store — is shown in the fence and the model is told to name no single town or store (drafting it as about the main store had put Raleigh copy on the Cary and Durham pages); and with any store the geography's `service_area` is dropped from the facts beside `city` and `address`. Updated: `lib/section-copy`, `endpoints/invocations`, `capabilities/section-copy-generation`, `qa/section-copy-generation`.
