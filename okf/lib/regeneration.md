---
type: Service Module
title: Regeneration
description: HOW-4.6. Regenerates from the template and current org data, preserving or discarding human edits by explicit choice — and refusing to run when it cannot tell which is which.
resource: app/howto_generation/regenerate.py
tags: [how-4.6, merge, refusal]
timestamp: 2026-09-03
---

# Regeneration

Three acceptance criteria, and the third governs the other two:

- the operation states which mode it ran in
- preserved edits survive verbatim
- **human copy is never silently overwritten**

"Silently" is the load-bearing word. Overwriting a human edit is a legitimate
outcome — it is what `discard` means, and somebody asked for it. What is not
legitimate is overwriting one without being able to say that it happened.

## The refusal

🔴 **`generated_baseline` is required, in both modes.** Without it a human edit
and a generated paragraph are the same bytes:

- in `discard`, that means overwriting human copy with no way to report which
  copy was human — the exact thing the third criterion forbids;
- in `preserve`, it means claiming edits survived verbatim while having no idea
  which ones they were, which is worse than failing because it reports success.

This is the only place this runtime refuses to proceed.

⚠️ **It is a real cross-repo dependency and it is not yet satisfied.**
`howto_articles.published_snapshot` is NULL on published rows today (measured
2026-09-03), so something has to retain what generation produced before
regeneration can run at all. Owner: the gateway.

## Identity is the heading, not the position

Generation varies section ordering — that is HOW-4.3 working as intended — so a
positional match after a re-order compares a step against an unrelated step and
reports both as edited. A report where everything is flagged is one nobody
reads. Headings are matched first, positions second.

A section in the current article with no counterpart in the baseline is treated
as **human-added**, which is the safe reading: the alternative is assuming
generation produced it and letting a later `discard` delete something a person
wrote by hand.

## An orphaned edit is appended, never dropped

If a preserved section's heading no longer appears in the regenerated article,
it is appended rather than discarded. Losing human copy is the one unrecoverable
outcome here — an article with a section in an odd place is a reviewer's
five-second fix; an article missing a paragraph somebody wrote is not
recoverable from anything this runtime returns.
