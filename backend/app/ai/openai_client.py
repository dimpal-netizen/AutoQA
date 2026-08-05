"""OpenAI adapter — the configured fallback.

Deliberately minimal: it satisfies the same LLMClient interface so nothing above
it changes, and it exists so LLM_PROVIDER=openai is a real option rather than a
promise. Claude is the primary provider.
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.ai.client import LLMClient, LLMError, LLMRefusal, LLMResponse
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MODEL = "gpt-5"

INPUT_COST_PER_MTOK = 1.25
OUTPUT_COST_PER_MTOK = 10.00


class OpenAIClient(LLMClient):
    provider = "openai"
    model = MODEL

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise LLMError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=key)

    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 8000) -> LLMResponse:
        started = time.monotonic()
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        try:
            response = self._client.chat.completions.create(
                model=MODEL, max_completion_tokens=max_tokens, messages=messages
            )
        except Exception as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise LLMRefusal("OpenAI's content filter declined this request")

        return self._to_response(response, text=choice.message.content or "", started=started)

    def complete_model(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str = "",
        max_tokens: int = 8000,
        image: bytes | None = None,  # noqa: ARG002 - this provider does not look
    ) -> LLMResponse:
        started = time.monotonic()
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        try:
            response = self._client.chat.completions.parse(
                model=MODEL,
                max_completion_tokens=max_tokens,
                messages=messages,
                response_format=schema,
            )
        except Exception as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise LLMRefusal("OpenAI's content filter declined this request")

        parsed = choice.message.parsed
        if parsed is None:
            raise LLMError(f"OpenAI returned no output matching {schema.__name__}")

        return self._to_response(
            response, text=choice.message.content or "", started=started, parsed=parsed
        )

    def _to_response(
        self, response, *, text: str, started: float, parsed: BaseModel | None = None
    ) -> LLMResponse:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0

        return LLMResponse(
            text=text,
            parsed=parsed,
            provider=self.provider,
            model=getattr(response, "model", MODEL),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(
                input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
                + output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK,
                6,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
