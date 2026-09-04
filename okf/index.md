---
okf_version: "0.1"
conqrse_siblings:
  - name: aeo-backend
    path: ../aeo-backend
    description: The gateway. Assembles this runtime's request from the org runtime context and the template library, calls it, and performs every write it only proposes — the article row, the similarity record, the audit trail.
  - name: aeo-howto-web
    path: ../aeo-howto-web
    description: The public renderer that eventually serves what this runtime generates, on the shop's own host. Never calls this runtime; the two meet only through rows the gateway writes.
  - name: aeo-frontend
    path: ../aeo-frontend
    description: The Meriwether portal where a human reviews and edits a generated draft before it is published. The editorial gate is the only control on generation quality in V1.
  - name: aeo-skill-builder-runtime
    path: ../aeo-skill-builder-runtime
    description: The sibling AgentCore runtime. Same deployment shape, same emit-only posture, same lazily-imported Bedrock client — several hard-won details in this repo were measured there first.
---

# OKF Bundle — aeo-howto-generation-runtime

Open Knowledge Format bundle for this repo. Start at [service.md](/service.md).

## Sections

- [service.md](/service.md) — the repo as a concept; agent entry point
- [endpoints/](/endpoints/invocations.md) — the two HTTP surfaces
- [lib/](/lib/slot-resolution.md) — slot resolution, similarity, regeneration, the prompt, the model seam
- [business/](/business/emit-only.md) — domain concepts this repo owns
- [integrations/](/integrations/bedrock-claude.md) — outward calls
- [playbooks/](/playbooks/run-locally.md) — operational runbooks
- [briefs/](/briefs/index.md) — product ⇄ design, before the code
- [capabilities/](/capabilities/howto-article-generation.md) — what the system does, as scenarios. No status
- [qa/](/qa/howto-article-generation.md) — one checklist per capability; every requirement has a check
- [log.md](/log.md) — change history

Reserved: `index.md` and `log.md` are never concept documents.
