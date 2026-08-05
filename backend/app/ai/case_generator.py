"""Invent the test cases a QA engineer would add around a recorded flow.

A recording gives one happy path. This asks the model the questions a thorough
tester would ask about it — what if the password is wrong, what if the field is
empty, what if someone pastes a script tag into it — and turns the sensible
answers into runnable tests.

Unlike `enhancer.py`, this feature genuinely needs a model. Inventing "a 320
character email address" from a successful login is judgement, not a lookup.
So when no key is configured this returns nothing and says why, rather than
pretending.

The safety property is unchanged though: the model returns *steps*, never code.
`synth.py` validates every step against locators that actually exist and emits
the Python itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.ai.client import LLMClient, LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import GeneratedCase, GeneratedCases
from app.codegen.converter import PageSpec, TestIR
from app.codegen.synth import SynthesisError, module_for, synthesise
from app.models.enums import CaseCategory, CasePriority

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior QA engineer writing test cases for a web application. "
    "You only ever reference elements you have been shown. You never suggest a "
    "test that destroys data, sends mail, or makes a payment."
)

DEFAULT_COUNT = 12
MAX_COUNT = 25


@dataclass
class SynthesisedCase:
    """One accepted case: what to store, and the IR to render."""

    ir: TestIR
    name: str
    description: str
    category: CaseCategory
    priority: CasePriority


@dataclass
class GenerationOutcome:
    cases: list[SynthesisedCase] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    skipped: str | None = None
    cost_usd: float = 0.0
    tokens: int = 0
    model: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.cases)


def generate_cases(
    recorded: TestIR,
    *,
    count: int = DEFAULT_COUNT,
    client: LLMClient | None = None,
    taken_modules: set[str] | None = None,
) -> GenerationOutcome:
    """Ask for `count` extra cases around `recorded`. Never raises."""
    if not recorded.pages:
        return GenerationOutcome(
            skipped=(
                "This recording only navigates — there are no elements to write "
                "test cases against."
            )
        )

    if client is None:
        if not ai_available():
            return GenerationOutcome(
                skipped=(
                    "Test case generation needs an AI provider. Add a key to .env "
                    "and restart the API."
                )
            )
        try:
            client = get_llm_client()
        except LLMError as exc:
            return GenerationOutcome(skipped=str(exc))

    count = max(1, min(count, MAX_COUNT))

    try:
        response = client.complete_model(
            load_prompt(
                "generate_cases",
                suite_name=recorded.suite_name,
                start_url=recorded.start_url,
                pages=describe_pages(recorded.pages),
                steps=describe_steps(recorded),
                target_count=count,
            ),
            GeneratedCases,
            system=SYSTEM,
            # Room for the answer with the thinking budget alongside it. The
            # answer for twelve cases measured 7482 tokens, so this is headroom
            # for roughly double that plus everything the model thinks first —
            # the old 16000 had to cover both and left 149 tokens spare.
            max_tokens=32000,
        )
    except LLMError as exc:
        logger.warning("Case generation unavailable: %s", exc)
        return GenerationOutcome(skipped=str(exc))
    except Exception as exc:  # noqa: BLE001 - a provider bug must not 500 the request
        logger.exception("Case generation failed unexpectedly")
        return GenerationOutcome(skipped=f"unexpected error: {exc}")

    suggestion = response.parsed
    if not isinstance(suggestion, GeneratedCases) or not suggestion.cases:
        return GenerationOutcome(skipped="the model returned no usable cases")

    outcome = GenerationOutcome(
        cost_usd=response.cost_usd,
        tokens=response.input_tokens + response.output_tokens,
        model=response.model,
    )

    taken = set(taken_modules or ()) | {recorded.module_name}
    for case in suggestion.cases:
        _accept(case, recorded, taken, outcome)

    logger.info(
        "Generated %d case(s), rejected %d (%d tokens, $%.4f)",
        len(outcome.cases),
        len(outcome.rejected),
        outcome.tokens,
        outcome.cost_usd,
    )
    return outcome


def _accept(
    case: GeneratedCase,
    recorded: TestIR,
    taken: set[str],
    outcome: GenerationOutcome,
) -> None:
    """Validate one case and keep it, or record why it was dropped."""
    name = " ".join(str(case.name or "").split())[:200]
    if not name:
        outcome.rejected.append("a case with no name")
        return

    module_name, function_name = module_for(name, taken)

    try:
        ir = synthesise(
            case,
            pages=recorded.pages,
            start_url=recorded.start_url,
            module_name=module_name,
            function_name=function_name,
        )
    except SynthesisError as exc:
        # Expected often enough to be routine: the model referenced an element
        # that does not exist, or wrote a test that asserts nothing.
        outcome.rejected.append(f"{name}: {exc}")
        return

    outcome.cases.append(
        SynthesisedCase(
            ir=ir,
            name=name,
            description=" ".join(str(case.description or "").split())[:500],
            category=_category(case.category),
            priority=_priority(case.priority),
        )
    )


def _category(value: str) -> CaseCategory:
    try:
        category = CaseCategory(str(value).strip().lower())
    except ValueError:
        return CaseCategory.POSITIVE
    # A generated case can never claim to be the recorded one.
    return CaseCategory.POSITIVE if category is CaseCategory.RECORDED else category


def _priority(value: str) -> CasePriority:
    try:
        return CasePriority(str(value).strip().lower())
    except ValueError:
        return CasePriority.MEDIUM


# ---------------------------------------------------------------------------
# What the model is shown
# ---------------------------------------------------------------------------
def describe_pages(pages: list[PageSpec]) -> str:
    """Pages and locators as text — the only elements a case may reference."""
    lines: list[str] = []
    for page in pages:
        lines.append(f"{page.class_name}  (url: {page.url})")
        for locator in page.locators:
            lines.append(f"  {page.class_name}.{locator.name}")
    return "\n".join(lines)


def describe_steps(ir: TestIR) -> str:
    lines: list[str] = []
    for step in ir.steps:
        line = f"{step.sequence}. {step.description}"
        if step.input_data:
            line += f"  (typed: {step.input_data[:60]!r})"
        lines.append(line)
    return "\n".join(lines)
