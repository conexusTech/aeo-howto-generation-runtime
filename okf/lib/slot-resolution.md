---
type: Service Module
title: Slot resolution
description: HOW-4.2. Decides which shop facts are legitimately available, which are missing, and which are refused outright — before a prompt is composed.
resource: app/howto_generation/slots.py
tags: [how-4.2, localization, refusal]
timestamp: 2026-09-03
---

# Slot resolution

HOW-4.2's three acceptance criteria are each a refusal:

- no slot renders a placeholder or an invented value
- a missing input omits the section rather than fabricating it
- pricing never appears without a source field

**All three are enforced here, in code, and none of them is enforced by the
prompt.** The generated copy never sees a slot this module refused to resolve,
so there is nothing for a model to substitute even if
[the prompt](/lib/prompt-composition.md) failed entirely.

## The division of labour with the gateway

The mechanical half already exists in `aeo-backend`
(`src/backend/howto/howto-slots.ts`): it substitutes the slot references and
drops any section referencing an unresolved one. What lives here is the half it
cannot do — deciding **which values are legitimately available** from an org's
runtime context, and which are not available at any price.

## Three outcomes, not two

| Outcome | Means | Consequence |
|---|---|---|
| `resolved` | A value, with the context path it came from | Used, and named in the audit |
| `omitted` | Declared by the template, nothing available | The section is dropped downstream |
| `refused` | Available-looking, but forbidden | Named to the model as forbidden |

The third exists because withholding is not the same as forbidding. A model that
merely sees no pricing slot will sometimes add pricing anyway — an article about
a repair reads as though it wants a price in it.

## Pricing

`PRICING_SLOTS` is refused unconditionally. The org runtime context has **no
pricing field**; `products_services[].pricing_model` is the nearest thing and it
is a billing model, not an amount. Reading it as a price is exactly the
fabrication the criterion forbids, and it is plausible enough that somebody
would.

When onboarding grows a real pricing-band field, delete a name from that set and
add a resolver. Until then it is a closed door rather than a missing resolver —
the two behave identically and only one of them says why.

## City is the one inference, and it is marked as one

The org record has no structured city column. `organization.address` is one
free-text line, so the choice is between inferring a city and shipping articles
with no locality at all — which removes most of what localization means.

`derive_city` errs hard toward omission:

1. The first comma-separated component is discarded unread. It is the street or
   the venue name, and a business called "Acme Auto" would otherwise be
   published as a city.
2. Of what remains, **exactly one** component must look like a city. Two
   candidates means the format is not one we recognise, and a coin flip between
   them is a fabricated value that happens to be well-formed.

Its provenance is recorded as a derived value, never as a direct read, so a
reviewer can tell an inferred city from one read out of a field.

## Known context gaps

`CONTEXT_GAP_SLOTS` names slots the templates ask for that the payload genuinely
does not carry — CTAs, phone, opening hours. Distinguished from "this org has
not filled it in" because the fix is different: an onboarding field has to exist
before any org can supply one.

⚠️ **Service area is NOT one of them**, contrary to an earlier roadmap note.
`geography` is present and documented as the geographic-strategy blob. What is
true is that it is unvalidated passthrough — present without being reliable — so
it is read defensively and omitted on anything unrecognised.
