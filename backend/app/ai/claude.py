"""Anthropic adapter.

Notes that are easy to get wrong from memory, and are why this file looks the
way it does:

- `temperature`, `top_p`, and `top_k` were REMOVED on Claude Opus 5 — sending
  any of them returns a 400. Steer with the prompt instead.
- `thinking={"type": "enabled", "budget_tokens": N}` was also removed. Thinking
  is on by default; depth is controlled with `output_config.effort`.
- A safety refusal is a normal HTTP 200 with `stop_reason == "refusal"`, so
  `response.content[0]` must never be read before checking it.
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.ai.client import LLMClient, LLMError, LLMRefusal, LLMResponse
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MODEL = "claude-opus-5"

# Per million tokens, for the cost ledger. Cheap to keep current; the point is
# that every analysis records what it cost rather than being a mystery.
INPUT_COST_PER_MTOK = 5.00
OUTPUT_COST_PER_MTOK = 25.00


class ClaudeClient(LLMClient):
    provider = "claude"
    model = MODEL

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=key)

    # ------------------------------------------------------------------
    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 8000) -> LLMResponse:
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": prompt}],
                # Adaptive thinking is the only supported mode; effort controls
                # how much of it happens. "medium" suits these tasks — they are
                # structured transformations, not open research.
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
            )
        except Exception as exc:
            raise _translate(exc) from exc

        _guard_refusal(response)

        text = "".join(block.text for block in response.content if block.type == "text")
        return self._to_response(response, text=text, started=started)

    # ------------------------------------------------------------------
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
        try:
            # parse() validates against the schema and retries on mismatch, so
            # we never hand malformed JSON to the rest of the app.
            response = self._client.messages.parse(
                model=MODEL,
                max_tokens=max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                output_format=schema,
            )
        except Exception as exc:
            raise _translate(exc) from exc

        _guard_refusal(response)

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMError(f"Claude returned no output matching {schema.__name__}")

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        return self._to_response(response, text=text, started=started, parsed=parsed)

    # ------------------------------------------------------------------
    def _to_response(
        self, response, *, text: str, started: float, parsed: BaseModel | None = None
    ) -> LLMResponse:
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

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
            raw={"stop_reason": getattr(response, "stop_reason", None)},
        )


def _guard_refusal(response) -> None:
    """Refusals arrive as a successful response, so check before reading content."""
    if getattr(response, "stop_reason", None) != "refusal":
        return

    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None) if details else None
    raise LLMRefusal(
        f"Claude declined this request{f' ({category})' if category else ''}. "
        "The content is unlikely to succeed on retry."
    )


def _translate(exc: Exception) -> Exception:
    """Map SDK exceptions to our own, most specific first."""
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, anthropic.AuthenticationError):
        return LLMError("Anthropic rejected the API key")
    if isinstance(exc, anthropic.NotFoundError):
        return LLMError(f"Model {MODEL} is not available to this key")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMError("Rate limited by Anthropic; try again shortly")
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMError("Could not reach the Anthropic API")
    if isinstance(exc, anthropic.APIStatusError):
        return LLMError(f"Anthropic API error {exc.status_code}: {exc.message}")
    return LLMError(f"Unexpected error calling Claude: {exc}")
