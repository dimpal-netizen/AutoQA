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
from app.ai.schemas import FailureAnalysis, RunTriage
from app.models.enums import FailureCategory, ResultStatus, Severity

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are a senior QA engineer triaging failed automated tests. You "
    "distinguish carefully between a broken application and a broken test, and "
    "you say when the evidence is thin rather than guessing confidently."
)

MAX_TRACE = 4000

#: Shorter per failure than `MAX_TRACE`, because a triage carries one of these
#: for every red test in the run. Sixteen full tracebacks is a prompt that costs
#: more than the sixteen separate calls it was meant to replace.
MAX_TRIAGE_TRACE = 1200


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
                case_description=describe_case(result),
                browser=result.browser.value,
                base_url=base_url or "unknown",
                steps=describe_steps(steps),
                status=result.status.value,
                failed_step=(
                    result.failed_step if result.failed_step is not None else "unknown"
                ),
                error_message=result.error_message or "(none recorded)",
                stack_trace=(result.stack_trace or "(none recorded)")[:MAX_TRACE],
                cross_browser=describe_siblings(result, siblings),
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


@dataclass
class TriageOutcome:
    """One call's worth of triage over a whole run."""

    triage: RunTriage | None = None
    skipped: str | None = None
    provider: str = ""
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return self.triage is not None


def triage_run(
    failures: list,
    *,
    steps_by_result: dict,
    suite_name: str = "",
    base_url: str | None = None,
    passed: int = 0,
    finished_at: str = "",
    client: LLMClient | None = None,
) -> TriageOutcome:
    """Explain every failure in a run in one call. Never raises.

    One call rather than one per failure, for two reasons that both matter.

    It is cheaper by the number of failures — sixteen red tests cost sixteen
    requests, which on a free-tier key is the whole day's quota spent on one
    run. And it is *better*: failures come in families, and a model that sees
    all sixteen can say "these six are one problem", which no analysis looking
    at a single failure can ever work out. "16 failed" and "16 failed, 3 causes"
    lead to completely different days.

    The trade is the screenshot. Sixteen images in one request is neither
    affordable nor reliable, so this works from text and says so in the prompt,
    with confidence lowered to match. `analyse()` remains the deep look at one
    failure, picture and all.
    """
    if not failures:
        return TriageOutcome(skipped="Nothing failed in this run.")

    if client is None:
        if not ai_available():
            return TriageOutcome(
                skipped=(
                    "Failure analysis needs an AI provider. Add a key to .env "
                    "and restart the API."
                )
            )
        try:
            client = get_llm_client()
        except LLMError as exc:
            return TriageOutcome(skipped=str(exc))

    try:
        response = client.complete_model(
            load_prompt(
                "run_triage",
                base_url=base_url or "unknown",
                suite_name=suite_name or "(unnamed)",
                finished_at=finished_at or "unknown",
                passed=passed,
                failed=len(failures),
                count=len(failures),
                failures=describe_failures(failures, steps_by_result),
            ),
            RunTriage,
            system=SYSTEM,
            # Scales with the number of failures: the answer carries a full
            # explanation each, and a truncated response is paid for and thrown
            # away. Capped so one enormous run cannot ask for a fortune.
            max_tokens=min(64000, 6000 + 2200 * len(failures)),
        )
    except LLMError as exc:
        logger.warning("Run triage unavailable: %s", exc)
        return TriageOutcome(skipped=str(exc))
    except Exception as exc:  # noqa: BLE001 - a provider bug must not 500 the request
        logger.exception("Run triage failed unexpectedly")
        return TriageOutcome(skipped=f"unexpected error: {exc}")

    parsed = response.parsed
    if not isinstance(parsed, RunTriage):
        return TriageOutcome(skipped="the model returned no usable triage")

    return TriageOutcome(
        triage=parsed,
        provider=client.provider,
        model=response.model or client.model,
        tokens=response.input_tokens + response.output_tokens,
        cost_usd=response.cost_usd,
    )


def describe_failures(failures: list, steps_by_result: dict) -> str:
    """Every failure, numbered, with the evidence for it.

    Numbered because the answer refers back by number. Test names repeat across
    browsers, and matching an explanation to a failure on prose the model
    retyped is how one ends up filed against the wrong row.
    """
    blocks: list[str] = []
    for number, result in enumerate(failures, 1):
        steps = steps_by_result.get(result.id) or []
        blocks.append(
            "\n".join(
                [
                    f"--- Failure {number} ---",
                    f"Test: {result.case_name}",
                    f"Browser: {result.browser.value}",
                    f"Status: {result.status.value}",
                    f"Failed at step: "
                    f"{result.failed_step if result.failed_step is not None else 'unknown'}",
                    f"Error: {result.error_message or '(none recorded)'}",
                    "Steps:",
                    describe_steps(steps),
                    "Traceback:",
                    (result.stack_trace or "(none recorded)")[:MAX_TRIAGE_TRACE],
                ]
            )
        )
    return "\n\n".join(blocks)


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
def describe_case(result) -> str:
    case = getattr(result, "test_case", None)
    description = getattr(case, "description", None)
    return description or "(no description recorded)"


def describe_steps(steps) -> str:
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


def describe_siblings(result, siblings) -> str:
    others = [s for s in siblings if s.id != result.id]
    if not others:
        return "This test only ran in one browser, so there is nothing to compare."

    lines = [
        f"- {s.browser.value}: {s.status.value}"
        + (f" ({s.error_message[:120]})" if s.error_message else "")
        for s in others
    ]
    return "\n".join(lines)
