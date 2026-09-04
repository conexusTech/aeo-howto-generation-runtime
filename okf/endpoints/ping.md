---
type: API Route
title: GET /ping
description: AgentCore liveness probe. Answers whether the process is up, and deliberately nothing else.
resource: GET /ping
tags: [agentcore, health]
timestamp: 2026-09-03
---

# GET /ping

Returns `{"status": "healthy"}`. Required by AgentCore alongside
[POST /invocations](/endpoints/invocations.md).

⚠️ **It does not construct the Bedrock client, and must not start.** Doing so
would turn a misconfigured model id, a missing region or an IAM denial into a
failing health check — so the container would be reported unhealthy and recycled
instead of accepting a request and returning one clear typed error naming the
actual problem. Liveness and model reachability are separate questions and this
answers only the first.

The same reasoning holds in the sibling runtime, where it is written down for
the same reason: the instinct to make a health check "more thorough" is strong
and the failure it produces is a restart loop with no diagnosis in it.
