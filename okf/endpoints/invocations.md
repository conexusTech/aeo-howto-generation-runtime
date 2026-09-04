---
type: API Route
title: POST /invocations
description: The single generation surface. A template plus one shop's runtime context in; a draft article, a similarity measurement and an audit record out.
resource: POST /invocations
tags: [agentcore, http, generation]
timestamp: 2026-09-03
---

# POST /invocations

One article, generated or regenerated. Called by the gateway,
[aeo-backend](aeo-backend:/service.md), which assembles the request from the
template library and the org runtime-context endpoint.

`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` is read and logged. It is not used
for anything else: generation is stateless, and two requests carrying the same
session id share nothing.

## Request

| Field | Meaning |
|---|---|
| `operation` | `generate` (default) or `regenerate` |
| `template` | The library template, sent whole — this runtime has no database to look one up in |
| `context` | The gateway's runtime-context payload, verbatim |
| `current_article` | Regeneration only: the article as it stands, human edits included |
| `generated_baseline` | Regeneration only: what generation last produced. **Required** — see [regeneration](/lib/regeneration.md) |
| `edit_policy` | `preserve` or `discard` |
| `corpus` | Published siblings from the same template, cross-tenant, body text only |
| `chrome_blocks` | Boilerplate the caller declares as furniture, removed before shingling |

Unknown fields are **ignored, not rejected**. The gateway's context DTO gains
fields regularly, and a runtime that rejects an unknown key turns every additive
gateway change into an outage in a repo nobody touched.

## Response

Always **HTTP 200**, carrying either a generation result or a typed error.

🔴 **This is deliberate and looks wrong at first glance.** AgentCore reports a
non-2xx as an invocation failure and frequently discards the body on the way
back, so a 400 with a precise explanation reaches the gateway as "it broke". The
gateway branches on `error_code` instead, and the distinction between a refusal
it should surface to an operator and a fault it should retry survives the trip.

| `error_code` | Means |
|---|---|
| `INVALID_REQUEST` | The body did not parse or failed validation. Detail is echoed — it describes the caller's own payload |
| `EMPTY_ARTICLE` | The model produced no usable sections. Retrying is the gateway's decision |
| `BASELINE_REQUIRED` | A regeneration arrived without `generated_baseline` |
| `INVALID_EDIT_POLICY` | `edit_policy` was neither `preserve` nor `discard` |
| `GENERATION_FAILED` | Anything unexpected. **The message is deliberately uninformative** — the gateway relays this body onward and a failure can carry fragments of tenant-authored context. The traceback stays in the runtime logs |

A success carries `title`, `sections`, `slots`, `similarity`, `regeneration`
(regeneration only), `audit` and `usage`.
