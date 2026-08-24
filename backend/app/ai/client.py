"""One interface, two providers.

Every AI feature depends on this abstraction, never on a vendor SDK, so
switching provider is a one-line change in .env rather than an edit across the
codebase. It also lets the whole test suite run against a fake with no network.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

T = TypeVar("T", bound=BaseModel)

#: Sampling is turned off for every call this app makes.
#:
#: A model asked the same question twice gives two different answers, which is
#: usually a feature and here is the bug. Regenerating a suite from an unchanged
#: recording produced a different set of tests each time: a case that passed on
#: Monday came back on Tuesday as a different test wearing the same name, and
#: went red against an application nobody had touched. The mirror of it was
#: quieter and worse — a case failing because it had found a real bug came back
#: weaker and went green.
#:
#: Nothing here wants a creative answer. Inventing test cases, explaining a
#: failure, naming a function: each has a best answer for its input, and the
#: same input should reach it every time. A verdict that moves on its own is not
#: a verdict.
TEMPERATURE = 0.0

#: Fixed, so temperature zero has something stable to be deterministic *about*.
#: Any constant would do; this one is arbitrary and must simply never change,
#: because changing it reshuffles every suite in the product at once.
SEED = 20260731


class LLMError(Exception):
    """The model could not be reached, or refused."""


class LLMRefusal(LLMError):
    """The provider's safety classifiers declined the request.

    A separate type because the caller's response differs: a refusal will not
    succeed on retry with the same input, unlike a timeout.
    """


@dataclass
class LLMResponse:
    """A completion plus what it cost, so spend is auditable per call."""

    text: str
    parsed: BaseModel | None = None
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """What the rest of the app is allowed to know about an LLM."""

    provider: str = "unknown"
    model: str = "unknown"

    @abstractmethod
    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 8000) -> LLMResponse:
        """Free-form text completion."""

    @abstractmethod
    def complete_model(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str = "",
        max_tokens: int = 8000,
        image: bytes | None = None,
    ) -> LLMResponse:
        """Completion validated against a Pydantic model.

        `response.parsed` is an instance of `schema`. Used everywhere the output
        feeds code rather than a human — a free-text answer we then regex would
        be the fragile version of this.

        `image` is a PNG to look at alongside the prompt. Optional, and a
        provider that cannot see is free to ignore it: an analysis reasoning
        from the traceback alone is the behaviour we already had, not a
        failure. It exists because a failure analysis reading only the error
        text said "the application is failing to complete the login process"
        while the screenshot plainly showed the user signed in.
        """


def load_prompt(name: str, **values: Any) -> str:
    """Read a prompt template and fill in its placeholders.

    Prompts are plain text files rather than string literals so they can be
    edited and diffed without touching Python.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    try:
        template = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LLMError(f"Prompt template '{name}' not found at {path}") from exc

    try:
        return template.format(**values)
    except KeyError as exc:
        raise LLMError(f"Prompt '{name}' expects a value for {exc}") from exc


def get_llm_client() -> LLMClient:
    """Build the configured provider. Raises if it isn't usable.

    Built through LangChain, so which model runs is a line in .env rather than
    a code path: see app/ai/langchain_client.py.
    """
    from app.ai.langchain_client import LangChainClient

    return LangChainClient(settings.LLM_PROVIDER)


# Which setting holds the key for each provider. One mapping so adding a
# provider cannot leave `ai_available()` silently answering for the wrong one.
_KEY_FOR: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def ai_available() -> bool:
    """Whether AI features can run at all.

    Callers use this to skip enhancement rather than fail: generated code must
    still be produced when no API key is configured.
    """
    setting = _KEY_FOR.get(settings.LLM_PROVIDER.strip().lower())
    return bool(setting and getattr(settings, setting, ""))
