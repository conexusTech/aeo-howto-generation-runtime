---
type: Business Concept
title: Emit-only
description: This runtime proposes; the gateway writes. It holds no database handle, no queue, no bucket and no write authority of any kind — which is also the prompt-injection backstop.
tags: [boundary, security, tenancy]
timestamp: 2026-09-03
---

# Emit-only

This runtime returns a draft article, a measurement and an audit record. It
**writes nothing, anywhere**. Every side effect — the article row, the
similarity record, the asset reference — is performed by the gateway,
[aeo-backend](aeo-backend:/service.md).

## Why it is a boundary and not a division of labour

The org runtime context is **tenant-authored free text**. A shop's description,
its personas' pain points, its market names — all of it was typed by somebody
outside our organisation, and all of it is fed to a language model. That is
prompt injection with a supply chain, and no amount of instruction-hardening
closes it.

What closes it is that the process reading that text has nowhere to write. An
injected instruction that persuades the model to exfiltrate data has no channel;
one that persuades it to modify a record has no handle. The containment is
structural rather than behavioural, which is the only kind that survives a model
being talked into something.

## How to tell it has been broken

`Settings` carries no field naming a database, a queue, a bucket or a broker. A
test asserts this by scanning the field names, which is a blunt check and
deliberately so — the failure it guards against does not arrive as a subtle
refactor, it arrives as somebody adding `DATABASE_URL` because a feature needed
one thing from Postgres.

If a change here wants a connection string, that is the signal to stop and
re-read this page, not to add a field. The thing it wants is the gateway's to
supply in the request or to do with the response.

## The same posture, one repo over

[aeo-skill-builder-runtime](aeo-skill-builder-runtime:/service.md) is emit-only
for identical reasons, and its config file carries the same warning. Two runtimes
reaching the same conclusion independently is worth noting: the shape is a
property of "an AgentCore runtime handling tenant data", not of either feature.
