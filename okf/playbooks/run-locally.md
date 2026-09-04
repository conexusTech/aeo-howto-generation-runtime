---
type: Playbook
title: Run the generation runtime locally
description: Start the runtime on this machine with no AWS, no credentials and no network, and drive one generation end to end against it.
tags: [local, testing]
timestamp: 2026-09-03
---

# Run it locally

The whole pipeline runs with no AWS. That is a deliberate property — see
[the model seam](/lib/model-seam.md) — and this is how you use it.

## Once

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest httpx
```

⚠️ On this Windows machine `python` on PATH is the Microsoft Store alias, which
is not a Python. The real 3.12 interpreter is at
`~/AppData/Local/Programs/Python/Python312/python.exe`; use it explicitly to
create the venv.

## The gate

```bash
bash scripts/gate.sh
```

Runs the whole suite and the OKF checker. Lint, typecheck and build are noted as
absent rather than skipped quietly — this repo has no toolchain for them yet,
and a note is honest where a silent pass would not be.

## Serve it

```bash
HOWTO_GENERATION_USE_STUB_MODEL=true .venv/Scripts/python -m uvicorn app.howto_generation.server:app --port 8090
```

🔴 **The stub flag is what makes this possible without credentials, and it makes
the articles canned.** The server logs a warning naming the flag on every model
construction, because canned prose is plausible enough to be mistaken for real
output — and an article that reads a little oddly is a far quieter failure than
one that never arrives. It defaults to off and a check asserts that default.

Everything around the model is real: slot resolution and its refusals, the
regeneration merge, the similarity measurement, the audit record. That is the
part worth exercising, and none of it needs a model to be real.

## Drive one generation

```bash
curl -s localhost:8090/ping
```

Then post a template and a context to `POST /invocations`. The shape is in
[the endpoint concept](/endpoints/invocations.md). The three things worth
looking at in the response:

- `slots.refused` — a pricing slot is refused with a reason, always
- `slots.omitted` — a CTA slot is omitted, because the gateway's context has no
  CTA field for any org
- `audit.inputs_used` — exactly which context paths were read

## Against a real model

Set AWS credentials for an account with Bedrock access in `us-east-1`, leave the
stub flag unset, and the same request goes to Claude. **That is an AWS
operation and is out of scope for local work** — the runtime is built and
tested; deploying and invoking it against Bedrock is a separate, later step.
