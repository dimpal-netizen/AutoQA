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

from app.ai.client import LLMClient, LLMError, LLMRefusal, LLMResponse
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-2.5-pro"

# Per million tokens, for the cost ledger only. Gemini prices by prompt size
# tier, so treat these as an estimate rather than an invoice.
INPUT_COST_PER_MTOK = 1.25
OUTPUT_COST_PER_MTOK = 10.00

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
        self, prompt: str, schema: type[T], *, system: str = "", max_tokens: int = 8000
    ) -> LLMResponse:
        started = time.monotonic()
        config = self._config(system, max_tokens)
        config.response_mime_type = "application/json"
        config.response_schema = schema

        response = self._generate(prompt, config)

        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, schema):
            # Truncation is the usual cause: a response cut off at the token
            # limit is not valid JSON, so nothing parses. Say which it was.
            if _finish_reason(response) is types.FinishReason.MAX_TOKENS:
                raise LLMError(
                    f"Gemini hit the {max_tokens} token limit before finishing its "
                    f"{schema.__name__} response"
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
        )

    def _generate(
        self, prompt: str, config: types.GenerateContentConfig
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

        return LLMResponse(
            text=text,
            parsed=parsed,
            provider=self.provider,
            model=getattr(response, "model_version", None) or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(
                input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
                + output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK,
                6,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            raw={"finish_reason": str(_finish_reason(response) or "")},
        )


def _finish_reason(response: types.GenerateContentResponse):
    candidates = getattr(response, "candidates", None) or []
    return getattr(candidates[0], "finish_reason", None) if candidates else None


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

    try:
        models = genai.Client(api_key=key).models.list()
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
