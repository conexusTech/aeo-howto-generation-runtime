# Log

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
