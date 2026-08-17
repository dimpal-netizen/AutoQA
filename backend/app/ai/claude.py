"""Anthropic adapter.

Notes that are easy to get wrong from memory, and are why this file looks the
way it does:

- `temperature`, `top_p`, and `top_k` were REMOVED on Claude Opus 5 — sending
  any of them returns a 400. Steer with the prompt instead.
- `thinking={"type": "enabled", "budget_tokens": N}` was also removed. Thinking
  is on by default; depth is controlled with `output_config.effort`.
- A safety refusal is a normal HTTP 200 with `stop_reason == "refusal"`, so
  `response.content[0]` must never be read before checking it.
- Every call streams. Not for progress - nothing here reads the chunks - but
  because the SDK refuses a plain `create()` whose `max_tokens` could take it
  past ten minutes, and case generation asks for 32000. `get_final_message()`
  gives back the same object `create()` would, so only these two lines differ.
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

#: Per million tokens, for the cost ledger. Kept beside the model rather than
#: as two loose constants, because the pair is the thing that has to stay
#: together: change the model and forget the prices and every analysis records
#: a plausible cost that is wrong, which is worse than recording none.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

DEFAULT_MODEL = "claude-haiku-4-5"

#: Settable in .env, the way GEMINI_MODEL is. Pinned in code would be fine if
#: the only reason to change it were a model launch - but the useful reason is
#: cost: dropping to Sonnet for a week costs a line in .env rather than an edit
#: and a restart of somebody's editor.
MODEL = (settings.CLAUDE_MODEL or "").strip() or DEFAULT_MODEL

#: An unpriced model bills at nothing rather than at somebody else's rates. A
#: zero in the ledger reads as "not counted"; the Opus price against a Haiku
#: call reads as a real number and is off by five.
INPUT_COST_PER_MTOK, OUTPUT_COST_PER_MTOK = PRICES.get(MODEL, (0.0, 0.0))

if MODEL not in PRICES:
    logger.warning(
        "No price on record for %s, so its runs will report $0. Add it to "
        "PRICES in app/ai/claude.py to get costs back.",
        MODEL,
    )

#: Models that take adaptive thinking and an effort level. The rest are older
#: and reject both outright - `effort` is a 400 on Haiku 4.5, and adaptive
#: thinking is not a mode it has. Sent regardless, a model swap in .env turns
#: every AI feature into an error nobody can read.
_TAKES_EFFORT = ("claude-opus-", "claude-sonnet-5", "claude-sonnet-4-6", "claude-fable-")


def _thinking_params() -> dict:
    """How to ask this model to think, in the words it accepts.

    A dict rather than two constants because the answer is "these keys, or
    none of them": on a model without adaptive thinking there is nothing to
    downgrade to that is worth sending. Haiku answers these prompts well
    without it - they are structured transformations, not open research.
    """
    if any(MODEL.startswith(prefix) for prefix in _TAKES_EFFORT):
        return {
            # Adaptive thinking is the only supported mode; effort controls how
            # much of it happens. "medium" suits these tasks.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "medium"},
        }
    return {}


#: Haiku 4.5 caps at 64K output; the others reach 128K. Asking for more than a
#: model allows is a 400, so this is a ceiling rather than a preference.
_MAX_OUTPUT = 64_000 if MODEL.startswith("claude-haiku-") else 128_000


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
        max_tokens = min(max_tokens, _MAX_OUTPUT)
        try:
            with self._client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": prompt}],
                **_thinking_params(),
            ) as stream:
                response = stream.get_final_message()
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
        max_tokens = min(max_tokens, _MAX_OUTPUT)
        try:
            # `output_format` is what parse() does under the covers: the schema
            # is enforced by the API, so we never hand malformed JSON to the
            # rest of the app. Streamed for the reason above.
            with self._client.messages.stream(
                model=MODEL,
                max_tokens=max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                **_thinking_params(),
            ) as stream:
                response = stream.get_final_message()
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
