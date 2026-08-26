"""Asking a model about the recorded values the rules could not place.

Deterministic first, and by a wide margin. `codegen/dataroles.py` decides every
value it has evidence for - a password is never an identity, a form that asks
for something twice is creating a record, an address that signs in needs the
account to already exist - and this is only ever asked about what is left over.
On most recordings that is nothing at all and no request is made.

Three rules keep it from being able to do harm.

It is only ever asked to *raise* confidence in a role the rules already reached
tentatively, or to leave it alone. It cannot invent a role for a value the rules
placed with evidence, and it cannot reach a value at all unless the rules
returned UNKNOWN or a low confidence for it.

It never sees the page. The fields below are what the recorder captured about
one input - what it is called, what type it is, what was typed - and the path of
the address it was on. No HTML, no DOM, no screenshot. If that does not answer
the question, the honest answer is UNKNOWN, and the prompt says so twice.

And it cannot make anything worse than not running. A failure, a timeout, a
missing key, an answer that does not parse: every one of them leaves the
deterministic decision exactly as it was. A suite generated with no model
configured is the same suite, with the ambiguous values replayed as recorded.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from app.ai.client import LLMClient, LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import ClassifiedFields
from app.codegen.dataroles import SUBSTITUTE_ABOVE, DataRole, Decision

logger = logging.getLogger(__name__)

SYSTEM = (
    "You classify test data. You are cautious: you answer UNKNOWN whenever the "
    "evidence given does not settle the question, and you never ask for more."
)

#: Below this the rules are guessing and a model may have something to add.
#: At or above it they had real evidence, and nothing here may touch the answer.
ASK_BELOW = SUBSTITUTE_ABOVE

#: A whole form's worth is one request. More than this and the recording is
#: large enough that the ambiguous fields are not the interesting part of it.
MAX_FIELDS = 12

_ROLES = {
    "UNIQUE": DataRole.UNIQUE,
    "EXISTING": DataRole.EXISTING,
    "STATIC": DataRole.STATIC,
    "UNKNOWN": DataRole.UNKNOWN,
}


def refine(
    actions: list[dict[str, Any]],
    decisions: dict[int, Decision],
    *,
    start_url: str,
    client: LLMClient | None = None,
) -> dict[int, Decision]:
    """Decisions with the uncertain ones reconsidered. Never raises.

    Returns a new mapping; the one passed in is not modified, so a caller that
    wants the deterministic answer still has it.
    """
    uncertain = [
        index
        for index, decision in decisions.items()
        if decision.confidence < ASK_BELOW
    ][:MAX_FIELDS]
    if not uncertain:
        return dict(decisions)

    if client is None:
        if not ai_available():
            return dict(decisions)
        try:
            client = get_llm_client()
        except LLMError as exc:
            logger.info("No data-role refinement: %s", exc)
            return dict(decisions)

    try:
        answer = client.complete_model(
            load_prompt(
                "classify_data",
                start_url=start_url,
                fields=_describe(actions, uncertain),
            ),
            ClassifiedFields,
            system=SYSTEM,
            max_tokens=1500,
        )
    except LLMError as exc:
        # Expected and survivable: the deterministic answer still ships.
        logger.warning("Data-role refinement unavailable: %s", exc)
        return dict(decisions)

    refined = dict(decisions)
    for field in getattr(answer.parsed, "fields", []) or []:
        position = int(getattr(field, "number", 0)) - 1
        if not 0 <= position < len(uncertain):
            continue
        index = uncertain[position]
        role = _ROLES.get(str(getattr(field, "role", "")).strip().upper())
        if role is None or role is DataRole.UNKNOWN:
            continue

        refined[index] = Decision(
            role=role,
            why=f"{str(getattr(field, 'why', '')).strip()[:160]} (judged, not measured)",
            confidence=min(float(getattr(field, "confidence", 0.0) or 0.0), 0.95),
        )
    return refined


def _describe(actions: list[dict[str, Any]], indexes: list[int]) -> str:
    """The fields, numbered, in as few words as answer the question."""
    lines = []
    for position, index in enumerate(indexes, start=1):
        action = actions[index]
        element = action.get("element") or {}
        attributes = element.get("attributes") or {}
        lines.append(
            f"{position}. label={element.get('accessible_name') or '?'!r} "
            f"name={attributes.get('name') or '?'!r} "
            f"type={element.get('input_type') or '?'!r} "
            f"autocomplete={attributes.get('autocomplete') or '-'!r} "
            f"typed={str((action.get('payload') or {}).get('value') or '')[:40]!r} "
            f"page={urlparse(str(action.get('url') or '')).path or '/'!r}"
        )
    return "\n".join(lines)
