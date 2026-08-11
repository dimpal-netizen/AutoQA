"""Google Gemini adapter.

Uses `google-genai`, the current SDK. The older `google-generativeai` package
has a different shape entirely (`genai.configure()` + `GenerativeModel`), so
examples found online often will not run against this one.

Things worth knowing, all verified against the installed SDK rather than
remembered:

- Everything optional goes in `GenerateContentConfig`, not as keyword
  arguments: system prompt, token cap, and the structured-output schema.
- Structured output is `response_schema=<PydanticModel>` together with
  `response_mime_type="application/json"`. The parsed instance comes back on
  `response.parsed`, already validated.
- A safety block is a *successful* response, not an exception. It shows up
  either as `prompt_feedback.block_reason` (the prompt was rejected) or as a
  candidate whose `finish_reason` is SAFETY or similar, in which case
  `response.text` is empty.
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors, types
from pydantic import BaseModel

from app.ai.client import (
    SEED,
    TEMPERATURE,
    LLMClient,
    LLMError,
    LLMRefusal,
    LLMResponse,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# An alias, not a pinned version, and deliberately so. Gemini model ids turn
# over fast — a key that has gemini-3.6-flash may no longer serve
# gemini-2.5-pro — and a hard-coded id silently becomes a 404 months later.
# Flash also has far higher free-tier limits than pro, which matters because
# these tasks are structured rewrites, not deep reasoning. Pin a specific
# version with GEMINI_MODEL when you want one.
DEFAULT_MODEL = "gemini-flash-latest"

# Thinking is billed as output and counted against max_output_tokens, so an
# unbounded budget competes with the answer for the same ceiling — and wins,
# because it happens first. Measured on a twelve-case generation:
#
#     prompt      2097
#     thinking    8369   <- more than half the ceiling, and invisible
#     answer      7482
#     total      17948   (16000 limit: 149 tokens of headroom)
#
# That run finished. One that thought a little longer did not, and a response
# cut off mid-JSON does not parse, which surfaced as "Gemini hit the 16000
# token limit before finishing its GeneratedCases response" — intermittently,
# because how long it thinks varies run to run.
#
# Bounded rather than disabled (thinking_budget=0). These tasks are structured
# rewrites, but the model still has to decide what is worth testing, and that
# is the part thinking is for.
THINKING_BUDGET = 4000

# Per million tokens, for the cost ledger only. Matched on the model id because
# the model is configurable: quoting pro prices for a flash run would overstate
# spend by an order of magnitude. Longest prefix wins, and the fallback is the
# most expensive tier so an unknown model is never *under*stated.
_COST_PER_MTOK: dict[str, tuple[float, float]] = {
    "flash-lite": (0.10, 0.40),
    "flash": (0.30, 2.50),
    "pro": (1.25, 10.00),
}
_FALLBACK_COST = (1.25, 10.00)


def _rates(model: str) -> tuple[float, float]:
    name = model.lower()
    for family in ("flash-lite", "flash", "pro"):
        if family in name:
            return _COST_PER_MTOK[family]
    return _FALLBACK_COST

# Candidate outcomes that mean "the model declined", as opposed to "the model
# answered". Retrying these with the same input will not help.
_REFUSAL_REASONS = {
    types.FinishReason.SAFETY,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.SPII,
    types.FinishReason.RECITATION,
}


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or settings.GEMINI_API_KEY
        if not key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.model = model or settings.GEMINI_MODEL or DEFAULT_MODEL
        self._client = genai.Client(api_key=key)

    # ------------------------------------------------------------------
    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 8000) -> LLMResponse:
        started = time.monotonic()
        response = self._generate(prompt, self._config(system, max_tokens))
        return self._to_response(response, text=response.text or "", started=started)

    # ------------------------------------------------------------------
    def complete_model(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str = "",
        max_tokens: int = 8000,
        image: bytes | None = None,
    ) -> LLMResponse:
        started = time.monotonic()
        config = self._config(system, max_tokens)
        config.response_mime_type = "application/json"
        config.response_schema = schema

        # The image goes first. A model that reads the question before looking
        # tends to answer from the text and treat the picture as decoration.
        contents = (
            [types.Part.from_bytes(data=image, mime_type="image/png"), prompt]
            if image
            else prompt
        )
        response = self._generate(contents, config)

        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, schema):
            # Truncation is the usual cause: a response cut off at the token
            # limit is not valid JSON, so nothing parses. Say which it was.
            if _finish_reason(response) is types.FinishReason.MAX_TOKENS:
                salvaged = _salvage(response.text or "", schema)
                if salvaged is not None:
                    logger.warning(
                        "Gemini ran out of room mid-answer; kept the %d complete "
                        "item(s) it had already written%s",
                        len(next(iter(salvaged.__dict__.values()), []) or []),
                        _token_split(response),
                    )
                    return self._to_response(
                        response,
                        text=response.text or "",
                        started=started,
                        parsed=salvaged,
                    )

                # Say how the ceiling was spent. "Hit the limit" on its own
                # invites raising the limit, when the answer to this has twice
                # been that thinking ate it before the answer began.
                raise LLMError(
                    f"Gemini hit the {max_tokens} token limit before finishing its "
                    f"{schema.__name__} response{_token_split(response)}"
                )
            raise LLMError(f"Gemini returned no output matching {schema.__name__}")

        return self._to_response(
            response, text=response.text or "", started=started, parsed=parsed
        )

    # ------------------------------------------------------------------
    def _config(self, system: str, max_tokens: int) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
            # Same recording, same question, same answer. Without these the
            # model samples, and regenerating a suite rewrote every test into a
            # slightly different one — which is how a passing case came back
            # red without the application changing. See `TEMPERATURE` in
            # client.py for the whole of it.
            temperature=TEMPERATURE,
            seed=SEED,
        )

    def _generate(
        self, prompt: str | list, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except Exception as exc:
            raise _translate(exc, self.model) from exc

        _guard_refusal(response)
        return response

    def _to_response(
        self,
        response: types.GenerateContentResponse,
        *,
        text: str,
        started: float,
        parsed: BaseModel | None = None,
    ) -> LLMResponse:
        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        # Thinking tokens are billed as output but reported separately.
        output_tokens = (getattr(usage, "candidates_token_count", 0) or 0) + (
            getattr(usage, "thoughts_token_count", 0) or 0
        )

        input_rate, output_rate = _rates(self.model)

        return LLMResponse(
            text=text,
            parsed=parsed,
            provider=self.provider,
            model=getattr(response, "model_version", None) or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(
                input_tokens / 1_000_000 * input_rate
                + output_tokens / 1_000_000 * output_rate,
                6,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            raw={"finish_reason": str(_finish_reason(response) or "")},
        )


def _salvage(text: str, schema: type[T]) -> T | None:
    """Whatever whole items the model had written before it ran out of room.

    A truncated answer is cut mid-object, so the JSON does not parse and the
    entire request is lost. On a key allowed twenty requests a day, that is a
    large fraction of the day spent on nothing - and eleven finished test cases
    were sitting in the reply.

    Only schemas that are a single list are salvageable, which is the shape that
    actually gets truncated: many items, each self-contained. The last item is
    dropped whether or not it looks complete, because "looks complete" is
    exactly what a cut-off object does when the cut lands after a closing brace
    on a nested field.

    Returns None when there is nothing whole to keep, so the caller raises as
    before.
    """
    fields = getattr(schema, "model_fields", {})
    if len(fields) != 1:
        return None
    field = next(iter(fields))

    opened = text.find("[")
    if opened < 0:
        return None

    # Walk the array and remember where each top-level item ends. Quotes and
    # escapes are tracked so a brace inside a string does not close an object.
    depth = 0
    in_string = False
    escaped = False
    ends: list[int] = []
    for index in range(opened + 1, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\" and in_string:
            escaped = True
        elif character == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                ends.append(index)

    if len(ends) < 2:
        return None  # nothing, or only the item the cut may have landed inside

    whole = text[opened : ends[-2] + 1] + "]"
    try:
        return schema.model_validate_json(f'{{"{field}": {whole}}}')
    except Exception:  # noqa: BLE001 - a partial answer that will not validate
        return None


def _finish_reason(response: types.GenerateContentResponse):
    candidates = getattr(response, "candidates", None) or []
    return getattr(candidates[0], "finish_reason", None) if candidates else None


def _token_split(response: types.GenerateContentResponse) -> str:
    """" — 8369 spent thinking, 7482 on the answer", when the numbers are there.

    Empty when they are not, so the message reads as a sentence either way.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return ""

    thoughts = getattr(usage, "thoughts_token_count", None) or 0
    answer = getattr(usage, "candidates_token_count", None) or 0
    if not thoughts and not answer:
        return ""

    return f" - {thoughts} spent thinking, {answer} on the answer"


def _guard_refusal(response: types.GenerateContentResponse) -> None:
    """A safety block arrives as a normal response, so check before reading text."""
    feedback = getattr(response, "prompt_feedback", None)
    blocked = getattr(feedback, "block_reason", None) if feedback else None
    if blocked:
        raise LLMRefusal(
            f"Gemini declined the prompt ({blocked}). "
            "The content is unlikely to succeed on retry."
        )

    reason = _finish_reason(response)
    if reason in _REFUSAL_REASONS:
        raise LLMRefusal(
            f"Gemini stopped generating ({reason}). "
            "The content is unlikely to succeed on retry."
        )


def _translate(exc: Exception, model: str) -> Exception:
    """Map SDK exceptions to ours, most specific first."""
    if isinstance(exc, LLMError):
        return exc

    if isinstance(exc, genai_errors.ClientError):
        code = getattr(exc, "code", None)
        if code == 401 or code == 403:
            return LLMError("Google rejected the API key")
        if code == 404:
            # Model ids change often enough that guessing one is a real risk.
            return LLMError(
                f"Model {model!r} is not available to this key. Set GEMINI_MODEL "
                f"in .env to one your key can use."
            )
        if code == 429:
            return LLMError("Rate limited by Google; try again shortly")
        return LLMError(f"Gemini rejected the request: {exc}")

    if isinstance(exc, genai_errors.ServerError):
        return LLMError(f"Gemini is unavailable right now: {exc}")
    if isinstance(exc, genai_errors.APIError):
        return LLMError(f"Gemini API error: {exc}")

    return LLMError(f"Unexpected error calling Gemini: {exc}")


def list_models(api_key: str | None = None) -> list[str]:
    """Model ids this key can actually use.

    Exists because a wrong model id is the most likely first-run failure, and
    "here is what you can use" is a far better error than "404".
    """
    key = api_key or settings.GEMINI_API_KEY
    if not key:
        raise LLMError("GEMINI_API_KEY is not set")

    # The client must outlive the iteration: `list()` returns a lazy pager, so
    # letting the client go out of scope fails mid-loop with "client has been
    # closed" rather than at the call site.
    client = genai.Client(api_key=key)
    try:
        models = list(client.models.list())
    except Exception as exc:
        raise _translate(exc, "") from exc

    names: list[str] = []
    for model in models:
        actions = getattr(model, "supported_actions", None) or []
        if actions and "generateContent" not in actions:
            continue
        name = (getattr(model, "name", "") or "").removeprefix("models/")
        if name:
            names.append(name)
    return sorted(names)
