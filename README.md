# aeo-howto-generation-runtime

Generates a how-to article for one shop from a shared template and that shop's
onboarding record — and measures how close it landed to every other shop's
article from the same template.

Deployed as an **AWS Bedrock AgentCore Runtime** (ARM64, Python 3.12). Called by
`aeo-backend`. Writes nothing.

```
POST /invocations   template + org context  ->  draft article + similarity + audit
GET  /ping          liveness
```

## Why this exists

Auto shops compete on price because nothing distinguishes them in the answers
customers actually see. How-to content published on the shop's own domain
signals expertise to answer engines — but only if each shop's article is
genuinely different from every other shop's. Fifty near-identical articles get
deduplicated down to one indexed page, and the other forty-nine shops pay for
something nobody is ever shown.

So the articles are **generated per shop**, not templated with the names
swapped, and the runtime records a lexical similarity score so a reviewer can
see when that is failing.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest httpx
bash scripts/gate.sh
```

The whole suite runs with **no AWS credentials, no network and no Bedrock SDK**.
That is a tested property, not a happy accident.

To serve it locally with canned articles:

```bash
HOWTO_GENERATION_USE_STUB_MODEL=true .venv/Scripts/python -m uvicorn app.howto_generation.server:app --port 8090
```

## Where things are

| | |
|---|---|
| `app/howto_generation/slots.py` | Which shop facts may be used, and which are refused |
| `app/howto_generation/similarity.py` | MinHash Jaccard over 5-word shingles |
| `app/howto_generation/regenerate.py` | Preserving human edits, and refusing when it cannot |
| `app/howto_generation/prompt.py` | The differentiation instruction |
| `app/howto_generation/runtime.py` | The pipeline |
| `okf/` | The knowledge bundle — **start at `okf/service.md`** |

## Docs

- What it does, as scenarios: `okf/capabilities/howto-article-generation.md`
- How each one is proven: `okf/qa/howto-article-generation.md`
- Running it here: `okf/playbooks/run-locally.md`
