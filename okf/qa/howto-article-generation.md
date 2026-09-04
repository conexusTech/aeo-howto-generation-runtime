---
type: QA Checklist
title: Checks for how-to article generation
description: One check per requirement in the howto-article-generation capability, with the exact command and the condition that makes it fail.
---

# Checks for how-to article generation

Proves [howto-article-generation](/capabilities/howto-article-generation.md).

**Preconditions for every check below.** All were satisfied when this list was
first executed, on 2026-09-03.

1. A Python 3.12 virtual environment at `.venv`, with `requirements.txt` plus
   `pytest` and `httpx` installed.
2. Nothing else. **No AWS credentials, no network, no Bedrock SDK reachability**
   — that is a property under test, not a convenience.

Run everything at once with `bash scripts/gate.sh`, or a single check with the
`Automated:` path beside it.

⚠️ **Every check here is automated, and that is worth one sentence of scepticism
rather than satisfaction.** The reason it was achievable is that this runtime is
a pure function of its inputs with exactly one external call, behind a seam. It
says nothing about whether the articles are any good — the only criterion that
measures that is
[deliberately human](/business/differentiation.md) and appears nowhere in this
list. A fully-green checklist here is compatible with generation producing
fifty articles that read identically.

---

### Check: gen-pricing-always-refused

**Requirement:** Pricing is never generated, whatever the template asks for
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestPricingIsRefused::test_every_pricing_slot_is_refused`

**Do**

Resolve each name in `PRICING_SLOTS`, one at a time, against a full org context.

**Expect**

Every name appears in `refused` and none in `resolved`. A single name resolving fails the check.

---

### Check: gen-pricing-refused-beside-plausible-field

**Requirement:** Pricing is never generated, whatever the template asks for
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestPricingIsRefused::test_pricing_is_refused_even_when_a_plausible_field_sits_nearby`

**Do**

Resolve a `price_band` slot against a context whose `products_services` carry `pricing_model: "one-time"`.

**Expect**

The slot is refused and the string `one-time` appears nowhere in the resolved values. This is the case a naive implementation gets wrong, so a refusal proven only against an empty context proves nothing.

---

### Check: gen-pricing-refusal-reaches-the-prompt

**Requirement:** Pricing is never generated, whatever the template asks for
**Surface:** Prompt composition
**Automated:** `tests/test_runtime.py::TestSlotsFlowThrough::test_the_refusal_reaches_the_prompt_the_model_saw`

**Do**

Generate with a pricing slot declared, and read the prompt the fake model was handed.

**Expect**

The volatile half names the slot under a FORBIDDEN heading. A refusal recorded in the response but absent from the prompt would let the model write a price anyway.

---

### Check: gen-missing-field-omits

**Requirement:** A fact the org record does not carry is omitted, never invented
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestOmitsRatherThanFabricates::test_a_missing_field_omits_the_slot`

**Do**

Resolve `shop_name` against an organization with no name.

**Expect**

The slot is listed in `omitted` and absent from `resolved`.

---

### Check: gen-non-string-never-coerced

**Requirement:** A fact the org record does not carry is omitted, never invented
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestOmitsRatherThanFabricates::test_a_non_string_field_is_never_coerced`

**Do**

Resolve `shop_name` against an organization whose `name` is null.

**Expect**

The slot is omitted, and the literal string `None` appears in no resolved value. This is the specific path by which a null becomes published copy.

---

### Check: gen-no-resolved-value-is-blank

**Requirement:** A fact the org record does not carry is omitted, never invented
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestOmitsRatherThanFabricates::test_no_resolved_value_is_ever_blank`

**Do**

Resolve a mixed set of seven slots and inspect every resolved value.

**Expect**

None is blank or whitespace, and none contains unsubstituted slot braces.

---

### Check: gen-unknown-slot-omitted

**Requirement:** A fact the org record does not carry is omitted, never invented
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestOmitsRatherThanFabricates::test_an_unrecognised_slot_is_omitted_not_guessed`

**Do**

Resolve a slot name no resolver is registered for.

**Expect**

It is omitted. Inventing a value for an unrecognised name is how a template starts quietly shipping sections nobody specified.

---

### Check: gen-city-derived-from-clear-address

**Requirement:** A city is inferred only when unambiguous, and is marked as inferred
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestDeriveCity::test_a_well_formed_address_yields_the_city`

**Do**

Derive a city from a four-part street address ending in a state, postcode and country.

**Expect**

The city component is returned, not the country and not the postcode line.

---

### Check: gen-city-omitted-when-ambiguous

**Requirement:** A city is inferred only when unambiguous, and is marked as inferred
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestDeriveCity::test_an_ambiguous_address_yields_nothing`, `tests/test_slots.py::TestDeriveCity::test_a_bare_street_yields_nothing`

**Do**

Derive a city from an address with two plausible candidates, and from a single-component street line.

**Expect**

Nothing is returned in either case. Choosing between two candidates is a fabricated value that happens to be well-formed.

---

### Check: gen-city-never-a-business-name

**Requirement:** A city is inferred only when unambiguous, and is marked as inferred
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestDeriveCity::test_a_business_name_is_never_returned_as_a_city`

**Do**

Derive a city from an address whose first component is a trading name.

**Expect**

Nothing is returned. The first component is discarded unread precisely for this case.

---

### Check: gen-city-marked-derived

**Requirement:** A city is inferred only when unambiguous, and is marked as inferred
**Surface:** Slot resolution
**Automated:** `tests/test_slots.py::TestDeriveCity::test_a_derived_value_is_marked_as_derived`

**Do**

Resolve a `city` slot and read its provenance.

**Expect**

The provenance is prefixed `derived:`, so a reviewer can tell an inferred city from one read out of a field.

---

### Check: gen-nearest-neighbour-reported

**Requirement:** Similarity is measured against the nearest sibling and blocks nothing
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestMeasurement::test_the_nearest_neighbour_is_the_one_reported`

**Do**

Measure against a corpus of two, one a near-duplicate and one unrelated.

**Expect**

The near-duplicate is named as the nearest, with its organization id, and the compared count is two.

---

### Check: gen-cost-figures-recorded

**Requirement:** Similarity is measured against the nearest sibling and blocks nothing
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestMeasurement::test_duration_and_count_are_recorded`

**Do**

Measure against a corpus of five and read the measurement.

**Expect**

`compared_count` is five and `duration_ms` is present. These are the evidence that replaces a guessed corpus ceiling.

---

### Check: gen-measurement-never-blocks

**Requirement:** Similarity is measured against the nearest sibling and blocks nothing
**Surface:** The generation pipeline
**Automated:** `tests/test_runtime.py::TestSimilarityIsMeasured::test_measurement_never_blocks_the_draft`

**Do**

Generate with a corpus containing an article identical to the one produced.

**Expect**

The score is above 0.9 AND a full draft is still returned. No exception, no threshold, no alert.

---

### Check: gen-chrome-stripped-scores-near-zero

**Requirement:** Two articles sharing only boilerplate score near zero
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestChromeExclusion::test_two_articles_sharing_only_chrome_score_near_zero`

**Do**

Measure two articles with an identical declared chrome block and entirely different bodies, declaring that block.

**Expect**

The score is below 0.02.

---

### Check: gen-chrome-control-proves-stripping-fires

**Requirement:** Two articles sharing only boilerplate score near zero
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestChromeExclusion::test_without_stripping_the_same_pair_scores_materially_higher`

**Do**

Measure the same pair twice, once declaring the chrome and once not.

**Expect**

The undeclared run scores above 0.15 and strictly higher than the declared run. **Without this control the check above passes just as happily against a stripper that does nothing.**

---

### Check: gen-empty-corpus-reports-zero-comparisons

**Requirement:** An unmeasured article is distinguishable from a distinct one
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestMeasurement::test_an_empty_corpus_reports_zero_comparisons`

**Do**

Measure with an empty corpus.

**Expect**

`compared_count` is zero, the score is 0.0 and the nearest article is null — so a consumer that reads the count first cannot mistake unmeasured for distinct.

---

### Check: gen-signature-deterministic

**Requirement:** The similarity score is reproducible across processes
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestMinHash::test_the_signature_is_deterministic_across_calls`

**Do**

Compute the signature of the same shingle set twice.

**Expect**

Identical tuples. A signature built on Python's randomised string hash would differ per process while still returning plausible scores, turning the stored history into noise.

---

### Check: gen-signature-order-independent

**Requirement:** The similarity score is reproducible across processes
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestMinHash::test_the_signature_does_not_depend_on_set_iteration_order`

**Do**

Compute the signature of the same shingles inserted in two different orders.

**Expect**

Identical tuples.

---

### Check: gen-estimator-tracks-exact-jaccard

**Requirement:** The similarity score is reproducible across processes
**Surface:** Similarity measurement
**Automated:** `tests/test_similarity.py::TestMinHash::test_the_estimate_tracks_exact_jaccard`

**Do**

Compare the MinHash estimate against exact Jaccard on a pair with known overlap.

**Expect**

They agree within 0.10. Bounding against ground truth rather than asserting an exact value, which would only be asserting the seed.

---

### Check: gen-preserve-states-mode

**Requirement:** Regeneration states its mode and preserves edits verbatim
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestPreserve::test_the_mode_is_stated`, `tests/test_runtime.py::TestRegeneration::test_a_regeneration_reports_its_mode`

**Do**

Regenerate in preserve mode and read the outcome.

**Expect**

The mode is stated on the response, so a reader never has to infer it.

---

### Check: gen-preserve-keeps-edit-verbatim

**Requirement:** Regeneration states its mode and preserves edits verbatim
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestPreserve::test_an_edited_section_survives_verbatim`

**Do**

Regenerate an article whose second section was rewritten by a person.

**Expect**

That section's body is byte-identical to what the person wrote — not merged, not re-flowed, not tidied.

---

### Check: gen-preserve-refreshes-unedited

**Requirement:** Regeneration states its mode and preserves edits verbatim
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestPreserve::test_unedited_sections_take_the_fresh_copy`

**Do**

Regenerate and inspect a section nobody edited.

**Expect**

It carries the fresh copy. Preserve means preserve the edits, not preserve the article — otherwise regeneration does nothing.

---

### Check: gen-discard-reports-what-it-threw-away

**Requirement:** A discarded edit is reported rather than silently overwritten
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestDiscard::test_what_was_discarded_is_reported`

**Do**

Regenerate in discard mode over an article with one edited section.

**Expect**

The fresh copy wins AND the outcome names the discarded position. A mode name alone does not tell a reviewer what was lost.

---

### Check: gen-regeneration-refuses-without-baseline

**Requirement:** Regeneration refuses when it cannot tell human copy from generated
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestRefusals::test_regeneration_without_a_baseline_is_refused`, `tests/test_runtime.py::TestRegeneration::test_a_regeneration_without_a_baseline_is_refused`

**Do**

Regenerate with no baseline, in preserve mode and again in discard mode.

**Expect**

Both refuse with `BASELINE_REQUIRED` and no article comes back. **Both modes** matters: refusing only `discard` would leave `preserve` claiming edits survived while having no idea which ones they were.

---

### Check: gen-refusal-names-the-missing-field

**Requirement:** Regeneration refuses when it cannot tell human copy from generated
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestRefusals::test_the_refusal_names_what_is_missing`

**Do**

Read the refusal message.

**Expect**

It names `generated_baseline`, so the caller knows what to send rather than what went wrong.

---

### Check: gen-orphaned-edit-is-appended

**Requirement:** A human edit survives even when its section disappears
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestPreserve::test_an_edit_whose_heading_vanished_is_appended_not_dropped`

**Do**

Regenerate so that the edited section's heading is absent from the fresh article.

**Expect**

The human text is present somewhere in the result. Losing it is the one unrecoverable outcome; an odd position is a five-second fix.

---

### Check: gen-reorder-is-not-an-edit

**Requirement:** Re-ordering sections is not mistaken for a human edit
**Surface:** Regeneration
**Automated:** `tests/test_regenerate.py::TestFindingEdits::test_reordering_alone_is_not_an_edit`

**Do**

Detect edits between a baseline and the same sections in a different order.

**Expect**

No edits. Generation varies ordering deliberately, and a report where everything is flagged is one nobody reads.

---

### Check: gen-audit-records-context-version

**Requirement:** The exact inputs used are recorded for audit
**Surface:** The generation pipeline
**Automated:** `tests/test_runtime.py::TestAudit::test_the_audit_records_the_context_version`

**Do**

Generate and read the audit record.

**Expect**

The gateway's context version is carried through unchanged. It is the token that pins which org snapshot generation saw.

---

### Check: gen-audit-lists-fields-read

**Requirement:** The exact inputs used are recorded for audit
**Surface:** The generation pipeline
**Automated:** `tests/test_runtime.py::TestAudit::test_the_audit_records_which_fields_were_read`

**Do**

Generate with four slots declared, two of which resolve.

**Expect**

`inputs_used` lists exactly the two paths that contributed, sorted — not the four that were asked for.

---

### Check: gen-audit-records-template-and-model

**Requirement:** The exact inputs used are recorded for audit
**Surface:** The generation pipeline
**Automated:** `tests/test_runtime.py::TestAudit::test_the_audit_records_the_template_and_the_model`

**Do**

Generate and read the audit record.

**Expect**

Template id, service key, vertical, model id and organization id are all present.

---

### Check: gen-unstamped-build-omitted

**Requirement:** The exact inputs used are recorded for audit
**Surface:** The generation pipeline
**Automated:** `tests/test_runtime.py::TestAudit::test_an_unstamped_build_is_omitted_rather_than_reported_unknown`, `tests/test_runtime.py::TestAudit::test_a_stamped_build_is_reported`

**Do**

Generate once with no build stamp and once with one.

**Expect**

Null when unstamped, the value when stamped. A deploy that forgot to stamp must look different from one that stamped a placeholder.

---

### Check: gen-rerunnable

**Requirement:** Generation is re-runnable and produces the same result
**Surface:** The generation pipeline
**Automated:** `tests/test_runtime.py::TestProducesADraft::test_it_is_rerunnable`

**Do**

Run generation twice with identical inputs and a deterministic model.

**Expect**

Identical sections and identical slot resolution.

---

### Check: gen-prospect-data-excluded-from-prompt

**Requirement:** Prospect-scanning data never reaches the model
**Surface:** Prompt composition
**Automated:** `tests/test_prompt.py::TestProspectDataIsExcluded::test_scanning_machinery_never_reaches_the_model`

**Do**

Compose a prompt from a context carrying known companies, a pipeline vocabulary, scoring strategy, lead scoring and discovery signals.

**Expect**

None of those values appears in either half. A prospect list can be twenty thousand names, and it would be paid for on every invocation as well as exposed.

---

### Check: gen-malformed-body-is-typed

**Requirement:** Every outcome reaches the gateway as a typed body, never a failure
**Surface:** `POST /invocations`
**Automated:** `tests/test_server.py::TestEveryOutcomeIsTyped::test_a_malformed_body_is_a_200_with_an_error_code`, `tests/test_server.py::TestEveryOutcomeIsTyped::test_a_json_array_body_is_refused_by_code`

**Do**

Post unparseable bytes, then a JSON array.

**Expect**

HTTP 200 with `INVALID_REQUEST` both times. A non-2xx would reach the gateway as an invocation failure with the explanation discarded.

---

### Check: gen-missing-template-is-typed

**Requirement:** Every outcome reaches the gateway as a typed body, never a failure
**Surface:** `POST /invocations`
**Automated:** `tests/test_server.py::TestEveryOutcomeIsTyped::test_a_missing_template_is_refused_by_code`

**Do**

Post a body with a context and no template.

**Expect**

HTTP 200 with `INVALID_REQUEST`.

---

### Check: gen-model-failure-is-typed

**Requirement:** Every outcome reaches the gateway as a typed body, never a failure
**Surface:** `POST /invocations`
**Automated:** `tests/test_server.py::TestEveryOutcomeIsTyped::test_a_model_failure_is_a_200_with_an_error_code`

**Do**

Inject a model that raises, and invoke.

**Expect**

HTTP 200 with `GENERATION_FAILED`.

---

### Check: gen-model-failure-does-not-leak

**Requirement:** Every outcome reaches the gateway as a typed body, never a failure
**Surface:** `POST /invocations`
**Automated:** `tests/test_server.py::TestEveryOutcomeIsTyped::test_a_model_failure_does_not_leak_its_message`

**Do**

Inject a model whose exception message names an internal host, and read the response body.

**Expect**

Neither the message nor the host appears. The gateway relays this body onward and a generation failure can carry fragments of tenant-authored context.

---

### Check: gen-empty-article-is-typed

**Requirement:** Every outcome reaches the gateway as a typed body, never a failure
**Surface:** `POST /invocations`
**Automated:** `tests/test_server.py::TestEveryOutcomeIsTyped::test_an_empty_article_is_a_200_with_an_error_code`

**Do**

Inject a model returning no usable sections.

**Expect**

HTTP 200 with `EMPTY_ARTICLE`. An article with no sections cannot be published and must not come back as though it could.

---

### Check: gen-unknown-fields-ignored

**Requirement:** An additive change to the gateway's context does not break generation
**Surface:** `POST /invocations`
**Automated:** `tests/test_server.py::TestInvocations::test_an_unknown_context_field_is_ignored_not_rejected`

**Do**

Invoke with an invented context field and an invented top-level key.

**Expect**

A normal article. Rejecting an unknown key would turn every additive gateway change into an outage in a repo nobody touched.

---

### Check: gen-settings-carry-no-connection-string

**Requirement:** The runtime holds no write authority anywhere
**Surface:** Configuration
**Automated:** `tests/test_server.py::TestEmitOnly::test_the_settings_carry_no_connection_string`

**Do**

Scan every settings field name for database, queue, bucket and broker tokens.

**Expect**

None matches. A blunt check, deliberately: the failure it guards against arrives as somebody adding a connection string because a feature needed one thing from Postgres.

---

### Check: gen-sdk-not-imported-eagerly

**Requirement:** The whole pipeline runs with no AWS
**Surface:** The model seam
**Automated:** `tests/test_model.py::TestImportBoundary::test_importing_the_module_does_not_import_the_anthropic_sdk`

**Do**

In a subprocess, import the model module and report whether the Bedrock SDK is in `sys.modules`.

**Expect**

It is not. A subprocess because inside pytest the SDK may already be loaded by something else, making an in-process assertion meaningless.

---

### Check: gen-sdk-probe-detects-an-eager-import

**Requirement:** The whole pipeline runs with no AWS
**Surface:** The model seam
**Automated:** `tests/test_model.py::TestImportBoundary::test_the_probe_would_notice_an_eager_import`

**Do**

Run the same probe against a script that does import the SDK.

**Expect**

It reports true. **The control for the check above** — without it, that check would pass against a probe that never imports anything.

---

### Check: gen-stub-flag-off-by-default

**Requirement:** The whole pipeline runs with no AWS
**Surface:** Configuration
**Automated:** `tests/test_server.py::TestStubModelFlag::test_the_stub_flag_is_off_by_default`

**Do**

Construct settings with no environment set and read the stub flag.

**Expect**

False. A default of true would mean a deploy that set nothing served canned articles, and canned prose is plausible enough that a reviewer might approve one.

---

### Check: gen-stub-flag-warns

**Requirement:** The whole pipeline runs with no AWS
**Surface:** Configuration
**Automated:** `tests/test_server.py::TestStubModelFlag::test_turning_the_flag_on_logs_a_warning`, `tests/test_server.py::TestStubModelFlag::test_the_stub_flag_returns_a_fake_and_never_builds_bedrock`

**Do**

Set the stub flag and build the model, capturing logs.

**Expect**

A fake model comes back, no Bedrock client is constructed, and a warning names the flag. A silent stub is the dangerous one.

---

### Check: gen-ping-independent-of-model

**Requirement:** The liveness probe does not depend on the model
**Surface:** `GET /ping`
**Automated:** `tests/test_server.py::TestPing::test_ping_does_not_construct_the_model`

**Do**

Clear every dependency override — so a real Bedrock client would be built if anything asked for one — and call the probe.

**Expect**

HTTP 200. If the probe touched the model, a bad model id or an IAM denial would recycle the container instead of returning one clear typed error.
