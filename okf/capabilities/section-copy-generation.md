---
type: Capability
title: Copy for one site section is written from the record's facts, and refused field by field when it states one the record lacks
description: What the runtime does when the gateway asks for a section's copy — which fields it writes, which numbers and names it will not let through, what counts as the record, how a person's edited fields are kept, and what it measures but never enforces.
---

# Section copy generation

Given one section of a customer's site template, the page it sits on, the Share of Voice questions it is
meant to win and one organization's record, the runtime drafts that section's text fields, re-checks every
drafted field in code after the model answers, and returns the draft with an audit. The gateway stores it;
the portal shows it; a person decides. The gateway's half (spend, assignment, review) is
[section drafting](aeo-backend:/capabilities/sites-section-drafting.md). The pipeline is
[section copy](/lib/section-copy.md).

**Seeded 2026-10-30** by `section-copy-generation` (Meriwether Sites C4, T-1) with its review fixes. Every
scenario below is executed by the suite in `tests/`, against the real modules, with a fake model injected.
The suite runs every scenario against a fake model: the post-checks are shown on constructed answers, and
quality of the copy is not a scenario because it cannot fail. **The first real-model run (2026-10-31)** found
copy that was well written, price-free and kept a person's edits, but invented how the business operates and,
where the record and the page disagreed, told readers the business does not do what its own page offers. The
two scenarios on claims and disagreements are the answer to that run. **A second real-model run the same day**
found a button label rewritten to promise a page the button does not open, a record industry of "Other"
reported as disagreeing with the page, and reasons a person gave for rejecting earlier drafts never reaching
the model; collection entries are drafted from that day too. The four scenarios after the disagreement one
answer it.

Related: [the pipeline](/lib/section-copy.md) · [slot resolution](/lib/slot-resolution.md) ·
[regeneration](/lib/regeneration.md) · [emit-only](/business/emit-only.md) ·
[the article capability](/capabilities/howto-article-generation.md)

## Scenarios

#### Scenario: A draft carries only the fields the template declares, each within its limits

- GIVEN a template with a headline, a body and a list of questions and answers
- WHEN the model answers with a field the template does not declare, a list item with an undeclared key, a field over its length limit, a list item missing a part the template requires, and a field it did not draft
- THEN the undeclared field and key are dropped, the over-long field is refused and never cut short, the list with the incomplete item is refused whole naming the item and the part, and the undrafted field is reported
- AND a list item missing only an optional part is kept, and a complete draft comes back whole

**Checked by:** scg-declared-fields

#### Scenario: No price appears unless the site allows it, and then only one on the organization's list

- GIVEN a site that does not allow prices, then one that does with a price list
- WHEN the model writes a price into one field, in a list item, in any currency format, or as a percentage discount
- THEN with prices off the field is removed and named in `refused`, and a price on the list is refused too
- AND with prices on, a listed price passes and an unlisted one is refused, as is a scaled amount such as `$40k` against a listed `$40`
- AND the other fields of the draft are kept, a price in one list item refuses the whole list, and a figure in the business description does not make a price listed

**Checked by:** scg-prices

#### Scenario: A phone number, licence, street number or opening hours the record does not hold removes the field

- GIVEN a record with a phone number, an address and no licence number or opening hours
- WHEN the model writes the record's own phone and address, then an invented phone, street number, licence or opening hours
- THEN the record's own pass, in any separator or clock style that is the same value
- AND an invented one removes its field, naming what it was, and a number found only in a part of the context the model was not shown is not the record's
- AND dates, years and plain counts are not flagged, and a bare run of seven digits does not source a formatted phone

**Checked by:** scg-unsourced-numbers

#### Scenario: A competitor named in any of the questions is never named in the draft

- GIVEN questions that name a competitor
- WHEN the model names it in a field, in a list item, in fullwidth letters, or in a different case
- THEN the field or list is refused naming the competitor
- AND a word that only contains the name is allowed, and with no competitors there is no check

**Checked by:** scg-competitors

#### Scenario: What counts as the record is what the model was shown

- GIVEN a number the model might write
- WHEN it appears only in an unedited current field, only in the generated baseline, only in a twenty-first product, only in the price list while prices are off, or in a field a person edited
- THEN only the field a person edited sources it, whatever the edit policy
- AND the sources are collected from the composed prompt itself, so what the prompt cuts is not a source: products past the twentieth, questions past the twelfth, questions longer than 300 characters

**Checked by:** scg-sources-are-the-prompt

#### Scenario: A claim about how the business works that no business input makes is noted for the person, and the field is kept

- GIVEN a record and a page that say nothing about guarantees or insurance, and a question that asks for a guarantee
- WHEN the model writes "guaranteed" and "insured" into a list item
- THEN the field is kept, nothing is refused, and the draft's notes carry `claim:guarantee (faqs)` and `claim:insured (faqs)`
- AND the same word in the record, in the page's other sections or in a field a person edited is not noted, a question naming it does not source it, a person's preserved words and a refused field add no note, and a word that only contains a term, such as uninsured, is not one
- AND the prompt tells the model to state how the business works only where an input says so, shows a sentence it may not write and one to write instead, and forbids saying the business does not do something unless an input says so

**Checked by:** scg-claims-noted

#### Scenario: Where the record and the page disagree about what the business does, the draft notes it and is not stopped

- GIVEN a model that reports the record and the page disagree about what the business does
- WHEN the draft is returned
- THEN the draft's notes carry `disagreement:` and the model's line, every field is kept and nothing is refused
- AND the line is made one line of at most 150 characters, at most three are kept, repeats are dropped, anything that is not a string is dropped, and with no disagreement there is no note
- AND the prompt tells the model to assert neither version of the disputed point and to report each one

**Checked by:** scg-disagreements-noted

#### Scenario: A label is written knowing where its link goes

- GIVEN a section whose button label opens the site's contact page, and a card in a list whose title links off the site
- WHEN its copy is drafted
- THEN the prompt shows, inside the data fence, that the label opens the page "Contact" (/contact) and that item 1's title opens an address that is not a page of the site, and the label's own field line points at it
- AND the prompt tells the model a label must describe where the link goes and never promise a destination the link does not have
- AND a link naming a field the template lacks, or a field a person's edit preserves, is not shown, a page title cannot close the fence or start an instruction, and a request with no links is drafted as before

**Checked by:** scg-link-destinations

#### Scenario: A catch-all value in the record is never a disagreement with the page

- GIVEN a record whose industry is "Other", "N/A" or "General", and a page about one line of work
- WHEN the model reports that the record's industry disagrees with the page
- THEN no disagreement note is returned, and the draft is otherwise unchanged
- AND a specific record value that conflicts with the page is still noted, as is a line about something else on a record holding "Other", and the word other in ordinary prose drops nothing
- AND the prompt tells the model that an empty, generic or catch-all record value says nothing about what the business does, and that only two specific conflicting claims are a disagreement

**Checked by:** scg-catch-all-not-disagreement

#### Scenario: Why a person rejected earlier drafts reaches the model as their words

- GIVEN reasons a person gave for rejecting earlier drafts of this same section, newest first
- WHEN the copy is drafted again
- THEN the prompt shows at most three reasons, in order, inside the data fence, and tells the model not to repeat what a reason objects to and to keep a fact a reason insists on
- AND a phone number or a claim a reason states may be written, a price a reason names is still refused unless the price list holds it, a reason cannot close the fence or start an instruction, and with no reasons nothing is shown

**Checked by:** scg-rejection-reasons

#### Scenario: A collection entry is drafted under the same rules and reads as an entry

- GIVEN a request for one entry of a blog collection, with the entry's title as its page
- WHEN its copy is drafted
- THEN the prompt calls it an entry of a collection whose copy is the whole entry, names the entry's title and the questions this entry is meant to win, and never calls it a section of a page
- AND every rule is the same as for a section, the cached half of the prompt is identical for both, a request that does not say which is a section, and the stub drafts an entry cleanly

**Checked by:** scg-entries

#### Scenario: A person's edited field is kept by name, word for word

- GIVEN a section whose current fields differ from the baseline the model last generated
- WHEN another draft is requested under the preserve policy
- THEN the edited field comes back exactly as sent, a list as a whole, matched by name and never by position, and is listed as preserved and never asked of the model
- AND a field the baseline never had, and a field a person deleted, are a person's, a preserved field is never post-checked, and when every field is preserved the model is not called
- AND a current section without its baseline is refused as needing one, in either policy

**Checked by:** scg-edits-preserved

#### Scenario: Under the discard policy an edited field is redrafted, and says so

- GIVEN an edited field and the discard policy
- WHEN the draft is requested
- THEN the field is redrafted and listed as discarded, and a deleted field likewise
- AND nothing is preserved

**Checked by:** scg-edits-discarded

#### Scenario: Voice and similarity are measured and never enforced

- GIVEN a draft with a stock phrase and a dash, and a corpus of other organizations' drafts for the same template
- WHEN it is returned
- THEN the voice tells are in the audit and the field is kept, a person's preserved words add no tells, and an empty corpus reads as unmeasured
- AND a near copy of another organization's draft is measured with its nearest draft and organization, and is still returned

**Checked by:** scg-measured-not-enforced

#### Scenario: The audit records what the draft was written from

- GIVEN a drafted section
- WHEN it is returned
- THEN the audit names the template, the questions, the context version, the organization, the model and the inputs used, and each field's note carries only inputs the prompt offered
- AND token usage is passed through, and a part of the context the model was never shown is not listed as an input

**Checked by:** scg-audit

#### Scenario: Business text cannot give the model an instruction

- GIVEN a page title, a question or a field name holding a line that starts like an instruction, or the closing marker of the fence
- WHEN the prompt is composed
- THEN the text stays inside its fence, which closes once, and no line of it starts a new instruction
- AND the prompt lists the facts the record does not hold, forbids prices where the site does not allow them, and lists the price list where it does

**Checked by:** scg-prompt-hygiene

#### Scenario: A request without a task is an article, and a bad request is a typed refusal

- GIVEN requests with no task, with `article`, with an unknown task, and with a malformed section request
- WHEN each is posted to the runtime
- THEN the first two are answered as an article exactly as before and carry no `task`
- AND the others are answered with a typed refusal in a 200 body, naming the unknown task or the invalid field
- AND a model that cannot draft sections fails typed, and the article still goes through its own tool

**Checked by:** scg-task-routing

#### Scenario: The local stub drafts deterministically and invents no number

- GIVEN the stub model flag
- WHEN a section is drafted twice
- THEN both drafts are identical, drawn from the questions or the page title, within every length limit, with no digits of the stub's own
- AND nothing it writes is refused

**Checked by:** scg-stub

#### Scenario: A brand field is written only from the brand record, and a list inside a list item is drafted under every check

- GIVEN a section request whose fields carry a copy source, a brand record, and a list item holding a list (an FAQ group's questions)
- WHEN the section is drafted
- THEN a brand field is written only from the brand record, citing it, and is left out with a reason when the record lacks the fact or there is no record
- AND a manual field is refused before anything is drafted
- AND every field inside the nested list is held to its limit, its required parts and the price, number and competitor checks, and a person's edit inside it is kept
- AND a list nested any deeper is refused with the path named

**Checked by:** scg-copy-sources
