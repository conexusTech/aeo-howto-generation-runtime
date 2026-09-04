# aeo-howto-generation-runtime

HOW-4 article generation. An AgentCore runtime: template + one shop's runtime
context in, a draft article + a similarity measurement + an audit record out.

**Onboard from `okf/service.md`**, not by reading the code first.

## The workspace governs

`../CLAUDE.md` and `../.claude/rules/methodology.md` win over anything here.
Work is a **change** with a roadmap row and an exit criterion; the status
surface is `../okf/roadmap.md` and nothing else.

## The gate

```bash
bash scripts/gate.sh
```

Lint, typecheck and build are **noted as absent**, not silently skipped — this
repo has no toolchain for them yet. CI runs this same script.

⚠️ Never read the gate's exit status through a pipe. `bash scripts/gate.sh |
tail` reports `tail`'s status, so a red gate looks green.

## Three things that are easy to break without noticing

🔴 **The Bedrock SDK import must stay inside `BedrockChatModel.__init__`.**
Moving it to module scope means the test suite needs AWS, which means it stops
being run. Two tests guard this, one of them a control proving the probe works.

🔴 **Never use `hash()` in `similarity.py`.** Python randomises string hashing
per process, so scores would change every run while still looking plausible.
`blake2b` throughout.

🔴 **Never add a connection string to `Settings`.** This runtime is emit-only —
it reads tenant-authored free text and feeds it to a model, and having nowhere
to write is the containment. See `okf/business/emit-only.md`. If a change wants
one, the thing it wants is the gateway's to do.

## Local run, no AWS

```bash
HOWTO_GENERATION_USE_STUB_MODEL=true .venv/Scripts/python -m uvicorn app.howto_generation.server:app --port 8090
```

Canned articles, everything else real. `okf/playbooks/run-locally.md` has the
detail, including the Windows Python-on-PATH trap.
