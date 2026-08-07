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
        expected="The 'Email' field should have been on the sign-in form.",
        actual="The form was there, but the email box was missing its label.",
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
# Expected against actual
#
# The report said what went wrong and what to do, and left the two facts a
# reader looks for first to be inferred from a sentence about the cause. Worse,
# the only statement of what happened was the raw assertion — "Locator expected
# to be hidden", which is neither of them and is not English.
# ---------------------------------------------------------------------------
def test_both_sides_of_the_mismatch_come_back():
    outcome = analyse(FakeResult(), client=FakeLLM(good()))

    assert outcome.analysis.expected
    assert outcome.analysis.actual
    assert outcome.analysis.expected != outcome.analysis.actual


def test_an_answer_missing_either_side_is_not_accepted():
    """Required, not optional. An analysis without them is the old one back."""
    import pydantic

    for missing in ("expected", "actual"):
        fields = {
            "expected": "The popup should have closed.",
            "actual": "The popup was still open.",
            "root_cause": "r", "suggested_fix": "s", "category": "test_bug",
            "severity": "low", "priority": "low", "confidence": 0.5,
            "is_product_bug": False,
        }
        del fields[missing]
        with pytest.raises(pydantic.ValidationError):
            FailureAnalysis(**fields)


def test_the_prompt_asks_for_them_in_a_persons_words():
    client = FakeLLM(good())
    analyse(FakeResult(), client=client)
    prompt = client.calls[0]

    assert "what was the test waiting to see" in prompt.lower()
    assert "what was on screen instead" in prompt.lower()
    # The pair is worthless if the model just negates one to make the other.
    assert "must genuinely disagree" in prompt


def test_the_prompt_still_forbids_the_language_of_a_traceback():
    client = FakeLLM(good())
    analyse(FakeResult(), client=client)

    assert "No Python, no Playwright" in client.calls[0]
    assert "snake_case" in client.calls[0]


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


# ---------------------------------------------------------------------------
# A whole run in one call
#
# It used to loop, one request per failure. Sixteen red tests meant sixteen
# requests — on a free-tier key, a whole day's quota on one run — and every
# explanation was written by a model that could see only its own failure.
#
# Seeing them together is what makes this worth doing rather than merely
# cheaper. Six tests that all fill the same form and all stop at the same check
# are one problem, and no per-failure analysis can work that out.
# ---------------------------------------------------------------------------
from app.ai.analyser import describe_failures, triage_run
from app.ai.schemas import RunTriage, TriagedFailure


def triaged(number: int, **overrides) -> TriagedFailure:
    base = dict(
        number=number,
        expected="The one-time-password popup should have opened.",
        actual="The form stayed put with a red message under Mobile Number.",
        root_cause="The number is rejected for the selected country.",
        suggested_fix="Choose the country before typing the number.",
        category="test_bug",
        severity="high",
        priority="high",
        confidence=0.6,
        is_product_bug=False,
        same_cause_as=[],
    )
    base.update(overrides)
    return TriagedFailure(**base)


def a_triage(**overrides) -> RunTriage:
    base = dict(
        summary="Six failures, all on the registration form, all one cause.",
        distinct_causes=1,
        failures=[triaged(1), triaged(2)],
    )
    base.update(overrides)
    return RunTriage(**base)


def test_one_call_covers_every_failure():
    """The whole point: sixteen failures must not cost sixteen requests."""
    client = FakeLLM(a_triage())
    failures = [FakeResult(id=1), FakeResult(id=2)]

    outcome = triage_run(failures, steps_by_result={}, client=client)

    assert outcome.ok
    assert len(client.calls) == 1
    assert len(outcome.triage.failures) == 2


def test_the_failures_are_numbered_so_answers_match_the_right_row():
    """Names repeat across browsers; matching on prose files it against the
    wrong failure."""
    text = describe_failures(
        [FakeResult(id=1), FakeResult(id=2, browser=Browser.WEBKIT)], {}
    )

    assert "--- Failure 1 ---" in text
    assert "--- Failure 2 ---" in text
    assert "webkit" in text


def test_the_prompt_asks_which_failures_share_a_cause():
    client = FakeLLM(a_triage())
    triage_run([FakeResult()], steps_by_result={}, client=client)
    prompt = client.calls[0]

    assert "same_cause_as" in prompt
    assert "distinct_causes" in prompt


def test_the_prompt_admits_it_cannot_see_the_screenshots():
    """The single-failure analysis gets one; sixteen is not affordable. The
    confidence has to reflect that rather than quietly not."""
    client = FakeLLM(a_triage())
    triage_run([FakeResult()], steps_by_result={}, client=client)

    assert "No screenshots are attached" in client.calls[0]


def test_a_run_with_nothing_red_is_not_sent_to_the_model():
    outcome = triage_run([], steps_by_result={}, client=FakeLLM(a_triage()))

    assert not outcome.ok
    assert "Nothing failed" in outcome.skipped


def test_a_provider_failure_does_not_raise():
    outcome = triage_run(
        [FakeResult()], steps_by_result={}, client=FakeLLM(error=LLMError("down"))
    )

    assert not outcome.ok and "down" in outcome.skipped


def test_the_token_budget_grows_with_the_number_of_failures():
    """One explanation each. A fixed ceiling truncates the answer and bins it."""
    small = FakeLLM(a_triage())
    triage_run([FakeResult()], steps_by_result={}, client=small)

    large = FakeLLM(a_triage())
    triage_run([FakeResult(id=i) for i in range(20)], steps_by_result={}, client=large)

    assert large.budgets[0] > small.budgets[0]


def test_the_traceback_per_failure_is_shorter_than_a_single_analysis():
    """Sixteen full tracebacks costs more than the calls it was replacing."""
    from app.ai.analyser import MAX_TRACE, MAX_TRIAGE_TRACE

    assert MAX_TRIAGE_TRACE < MAX_TRACE
