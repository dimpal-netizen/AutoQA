"""Google Gemini model, prices, and the two things only Gemini needs.

The call itself goes through app/ai/langchain_client.py. `_salvage` keeps the
finished items out of an answer cut off mid-JSON; `list_models` turns the most
likely first-run failure — a stale model id — into an answer.
"""

from __future__ import annotations

from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.ai.client import LLMError
from app.core.config import settings

T = TypeVar("T", bound=BaseModel)

#: An alias, not a pinned version: Gemini model ids turn over fast, and a
#: hard-coded one silently becomes a 404 months later. Pin with GEMINI_MODEL.
DEFAULT_MODEL = "gemini-flash-latest"

#: Thinking is billed as output and counted against the same ceiling as the
#: answer, so unbounded it wins — it happens first — and the answer is truncated.
THINKING_BUDGET = 4000

#: Per million tokens, for the cost ledger. Matched on the model id because the
#: model is configurable; unknown falls back to the dearest tier, never under.
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


def _salvage(text: str, schema: type[T]) -> T | None:
    """Whatever whole items the model had written before it ran out of room.

    Only schemas that are a single list are salvageable, which is the shape that
    actually gets truncated. The last item is dropped whether or not it looks
    complete, because "looks complete" is exactly what a cut-off object does
    when the cut lands after a closing brace on a nested field.
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
    """Model ids this key can actually use."""
    key = api_key or settings.GEMINI_API_KEY
    if not key:
        raise LLMError("GEMINI_API_KEY is not set")

    # The client must outlive the iteration: `list()` returns a lazy pager, so
    # letting the client go out of scope fails mid-loop, not at the call site.
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
