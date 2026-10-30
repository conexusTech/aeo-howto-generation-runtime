---
type: Service Module
title: Section copy
description: The second task on POST /invocations. Copy for one section of an organization's own site, written for the questions the section is meant to win, with prices, phone, licence, address and hours numbers re-checked in code after the model answers, and a person's edited fields kept word for word.
resource: app/howto_generation/section_copy.py
tags: [meriwether-sites, section-copy, refusal, merge]
timestamp: 2026-10-30
---

# Section copy

`task: "section_copy"` on [POST /invocations](/endpoints/invocations.md). A
body with no `task`, or `task: "article"`, is an article request exactly as it
always was; the server picks the request model from this one field.

```
edits  ->  facts  ->  compose  ->  MODEL  ->  normalize  ->  post-checks  ->  merge  ->  measure  ->  audit
```

The same rules as an article, applied per **field** of a site template's
section rather than per article section: facts only from the record, prices
only where the site allows them and only from the organization's own list, a
person's edits kept, voice and similarity measured and never enforced. Emit-only
as ever: the gateway stores the draft, prices it against the drafting budget and
writes the section only when a person accepts it.

## The prompt asks; the post-checks enforce

The prompt lists what the record holds and, by reusing the
[slot resolver](/lib/slot-resolution.md), what it does not (phone, email,
opening hours). It is still a request. After the model answers, every drafted
field and every list item's fields are scanned, and a field carrying any of
the following is **removed whole** and named in `refused` with the reason:

- a currency amount when the site does not allow prices; when it does, an amount
  whose value is not on the price list (a figure in the business description
  does not count: only the list sources a price);
- a phone number, a licence or registration number, a street or postal number,
  or opening hours that the inputs do not hold;
- the name of a competitor from any of the request's questions (case-insensitive,
  a whole word or phrase after NFKC: `Ace` is caught in `Call Ace`, not in
  `space`). The prompt already says never to name one; this is the enforcement.

Currency is matched after NFKC and with every Unicode dash read as a hyphen:
markers and ISO codes in any case, before or after the amount, joined by nothing,
a space or a hyphen (`usd 40`, `40-dollar`, `99¢`, `₤40`, `1299 kr`, `Rs. 500`,
`$.99`), and a magnitude (`k`, `M`, `thousand`, `million`, `bn`) scales the amount
before it is compared with the list, so `$40k` is not a listed `$40`. A percentage
discount is a price by the module's own `percent_off` rule, whether written `%`
or `percent`; a percentage that is not a discount is not.

"The inputs hold it" means the same detector, run over the inputs, finds the
same canonical value: `412 Kirkwood Avenue` is sourced by `412 Kirkwood Ave`,
`9am` by `9:00 AM`, `(555) 123-4567` by `+1 555 123 4567`. It is never a
substring search, because a bare `27` is inside almost any input. The inputs are
the context the model was shown (another product's prospect lists excluded),
the page, the questions, the price list (only when prices are on) and the
person's edited fields: **exactly what the prompt shows**, collected where the
prompt is composed (`SectionCopyPrompt.source_texts`), so the two cannot drift.
So not products past the twentieth, not questions past the twelfth, not another
product's prospect lists, not a field the person left unedited and not the
generated baseline: a number is not sourced by having been drafted before. A bare
run of seven to nine digits (`ref 5551234`) is not a phone; a formatted number or a
full 10-digit run is. Hours are compared as 24-hour times, so `9:00` and
`9:00 AM` are one time, as are `17:00` and `5:00 PM`.

The patterns, each with a firing case and a sourced control, are documented in
`section_checks.py` and tested one by one. Two choices are deliberately
conservative: bare `pounds` counts as money, and an amount in words cannot be
compared with a list, so both are refused. A refused field is a person's short
fix; an invented price or phone number on the organization's own site is a
false statement under its name.

Also removed, before the checks: a field longer than its template limit (refused,
never truncated), a list with an item that lacks a part the template marks
`required` (refused whole, naming the item and the part), any field name or
list-item key the template does not declare, and any `inputs_used` id the prompt
never offered.

The prompt caps what it carries, like the other caps (sections 12, competitors
10, prices 50): at most 12 questions of 300 characters each. What is cut is not
shown and so is not a source.

## Notes, never refusals: claims and disagreements

The first real-model run (2026-10-31) found what the number checks cannot see:
drafts stating how the business operates ("a same-day job, not something that
sits in a general queue") when nothing the model was shown said so, and, where
the record's industry and the page's own sections described different work, a
field telling readers the business does not do what its own page offers.

The **prompt** carries most of the answer, because a sentence about a process
has no fixed vocabulary: a claim about what the business does, how it works,
how fast, what it guarantees, where, what it is licensed, certified or insured
for, or when it is available may be written only from THE BUSINESS, the
resolved facts, THE PAGE or the price list; the questions are not facts about
the business; otherwise write around it; never say the business does not do
something unless an input says so. Where the record and the page disagree about
what the business does, the draft asserts neither version of that point and the
model names it in the tool's optional `disagreements`.

Two notes follow in code, and neither removes anything:

- `claim:<family> (<field>)` for a promise word a drafted field uses that no
  business input does: `same day`, `next day`, `around the clock`, `guarantee`,
  `warranty`, `licensed`, `certified`, `insured`, `bonded`, `accredited`.
  Matched by family and whole word (`guaranteed` is sourced by `guarantee`;
  `uninsured` is not `insured`). The sources are what the prompt showed **about
  the business** (`SectionCopyPrompt.claim_source_texts`: everything but the
  questions, their competitors and cited hosts) plus the person's edited fields.
  Clock times, `24/7` and `24 hours` are not here: the hours check already
  refuses them. It is a note rather than a refusal because, unlike an invented
  phone number, "guaranteed" may be true and merely missing from the record.
- `disagreement:<line>` per point the model reported, one line, at most 150
  characters, at most three, deduplicated.

Both travel in `audit.voice_tells` after the voice tells, under their prefixes:
it is the one list of notes the gateway stores and shows, and an unknown key in
`field_notes` or `audit` is dropped there. ⚠️ The portal currently introduces
that list as phrasing that can read as machine-written, which fits a claim
note loosely and a disagreement note poorly; giving them their own line is the
gateway's and the portal's to do.

## A person's field is kept by name

A field whose current value differs from the generated baseline is a person's
edit. Fields are matched **by name**, and a list is compared as one whole value,
so editing, re-ordering or removing one item makes the whole list the person's.
A field the baseline never had is treated as the person's, the safe reading, and
so is a field the baseline had that the person deleted: `preserve` keeps it
deleted (listed in `preserved_fields`, absent from `fields`), `discard` redrafts
it and lists it in `discarded_fields`.

- `preserve`: the field comes back exactly as sent, is listed in
  `preserved_fields`, is never asked of the model and never post-checked: the
  checks police what the model wrote, not what a person wrote. When every field
  is preserved the model is not called at all.
- `discard`: the field is redrafted and listed in `discarded_fields`, so the
  overwrite is never silent. A field the post-checks then removed is not listed,
  because nothing replaced it.

`current_fields` without `generated_baseline` is refused as `BASELINE_REQUIRED`
in both modes, for the reason [regeneration](/lib/regeneration.md) gives.

## The local stub

`HOWTO_GENERATION_USE_STUB_MODEL` serves this task too. The stub drafts from the
inputs, deterministically: a field whose name suggests a headline gets the first
question's text (or the page title), every other field an obviously canned
sentence, a list one item per question up to three. It respects every length
limit and writes no digits of its own, so a local run exercises the whole
pipeline without tripping a check the inputs did not already pass.

## The model call

The section tool is generic (`fields` as an array of `{name, text | items,
inputs_used}`, plus an optional `disagreements` array of strings) rather than
built per template, so its definition is byte-stable
and stays in the cached prefix. The streaming, the unforced first call and the
one forced retry are the same code as the article's, shared through one helper
in [the model seam](/lib/model-seam.md).
