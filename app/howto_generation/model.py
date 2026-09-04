"""The model seam.

Generation is model-driven; everything around it is not. This module is the only
place a model is called, and it hands back a plain `GeneratedArticle` that the
deterministic parts — slot resolution, similarity, the regeneration merge — work
on without knowing a model exists.

`BedrockChatModel` imports the `anthropic` SDK **lazily, inside `__init__`**, so
importing this module and running the entire test suite needs no SDK, no AWS
credentials and no network. That is not a convenience: a runtime whose logic can
only be exercised with a live model endpoint is a runtime whose logic does not
get exercised.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from anthropic.types import MessageParam, TextBlockParam

from app.howto_generation.contracts import Section, TokenUsage
from app.howto_generation.prompt import PromptComposition

logger = logging.getLogger(__name__)


class GeneratedArticle(BaseModel):
    """One article as the model produced it, before any of our processing."""

    model_config = ConfigDict(extra="ignore")

    title: str
    sections: list[Section] = Field(default_factory=list)
    usage: TokenUsage | None = None


class ChatModel(ABC):
    """Injectable model. Synchronous, matching the deterministic pipeline; the
    server dispatches it off the event loop."""

    @abstractmethod
    def generate(self, *, prompt: PromptComposition) -> GeneratedArticle: ...


class FakeChatModel(ChatModel):
    """Test double. Returns a scripted article, or a deterministic default."""

    def __init__(self, article: GeneratedArticle | None = None) -> None:
        self._article = article
        #: Every prompt it was called with, so tests can assert on what the
        #: model was actually told rather than only on what came back.
        self.calls: list[PromptComposition] = []

    def generate(self, *, prompt: PromptComposition) -> GeneratedArticle:
        self.calls.append(prompt)
        if self._article is not None:
            return self._article
        return GeneratedArticle(
            title="How to replace a timing belt",
            sections=[
                Section(
                    type="intro",
                    position=1,
                    heading="Why this matters",
                    body_md="A timing belt failure is not a repair you schedule.",
                ),
                Section(
                    type="step",
                    position=2,
                    heading="Check the service interval",
                    body_md="Start with the manufacturer interval for the engine.",
                ),
            ],
        )


#: The article envelope, delivered as a TOOL rather than `output_config.format`.
#:
#: 🔴 Structured outputs are documented for Bedrock but the **Mantle** endpoint
#: rejects them — `output_config.format: Extra inputs are not permitted`, and
#: `strict: true` on a tool is refused too. Measured on the sibling runtime, not
#: inferred: `output_config.effort` is accepted on the same endpoint, so it is
#: `format` specifically. A tool schema is the only way to get a structured
#: result out of this endpoint at all.
_ARTICLE_TOOL: dict[str, Any] = {
    "name": "emit_article",
    "description": (
        "Emit the finished article. Call this exactly once — it is the only way "
        "your work is delivered. Do not reply in prose instead; prose is "
        "discarded. `sections_json` is a JSON-encoded ARRAY of section objects, "
        'each {"type": "intro"|"step"|"tip"|"outro", "heading": str, '
        '"body_md": str}. Order the array the way the article should read; '
        "positions are assigned from that order, so do not include them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "This article's own title, not the template's.",
            },
            "sections_json": {
                "type": "string",
                "description": "JSON-encoded array of section objects.",
            },
        },
        "required": ["title", "sections_json"],
        "additionalProperties": False,
    },
}

_VALID_TYPES = {"intro", "step", "tip", "outro"}


class BedrockChatModel(ChatModel):
    """Claude on Amazon Bedrock via the Mantle client.

    Live Bedrock behaviour is NOT exercised by the test suite — `FakeChatModel`
    stands in there, and this class is covered only for its parsing. Verify
    against Bedrock before production.
    """

    def __init__(
        self, *, model_id: str, aws_region: str, max_tokens: int = 32000
    ) -> None:
        # Lazy: this module imports without the SDK present.
        from anthropic import AnthropicBedrockMantle

        self._client = AnthropicBedrockMantle(aws_region=aws_region)
        self._model_id = model_id
        self._max_tokens = max_tokens

    def generate(self, *, prompt: PromptComposition) -> GeneratedArticle:
        stable, volatile = prompt.split()
        system: list[TextBlockParam] = [
            # The cache breakpoint. Byte-stable across every article for one org.
            {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": volatile},
        ]
        messages: list[MessageParam] = [
            {"role": "user", "content": "Write the article now."}
        ]

        # 🔴 STREAMED, not `messages.create`, and this is not a preference.
        #
        # Measured against the live endpoint on 2026-09-04, first invocation of
        # the deployed runtime:
        #
        #   ValueError: Streaming is required for operations that may take
        #   longer than 10 minutes
        #
        # The SDK refuses a non-streaming call whose `max_tokens` could run past
        # its 10-minute ceiling, and 32000 trips it. The sibling chat runtime
        # never hit this because its budget is 16000.
        #
        # ⚠️ The fix is to stream, NOT to shrink the budget. The sibling
        # documented 8000 being too small and killing a turn outright —
        # thinking and the answer share this allowance, so cutting it trades a
        # hard failure for a silent truncation, and a truncated article is
        # indistinguishable from a short one by the time a reviewer sees it.
        #
        # Streaming here is an INTERNAL detail: the runtime still answers the
        # gateway with one JSON body. Nothing above this line changes.
        with self._client.messages.stream(
            model=self._model_id,
            max_tokens=self._max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            messages=messages,
            tools=[_ARTICLE_TOOL],
            # DELIBERATELY NOT `tool_choice`. Measured on the sibling runtime
            # against the live Mantle endpoint: forcing the tool SUPPRESSES the
            # thinking block, and the model then reasons inside the argument
            # field and contradicts itself — worse answers for roughly double
            # the tokens. The unforced call gets one bounded retry below.
        ) as stream:
            response = stream.get_final_message()
        usage = _usage_from_response(response)
        logger.info(
            "generate: stop_reason=%s blocks=%s output_tokens=%s max_tokens=%s",
            response.stop_reason,
            [b.type for b in response.content],
            getattr(response.usage, "output_tokens", None),
            self._max_tokens,
        )
        if response.stop_reason == "max_tokens":
            logger.warning(
                "model hit max_tokens (%s) — thinking and the article share this "
                "budget, so the article may be truncated or absent",
                self._max_tokens,
            )

        tool_use = next((b for b in response.content if b.type == "tool_use"), None)

        if tool_use is None and _has_text(response):
            # Answered in prose. Reachable by design, and it happened on the
            # sibling runtime's first end-to-end run. Retry ONCE with the tool
            # forced: the unforced call already failed, so the choice is a worse
            # answer versus no answer. Bounded to one so a stubborn model cannot
            # loop at ~30k tokens a time.
            logger.warning(
                "no tool call (stop_reason=%s) — retrying once with tool_choice forced",
                response.stop_reason,
            )
            # Streamed for the same reason as the first call. A retry that
            # used the non-streaming path would fail on the SDK guard rather
            # than on the model, and the error would name neither.
            with self._client.messages.stream(
                model=self._model_id,
                max_tokens=self._max_tokens,
                thinking={"type": "adaptive"},
                system=system,
                messages=messages,
                tools=[_ARTICLE_TOOL],
                tool_choice={"type": "tool", "name": _ARTICLE_TOOL["name"]},
            ) as stream:
                response = stream.get_final_message()
            # Summed, not replaced: the first call's tokens were really spent,
            # and billing that reads only the retry under-reports every repaired
            # generation.
            usage = usage + _usage_from_response(response)
            tool_use = next(
                (b for b in response.content if b.type == "tool_use"), None
            )

        if tool_use is None:
            raise RuntimeError(
                "model produced no article: stop_reason="
                f"{response.stop_reason!r}, blocks="
                f"{[b.type for b in response.content]}, "
                f"max_tokens={self._max_tokens}"
                + (
                    " — the budget was consumed before an answer was produced;"
                    " raise max_tokens or lower effort."
                    if response.stop_reason == "max_tokens"
                    else ""
                )
            )

        article = parse_article(dict(tool_use.input))
        article.usage = usage
        return article


def parse_article(data: dict[str, Any]) -> GeneratedArticle:
    """Wire mapping -> `GeneratedArticle`, assigning positions from array order.

    Positions are OURS, never the model's. A model asked for contiguous 1-based
    positions will occasionally skip one or repeat one, and the gateway's stored
    invariant is contiguity — so taking the array order and numbering it here
    removes a whole class of defect rather than validating for it.

    A section with an unrecognised `type` is dropped rather than coerced. The
    four types drive rendering, and quietly mapping an invented fifth onto
    `step` publishes something in a shape nobody chose.
    """
    raw = data.get("sections_json")
    parsed: Any = []
    if isinstance(raw, str) and raw.strip():
        parsed = json.loads(raw)
    elif isinstance(raw, list):
        # Tolerated: some endpoints hand back an already-decoded array.
        parsed = raw

    sections: list[Section] = []
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            section_type = item.get("type")
            if section_type not in _VALID_TYPES:
                logger.warning("dropping section with unknown type %r", section_type)
                continue
            heading = item.get("heading")
            body = item.get("body_md")
            if not isinstance(heading, str) or not isinstance(body, str):
                continue
            sections.append(
                Section(
                    type=section_type,  # type: ignore[arg-type]
                    position=len(sections) + 1,
                    heading=heading,
                    body_md=body,
                    image_asset_key=item.get("image_asset_key"),
                    image_alt=item.get("image_alt"),
                )
            )

    title = data.get("title")
    return GeneratedArticle(
        title=title if isinstance(title, str) and title.strip() else "",
        sections=sections,
    )


def _has_text(response: Any) -> bool:
    """True when the response carries any non-blank text block.

    Distinguishes "answered in prose" — worth one forced retry, the model had
    something to say and used the wrong channel — from "produced nothing", where
    a retry burns the budget a second time and fails identically.
    """
    return any(
        b.type == "text" and b.text.strip() for b in getattr(response, "content", [])
    )


def _usage_from_response(response: Any) -> TokenUsage:
    """Map the SDK's usage onto our wire names.

    The names differ and the mapping is not guessable: the SDK calls them
    `cache_read_input_tokens` and `cache_creation_input_tokens`, and both are
    OPTIONAL — None when the request had no cache breakpoint. A zero here is
    indistinguishable from a cache that never hit, which is the exact number
    the `cache_control` marker is tuned by.

    Never raises. Usage is billing metadata, and losing a generated article
    because a provider renamed a usage field trades an article for a statistic.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


def get_chat_model(*, model_id: str, aws_region: str, max_tokens: int) -> ChatModel:
    """Build the production model. Called by the server entry."""
    return BedrockChatModel(
        model_id=model_id, aws_region=aws_region, max_tokens=max_tokens
    )
