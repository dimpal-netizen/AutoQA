"""AI polish for an already-working test.

The rule this file exists to enforce: **the model never writes code.** It is
shown the generated test as structured data and asked only for names and
sentences. Everything it returns is validated before being applied, and a bad
suggestion is dropped rather than trusted.

That is why AI is optional here. No key, no credit, API down, model refuses,
model returns nonsense — all of those end with the deterministic Phase 3 output
being saved unchanged. AI improves readability; it is never load-bearing.
"""

from __future__ import annotations

import keyword
import logging
import re
from dataclasses import dataclass, field

from app.ai.client import LLMClient, LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import CodeEnhancement
from app.codegen.converter import MAX_IDENT, TestIR, page_variables

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior QA automation engineer. You improve the readability of "
    "generated Playwright tests. You never invent behaviour that was not "
    "recorded."
)

# Attributes every page object already has; a locator cannot take these names.
RESERVED = {"page", "open", "url", "self"}

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

MAX_DESCRIPTION = 300
MAX_TITLE = 80


@dataclass
class EnhancementOutcome:
    """What the AI pass did, for logging and for the suite record."""

    applied: bool = False
    title: str | None = None
    description: str | None = None
    changes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens: int = 0
    model: str = ""
    skipped: str | None = None


def enhance(ir: TestIR, *, client: LLMClient | None = None) -> EnhancementOutcome:
    """Improve names and descriptions on `ir`, in place. Never raises."""
    if client is None:
        if not ai_available():
            return EnhancementOutcome(skipped="no LLM provider configured")
        try:
            client = get_llm_client()
        except LLMError as exc:
            return EnhancementOutcome(skipped=str(exc))

    try:
        response = client.complete_model(
            load_prompt(
                "enhance_code",
                suite_name=ir.suite_name,
                start_url=ir.start_url,
                pages=_describe_pages(ir),
                steps=_describe_steps(ir),
            ),
            CodeEnhancement,
            system=SYSTEM,
            max_tokens=4000,
        )
    except LLMError as exc:
        # Expected and survivable: the deterministic output still ships.
        logger.warning("AI enhancement unavailable: %s", exc)
        return EnhancementOutcome(skipped=str(exc))
    except Exception as exc:  # noqa: BLE001 - a provider bug must not lose the suite
        logger.exception("AI enhancement failed unexpectedly")
        return EnhancementOutcome(skipped=f"unexpected error: {exc}")

    suggestion = response.parsed
    if not isinstance(suggestion, CodeEnhancement):
        return EnhancementOutcome(skipped="model returned no usable suggestion")

    outcome = EnhancementOutcome(
        applied=True,
        cost_usd=response.cost_usd,
        tokens=response.input_tokens + response.output_tokens,
        model=response.model,
    )
    _apply(ir, suggestion, outcome)
    logger.info(
        "AI enhancement applied to %r: %s (%d tokens, $%.4f)",
        ir.suite_name,
        ", ".join(outcome.changes) or "no changes",
        outcome.tokens,
        outcome.cost_usd,
    )
    return outcome


# ---------------------------------------------------------------------------
# Applying — every suggestion is checked before it is used
# ---------------------------------------------------------------------------
def _apply(ir: TestIR, suggestion: CodeEnhancement, outcome: EnhancementOutcome) -> None:
    name = _clean_function_name(suggestion.function_name)
    if name and name != ir.function_name:
        ir.function_name = name
        outcome.changes.append(f"function -> {name}")
        # module_name is deliberately left alone: the folder a QA engineer has
        # open in VS Code should not shuffle its filenames on every regenerate.

    title = _clean_text(suggestion.title, MAX_TITLE)
    if title:
        ir.suite_name = title
        outcome.title = title
        outcome.changes.append("title")

    description = _clean_text(suggestion.description, MAX_DESCRIPTION)
    if description:
        outcome.description = description
        outcome.changes.append("description")

    renamed = _rename_locators(ir, suggestion.locator_names)
    if renamed:
        outcome.changes.append(f"{renamed} locator(s)")

    described = _describe_step_intent(ir, suggestion.step_descriptions)
    if described:
        outcome.changes.append(f"{described} step description(s)")


def _clean_function_name(value: str | None) -> str | None:
    name = (value or "").strip()
    if not name.startswith("test_") or len(name) > MAX_IDENT:
        return None
    if not IDENTIFIER.match(name) or keyword.iskeyword(name):
        return None
    return name


def _clean_text(value: str | None, limit: int) -> str | None:
    """Make model prose safe to drop into a docstring or a `#` comment.

    Both are places where the text is not quoted, so the sanitising matters:
    a newline escapes a comment, and a stray triple quote or a trailing
    backslash ends the docstring early. Collapsing whitespace handles the
    first; swapping the
    quote character and dropping backslashes handles the rest.
    """
    text = " ".join((value or "").split())
    text = text.replace("\\", "").replace('"', "'")
    text = "".join(ch for ch in text if ch.isprintable())
    if not text:
        return None
    return text[:limit].rstrip()


def _describe_step_intent(ir: TestIR, descriptions: dict[str, str]) -> int:
    """Replace step wording. Only steps that exist, only non-empty text."""
    by_sequence = {step.sequence: step for step in ir.steps}
    changed = 0
    for key, text in descriptions.items():
        try:
            step = by_sequence[int(key)]
        except (ValueError, KeyError):
            continue
        cleaned = _clean_text(text, MAX_DESCRIPTION)
        if cleaned and cleaned != step.description:
            step.description = cleaned
            changed += 1
    return changed


def _rename_locators(ir: TestIR, renames: dict[str, str]) -> int:
    """Rename page-object properties and every reference to them.

    A rename has to touch two places or the generated code stops compiling: the
    property on the page object, and the `page.locator_name` occurrences inside
    the test body. Doing both together is why this is worth validating so
    carefully.
    """
    variable_of = {class_name: variable for variable, class_name in page_variables(ir)}
    changed = 0

    for page in ir.pages:
        page_var = variable_of.get(page.class_name)
        if page_var is None:
            continue

        existing = {locator.name for locator in page.locators}
        mapping: dict[str, str] = {}

        for key, proposed in renames.items():
            class_name, _, old = key.partition(".")
            if class_name != page.class_name or old not in existing:
                continue

            new = (proposed or "").strip()
            if not IDENTIFIER.match(new) or len(new) > MAX_IDENT:
                continue
            if keyword.iskeyword(new) or new in RESERVED:
                continue
            # Would collide with another locator, or with a rename already
            # accepted this round. Two properties with one name is a silent
            # shadowing bug, so drop the suggestion instead.
            if new in existing or new in mapping.values() or new == old:
                continue

            mapping[old] = new
            existing.discard(old)
            existing.add(new)

        if not mapping:
            continue

        for locator in page.locators:
            if locator.name in mapping:
                locator.name = mapping[locator.name]
                changed += 1

        # One pass with an alternation, so a -> b and b -> c cannot chain.
        pattern = re.compile(
            rf"\b{re.escape(page_var)}\.({'|'.join(re.escape(k) for k in mapping)})\b"
        )
        for step in ir.steps:
            step.code = [
                pattern.sub(lambda m: f"{page_var}.{mapping[m.group(1)]}", line)
                for line in step.code
            ]
            if step.page_var == page_var and step.locator_name in mapping:
                step.locator_name = mapping[step.locator_name]

    return changed


# ---------------------------------------------------------------------------
# Describing — what the model is allowed to see
# ---------------------------------------------------------------------------
def _describe_pages(ir: TestIR) -> str:
    """Pages and their locators as text. No code, so none can come back."""
    if not ir.pages:
        return "(none - this test only navigates)"

    lines: list[str] = []
    for page in ir.pages:
        lines.append(f"{page.class_name} ({page.url})")
        for locator in page.locators:
            fragile = " [fragile selector]" if locator.fragile else ""
            lines.append(f"  - {locator.name}: found by {locator.strategy}{fragile}")
    return "\n".join(lines)


def _describe_steps(ir: TestIR) -> str:
    lines: list[str] = []
    for step in ir.steps:
        detail = f"{step.sequence}. [{step.action.value}] {step.description}"
        if step.input_data:
            detail += f" (data: {step.input_data[:80]!r})"
        if step.expected_result:
            detail += f" (expects: {step.expected_result[:80]})"
        lines.append(detail)
    return "\n".join(lines)
