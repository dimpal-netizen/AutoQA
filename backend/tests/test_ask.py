"""Answering questions about a project's results. No network.

"Why did registration start failing this week?" is the question a tester
actually has. The information was always there — runs, results, analyses,
bugs — spread across four screens and joined up by hand.

The guards here are all about grounding. An answer nobody can check is a
rumour, and a confident wrong one costs an afternoon, so what matters is not
that the model says something plausible but that everything it was shown came
from rows this code selected.
"""

from dataclasses import dataclass, field
from datetime import datetime

import pytest

from app.ai.schemas import ResultsAnswer
from app.models.enums import Browser, ResultStatus, RunStatus, Severity
from app.services.ask_service import MAX_QUESTION, AskService
from app.services.exceptions import NotFound, ValidationError

from tests.test_ai import FakeLLM


# ---------------------------------------------------------------------------
# Stand-ins for the rows the service reads. Only the fields it touches.
# ---------------------------------------------------------------------------
@dataclass
class FakeProject:
    id: int = 1
    name: str = "Homeske"
    base_url: str = "https://homeske-dev.betaeserver.com/"


@dataclass
class FakeSuite:
    name: str = "Registration Page"
    cases: list = field(default_factory=lambda: [object(), object()])


@dataclass
class FakeRun:
    status: RunStatus = RunStatus.FAILED
    passed: int = 7
    failed: int = 9
    skipped: int = 0
    browsers: list = field(default_factory=lambda: ["chromium"])
    started_at: datetime = datetime(2026, 8, 4, 10, 0)
    finished_at: datetime = datetime(2026, 8, 4, 10, 12)


@dataclass
class FakeResult:
    id: int = 1
    run_id: int = 1
    test_case_id: int | None = 1
    failed_step: int | None = 7
    stack_trace: str | None = "tests/test_reg.py:20: in test_reg"
    case_name: str = "Register buyer with valid credentials"
    browser: Browser = Browser.CHROMIUM
    status: ResultStatus = ResultStatus.FAILED
    error_message: str | None = "AssertionError: Locator expected to be visible"


@dataclass
class FakeAnalysis:
    root_cause: str = "The mobile number is rejected for the selected country."
    suggested_fix: str = "Choose the country before typing the number."
    expected: str | None = "The one-time-password popup should have opened."
    actual: str | None = "The form stayed put with a red message."
    category: object = None
    is_product_bug: bool = True
    confidence: float = 0.7

    def __post_init__(self):
        from app.models.enums import FailureCategory

        self.category = self.category or FailureCategory.APPLICATION_BUG


@dataclass
class FakeBug:
    title: str = "Registration accepts an invalid mobile number"
    severity: Severity = Severity.CRITICAL
    status: object = None

    def __post_init__(self):
        from app.models.enums import BugStatus

        self.status = self.status or BugStatus.OPEN


def service(
    *,
    suites=None,
    runs=None,
    failures=None,
    analyses=None,
    bugs=None,
    project=None,
) -> AskService:
    """An AskService whose repositories are the rows a test wants shown."""
    found = analyses or {}
    ask = AskService.__new__(AskService)
    ask.projects = type("P", (), {"get": lambda _s, _i, _u: project or FakeProject()})()
    ask.suites = type(
        "S", (), {"list_for_projects": lambda _s, _i, limit=50: suites or []}
    )()
    ask.runs = type(
        "R", (), {"list_for_projects": lambda _s, _i, limit=12: runs or []}
    )()
    ask.results = type(
        "T",
        (),
        {"latest_failures_for_project": lambda _s, _p: failures or []},
    )()
    ask.analyses = type(
        "A", (), {"latest_for_result": lambda _s, rid: found.get(rid)}
    )()
    ask.bugs = type(
        "B", (), {"list_for_project": lambda _s, _p, limit=25: bugs or []}
    )()
    return ask


def answered(**overrides) -> ResultsAnswer:
    base = dict(
        answer="9 of 16 tests are failing, all on the registration form.",
        cites=["Register buyer with valid credentials"],
        confident=True,
    )
    base.update(overrides)
    return ResultsAnswer(**base)


# ---------------------------------------------------------------------------
# The answer is grounded in stored rows
# ---------------------------------------------------------------------------
def test_the_question_reaches_the_model(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service().ask(1, "Why did registration break this week?", user=object())

    assert "Why did registration break this week?" in client.calls[0]


def test_what_is_failing_now_is_part_of_the_prompt(monkeypatch):
    """Without it every answer is a guess about the past."""
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service(failures=[FakeResult()]).ask(1, "What is broken?", user=object())

    assert "Register buyer with valid credentials" in client.calls[0]


def test_a_diagnosis_travels_with_the_failure_it_explains(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service(
        failures=[FakeResult(id=5)], analyses={5: FakeAnalysis()}
    ).ask(1, "Why?", user=object())
    prompt = client.calls[0]

    assert "rejected for the selected country" in prompt
    assert "application bug" in prompt


def test_a_failure_nobody_analysed_says_so(monkeypatch):
    """"Not analysed" is a fact worth having — it is what to do next."""
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service(failures=[FakeResult()]).ask(1, "Why?", user=object())

    assert "not analysed" in client.calls[0]


def test_run_history_and_bugs_are_shown(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service(runs=[FakeRun()], bugs=[FakeBug()], suites=[FakeSuite()]).ask(
        1, "How are we doing?", user=object()
    )
    prompt = client.calls[0]

    assert "7 passed, 9 failed" in prompt
    assert "Registration accepts an invalid mobile number" in prompt
    assert "Registration Page" in prompt


def test_an_empty_project_says_so_rather_than_showing_nothing(monkeypatch):
    """A blank section reads as missing data; a sentence reads as an answer."""
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service().ask(1, "What is failing?", user=object())
    prompt = client.calls[0]

    assert "never been run" in prompt
    assert "nothing is currently failing" in prompt
    assert "no bug reports have been drafted" in prompt


def test_the_prompt_forbids_answering_from_outside_the_data(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service().ask(1, "What is failing?", user=object())
    prompt = client.calls[0]

    assert "Only from what is above" in prompt
    assert "Say when you are unsure" in prompt


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------
def test_the_answer_carries_what_it_rests_on(monkeypatch):
    """An answer nobody can check is a rumour."""
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ask_service.get_llm_client", lambda: FakeLLM(answered())
    )

    outcome = service().ask(1, "What is failing?", user=object())

    assert outcome.answer.startswith("9 of 16")
    assert outcome.cites == ["Register buyer with valid credentials"]
    assert outcome.confident is True


def test_low_confidence_survives_to_the_caller(monkeypatch):
    """Hiding it is how someone acts on an answer the data never supported."""
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ask_service.get_llm_client",
        lambda: FakeLLM(answered(confident=False)),
    )

    assert service().ask(1, "Is this flaky?", user=object()).confident is False


def test_blank_citations_are_dropped(monkeypatch):
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ask_service.get_llm_client",
        lambda: FakeLLM(answered(cites=["Real test", "", "   "])),
    )

    assert service().ask(1, "What?", user=object()).cites == ["Real test"]


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("empty", ["", "   ", "\n\t"])
def test_an_empty_question_is_refused(empty):
    with pytest.raises(ValidationError, match="Ask a question"):
        service().ask(1, empty, user=object())


def test_an_essay_is_refused_with_the_limit_named():
    with pytest.raises(ValidationError, match=str(MAX_QUESTION)):
        service().ask(1, "why " * 300, user=object())


def test_no_provider_is_explained_not_swallowed(monkeypatch):
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: False)

    with pytest.raises(ValidationError, match="needs an AI provider"):
        service().ask(1, "What is failing?", user=object())


def test_a_provider_failure_becomes_a_readable_error(monkeypatch):
    from app.ai.client import LLMError

    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ask_service.get_llm_client",
        lambda: FakeLLM(error=LLMError("Rate limited by Google")),
    )

    with pytest.raises(ValidationError, match="Rate limited"):
        service().ask(1, "What is failing?", user=object())


def test_an_empty_answer_is_not_passed_off_as_one(monkeypatch):
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr(
        "app.services.ask_service.get_llm_client",
        lambda: FakeLLM(answered(answer="   ")),
    )

    with pytest.raises(ValidationError, match="no usable answer"):
        service().ask(1, "What is failing?", user=object())


# ---------------------------------------------------------------------------
# Asking about one failure
#
# The project-wide box answers "what is failing, and since when". This is the
# other half, and where it sits is the feature: under the screenshot, at the
# bottom of the expanded row. By then you know what failed and you are looking
# at the picture of it, so the questions are specific ones — "is this the app
# or my test?" — and they only make sense with the evidence in view.
# ---------------------------------------------------------------------------
@dataclass
class FakeStep:
    description: str = "Click 'Create Account'"
    input_data: str | None = None
    expected_result: str | None = None
    sequence: int = 0


@dataclass
class FakeRunWithProject:
    id: int = 1
    project: object = field(default_factory=FakeProject)


def failure_service(
    *, result=None, analysis=None, steps=None, screenshot=None, siblings=None
) -> AskService:
    ask = AskService.__new__(AskService)
    ask.results = type(
        "T",
        (),
        {
            "get_full": lambda _s, _i: result,
            "list_for_run": lambda _s, _r: siblings or [],
        },
    )()
    ask.execution = type("E", (), {"get": lambda _s, _r, _u: FakeRunWithProject()})()
    ask.analyses = type("A", (), {"latest_for_result": lambda _s, _r: analysis})()
    ask.cases = type(
        "C", (), {"get_with_steps": lambda _s, _c: type("K", (), {"steps": steps or []})()}
    )()
    ask.db = object()
    return ask


def ask_failure(monkeypatch, client, **kwargs):
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)
    monkeypatch.setattr(
        "app.services.ask_service.screenshot_for",
        lambda _db, _r: kwargs.pop("screenshot", None),
    )
    service = failure_service(result=FakeResult(test_case_id=1), **kwargs)
    return service.ask_about_failure(1, "Is this the app or my test?", user=object())


def test_the_failures_own_evidence_reaches_the_model(monkeypatch):
    client = FakeLLM(answered())
    ask_failure(monkeypatch, client, steps=[FakeStep()])
    prompt = client.calls[0]

    assert "Is this the app or my test?" in prompt
    assert "Register buyer with valid credentials" in prompt
    assert "Locator expected to be visible" in prompt
    assert "Click 'Create Account'" in prompt


def test_the_screenshot_is_attached(monkeypatch):
    """One failure, one image — affordable here, and it is the evidence that
    most often contradicts the error text."""
    client = FakeLLM(answered())
    ask_failure(monkeypatch, client, screenshot=b"PNGDATA")

    assert client.image == b"PNGDATA"


def test_a_failure_with_no_screenshot_still_answers(monkeypatch):
    client = FakeLLM(answered())
    outcome = ask_failure(monkeypatch, client, screenshot=None)

    assert client.image is None
    assert outcome.answer


def test_an_existing_diagnosis_is_shown_so_the_answer_builds_on_it(monkeypatch):
    """They sit on the same row; two panels contradicting each other is worse
    than one."""
    client = FakeLLM(answered())
    ask_failure(monkeypatch, client, analysis=FakeAnalysis())

    assert "rejected for the selected country" in client.calls[0]


def test_no_diagnosis_says_so_rather_than_leaving_a_gap(monkeypatch):
    client = FakeLLM(answered())
    ask_failure(monkeypatch, client, analysis=None)

    assert "nobody has run an explanation" in client.calls[0]


def test_the_prompt_tells_it_to_believe_the_picture_over_the_error(monkeypatch):
    client = FakeLLM(answered())
    ask_failure(monkeypatch, client)

    assert "overrule the error text" in client.calls[0]


def test_the_prompt_asks_for_the_question_not_a_lecture(monkeypatch):
    """The explanation is already on the row above the box they typed into."""
    client = FakeLLM(answered())
    ask_failure(monkeypatch, client)

    assert "Answer the question that was asked" in client.calls[0]


def test_a_missing_result_is_a_not_found(monkeypatch):
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)

    with pytest.raises(NotFound):
        failure_service(result=None).ask_about_failure(9, "why?", user=object())


def test_an_empty_question_is_refused_here_too():
    with pytest.raises(ValidationError, match="Ask a question"):
        failure_service(result=FakeResult()).ask_about_failure(1, "  ", user=object())


# ---------------------------------------------------------------------------
# More than one question
#
# It answered one and forgot it. Every question had to be asked in full, which
# makes the box a search engine rather than a conversation — "and if that is
# fine?" meant nothing, so you asked the whole thing again.
# ---------------------------------------------------------------------------
@dataclass
class Turn:
    question: str
    answer: str


def test_a_follow_up_can_see_what_was_already_said(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)
    monkeypatch.setattr("app.services.ask_service.screenshot_for", lambda _d, _r: None)

    failure_service(result=FakeResult()).ask_about_failure(
        1,
        "And if that is fine?",
        user=object(),
        history=[Turn("Is this the app or my test?", "The application — the form kept the number.")],
    )
    prompt = client.calls[0]

    assert "Is this the app or my test?" in prompt
    assert "the form kept the number" in prompt
    assert "And if that is fine?" in prompt


def test_the_first_question_says_it_is_the_first(monkeypatch):
    """An empty section reads as missing context; a sentence reads as a fact."""
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)
    monkeypatch.setattr("app.services.ask_service.screenshot_for", lambda _d, _r: None)

    failure_service(result=FakeResult()).ask_about_failure(1, "why?", user=object())

    assert "this is the first question" in client.calls[0]


def test_a_long_conversation_only_carries_the_recent_turns(monkeypatch):
    """Otherwise every question costs more than the one before it."""
    from app.services.ask_service import MAX_HISTORY, describe_conversation

    turns = [Turn(f"question {i}", f"answer {i}") for i in range(20)]
    shown = describe_conversation(turns)

    assert "question 19" in shown
    assert "question 0" not in shown
    assert shown.count("Q: ") == MAX_HISTORY


def test_the_project_box_carries_a_conversation_too(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)

    service().ask(
        1,
        "And which of those is worst?",
        user=object(),
        history=[Turn("What is failing?", "Nine tests, all on registration.")],
    )

    assert "Nine tests, all on registration." in client.calls[0]


def test_the_prompt_tells_it_not_to_repeat_itself(monkeypatch):
    client = FakeLLM(answered())
    monkeypatch.setattr("app.services.ask_service.ai_available", lambda: True)
    monkeypatch.setattr("app.services.ask_service.get_llm_client", lambda: client)
    monkeypatch.setattr("app.services.ask_service.screenshot_for", lambda _d, _r: None)

    failure_service(result=FakeResult()).ask_about_failure(1, "why?", user=object())

    assert "say the next thing" in client.calls[0]
