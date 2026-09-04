---
type: Service Module
title: Prompt composition
description: HOW-4.3. The instruction to produce a materially different article rather than the same one with the names changed — and an explicit note that this is not the enforcement layer.
resource: app/howto_generation/prompt.py
tags: [how-4.3, differentiation, prompt-cache]
timestamp: 2026-09-03
---

# Prompt composition

## The failure being managed is not the one people assume

Cross-domain duplication rarely draws a manual penalty. What happens is **index
filtering**: one shop's article is indexed and the rest are suppressed, so fifty
clients quietly become one. Retrieval converges the same way, giving a model no
reason to cite any particular copy. The articles are all live, all correct, and
all but one invisible.

So the instruction is not "reword this". It is: produce a materially different
article for this shop — different structure, different ordering, different
emphasis, different examples — from the same source material. The template is
framed as **subject matter, not a spine to hang copy on**.

## This is not the enforcement layer

⚠️ Everything in the prompt is a request the model complies with most of the
time, and most of the time is indistinguishable from always until it is not. The
hard rules live in [slot resolution](/lib/slot-resolution.md). Read the prompt as
the part that shapes good output, not the part that prevents bad output.

## What is excluded, and why that is a decision

The runtime-context payload also carries an entire prospect-scanning product:
`pipeline`, `known_companies`, `scoring_strategy`, `lead_scoring`,
`discovery_project_signals`. None of it reaches the model.

`known_companies` alone can be twenty thousand company names. Sending another
tenant's prospect list into a text generator is a data-exposure question we do
not need to have, and it would be paid for on every invocation.

## The cache breakpoint

The stable half carries the baseline instructions and the org; the volatile half
carries the template and the task. That is the right way round for the access
pattern — one shop gets several articles from different templates, so the shop
is what repeats — and Bedrock has no automatic prompt caching, making the manual
cache marker the main cost lever.
