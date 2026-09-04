#!/usr/bin/env bash
# The gate — one entry point, five checks, and CI runs this same script.
# The name 'gate' is fixed even where the runner is not, so that CI, the engineer
# and .claude/rules/methodology.md all say the same word.
#
# Steps this repo has no toolchain for are NOTED, not skipped quietly. Replace a
# note with a real command as soon as the toolchain exists.
#
# pytest is not in requirements.txt (the runtime image stays minimal); install it
# into the venv:  .venv/Scripts/python -m pip install pytest httpx
set -euo pipefail
cd "$(dirname "$0")/.."

absent=0
note() { echo "GATE: $1 — no toolchain in this repo; not checked"; absent=1; }

# Prefer the repo venv when one exists, so the gate runs against the pinned
# dependencies rather than whatever is on PATH. On Windows the venv puts the
# interpreter in Scripts/ rather than bin/.
PY="python"
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
fi

note "lint"

note "typecheck"

note "build"

echo "== test =="
"$PY" -m pytest tests/ -q

echo "== okf:check =="
node scripts/okf-check.mjs

if [ "$absent" = "1" ]; then
  echo "gate: the steps noted above are unimplemented in this repo; everything else is green."
fi
