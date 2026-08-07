"""Answering questions about a project's test results.

"Why did registration start failing this week?" is the question a tester
actually has, and until now nothing could answer it. The information was all
there — runs, results, analyses, bugs — spread across four screens and joined
up by hand.

This is deliberately not an agent. It does not decide what to look at, run
queries, or take actions. A bounded, readable summary of the project's recent
history is assembled here in Python, the question is asked once against it, and
the answer comes back with the names it rests on so the reader can go and check.
That ceiling is the feature: everything the model can say is grounded in rows
that were selected by code, which is the difference between an answer and a
plausible paragraph.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.analyser import (
    MAX_TRACE,
    describe_case,
    describe_siblings,
    describe_steps,
)
from app.ai.client import LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import ResultsAnswer
from app.core.config import settings
from app.models.enums import ArtifactType
from app.models.user import User
from app.repositories.analysis_repo import AnalysisRepository
from app.repositories.test_case_repo import TestCaseRepository, TestSuiteRepository
from app.repositories.test_run_repo import (
    ArtifactRepository,
    TestResultRepository,
    TestRunRepository,
)
from app.services.bug_service import BugRepository
from app.services.exceptions import NotFound, ValidationError
from app.services.execution_service import ExecutionService
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)

SYSTEM = (
    "You answer questions about automated test results. You answer only from "
    "the results you are given, you name the tests and runs you are drawing "
    "on, and you say when the data does not support an answer rather than "
    "guessing."
)

#: How much history to send. Enough for "this week" and "is this getting
#: worse", bounded so a project with a year of runs still asks one affordable
#: question. A larger window would also bury the recent runs that most
#: questions are actually about.
MAX_RUNS = 12
MAX_FAILURES = 40
MAX_BUGS = 25

#: A question, not an essay. The ceiling is here rather than in the schema so
#: the message can say what to do about it.
MAX_QUESTION = 500

#: A full-page screenshot runs to megabytes and is charged per image whatever it
#: shows. Above this the question is answered from the text instead.
MAX_SCREENSHOT_BYTES = 4 * 1024 * 1024

#: How many earlier exchanges a follow-up carries. Enough that "and if that is
#: fine?" works; bounded because every question would otherwise cost more than
#: the one before it, and a twenty-turn conversation about one failure has
#: stopped being about the failure.
MAX_HISTORY = 6


@dataclass
class AnswerOutcome:
    answer: str = ""
    cites: list[str] | None = None
    confident: bool = True
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0


class AskService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectService(db)
        self.suites = TestSuiteRepository(db)
        self.runs = TestRunRepository(db)
        self.results = TestResultRepository(db)
        self.analyses = AnalysisRepository(db)
        self.bugs = BugRepository(db)
        self.cases = TestCaseRepository(db)
        self.execution = ExecutionService(db)

    def ask(
        self, project_id: int, question: str, user: User, *, history: list = ()
    ) -> AnswerOutcome:
        """Answer one question about this project's results.

        `history` is what has already been asked and answered, so a follow-up
        like "and which of those is worst?" means something.
        """
        project = self.projects.get(project_id, user)  # authorises

        question = self._clean_question(question)

        if not ai_available():
            raise ValidationError(
                "Answering questions needs an AI provider. Add a key to .env "
                "and restart the API."
            )

        suites = self.suites.list_for_projects([project_id], limit=50)
        runs = self.runs.list_for_projects([project_id], limit=MAX_RUNS)

        try:
            client = get_llm_client()
            response = client.complete_model(
                load_prompt(
                    "ask_results",
                    question=question,
                    project_name=project.name,
                    base_url=project.base_url,
                    suites=self._describe_suites(suites),
                    runs=self._describe_runs(runs),
                    failures=self._describe_failures(project_id),
                    bugs=self._describe_bugs(project_id),
                    conversation=describe_conversation(history),
                ),
                ResultsAnswer,
                system=SYSTEM,
                max_tokens=8000,
            )
        except LLMError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a provider bug must not 500
            logger.exception("Answering a question failed unexpectedly")
            raise ValidationError(f"Could not answer that: {exc}") from exc

        return self._outcome(response, client)

    # ------------------------------------------------------------------
    def ask_about_failure(
        self, result_id: int, question: str, user: User, *, history: list = ()
    ) -> AnswerOutcome:
        """Answer one question about one failure, with its screenshot attached.

        The project-wide box answers "what is failing, and since when". This is
        the other half: a tester is looking at one red test, its error and the
        picture of the page, and wants to ask about *that* — "is this the app or
        my test?", "why did it stop there?", "what would I check first?".

        Asking it here rather than at the top of the page is what makes it
        usable. The evidence is on screen, so the question is specific, and the
        answer can point at the same screenshot the reader is looking at.

        `history` is what has already been asked and answered, so "and if that
        is fine?" means something. Without it every question started again from
        nothing, which makes the box a search engine rather than a conversation
        — you could ask one thing and then had to ask the next one in full.
        """
        question = self._clean_question(question)

        result = self.results.get_full(result_id)
        if result is None:
            raise NotFound(f"Result {result_id} not found")

        run = self.execution.get(result.run_id, user)  # authorises

        if not ai_available():
            raise ValidationError(
                "Answering questions needs an AI provider. Add a key to .env "
                "and restart the API."
            )

        analysis = self.analyses.latest_for_result(result_id)
        siblings = self.results.list_for_run(result.run_id)

        try:
            client = get_llm_client()
            response = client.complete_model(
                load_prompt(
                    "ask_failure",
                    question=question,
                    case_name=result.case_name,
                    case_description=describe_case(result),
                    browser=result.browser.value,
                    base_url=(run.project.base_url if run.project else "unknown"),
                    steps=describe_steps(self._steps_for(result)),
                    status=result.status.value,
                    failed_step=(
                        result.failed_step
                        if result.failed_step is not None
                        else "unknown"
                    ),
                    error_message=result.error_message or "(none recorded)",
                    stack_trace=(result.stack_trace or "(none recorded)")[:MAX_TRACE],
                    cross_browser=describe_siblings(result, siblings),
                    analysis=describe_analysis(analysis),
                    conversation=describe_conversation(history),
                ),
                ResultsAnswer,
                system=SYSTEM,
                max_tokens=8000,
                # One failure, one image — affordable here in a way it is not
                # for a whole-run triage, and it is the evidence that most often
                # contradicts the error text.
                image=screenshot_for(self.db, result),
            )
        except LLMError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a provider bug must not 500
            logger.exception("Answering a question about a failure failed")
            raise ValidationError(f"Could not answer that: {exc}") from exc

        return self._outcome(response, client)

    # ------------------------------------------------------------------
    def _clean_question(self, question: str) -> str:
        question = " ".join(str(question or "").split())
        if not question:
            raise ValidationError("Ask a question first.")
        if len(question) > MAX_QUESTION:
            raise ValidationError(
                f"That question is {len(question)} characters. Keep it under "
                f"{MAX_QUESTION} — shorter questions get sharper answers."
            )
        return question

    def _outcome(self, response, client) -> AnswerOutcome:
        parsed = response.parsed
        if not isinstance(parsed, ResultsAnswer) or not parsed.answer.strip():
            raise ValidationError("The model returned no usable answer.")

        return AnswerOutcome(
            answer=parsed.answer.strip(),
            cites=[c for c in (parsed.cites or []) if str(c).strip()][:12],
            confident=bool(parsed.confident),
            model=response.model or client.model,
            tokens=response.input_tokens + response.output_tokens,
            cost_usd=response.cost_usd,
        )

    def _steps_for(self, result) -> list:
        if result.test_case_id is None:
            return []
        case = self.cases.get_with_steps(result.test_case_id)
        return list(case.steps) if case else []

    # ------------------------------------------------------------------
    # What the model is shown. Bounded and pre-joined, so the answer can only
    # be about rows this code chose.
    # ------------------------------------------------------------------
    def _describe_suites(self, suites) -> str:
        if not suites:
            return "(nothing has been recorded for this project yet)"
        return "\n".join(
            f"- {suite.name}: {len(suite.cases)} test case(s)" for suite in suites
        )

    def _describe_runs(self, runs) -> str:
        if not runs:
            return "(this project has never been run)"

        lines = []
        for run in runs:
            when = run.finished_at or run.started_at
            lines.append(
                f"- {when.strftime('%d %b %Y %H:%M') if when else 'not finished'}"
                f" · {run.status.value}"
                f" · {run.passed} passed, {run.failed} failed, {run.skipped} skipped"
                f" · browsers: {', '.join(run.browsers) or 'unknown'}"
            )
        return "\n".join(lines)

    def _describe_failures(self, project_id: int) -> str:
        """What is red as of the newest run for each test, with any analysis."""
        failures = self.results.latest_failures_for_project(project_id)
        if not failures:
            return "(nothing is currently failing)"

        lines = []
        for result in failures[:MAX_FAILURES]:
            analysis = self.analyses.latest_for_result(result.id)
            line = (
                f"- {result.case_name} [{result.browser.value}]: "
                f"{(result.error_message or 'failed').splitlines()[0][:160]}"
            )
            if analysis:
                line += (
                    f"\n    diagnosis: {analysis.root_cause[:200]}"
                    f" (category {analysis.category.value},"
                    f" {'application bug' if analysis.is_product_bug else 'test problem'},"
                    f" {analysis.confidence:.0%} confident)"
                )
            else:
                line += "\n    diagnosis: not analysed"
            lines.append(line)

        if len(failures) > MAX_FAILURES:
            lines.append(f"- ... and {len(failures) - MAX_FAILURES} more")
        return "\n".join(lines)

    def _describe_bugs(self, project_id: int) -> str:
        bugs = self.bugs.list_for_project(project_id, limit=MAX_BUGS)
        if not bugs:
            return "(no bug reports have been drafted)"
        return "\n".join(
            f"- [{bug.severity.value}/{bug.status.value}] {bug.title}" for bug in bugs
        )


def describe_conversation(history) -> str:
    """What has already been asked and answered here.

    Only the last few exchanges. A conversation about one failure that has run
    to twenty turns has stopped being about the failure, and carrying all of it
    makes each question cost more than the one before it.
    """
    turns = list(history or [])[-MAX_HISTORY:]
    if not turns:
        return "(this is the first question about this failure)"

    return "\n\n".join(
        f"Q: {' '.join(str(getattr(turn, 'question', '')).split())}\n"
        f"A: {' '.join(str(getattr(turn, 'answer', '')).split())[:1200]}"
        for turn in turns
    )


def describe_analysis(analysis) -> str:
    """What was already worked out about this failure, if anything was.

    Shown so a follow-up question builds on the diagnosis rather than quietly
    contradicting it two panels apart — the analysis and this box sit on the
    same row.
    """
    if analysis is None:
        return "(nobody has run an explanation on this failure yet)"
    return (
        f"Verdict: {'application bug' if analysis.is_product_bug else 'test problem'}\n"
        f"Category: {analysis.category.value}\n"
        f"Confidence: {analysis.confidence:.0%}\n"
        f"Expected: {analysis.expected or '(not recorded)'}\n"
        f"Actual: {analysis.actual or '(not recorded)'}\n"
        f"Root cause: {analysis.root_cause}\n"
        f"Suggested fix: {analysis.suggested_fix}"
    )


def screenshot_for(db: Session, result) -> bytes | None:
    """The page as it looked when the test gave up.

    Never raises: a question answered from the error text alone is still worth
    having, and a missing file must not turn into a 500 on someone typing a
    question.
    """
    for artifact in ArtifactRepository(db).list_for_result(result.id):
        if artifact.type is not ArtifactType.SCREENSHOT:
            continue

        path = (settings.storage_dir / artifact.file_path).resolve()
        root = settings.storage_dir.resolve()
        # The stored path is data. Treating it as a filesystem instruction
        # without this check turns a database read into an arbitrary one.
        if not path.is_relative_to(root) or not path.is_file():
            continue
        if path.stat().st_size > MAX_SCREENSHOT_BYTES:
            continue

        try:
            return path.read_bytes()
        except OSError:
            logger.exception("Could not read %s", path)
    return None
