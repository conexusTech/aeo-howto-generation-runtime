---
type: External Integration
title: Claude on Bedrock (Mantle)
description: The only outward call this runtime makes. Claude Sonnet 5 through the Bedrock Mantle client, with adaptive thinking and a manual prompt-cache breakpoint.
resource: anthropic.claude-sonnet-5
tags: [bedrock, anthropic, model]
timestamp: 2026-09-03
---

# Claude on Bedrock

The one outward call. Everything else this runtime does is local computation.

| | |
|---|---|
| Model | `anthropic.claude-sonnet-5` (default), region `us-east-1` |
| Client | `AnthropicBedrockMantle`, imported lazily — see [the model seam](/lib/model-seam.md) |
| Thinking | adaptive |
| Structured output | a tool schema, because the format parameter is rejected on this endpoint |
| Cache | one manual breakpoint on the stable prompt prefix |

## The model id prefix

🔴 The bare `anthropic.` prefix is **correct** — do not normalise it to the
regional `us.anthropic.` form. Prefix forms are per-endpoint: the Mantle client
wants the bare form and returns 404 on the other, while `bedrock-runtime` wants
exactly the opposite. This cost the sibling runtime a debugging session and is
written down so it costs this one nothing.

## Why `[bedrock]` is load-bearing in requirements.txt

🔴 The extra pulls boto3/botocore, which the Mantle client needs for request
signing. Without it the first model-backed call dies with a missing-module error
naming botocore — and **botocore appears in no import statement anywhere**, so a
grep of the package's imports cannot find it. The sibling runtime shipped
without the extra for exactly this reason.

## Cost shape

Generation is one long call per article, billed per invocation, with a
`max_tokens` of 32000 that thinking and the article **share**. A truncated
article is indistinguishable from a short one once it reaches a reviewer, which
is why the ceiling is higher here than in the chat sibling.

The stable prompt prefix — baseline instructions plus the org context — carries
the cache marker. One shop typically gets several articles from different
templates, so the org half is what repeats and is worth caching.
