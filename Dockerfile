# AgentCore Runtime requires linux/arm64. An amd64 image fails at DEPLOY, not at
# build, so the platform is pinned here rather than left to the builder's host.
FROM --platform=linux/arm64 python:3.12-slim-bookworm

# No browser, no Chromium, no fonts. This runtime never opens a page: it takes a
# template and an org context and returns text. The sibling ground-truth runtime
# prompts the question because it drives a browser — that one attaches to a
# REMOTE browser and still installs none locally.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Contract: 0.0.0.0:8080, POST /invocations, GET /ping.
EXPOSE 8080

# Single worker on purpose. The blocking Bedrock call is already dispatched off
# the event loop via `run_in_threadpool` in server.py, and generation is a
# long-running call billed per invocation — adding workers here multiplies
# concurrent spend against a cap this image cannot see.
CMD ["uvicorn", "app.howto_generation.server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
