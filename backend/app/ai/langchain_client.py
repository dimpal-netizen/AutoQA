"""LangChain adapter — one code path for every provider.

Every provider is built through `init_chat_model`, so switching model is a line
in .env rather than a new adapter. What differs between vendors lives in
`_provider()` and is imported from the vendor adapters, not copied.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
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


@dataclass(frozen=True)
class _Provider:
    """Everything that differs between vendors, in one place."""

    langchain_name: str
    key_setting: str
    model: str
    #: (input, output) US dollars per million tokens, for the cost ledger.
    rates: tuple[float, float]
    #: Hard ceiling on output tokens. Asking for more than a model allows is a 400.
    max_output: int | None = None
    #: Constructor arguments only this provider accepts.
    kwargs: dict[str, Any] = field(default_factory=dict)


def _provider(name: str) -> _Provider:
    """Resolve a configured provider name, or say which ones exist."""
    if name == "claude":
        from app.ai import claude

        return _Provider(
            langchain_name="anthropic",
            key_setting="ANTHROPIC_API_KEY",
            model=claude.MODEL,
            rates=claude.PRICES.get(claude.MODEL, (0.0, 0.0)),
            max_output=claude._MAX_OUTPUT,
            # No temperature or seed: both were removed on the current Opus and
            # sending them is a 400. Determinism is steered with the prompt.
            kwargs=claude._thinking_params(),
        )

    if name == "openai":
        from app.ai import openai_client

        return _Provider(
            langchain_name="openai",
            key_setting="OPENAI_API_KEY",
            model=openai_client.MODEL,
            rates=(
                openai_client.INPUT_COST_PER_MTOK,
                openai_client.OUTPUT_COST_PER_MTOK,
            ),
            # See `TEMPERATURE` in client.py: the same recording has to produce
            # the same test cases, or a verdict means nothing.
            kwargs={"temperature": TEMPERATURE, "seed": SEED},
        )

    if name == "gemini":
        from app.ai import gemini

        model = (settings.GEMINI_MODEL or "").strip() or gemini.DEFAULT_MODEL
        return _Provider(
            langchain_name="google_genai",
            key_setting="GEMINI_API_KEY",
            model=model,
            rates=gemini._rates(model),
            kwargs={
                "temperature": TEMPERATURE,
                "seed": SEED,
                "thinking_budget": gemini.THINKING_BUDGET,
            },
        )

    raise LLMError(f"Unknown LLM_PROVIDER {name!r}. Use one of: claude, gemini, openai.")


#: What "the model declined" looks like per provider. Retrying will not help.
_REFUSAL_REASONS: dict[str, set[str]] = {
    "claude": {"refusal"},
    "openai": {"content_filter"},
    "gemini": {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"},
}

#: What "the model ran out of room" looks like. Same meaning, three spellings.
_TRUNCATED = {"max_tokens", "MAX_TOKENS", "length"}


class LangChainClient(LLMClient):
    """The one client the app builds, whichever provider is configured."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        name = (provider or settings.LLM_PROVIDER).strip().lower()
        spec = _provider(name)

        key = api_key or getattr(settings, spec.key_setting, "")
        if not key:
            # Better to fail here than to send an unauthenticated request.
            raise LLMError(f"{spec.key_setting} is not set")

        self.provider = name
        self.model = model or spec.model
        self._spec = spec
        self._key = key
        # Output ceilings are a constructor argument, and callers ask for
        # different ones, so chat models are built per ceiling and kept.
        self._chats: dict[int, BaseChatModel] = {}

        if spec.rates == (0.0, 0.0):
            logger.warning(
                "No price on record for %s, so its runs will report $0.", self.model
            )

    # ------------------------------------------------------------------
    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 8000) -> LLMResponse:
        started = time.monotonic()
        chat = self._chat(max_tokens)
        try:
            message = chat.invoke(_messages(prompt, system))
        except Exception as exc:
            raise self._translate(exc) from exc

        self._guard_refusal(message)
        return self._to_response(message, text=_text_of(message), started=started)

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
        # `json_schema` is the provider's own structured-output mode on all three,
        # and the mode that leaves the JSON in the message text for `_salvage`.
        chat = self._chat(max_tokens).with_structured_output(
            schema, method="json_schema", include_raw=True
        )
        try:
            result = chat.invoke(_messages(prompt, system, image))
        except Exception as exc:
            raise self._translate(exc) from exc

        message = result["raw"]
        self._guard_refusal(message)

        text = _text_of(message)
        parsed = result["parsed"]
        if parsed is None:
            return self._salvaged(
                message, schema, text=text, started=started, max_tokens=max_tokens
            )

        return self._to_response(message, text=text, started=started, parsed=parsed)

    # ------------------------------------------------------------------
    def _chat(self, max_tokens: int) -> BaseChatModel:
        if self._spec.max_output is not None:
            max_tokens = min(max_tokens, self._spec.max_output)

        chat = self._chats.get(max_tokens)
        if chat is None:
            try:
                chat = init_chat_model(
                    self.model,
                    model_provider=self._spec.langchain_name,
                    api_key=self._key,
                    max_tokens=max_tokens,
                    **self._spec.kwargs,
                )
            except Exception as exc:
                raise self._translate(exc) from exc
            self._chats[max_tokens] = chat
        return chat

    # ------------------------------------------------------------------
    def _salvaged(
        self,
        message: BaseMessage,
        schema: type[T],
        *,
        text: str,
        started: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Whatever whole items survived a truncated answer, or a clear error.

        A response cut off mid-object is not valid JSON, so without this the
        entire request — finished test cases included — is lost.
        """
        if _finish_reason(message) in _TRUNCATED:
            # `_salvage` is Gemini's by history, not by nature: any provider
            # that stops mid-JSON leaves the same wreckage.
            from app.ai.gemini import _salvage

            rescued = _salvage(text, schema)
            if rescued is not None:
                logger.warning(
                    "%s ran out of room mid-answer; kept the %d complete item(s) it "
                    "had already written%s",
                    self.provider,
                    len(next(iter(rescued.__dict__.values()), []) or []),
                    _token_split(message),
                )
                return self._to_response(
                    message, text=text, started=started, parsed=rescued
                )

            # Say how the ceiling was spent: "hit the limit" on its own invites
            # raising the limit, when thinking usually ate it before the answer.
            raise LLMError(
                f"{self.provider} hit the {max_tokens} token limit before finishing "
                f"its {schema.__name__} response{_token_split(message)}"
            )

        raise LLMError(f"{self.provider} returned no output matching {schema.__name__}")

    # ------------------------------------------------------------------
    def _guard_refusal(self, message: BaseMessage) -> None:
        """Refusals arrive as a successful response, so check before reading."""
        metadata = getattr(message, "response_metadata", None) or {}

        blocked = (metadata.get("prompt_feedback") or {}).get("block_reason")
        if blocked:
            raise LLMRefusal(
                f"{self.provider} declined the prompt ({blocked}). "
                "The content is unlikely to succeed on retry."
            )

        reason = _finish_reason(message)
        if reason and reason in _REFUSAL_REASONS.get(self.provider, set()):
            raise LLMRefusal(
                f"{self.provider} declined this request ({reason}). "
                "The content is unlikely to succeed on retry."
            )

    # ------------------------------------------------------------------
    def _to_response(
        self,
        message: BaseMessage,
        *,
        text: str,
        started: float,
        parsed: BaseModel | None = None,
    ) -> LLMResponse:
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0) or 0
        # LangChain folds thinking tokens into the output count, which is how
        # every provider bills them.
        output_tokens = usage.get("output_tokens", 0) or 0

        input_rate, output_rate = self._spec.rates
        metadata = getattr(message, "response_metadata", None) or {}

        return LLMResponse(
            text=text,
            parsed=parsed,
            provider=self.provider,
            model=metadata.get("model_name") or metadata.get("model") or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(
                input_tokens / 1_000_000 * input_rate
                + output_tokens / 1_000_000 * output_rate,
                6,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            raw={"finish_reason": _finish_reason(message) or ""},
        )

    # ------------------------------------------------------------------
    def _translate(self, exc: Exception) -> Exception:
        """Map whatever the vendor SDK raised onto our own errors.

        By status code rather than exception class: this file does not know
        which SDK is underneath, and the codes mean the same at all three.
        """
        if isinstance(exc, LLMError):
            return exc

        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if status in (401, 403):
            return LLMError(f"{self.provider} rejected the API key")
        if status == 404:
            # Model ids change often enough that guessing one is a real risk.
            return LLMError(
                f"Model {self.model!r} is not available to this key. "
                f"Set it in .env to one your key can use."
            )
        if status == 429:
            return LLMError(f"Rate limited by {self.provider}; try again shortly")
        if isinstance(status, int) and status >= 500:
            return LLMError(f"{self.provider} is unavailable right now: {exc}")
        if isinstance(status, int):
            return LLMError(f"{self.provider} API error {status}: {exc}")

        if isinstance(exc, ImportError):
            # init_chat_model imports its integration package lazily.
            return LLMError(f"The LangChain package for {self.provider} is not installed: {exc}")

        return LLMError(f"Unexpected error calling {self.provider}: {exc}")


# ----------------------------------------------------------------------
def _messages(prompt: str, system: str = "", image: bytes | None = None) -> list[BaseMessage]:
    """The prompt as LangChain messages, with the picture first if there is one.

    A model that reads the question before looking tends to answer from the
    text and treat the picture as decoration.
    """
    content: str | list[dict[str, Any]] = prompt
    if image:
        content = [
            {
                "type": "image",
                "base64": base64.b64encode(image).decode("ascii"),
                "mime_type": "image/png",
            },
            {"type": "text", "text": prompt},
        ]

    messages: list[BaseMessage] = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=content))
    return messages


def _text_of(message: BaseMessage) -> str:
    """The text of a reply, with thinking and tool blocks left out."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _finish_reason(message: BaseMessage) -> str | None:
    """Why the model stopped, whichever key this provider files it under."""
    metadata = getattr(message, "response_metadata", None) or {}
    reason = metadata.get("finish_reason") or metadata.get("stop_reason")
    return str(reason) if reason else None


def _token_split(message: BaseMessage) -> str:
    """" — 8369 spent thinking, 7482 on the answer", or empty when unknown."""
    usage = getattr(message, "usage_metadata", None) or {}
    answer = usage.get("output_tokens", 0) or 0
    if not answer:
        return ""

    thoughts = (usage.get("output_token_details") or {}).get("reasoning", 0) or 0
    return f" - {thoughts} spent thinking, {answer - thoughts} on the answer"
