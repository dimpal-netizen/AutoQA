"""Anthropic model, prices and per-model request rules.

The call itself goes through app/ai/langchain_client.py; what lives here is only
what Anthropic needs to know.
"""

from __future__ import annotations

from app.core.config import settings

#: Per million tokens, for the cost ledger. Beside the model rather than as two
#: loose constants: change one and forget the other and every run records a
#: plausible cost that is wrong, which is worse than recording none.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

DEFAULT_MODEL = "claude-haiku-4-5"

#: Settable in .env, because the useful reason to change model is cost:
#: dropping to Sonnet for a week is a line in .env rather than an edit.
MODEL = (settings.CLAUDE_MODEL or "").strip() or DEFAULT_MODEL

#: Models that take adaptive thinking and an effort level. The rest reject both
#: outright, and sent regardless a model swap turns every AI feature into an
#: error nobody can read.
_TAKES_EFFORT = ("claude-opus-", "claude-sonnet-5", "claude-sonnet-4-6", "claude-fable-")


def _thinking_params() -> dict:
    """How to ask this model to think, in the words it accepts.

    These keys or none of them: a model without adaptive thinking has nothing
    worth downgrading to, and answers these structured prompts well without it.
    """
    if any(MODEL.startswith(prefix) for prefix in _TAKES_EFFORT):
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "medium"},
        }
    return {}


#: Haiku 4.5 caps at 64K output; the others reach 128K. Asking for more than a
#: model allows is a 400, so this is a ceiling rather than a preference.
_MAX_OUTPUT = 64_000 if MODEL.startswith("claude-haiku-") else 128_000
