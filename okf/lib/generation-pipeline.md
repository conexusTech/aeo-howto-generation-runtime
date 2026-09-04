---
type: Service Module
title: The generation pipeline
description: One request, end to end. The deterministic spine that calls the model exactly once and does everything else itself.
resource: app/howto_generation/runtime.py
tags: [how-4.1, orchestration]
timestamp: 2026-09-03
---

# The generation pipeline

```
resolve slots  ->  compose prompt  ->  MODEL  ->  merge  ->  measure  ->  audit
   HOW-4.2          HOW-4.3                      HOW-4.6    HOW-4.4     HOW-4.1
```

Order matters and is not arbitrary. **Slots resolve first** because everything
downstream depends on knowing which facts exist — and because the refusals have
to be in hand before the prompt is written. A prompt composed before the pricing
refusal is known is a prompt that never mentions it.

Every stage except the model call is a pure function of its inputs, so the whole
pipeline is deterministic given a deterministic model. That is what makes
HOW-4.1's "re-runnable" a testable claim rather than an aspiration.

**There is no path through this module that requires AWS.** The model sits
behind [the model seam](/lib/model-seam.md) and the tests inject a fake.

## The audit record

HOW-4.1 asks that the exact inputs used are recorded for audit — inputs, not a
summary of them.

| Field | Answers |
|---|---|
| `context_version` | Which org snapshot generation saw. The gateway's token changes whenever onboarding data changes |
| `inputs_used` | Which fields of it were actually read. The complement against the context is what was ignored — occasionally the more interesting half |
| `template_id`, `template_service_key`, `template_vertical` | What it was generated from |
| `model_id`, `build_version` | What generated it |

An unstamped `build_version` is **omitted** rather than reported as "unknown": a
deploy that forgot to stamp should look different from one that stamped a
placeholder.

Together these answer "what did the generator see" without this runtime storing
anything, which it [cannot do](/business/emit-only.md).
