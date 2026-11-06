---
type: Service Module
title: Section copy
description: The second task on POST /invocations. Copy for one section of an organization's own site, written for the questions the section is meant to win, with prices, phone, licence, address and hours numbers re-checked in code after the model answers, and a person's edited fields kept word for word.
resource: app/howto_generation/section_copy.py
tags: [meriwether-sites, section-copy, refusal, merge]
timestamp: 2026-11-04
---

# Section copy

`task: "section_copy"` on [POST /invocations](/endpoints/invocations.md). A
body with no `task`, or `task: "article"`, is an article request exactly as it
always was; the server picks the request model from this one field.

The subject is one section of a page or, since 2026-10-31, one **entry** of a
collection (a blog post, a case study): `subject: "entry"`, with the
collection's entry schema as `template` and the entry's own page as `page`.
`subject` changes wording only, and is `section` when absent. The rules in the
prompt's cached half are written for both, so that half is byte-identical
whichever is drafted; the task half says THE SECTION or THE ENTRY ("one entry of
a collection on the site; the copy is the whole entry, not a section of a
page"), titles the page `Entry title` and names the questions this entry is
meant to win. The tool and the user turn name neither.

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

A record value that is a catch-all (`Other`, `N/A`, `General`, `misc`,
`unknown` and the like, compared case-insensitively, in any string field of the
organization record) says nothing about what the business does, so it is never
in disagreement with a page. The prompt says so (found when the second real-model
run reported an industry of "Other" as disagreeing with a plumbing page), and a
disagreement line that **names** one the record holds is dropped: quoted in any
case, or written exactly as the record spells it in the middle of a sentence
when that spelling has a capital. So `as Other` is dropped, while `the page's
other sections …` and `… roofing. Other sections …` are prose and kept, and a
line naming `Other` when the record's industry is specific is kept, because the
filter keys on what the record holds. A blank value cannot be named, so for it
the prompt is the whole rule.

Both travel in `audit.voice_tells` after the voice tells, under their prefixes:
it is the one list of notes the gateway stores and shows, and an unknown key in
`field_notes` or `audit` is dropped there. ⚠️ The portal currently introduces
that list as phrasing that can read as machine-written, which fits a claim
note loosely and a disagreement note poorly; giving them their own line is the
gateway's and the portal's to do.

## Links and rejection reasons: what the model is now told

Two inputs added after the second real-model run (2026-10-31), both optional,
so a gateway that omits them gets the earlier prompt.

- **`template.links`**: where each label field's link goes (`field`, `href`,
  `target` the site page's title or null, `item` the 0-based item index for a
  label inside a list item). The prompt lists them inside the data fence under
  WHERE THE LINKS GO (`[link:buttonLabel] buttonLabel is the label of a link
  that opens the page "Contact" (/contact)`; an item link names its list and its
  1-based item; a null target reads "not a page of this site we can name"), and
  the label's field line, outside the fence, points at that id. The rule: a
  label describes what happens when it is clicked and never promises a
  destination the link does not have. Only links on fields being drafted are
  shown; a link for a field the template lacks, or a person's preserved field,
  has no label to write. Page titles and hrefs are sources like the rest of the
  page. **There is no deterministic note for a label**: whether "Get in touch"
  describes /contact is a question of meaning, and a word-overlap heuristic
  would flag that honest label while passing a dishonest one that happens to
  share a word with the page title. The prompt is the whole measure.

- **`template.shows`**: what the section lists, when it lists something —
  `source` "collection" with the collection's `name`, what one `entry_type`
  is and up to a dozen of its newest `titles` (a feed, case study cards, a
  team grid), or "guides" for the organization's how-to guides. The prompt
  shows it inside the data fence under WHAT THIS SECTION LISTS (`[shows] The
  site's collection "Services", whose entries are each a Service`, the titles
  beneath), and outside the fence tells the model to write the heading and any
  text about the list for exactly that. Without it a feed of services was
  headed "Recent Roofing Work". Absent from an older gateway: no block. The
  name and titles are sources like the rest of the page.
- **`places`** (`drafting-names-every-store`, 2026-11-06): where the business
  is — every live store (`name`, `city`, `region`, `main`), the main one first,
  and the one `store` this section or entry is about (a map, contact block or
  reviews section showing one store, or a store's own page), or null. Before it
  the only place a draft knew was the organization profile's location, resolved
  as the facts `city` and `address`; Bramblewood Dental, with offices in
  Raleigh, Cary and Durham and a profile reading "Raleigh, NC", was drafted as
  "Dental Care for Raleigh" everywhere, a map of the Durham office included.
  With any store, `city` and `address` are dropped from the facts (neither
  resolved nor listed as lacking), and the prompt shows, inside the fence under
  WHERE THE BUSINESS IS, `[places] The business has stores in: Raleigh, NC (the
  main store); Cary, NC; Durham, NC` (each town once, at most 30, the rest
  counted) and `[places.store] This section is about one store: <name>, in
  <town>`. Outside the fence: with a store, name that store's town and no other
  store's; with several towns and no store, name every one or a regional
  phrase true of all of them, never one alone and never the main store's town
  alone. The stable half carries the same rule under WHERE THE BUSINESS IS and
  lists it among the inputs a claim may come from. Names and towns are sources
  like the rest of the page. Absent or empty: the earlier prompt, the profile's
  location as facts. ⚠️ The geography's `service_area` fact is unchanged: a
  home market narrower than the stores still reaches the model, and only the
  instruction stands against it.
- **`rejected`**: reasons a person gave for rejecting earlier drafts of this
  same section or entry, newest first. At most three are shown, each one line of
  at most 500 characters, blanks skipped, inside the data fence under EARLIER
  DRAFTS WERE REJECTED BECAUSE, as `[rejected:<n>]`. The rule: do not repeat
  what a reason objects to, keep a fact a reason insists on, and a reason is the
  person's words about the copy, not an instruction about anything else. They
  are the person's words as much as an edited field is, so they **are** sources
  for a phone, address, hours or licence number and for a claim; they never make
  a price listed, because only the price list does.

## Copy sources and lists inside list items

Since 2026-11-04 (`copy-source-on-every-field`, Meriwether Sites C20) every field
and item field carries a **copy source**:

- `generated` (the default, and what a field with no `source` means, so an older
  gateway's request is drafted exactly as before): written from the questions,
  the business, the page and the price list, as above.
- `brand`: written **only** from the request's `brand`, the organization's brand
  record. A `brand` list field makes everything inside it brand.
- `manual` is never sent: a manual field is a person's alone. A request carrying
  one is refused at validation rather than drafted.

The brand record is shown fenced in the prompt's stable half, beside the
business, one `[brand:<key>]` line per fact, in the record's order: at most 30
facts, each value at most 1000 characters (bounded before a list is joined); a
list's plain values are joined with "; ", and an object, a nested list, a
boolean or null is skipped. Two keys that shorten to the same name get distinct
ids (`brand:tagline`, `brand:tagline-2`). The gateway sends `brand` with its keys
in a stable, sorted order, so the 30-fact cut and the suffixes are stable too.
`brand: null` is no record.

⚠️ **That a brand field's WORDING comes from the record is a prompt rule, not a
check.** The field's line says "from the brand record", and the rules tell the
model to use the record's words and to leave the field out when the record does
not hold what it asks for. Code cannot tell a faithful shortening from an
invention, and does not try. What code does enforce:

- **No brand record**: a brand field is never asked of the model and comes back
  in `refused` as `BRAND_EMPTY`, as does a list with a **required** brand part
  at any depth, which could never be complete. An optional brand part of a list
  item is not listed in the prompt, and a link on it is not shown. When every
  field is refused this way, the model is not called.
- **Left out**: refused as `BRAND_LEFT_OUT` (`left out: the brand record does not
  hold it`).
- **Written but citing no `brand:` id** in `inputs_used`: the field, list or
  not, is refused as `BRAND_UNCITED`; a brand part of a generated list item is
  left out of every item instead (and an item that then lacks a required part
  refuses the list, as any missing part does).
- **Numbers in a brand value** (phone, licence, address, hours) are sourced
  only by the brand record's **values**, not by the page, the questions or the
  business record. This is the one place the record is checked against what
  was written. Prices follow the price list exactly as for any field.

The record's values are also sources for a generated field's numbers and for
claims; its keys never are, because a key is the record's label for a fact,
not a fact. The audit's `inputs_used` lists only the `brand:` ids a kept field
cited.

A list item may hold **one** more level of list (FAQ groups and their
questions, a plan's features, a comparison's cells): an item field of `kind:
list` with its own `item_fields`. A list inside that is refused at validation
with a message naming the path. The nested list gets every check a top-level
field gets: its own character limits and `required` parts (a reason names the
path, `item 1's questions item 2's answer is longer than …`), undeclared keys
dropped, the price, number and competitor checks, claim notes, voice tells and
similarity. A person's edit anywhere inside a list makes the whole top-level
field theirs, because the field is compared as one value, so `preserve` keeps a
nested edit word for word and `discard` names the field it replaced.

**List counts** (`faq-groups-draft-meets-its-minimum`, 2026-11-06). A list
field, or a list inside an item, carries the template's `min_items` and
`max_items`. Before them the prompt said only "a list of items" and nothing
checked a count, so FAQ groups (at least three questions a group) were drafted
with two a group and every draft failed publishing. The field line now says
`a list of at least 3 and at most 15 items`, or the one bound the template
sets; the stable half's LISTS INSIDE LIST ITEMS rule says to write at least
that many in every item that holds one. In code, after the items are
allowlisted: a list longer than its most is cut to its first `max_items`, at
either level; one shorter than its least refuses the whole top-level field
with a reason naming the place (`item 2's items has 2 items; the template
needs at least 3`, or `has 2 items; …` at the top). A draft therefore never
offers a list publishing would refuse, and a short one comes back refused
rather than topped up — inventing a question is not ours to do. The local stub
pads each list to its least and cuts it to its most. Absent counts: as before.

A link on a label inside a nested list is not placed in the prompt: links are
matched to top-level fields and first-level item fields only.

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
sentence, a list one item per question up to three, a list inside an item
one item per question up to two, and a brand field the brand fact whose key
matches its name (case and punctuation ignored), citing it, or nothing when no
fact matches, so it is left out. It respects every length
limit and writes no digits of its own, so a local run exercises the whole
pipeline without tripping a check the inputs did not already pass.

## The model call

The section tool is generic (`fields` as an array of `{name, text | items,
inputs_used}`, an item's value a string or an array of objects for a list
inside it, plus an optional `disagreements` array of strings) rather than
built per template or per subject, so its definition is byte-stable
and stays in the cached prefix. The streaming, the unforced first call and the
one forced retry are the same code as the article's, shared through one helper
in [the model seam](/lib/model-seam.md).
