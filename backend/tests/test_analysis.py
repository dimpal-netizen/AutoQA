"""Failure analysis. No network.

The interesting tests are the guards. An analysis is advice someone acts on,
so a garbled response must degrade into something harmless rather than into
confident nonsense pointing at the wrong culprit.
"""

from dataclasses import dataclass, field

import pytest

from app.ai.analyser import analyse, category_of, confidence_of, severity_of
from app.ai.client import LLMError
from app.ai.schemas import FailureAnalysis
from app.models.enums import Browser, FailureCategory, ResultStatus, Severity

from tests.test_ai import FakeLLM


@dataclass
class FakeStep:
    sequence: int
    description: str
    input_data: str | None = None
    expected_result: str | None = None


@dataclass
class FakeResult:
    id: int = 1
    case_name: str = "Login is rejected with a wrong password"
    browser: Browser = Browser.CHROMIUM
    status: ResultStatus = ResultStatus.FAILED
    failed_step: int | None = 3
    error_message: str | None = "AssertionError: Locator expected to be visible"
    stack_trace: str | None = "tests/test_login.py:20: in test_login"
    test_case: object | None = None
    artifacts: list = field(default_factory=list)


def good() -> FailureAnalysis:
    return FailureAnalysis(
        root_cause="The email field moved, so the placeholder no longer matches.",
        suggested_fix="Point the locator at #email instead of the placeholder.",
        category="selector_broken",
        severity="medium",
        priority="high",
        confidence=0.8,
        is_product_bug=False,
    )


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
def test_a_failure_is_explained():
    outcome = analyse(FakeResult(), client=FakeLLM(good()))

    assert outcome.ok
    assert outcome.analysis.category == "selector_broken"
    assert outcome.analysis.is_product_bug is False


def test_the_other_browsers_are_part_of_the_prompt():
    """"Passes in Chrome, fails in WebKit" is the strongest signal there is."""
    client = FakeLLM(good())
    siblings = [
        FakeResult(id=1),
        FakeResult(id=2, browser=Browser.WEBKIT, status=ResultStatus.PASSED,
                   error_message=None),
    ]

    analyse(FakeResult(id=1), siblings=siblings, client=client)

    assert "webkit: passed" in client.calls[0]


def test_the_tests_own_steps_are_part_of_the_prompt():
    """Without them the model is guessing at what the test was trying to do."""
    client = FakeLLM(good())
    steps = [FakeStep(0, "Open the login page"), FakeStep(1, "Type the email")]

    analyse(FakeResult(), steps=steps, client=client)

    assert "Type the email" in client.calls[0]


def test_a_single_browser_run_says_so_rather_than_implying_agreement():
    client = FakeLLM(good())
    analyse(FakeResult(), siblings=[FakeResult(id=1)], client=client)

    assert "only ran in one browser" in client.calls[0]


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", [ResultStatus.PASSED, ResultStatus.SKIPPED])
def test_a_test_that_did_not_fail_is_not_analysed(status):
    outcome = analyse(FakeResult(status=status), client=FakeLLM(good()))

    assert not outcome.ok
    assert "Only failed tests" in outcome.skipped


def test_no_provider_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr("app.ai.analyser.ai_available", lambda: False)

    outcome = analyse(FakeResult())

    assert not outcome.ok and "needs an AI provider" in outcome.skipped


def test_a_provider_failure_does_not_raise():
    outcome = analyse(FakeResult(), client=FakeLLM(error=LLMError("API is down")))

    assert not outcome.ok and "API is down" in outcome.skipped


def test_a_huge_traceback_is_trimmed():
    """Playwright tracebacks run to pages; the prompt has to stay affordable."""
    client = FakeLLM(good())
    analyse(FakeResult(stack_trace="x" * 50_000), client=client)

    assert len(client.calls[0]) < 20_000


# ---------------------------------------------------------------------------
# Coercion — a garbled answer must not become confident nonsense
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("application_bug", FailureCategory.APPLICATION_BUG),
        ("  Selector_Broken ", FailureCategory.SELECTOR_BROKEN),
        ("something the model invented", FailureCategory.TEST_BUG),
        ("", FailureCategory.TEST_BUG),
    ],
)
def test_an_unknown_category_blames_the_test_not_the_application(raw, expected):
    """The safe default never sends anyone to raise a bug on a guess."""
    assert category_of(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("critical", Severity.CRITICAL), ("HIGH", Severity.HIGH), ("nonsense", Severity.MEDIUM)],
)
def test_severity_falls_back_to_medium(raw, expected):
    assert severity_of(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.8, 0.8), (1.7, 1.0), (-2, 0.0), ("not a number", 0.0), (None, 0.0)],
)
def test_confidence_is_always_a_real_probability(raw, expected):
    """It is shown as a percentage, so 170% would make the whole panel absurd."""
    assert confidence_of(raw) == expected
