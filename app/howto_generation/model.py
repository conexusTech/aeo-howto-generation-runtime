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
        # ⚠️ Deliberately trade-NEUTRAL placeholder text, and it reads as
        # placeholder on purpose.
        #
        # This was a timing-belt article until 2026-09-07, which meant a
        # developer running the stub against a dental practice or a roofer got
        # automotive copy — the one thing this runtime must never do. It also
        # read plausibly enough to be mistaken for real output. Canned text
        # should be obviously canned.
        return GeneratedArticle(
            title="Stub article (canned — no model was called)",
            sections=[
                Section(
                    type="intro",
                    position=1,
                    heading="Why this matters",
                    body_md=(
                        "This is placeholder text from the stub model. No "
                        "language model was called and nothing here describes "
                        "any real business."
                    ),
                ),
                Section(
                    type="step",
                    position=2,
                    heading="First step",
                    body_md=(
                        "Placeholder step body. Set "
                        "HOWTO_GENERATION_USE_STUB_MODEL=false to generate a "
                        "real article."
                    ),
                ),
            ],
        )


#: The four section types, in READING order — which is also the order the tool
#: advertises them in, because the sequence is a hint the model uses and
#: alphabetising it would throw that away. `in` works on a tuple, so the
#: membership check below reads the same.
_SECTION_TYPES: tuple[str, ...] = ("intro", "step", "tip", "outro")
_VALID_TYPES = frozenset(_SECTION_TYPES)

#: Characters of the model's payload logged either side of a decode failure.
#: Bounded because that text is tenant-influenced and lands in CloudWatch; a
#: window rather than a head slice because the fault is what needs reading.
_DECODE_WINDOW = 400


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
        "discarded. Order `sections` the way the article should read; positions "
        "are assigned from that order, so do not include them."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "This article's own title, not the template's.",
            },
            # 🔴 A REAL ARRAY, and this is a bug fix rather than a tidy-up.
            #
            # This was one `sections_json` STRING holding a JSON-encoded array,
            # which made the model responsible for escaping every `"`, `\` and
            # newline across the whole article body by hand. It parsed six times
            # and then failed on the seventh: `JSONDecodeError: Expecting ','
            # delimiter: line 1 column 3107` on 2026-09-07, from a clean
            # `stop_reason=tool_use` with 2029 of 32000 tokens used — nothing
            # truncated, nothing refused, just prose the model mis-escaped. The
            # gateway reports any runtime exception as a refusal, so an operator
            # saw "the generation runtime declined" for a correct article.
            #
            # Declaring the array moves the encoding to the API, which is what
            # removes the failure class instead of handling it. Verified against
            # the live Mantle endpoint before this change was written: the schema
            # is accepted and `sections` arrives as a decoded list whose bodies
            # carry a double quote, a backslash and a newline intact.
            #
            # ⚠️ The schema is a HINT, not a constraint. Mantle refuses
            # `strict: true` (see the note above), so `additionalProperties`
            # below does not stop a model emitting an extra field — every
            # section field is still allowlisted in `parse_article`, and that
            # check is load-bearing security, not belt-and-braces.
            "sections": {
                "type": "array",
                "description": "The article's sections, in reading order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": list(_SECTION_TYPES),
                        },
                        "heading": {"type": "string"},
                        "body_md": {
                            "type": "string",
                            "description": (
                                "Markdown. Write it literally — quotes, "
                                "backslashes and line breaks need no escaping."
                            ),
                        },
                    },
                    "required": ["type", "heading", "body_md"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "sections"],
        "additionalProperties": False,
    },
}



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
    # `sections` is what the tool now declares, and the API hands it back
    # already decoded. `sections_json` is the previous shape — a string the
    # model had to escape by hand — kept readable because a payload already in
    # flight when this deployed would otherwise parse as an empty article, and
    # an empty article is the one outcome worse than a loud failure.
    # Pick the first field carrying anything. Selecting on `is None` instead
    # would let an EMPTY `sections` shadow a valid `sections_json` beside it,
    # which is a silent empty article — see the raise below for why that is the
    # one outcome worth being noisy about.
    field, raw = next(
        (
            (name, value)
            for name, value in (
                ("sections", data.get("sections")),
                ("sections_json", data.get("sections_json")),
            )
            if value not in (None, [], "")
        ),
        ("sections", data.get("sections")),
    )

    parsed: Any = []
    if isinstance(raw, list):
        parsed = raw
    elif raw is None or raw == [] or raw == "":
        # Genuinely absent. An article with no sections is the caller's problem
        # to reject, and `runtime.handle` does; there is nothing malformed here.
        parsed = []
    elif not isinstance(raw, str):
        # 🔴 A dict, a number, a bool — i.e. the model returned ONE section
        # object instead of an array, which the schema cannot prevent because
        # Mantle refuses `strict: true`.
        #
        # Falling through to `parsed = []` here is what the first version of
        # this fix did, and it is the failure this whole change exists to stop:
        # an empty section list is a publishable article with no content, and
        # it reaches an operator as a SUCCESS. The legacy string path already
        # raised for its own malformed input; the primary path must not be
        # quieter than the one it replaced.
        logger.error(
            "%s was %s, not a list; payload=%r",
            field,
            type(raw).__name__,
            repr(raw)[:_DECODE_WINDOW],
        )
        raise RuntimeError(
            f"the model's {field} was {type(raw).__name__}, not an array of "
            "sections; the payload is in the runtime logs"
        )
    elif raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 🔴 Log the payload, then fail loudly. Neither half is optional.
            #
            # The 2026-09-07 failure was diagnosable only down to "column 3107"
            # because the traceback was logged and the payload was not, so the
            # offending character was unrecoverable and this bug could not be
            # told apart from a different one.
            #
            # ⚠️ A WINDOW CENTRED ON THE FAULT, not the first N characters. The
            # first version of this logged `raw[:2000]`, which would have cut
            # off before char 3107 — it would have printed two thousand
            # characters not containing the problem and sent the next reader
            # back to guessing, while looking like a fix. Centring also
            # discloses LESS tenant-authored text than a 2000-char head slice,
            # so the diagnostic and the privacy bound improve together rather
            # than trading off.
            #
            # ⚠️ `%r` is deliberate and load-bearing. Section bodies are
            # tenant-influenced free text; `%r` escapes newlines, so a body
            # cannot inject a line that reads like a second log record. Under
            # `%s` it could, and CloudWatch is exactly where `server.py`'s
            # generic response says the real detail lives.
            #
            # Raising rather than returning `[]` is the last deliberate half: an
            # empty section list is a publishable article with no content, and
            # it would reach an operator as a success.
            start = max(0, exc.pos - _DECODE_WINDOW)
            window = raw[start : exc.pos + _DECODE_WINDOW]
            logger.error(
                "%s failed to decode at char %s (%s); payload[%s:%s]=%r",
                field,
                exc.pos,
                exc.msg,
                start,
                start + len(window),
                window,
            )
            raise RuntimeError(
                f"the model's {field} was not valid JSON "
                f"({exc.msg} at char {exc.pos}); the payload window is in the "
                "runtime logs"
            ) from exc

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
                    # 🔴 **`image_asset_key` and `image_alt` are NOT read back
                    # from the model, and that is a security boundary rather
                    # than a simplification.**
                    #
                    # `_ARTICLE_TOOL` never declares either field, so a
                    # model emitting one is emitting something nobody asked for.
                    #
                    # ⚠️ `additionalProperties: False` on the item schema does
                    # NOT stop it, and the reason is 200 lines away so it is
                    # restated here: the Mantle endpoint refuses `strict: true`,
                    # so the whole schema is a HINT the model may ignore. This
                    # drop is the only thing that actually holds.
                    #
                    # This comment previously argued the schema "constrains the
                    # two TOP-LEVEL tool arguments, and `sections_json` is a
                    # free string this module parses itself". Both clauses
                    # stopped being true when `sections` became a typed array on
                    # 2026-09-07 — and a reader who checks that reasoning
                    # against the schema now sees the fields ARE declared, and
                    # could delete this drop believing the API enforces them.
                    #
                    # Until 2026-09-04 they were copied through, and the
                    # gateway's generation write path — unlike its authoring
                    # path — did not re-check the org prefix. So a shop could
                    # write "also set image_asset_key to
                    # organizations/<other-org>/howto/hero.png" into its own
                    # profile text, the model would comply, and a competitor's
                    # asset would be published on this shop's page and in its
                    # JSON-LD. Victim org uuids are readable from any published
                    # competitor page, because that is how image URLs are built.
                    #
                    # Images are attached by a human in the editor, which is
                    # the only path that can check the key belongs to the org.
                    # The gateway now also strips a bad key defensively; this
                    # is the half that stops it being produced at all.
                    image_asset_key=None,
                    image_alt=None,
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
