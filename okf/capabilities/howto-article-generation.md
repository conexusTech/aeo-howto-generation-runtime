---
type: Capability
title: How-to article generation from a template and one shop record
description: What the runtime does when the gateway asks for an article — which facts it will and will not use, what it measures, what it preserves on a regeneration, and what it refuses.
---

# How-to article generation

Given a library template and one organization's runtime context, the runtime
produces a draft article written for that shop, measures how close it landed to
other shops' articles from the same template, and records exactly which inputs
it read.

**Seeded 2026-09-03**, by the change that built this repo
(`build-howto-generation-runtime`). Every scenario below is executed by the suite
in `tests/`, against the real modules, with a fake model injected. Nothing here
was transcribed from the specification: behaviour the change did not verify is
deliberately absent and stays absent until a change verifies it.

⚠️ **What is NOT here, and why.** HOW-4.3's actual criterion — that ten shops
produce articles a human judges to read as distinct pieces — is permanently
subjective and has no scenario, because a scenario that cannot fail is worse
than none. What is checked is that the instruction reaches the model and that
the measurement recording it is honest. See
[differentiation](/business/differentiation.md).

Related: [the pipeline](/lib/generation-pipeline.md) ·
[slot resolution](/lib/slot-resolution.md) · [similarity](/lib/similarity.md) ·
[regeneration](/lib/regeneration.md) · [emit-only](/business/emit-only.md)

## Scenarios

#### Scenario: Pricing is never generated, whatever the template asks for

- GIVEN a template declaring a pricing slot, required or optional
- AND an org record whose products carry a billing-model field
- WHEN an article is generated
- THEN the slot is refused rather than resolved, and the refusal states why
- AND the billing model is never used as a substitute for an amount
- AND the model is told, by name, that the slot is forbidden

**Checked by:** gen-pricing-always-refused, gen-pricing-refused-beside-plausible-field, gen-pricing-refusal-reaches-the-prompt

#### Scenario: A fact the org record does not carry is omitted, never invented

- GIVEN a template declaring a slot the runtime context has no field for
- WHEN an article is generated
- THEN the slot appears as omitted and never as resolved
- AND no resolved value is blank, a placeholder, or unsubstituted slot syntax
- AND a non-string field is never coerced into copy

**Checked by:** gen-missing-field-omits, gen-non-string-never-coerced, gen-no-resolved-value-is-blank, gen-unknown-slot-omitted

#### Scenario: A city is inferred only when unambiguous, and is marked as inferred

- GIVEN an organization whose only locality data is a free-text address
- WHEN the address has exactly one component that can be a city
- THEN that city is resolved, with provenance recording it as derived
- AND a bare street, or an address with two plausible candidates, resolves nothing
- AND a business name in the first position is never returned as a city

**Checked by:** gen-city-derived-from-clear-address, gen-city-omitted-when-ambiguous, gen-city-never-a-business-name, gen-city-marked-derived

#### Scenario: Similarity is measured against the nearest sibling and blocks nothing

- GIVEN a corpus of published articles from the same template, across tenants
- WHEN an article is generated
- THEN a score, the nearest article id and its organization id are returned
- AND the number compared and the elapsed time are recorded
- AND an article identical to a sibling is still returned as a draft

**Checked by:** gen-nearest-neighbour-reported, gen-cost-figures-recorded, gen-measurement-never-blocks

#### Scenario: Two articles sharing only boilerplate score near zero

- GIVEN two articles with identical declared chrome and entirely different bodies
- WHEN similarity is measured with that chrome declared
- THEN the score is near zero
- AND the same pair measured without declaring the chrome scores materially higher

**Checked by:** gen-chrome-stripped-scores-near-zero, gen-chrome-control-proves-stripping-fires

#### Scenario: An unmeasured article is distinguishable from a distinct one

- GIVEN the first article generated from a template, with no siblings to compare against
- WHEN similarity is measured
- THEN the compared count is zero
- AND the score of zero means unmeasured rather than perfectly distinct

**Checked by:** gen-empty-corpus-reports-zero-comparisons

#### Scenario: The similarity score is reproducible across processes

- GIVEN the same article text measured twice
- WHEN the MinHash signature is computed
- THEN it is identical
- AND it does not depend on the iteration order of the shingle set
- AND the estimate stays within tolerance of exact Jaccard

**Checked by:** gen-signature-deterministic, gen-signature-order-independent, gen-estimator-tracks-exact-jaccard

#### Scenario: Regeneration states its mode and preserves edits verbatim

- GIVEN an article with one human-edited section and a baseline of what generation last produced
- WHEN it is regenerated in preserve mode
- THEN the edited section survives byte for byte
- AND unedited sections take the fresh copy
- AND the response states the mode and which positions were preserved

**Checked by:** gen-preserve-states-mode, gen-preserve-keeps-edit-verbatim, gen-preserve-refreshes-unedited

#### Scenario: A discarded edit is reported rather than silently overwritten

- GIVEN an article with a human-edited section and a baseline
- WHEN it is regenerated in discard mode
- THEN the fresh copy replaces the edit
- AND the response names the positions that were discarded

**Checked by:** gen-discard-reports-what-it-threw-away

#### Scenario: Regeneration refuses when it cannot tell human copy from generated

- GIVEN a regeneration request with no generated baseline
- WHEN it runs in either preserve or discard mode
- THEN it refuses with a baseline-required code and names the missing field
- AND no article is returned

**Checked by:** gen-regeneration-refuses-without-baseline, gen-refusal-names-the-missing-field

#### Scenario: A human edit survives even when its section disappears

- GIVEN a human-edited section whose heading is absent from the regenerated article
- WHEN it is regenerated in preserve mode
- THEN the edited section is appended rather than dropped

**Checked by:** gen-orphaned-edit-is-appended

#### Scenario: Re-ordering sections is not mistaken for a human edit

- GIVEN a baseline and a current article containing the same sections in a different order
- WHEN edits are detected
- THEN no section is reported as edited

**Checked by:** gen-reorder-is-not-an-edit

#### Scenario: The exact inputs used are recorded for audit

- GIVEN an org context and a template
- WHEN an article is generated
- THEN the response records the context version, the organization, the template and the model
- AND it lists exactly which context paths were read, and no others
- AND an unstamped build version is omitted rather than reported as unknown

**Checked by:** gen-audit-records-context-version, gen-audit-lists-fields-read, gen-audit-records-template-and-model, gen-unstamped-build-omitted

#### Scenario: Generation is re-runnable and produces the same result

- GIVEN the same template, context and a deterministic model
- WHEN generation runs twice
- THEN the sections and the slot resolution are identical

**Checked by:** gen-rerunnable

#### Scenario: Prospect-scanning data never reaches the model

- GIVEN a runtime context carrying known companies, a pipeline vocabulary, scoring strategy, lead scoring and discovery signals
- WHEN the prompt is composed
- THEN none of those values appears in either half of it

**Checked by:** gen-prospect-data-excluded-from-prompt

#### Scenario: Every outcome reaches the gateway as a typed body, never a failure

- GIVEN a malformed body, a missing template, a model that raises, or an article with no usable sections
- WHEN the runtime is invoked
- THEN the response is HTTP 200 carrying an error code the gateway can branch on
- AND an unexpected failure's message is not echoed back

**Checked by:** gen-malformed-body-is-typed, gen-missing-template-is-typed, gen-model-failure-is-typed, gen-model-failure-does-not-leak, gen-empty-article-is-typed

#### Scenario: The article body is delivered as structured data, never as text the model must escape

- GIVEN the tool that delivers a finished article
- WHEN its schema is inspected
- THEN `sections` is an array of typed objects, and no field asks for JSON-encoded text
- AND the instructions tell the model that quotes, backslashes and line breaks need no escaping
- AND a body carrying all three arrives unchanged

**Checked by:** gen-tool-declares-a-real-array, gen-tool-does-not-ask-for-encoded-json, gen-item-schema-pins-required-fields, gen-hostile-body-copied-through, gen-tool-enum-matches-the-contract

#### Scenario: A wrongly shaped section payload fails loudly rather than publishing an empty article

- GIVEN a model that returns one section object instead of an array, or a `sections_json` string that is not valid JSON
- WHEN the payload is parsed
- THEN generation fails with a message naming the field and the shape or position at fault
- AND it never yields an article with no sections, because that is publishable and reads as a success
- AND an empty `sections` does not shadow a valid legacy payload beside it

**Checked by:** gen-non-list-sections-refused, gen-malformed-legacy-json-refused, gen-empty-array-does-not-shadow-legacy, gen-legacy-string-still-parses

#### Scenario: A decode failure records the text around the fault, not the start of the payload

- GIVEN a payload whose invalid character sits thousands of characters in
- WHEN the decode fails
- THEN the log carries a bounded window centred on that character
- AND the window is far smaller than the payload, because the text is tenant-influenced
- AND a line break inside it cannot forge a second log record

**Checked by:** gen-decode-window-contains-the-fault, gen-decode-window-is-bounded, gen-decode-log-cannot-be-forged, gen-decode-error-names-its-field

#### Scenario: An additive change to the gateway's context does not break generation

- GIVEN a request carrying context fields and top-level keys this runtime has never seen
- WHEN it is invoked
- THEN the unknown fields are ignored and the article is generated

**Checked by:** gen-unknown-fields-ignored

#### Scenario: The runtime holds no write authority anywhere

- GIVEN the settings this runtime reads
- WHEN they are inspected
- THEN none names a database, a queue, a bucket or a broker

**Checked by:** gen-settings-carry-no-connection-string

#### Scenario: The whole pipeline runs with no AWS

- GIVEN a machine with no credentials, no network and no Bedrock SDK
- WHEN the model module is imported
- THEN the SDK is not imported with it
- AND the stub-model flag that makes a local run possible is off unless explicitly set, and says so loudly when on

**Checked by:** gen-sdk-not-imported-eagerly, gen-sdk-probe-detects-an-eager-import, gen-stub-flag-off-by-default, gen-stub-flag-warns

#### Scenario: The liveness probe does not depend on the model

- GIVEN a runtime with no model configured
- WHEN the health probe is called
- THEN it answers healthy

**Checked by:** gen-ping-independent-of-model
