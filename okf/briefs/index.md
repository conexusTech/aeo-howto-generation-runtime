# Briefs

A brief is what product and design agreed **before engineering started** — the
narrative, the screens, the states, the scenarios.

**There are none here, and that is correct rather than a gap.** This runtime has
no screens. It is called by the gateway and answers with JSON; nobody looks at
it. The human-facing half of HOW-4 — how a reviewer sees a generated draft, what
a similarity score looks like to them, whether a near-duplicate is shown at
all — is a brief in the portal that owns those screens:
`aeo-frontend:/briefs/howto-editorial-review.md`.

A brief will appear here only if this runtime ever grows a surface a person
looks at, which nothing currently plans.

The scenarios for what this runtime *does* live in
[capabilities/](/capabilities/howto-article-generation.md), where they belong
once the behaviour exists and has evidence behind it.
