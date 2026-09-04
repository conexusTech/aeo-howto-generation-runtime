"""AgentCore Runtime HTTP entry.

`POST /invocations` and `GET /ping` — the two surfaces AgentCore requires. This
runtime is **not** AGUI: generation is one request in, one article out, so the
plain HTTP protocol is right and an event stream would be ceremony around a
single result. The sibling `aeo-skill-builder-runtime` streams because it is a
conversation; this one does not because it is not.

The model is injected as a FastAPI dependency so tests override it with a fake
and never construct a Bedrock client.
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import get_settings
from app.howto_generation import model as model_module
from app.howto_generation import runtime
from app.howto_generation.contracts import ErrorResponse, GenerationRequest
from app.howto_generation.model import ChatModel

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"

#: Cap on validation detail echoed back for a malformed body.
_MAX_ERROR_DETAIL = 600

_model_singleton: ChatModel | None = None


def get_chat_model() -> ChatModel:
    """Build the production Bedrock model once. Overridden in tests via
    `app.dependency_overrides`, so Bedrock is never constructed there."""
    global _model_singleton
    if _model_singleton is None:
        settings = get_settings()
        if settings.HOWTO_GENERATION_USE_STUB_MODEL:
            # Loud, and on every construction rather than once at import. Canned
            # prose is plausible enough to be mistaken for real output, so the
            # failure this guards against is somebody reviewing a stub article
            # and approving it.
            logger.warning(
                "HOWTO_GENERATION_USE_STUB_MODEL is ON — articles are CANNED, "
                "no model is being called. This must never be set outside a "
                "local run."
            )
            return model_module.FakeChatModel()
        _model_singleton = model_module.get_chat_model(
            model_id=settings.HOWTO_GENERATION_MODEL_ID,
            aws_region=settings.HOWTO_GENERATION_AWS_REGION,
            max_tokens=settings.HOWTO_GENERATION_MAX_TOKENS,
        )
    return _model_singleton


#: 🔴 Without this, none of our `logger.info` calls reach CloudWatch.
#:
#: uvicorn configures its own loggers, so its INFO lines appear and the log
#: looks healthy while our root logger sits at the default WARNING and drops
#: every `logger.info` we emit. `logger.warning` and `logger.exception` are
#: unaffected, which is exactly why it goes unnoticed — tracebacks arrive, so
#: the logging "obviously works". Measured on the sibling runtime, where it
#: silently voided a diagnostic line that was believed to be running.
#:
#: `force=True` because uvicorn may already have installed handlers by import
#: time and `basicConfig` is a no-op when handlers exist — without it this fix
#: would itself be a no-op some of the time, depending on import order.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="How-to Article Generation",
    description="HOW-4 article generation — Bedrock AgentCore Runtime.",
    version="0.1.0",
)


@app.get("/ping")
def ping() -> dict[str, str]:
    """AgentCore health probe.

    Deliberately does NOT touch `get_chat_model()`. Constructing the Bedrock
    client here would turn a misconfigured model id, a missing region or an IAM
    denial into a failing health check — so the runtime would be reported
    unhealthy and recycled instead of accepting a request and returning one
    clear typed error. Liveness and model reachability are separate questions;
    this answers only the first.
    """
    return {"status": "healthy"}


@app.post("/invocations")
async def invocations(
    request: Request,
    model: ChatModel = Depends(get_chat_model),
) -> JSONResponse:
    """Generate or regenerate one article.

    🔴 **Every outcome is HTTP 200 with a typed body.** AgentCore reports a
    non-2xx as an invocation failure and the body is frequently discarded on the
    way back, so a 400 carrying a precise explanation reaches the gateway as
    "it broke". The gateway branches on `error_code` instead, and the
    distinction between a refusal it should surface to an operator and a fault
    it should retry survives the trip.
    """
    session_id = request.headers.get(SESSION_HEADER)

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("body must be a JSON object")
        parsed = GenerationRequest.model_validate(payload)
    except ValidationError as exc:
        # Echoing detail is safe here: it describes the CALLER's own body, not
        # our infrastructure. Truncated so a pathological error tree cannot
        # bloat a response that is billed per invocation.
        return JSONResponse(
            ErrorResponse(
                error_code="INVALID_REQUEST",
                message=f"request body failed validation: {exc}"[:_MAX_ERROR_DETAIL],
            ).model_dump()
        )
    except Exception as exc:  # noqa: BLE001 — a bad body is a typed answer, not a 500
        return JSONResponse(
            ErrorResponse(
                error_code="INVALID_REQUEST",
                message=f"invalid request body: {exc}"[:_MAX_ERROR_DETAIL],
            ).model_dump()
        )

    settings = get_settings()

    try:
        # `handle` is synchronous and, with a real model, makes a blocking HTTPS
        # call that can run to tens of seconds on a long article. Running it on
        # the event loop stalls every other request on this runtime — including
        # `GET /ping`, whose probe timeout would get the container recycled
        # mid-generation.
        result = await run_in_threadpool(
            runtime.handle, parsed, model=model, settings=settings
        )
    except Exception:  # noqa: BLE001 — surfaced as a typed body, never a 500
        # Logged with the traceback, answered without one. The caller gets a
        # code it can branch on; the stack trace stays in CloudWatch, because a
        # generation failure can carry fragments of tenant-authored context and
        # the gateway relays this body onward.
        logger.exception("generation failed (session=%s)", session_id)
        return JSONResponse(
            ErrorResponse(
                error_code="GENERATION_FAILED",
                message=(
                    "generation failed unexpectedly. The runtime logs carry the "
                    "detail; this response deliberately does not."
                ),
            ).model_dump()
        )

    return JSONResponse(result.model_dump(mode="json"))
