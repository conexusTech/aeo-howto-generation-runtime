---
type: Service Module
title: The model seam
description: The only place a model is called, and the boundary that lets the entire test suite run with no AWS, no credentials and no network.
resource: app/howto_generation/model.py
tags: [bedrock, testing, boundary]
timestamp: 2026-09-03
---

# The model seam

`ChatModel` is the injection point. `FakeChatModel` stands in for tests;
`BedrockChatModel` is production.

## The lazy import is load-bearing

🔴 The Bedrock SDK is imported **inside `BedrockChatModel.__init__`**, so
importing this module and running the whole suite needs no SDK, no credentials
and no network. That is not a convenience: a runtime whose logic can only be
exercised against a live model endpoint is a runtime whose logic does not get
exercised.

A test asserts this in a **subprocess** — inside pytest the SDK may already be in
`sys.modules` because something else pulled it in, so an in-process assertion
would pass or fail for reasons unrelated to the module. A second test proves the
probe reports true when the SDK really is loaded, so false means something.

## Structured output is a tool, not a format

🔴 Structured outputs are documented for Bedrock, but the **Mantle** endpoint
rejects them: `output_config.format` comes back as an extra input that is not
permitted, and strict mode on a tool is refused too. Measured on the sibling
runtime rather than inferred — `output_config.effort` is accepted on the same
endpoint, so it is the format parameter specifically. A tool schema is the only
way to get a structured result out of this endpoint at all.

## `tool_choice` is deliberately unforced

Measured on the sibling against the live endpoint: forcing the tool **suppresses
the thinking block**, so the model reasons inside the argument field instead —
and it produced an answer contradicting its own stated reasoning, in roughly
double the tokens. Forcing costs accuracy *and* money; it is not the
safe-looking option it appears to be.

The cost is that the model sometimes answers in prose. That gets **one** bounded
retry with the tool forced: the unforced call already failed, so the choice is a
worse answer versus no answer. Usage from both calls is summed, because the
first call's tokens were really spent.

## Positions are ours, never the model's

A model asked for contiguous 1-based positions will occasionally skip one or
repeat one, and the gateway's stored invariant is contiguity. Taking the array
order and numbering it here removes a class of defect rather than validating for
it. A section with an unrecognised type is **dropped rather than coerced** — the
four types drive rendering, and quietly mapping an invented fifth onto a step
publishes something in a shape nobody chose.
