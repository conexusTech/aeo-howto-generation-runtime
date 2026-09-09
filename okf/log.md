# Log

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
