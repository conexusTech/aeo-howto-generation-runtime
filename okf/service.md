---
type: Service
title: aeo-howto-generation-runtime
description: HOW-4 article generation — an AgentCore runtime that turns a library template plus one shop's onboarding record into a differentiated draft how-to article, measures how close it landed to other shops' articles, and writes nothing.
resource: app/howto_generation/server.py
tags: [agentcore, howto, generation, bedrock, arm64]
timestamp: 2026-09-03
---

# aeo-howto-generation-runtime

**HOW-4.** Given a how-to template from the global library and one shop's runtime
context, produce a draft article written *for that shop* — and record how similar
it turned out to every other shop's article from the same template.

## Why it is a separate repo

Generation was specified as living in `aeo-agent-service`. It does not, and the
reasoning is the same one that moved
[the skill builder](aeo-skill-builder-runtime:/service.md) out first: an
AgentCore runtime is a container with its own deployment, its own dependency
set, and a config surface of five fields. Inside `aeo-agent-service` those five
fields sat at the bottom of a ~360-line `Settings` class next to PostgreSQL,
Redis, Neo4j and Apify — none of which generation touches, and all of which it
would then have been able to reach.

`aeo-agent-service` has **no** how-to code and is **not** in this runtime's call
path. The gateway calls AgentCore runtimes directly.

## The shape of it

| | |
|---|---|
| Runtime | AWS Bedrock AgentCore Runtime, plain HTTP protocol, ARM64, Python 3.12 |
| Wire | `POST /invocations` takes a template + org context and answers with a draft article, a similarity measurement and an audit record; `GET /ping` is the liveness probe |
| Invoked by | the gateway, [aeo-backend](aeo-backend:/service.md) |
| Served on | port 8080, single uvicorn worker — the blocking model call is threadpooled |
| Entry point | `app/howto_generation/server.py` is the ASGI app; [lib/](/lib/slot-resolution.md) holds the logic |

**Not AGUI**, unlike the sibling. Generation is one request in and one article
out; an event stream would be ceremony around a single result. The skill builder
streams because it is a conversation.

## The three properties everything else follows from

**It is emit-only.** No database handle, no queue, no bucket, no write authority
of any kind. It proposes an article; the gateway writes one. See
[business/emit-only](/business/emit-only.md) — this is also the prompt-injection
backstop, because the org context it reads is tenant-authored free text.

**It refuses in code, not in the prompt.** HOW-4.2's three criteria — no invented
values, omit rather than fabricate, never price without a source — are enforced
by [slot resolution](/lib/slot-resolution.md) before the prompt is composed. A
prompt instruction is a request that is obeyed most of the time, and most of the
time is indistinguishable from always until it is not.

**It measures without enforcing.** [Similarity](/lib/similarity.md) returns a
number, a neighbour and two cost figures. It blocks nothing and alerts nothing;
the editorial gate in [aeo-frontend](aeo-frontend:/service.md) is the only
control on publication in V1.

## Where to go next

- One request, end to end: [lib/generation-pipeline](/lib/generation-pipeline.md)
- The refusals: [lib/slot-resolution](/lib/slot-resolution.md)
- The metric, and why it is lexical: [lib/similarity](/lib/similarity.md)
- Preserving human edits: [lib/regeneration](/lib/regeneration.md)
- What must be true: [capabilities/](/capabilities/howto-article-generation.md), proven by [qa/](/qa/howto-article-generation.md)
- Run it on this machine: [playbooks/run-locally](/playbooks/run-locally.md)
