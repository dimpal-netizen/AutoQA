"""Check the configured AI provider actually works.

    poetry run python scripts/check_ai.py

Answers the three questions a first run raises, in order: is a key configured,
does the provider accept it, and does structured output come back in the shape
the app expects. Everything downstream depends on the third one, so it is worth
proving before wondering why enhancement silently did nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field  # noqa: E402

from app.ai.client import LLMError, LLMRefusal, ai_available, get_llm_client  # noqa: E402
from app.core.config import settings  # noqa: E402


class Ping(BaseModel):
    """Deliberately tiny — this is a connectivity check, not a benchmark."""

    answer: str = Field(description="The word 'pong'")
    confident: bool = Field(description="Always true")


def main() -> int:
    provider = settings.LLM_PROVIDER.strip().lower()
    print(f"provider : {provider}")

    if not ai_available():
        print("\nNo API key configured for this provider.")
        print("Set the matching key in .env, then restart the API:")
        print("  claude -> ANTHROPIC_API_KEY")
        print("  openai -> OPENAI_API_KEY")
        print("  gemini -> GEMINI_API_KEY")
        print("\nAutoQA still records, generates and runs tests without one.")
        return 1

    try:
        client = get_llm_client()
    except LLMError as exc:
        print(f"\nCould not build the client: {exc}")
        return 1

    print(f"model    : {client.model}")

    # Listing first: a wrong model id is the most likely failure, and knowing
    # what the key *can* use turns a 404 into an answer.
    if provider == "gemini":
        try:
            from app.ai.gemini import list_models

            available = list_models()
            print(f"available: {len(available)} models")
            for name in available:
                if "gemini" in name and "embedding" not in name:
                    print(f"           {name}")
        except LLMError as exc:
            print(f"available: could not list ({exc})")

    print("\nSending a test prompt...")
    try:
        response = client.complete_model(
            "Reply with the word 'pong'.", Ping, max_tokens=2000
        )
    except LLMRefusal as exc:
        print(f"REFUSED: {exc}")
        return 1
    except LLMError as exc:
        print(f"FAILED: {exc}")
        return 1

    parsed = response.parsed
    print(f"reply    : {parsed.answer!r} (confident={parsed.confident})")
    print(f"tokens   : {response.input_tokens} in, {response.output_tokens} out")
    print(f"cost     : ${response.cost_usd:.6f}")
    print(f"latency  : {response.latency_ms} ms")
    print("\nWorking. Structured output came back in the right shape.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
