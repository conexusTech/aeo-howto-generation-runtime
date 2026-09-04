---
type: Service Module
title: Similarity measurement
description: HOW-4.4. MinHash Jaccard over 5-word shingles against the nearest published sibling. Records a score, a neighbour, and the two figures that make the corpus-growth question answerable.
resource: app/howto_generation/similarity.py
tags: [how-4.4, minhash, measurement]
timestamp: 2026-09-03
---

# Similarity measurement

The metric is fixed by specification and is not a free choice: **Jaccard
similarity over 5-word shingles via MinHash**, on body text with chrome
stripped, against the nearest neighbour across all tenants.

## Lexical, deliberately — not semantic

Two genuinely distinct articles about the same repair are *supposed* to be
semantically close; they are about the same repair. An embedding metric would
score good, differentiated content as duplicate, and would be at its most
confident exactly when it was most wrong. Word-level overlap is the signal
because word-level overlap is what a search index collapses on.

## What it does not do

It blocks nothing and alerts nothing. There is no threshold anywhere in the
module. The editorial gate is the control on publication in V1; this produces
the evidence a reviewer weighs, and the history a later threshold would be
calibrated against.

## Chrome

Two kinds, handled differently:

- **Renderer chrome** — nav, header, footer, breadcrumb, JSON-LD — is excluded
  *by construction*. It lives in [aeo-howto-web](aeo-howto-web:/service.md) and
  is never part of an article row, so it cannot reach the metric.
- **Template boilerplate inside the body** is removed via `chrome_blocks`, which
  the caller declares. Identical across every shop using a template, it would
  otherwise be counted as shop-to-shop similarity when it is really
  template-to-itself.

## Two implementation details that would fail silently

🔴 **The hash must be stable across processes.** Python randomises string
hashing unless the hash seed is pinned, so a MinHash built on the builtin would
produce a different signature every run — and the failure is invisible, because
the scores still come back as plausible numbers between zero and one. Articles
compared today and re-compared tomorrow would disagree, and the stored history
would be noise wearing four decimal places. `blake2b` is used throughout.

⚠️ **The stored precision exceeds the measurement precision.** The gateway
column is `numeric(7,4)`; the estimator at 256 permutations is good to roughly
the second decimal place. The precision is kept because calibration wants the
raw number — but a threshold set on the fourth decimal would be measuring noise.

## `compared_count` is not optional reading

Zero means the corpus was empty — the first article from a template — and a
score of zero then means **unmeasured**, not "perfectly distinct". Reporting it
as distinctness would tell a reviewer the opposite of the truth at the moment
they have least other information. Every consumer branches on the count first;
the portal's similarity band does exactly this.

## Cost

No corpus ceiling is pre-set, because a guessed number would be precisely the
unfalsifiable criterion the specification flags elsewhere. Instead every
measurement records `compared_count` and `duration_ms`, so moving the work off
the publish path becomes a decision with evidence behind it rather than a guess
about the fiftieth shop.

## Why no third-party MinHash

The metric above is specified tightly enough that "whatever the library does" is
not an acceptable answer to "what does this score mean", and the acceptance
criteria ride on the exact behaviour. Forty lines of hashing we can point at
beats a dependency we would have to characterise anyway.
