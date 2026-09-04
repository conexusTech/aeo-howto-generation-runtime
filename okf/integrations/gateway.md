---
type: External Integration
title: The gateway (aeo-backend)
description: The only caller. Assembles the request from the template library and the org runtime context, and performs every write this runtime only proposes.
resource: aeo-backend
tags: [gateway, contract]
timestamp: 2026-09-03
---

# The gateway

[aeo-backend](aeo-backend:/service.md) is the only thing that calls this
runtime, and the only thing that writes what it produces.

## What the gateway supplies

| Piece | Where it comes from |
|---|---|
| `template` | `howto_templates` — the global, SU-managed library |
| `context` | The org runtime-context endpoint, verbatim |
| `corpus` | Published articles from the same source template, **cross-tenant, assembled under SU context**, body text only |
| `generated_baseline` | Regeneration only. What generation last produced |

## What the gateway does with the answer

Writes the article row, writes the similarity record, and surfaces the draft to
the editorial queue in [aeo-frontend](aeo-frontend:/service.md). None of that
happens here — see [emit-only](/business/emit-only.md).

## Two open dependencies on the gateway

⚠️ **The baseline.** `howto_articles.published_snapshot` is NULL on published
rows today (measured 2026-09-03). Until something retains what generation
produced, [regeneration](/lib/regeneration.md) refuses to run at all.

⚠️ **The corpus assembly is cross-tenant and this runtime cannot check it.** We
receive body text and two ids; we have no way to verify the caller scoped the
query to one source template, and no way to notice if it sent something it
should not have. The `CorpusArticle` shape is deliberately minimal — no shop
name, no host, no tenant id — so the blast radius of a mistake up there is
bounded by what can physically be in the payload.

## What never crosses

The gateway sends the whole runtime-context payload, but
[the prompt](/lib/prompt-composition.md) forwards only the business half. The
prospect-scanning sections stay in this process and reach no model.
