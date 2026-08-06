"""Explain a failed test.

Workflow 3. The question every red test raises is the same one — is the
application broken, or is my test? — and answering it by hand means reading a
traceback, remembering what the test was for, and checking whether the other
browsers agree. This does that reading.

Two limits worth stating rather than hiding:

- The model sees the error, the traceback, the test's own steps, how the other
  browsers fared, and the screenshot taken when the test gave up — when one was
  captured. It cannot see the network or the server logs, which is why the
  prompt forbids describing what "the server returned" unless the error says so.
- It can be wrong. `confidence` is stored and shown, and the prompt is explicit
  that a confident wrong answer is more expensive than an honest "not sure",
  because it sends someone to debug the wrong thing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai.client import LLMClient, LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import FailureAnalysis
from app.models.enums import FailureCategory, ResultStatus, Severity

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior QA engineer triaging failed automated tests. You "
    "distinguish carefully between a broken application and a broken test, and "
    "you say when the evidence is thin rather than guessing confidently."
)

MAX_TRACE = 4000


@dataclass
class AnalysisOutcome:
    analysis: FailureAnalysis | None = None
    skipped: str | None = None
    provider: str = ""
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return self.analysis is not None


def analyse(
    result,
    *,
    siblings: list = (),
    steps: list = (),
    base_url: str | None = None,
    screenshot: bytes | None = None,
    client: LLMClient | None = None,
) -> AnalysisOutcome:
    """Explain one failed result. Never raises.

    `siblings` are the same test's results in the other browsers — the single
    most useful piece of context there is. "Passes in Chrome, fails in WebKit"
    points at the application; failing everywhere usually points at the test.
    """
    if result.status not in (ResultStatus.FAILED, ResultStatus.ERROR):
        return AnalysisOutcome(skipped="Only failed tests can be analysed.")

    if client is None:
        if not ai_available():
            return AnalysisOutcome(
                skipped=(
                    "Failure analysis needs an AI provider. Add a key to .env "
                    "and restart the API."
                )
            )
        try:
            client = get_llm_client()
        except LLMError as exc:
            return AnalysisOutcome(skipped=str(exc))

    try:
        response = client.complete_model(
            load_prompt(
                "failure_analysis",
                case_name=result.case_name,
                case_description=_describe_case(result),
                browser=result.browser.value,
                base_url=base_url or "unknown",
                steps=_describe_steps(steps),
                status=result.status.value,
                failed_step=(
                    result.failed_step if result.failed_step is not None else "unknown"
                ),
                error_message=result.error_message or "(none recorded)",
                stack_trace=(result.stack_trace or "(none recorded)")[:MAX_TRACE],
                cross_browser=_describe_siblings(result, siblings),
            ),
            FailureAnalysis,
            system=SYSTEM,
            # Generous, because reasoning models spend "thinking" tokens out of
            # the same budget as the answer. At 4000 a third of these analyses
            # were truncated mid-JSON and thrown away after being paid for.
            max_tokens=12000,
            image=screenshot,
        )
    except LLMError as exc:
        logger.warning("Failure analysis unavailable: %s", exc)
        return AnalysisOutcome(skipped=str(exc))
    except Exception as exc:  # noqa: BLE001 - a provider bug must not 500 the request
        logger.exception("Failure analysis failed unexpectedly")
        return AnalysisOutcome(skipped=f"unexpected error: {exc}")

    parsed = response.parsed
    if not isinstance(parsed, FailureAnalysis):
        return AnalysisOutcome(skipped="the model returned no usable analysis")

    return AnalysisOutcome(
        analysis=parsed,
        provider=client.provider,
        model=response.model or client.model,
        tokens=response.input_tokens + response.output_tokens,
        cost_usd=response.cost_usd,
    )


def category_of(value: str) -> FailureCategory:
    try:
        return FailureCategory(str(value).strip().lower())
    except ValueError:
        # An unrecognised category is not a reason to lose the analysis, and
        # "the test is at fault" is the safer default: it does not send anyone
        # to raise a bug against the application on a guess.
        return FailureCategory.TEST_BUG


def severity_of(value: str) -> Severity:
    try:
        return Severity(str(value).strip().lower())
    except ValueError:
        return Severity.MEDIUM


def confidence_of(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def _describe_case(result) -> str:
    case = getattr(result, "test_case", None)
    description = getattr(case, "description", None)
    return description or "(no description recorded)"


def _describe_steps(steps) -> str:
    if not steps:
        return "(the test's steps were not recorded)"

    lines = []
    for step in steps:
        line = f"{step.sequence}. {step.description}"
        if getattr(step, "input_data", None):
            line += f"  (data: {str(step.input_data)[:60]!r})"
        if getattr(step, "expected_result", None):
            line += f"  (expects: {str(step.expected_result)[:60]})"
        lines.append(line)
    return "\n".join(lines)


def _describe_siblings(result, siblings) -> str:
    others = [s for s in siblings if s.id != result.id]
    if not others:
        return "This test only ran in one browser, so there is nothing to compare."

    lines = [
        f"- {s.browser.value}: {s.status.value}"
        + (f" ({s.error_message[:120]})" if s.error_message else "")
        for s in others
    ]
    return "\n".join(lines)
