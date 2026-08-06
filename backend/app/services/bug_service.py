"""Drafting bug reports from failures.

The gap this closes: an analysis explains a failure to someone looking at
AutoQA. A bug report explains it to a developer who never will. Those need
different writing — reproduction steps a person can follow by hand, with the
actual values, starting from a URL.

Drafts start as DRAFT and stay there until someone opens them. An AI-written
ticket appearing in a backlog that nobody reviewed is how a team learns to
ignore the backlog.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.analyser import severity_of
from app.ai.client import LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import DraftedBug
from app.models.bug_report import BugReport
from app.models.enums import BugStatus, ResultStatus, Severity
from app.models.user import User
from app.reports.bugs import BugRow, build_bug_workbook
from app.repositories.analysis_repo import AnalysisRepository
from app.repositories.base import BaseRepository
from app.repositories.test_case_repo import TestCaseRepository
from app.repositories.test_run_repo import TestResultRepository
from app.services.exceptions import NotFound, ValidationError
from app.services.execution_service import ExecutionService

logger = logging.getLogger(__name__)

SYSTEM = (
    "You write bug reports a developer can act on without opening the test "
    "tool. You report only what the evidence shows, and you say when a failure "
    "looks like a test problem rather than an application one."
)

MAX_STEPS = 20
MAX_TRACE = 3000

#: A ceiling on one export. High enough that no real project reaches it, low
#: enough that a runaway table cannot build a workbook that never finishes.
MAX_EXPORT = 2000


class BugRepository(BaseRepository[BugReport]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, BugReport)

    def for_result(self, result_id: int) -> BugReport | None:
        statement = (
            select(BugReport)
            .where(BugReport.result_id == result_id)
            .order_by(BugReport.id.desc())
            .limit(1)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_project(self, project_id: int, skip: int = 0, limit: int = 100):
        statement = (
            select(BugReport)
            .where(BugReport.project_id == project_id)
            .order_by(BugReport.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())


class BugService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.bugs = BugRepository(db)
        self.results = TestResultRepository(db)
        self.analyses = AnalysisRepository(db)
        self.cases = TestCaseRepository(db)
        self.execution = ExecutionService(db)

    # ------------------------------------------------------------------
    def draft(self, result_id: int, user: User) -> BugReport:
        """Write a bug report for one failure."""
        result = self.results.get_full(result_id)
        if result is None:
            raise NotFound(f"Result {result_id} not found")

        run = self.execution.get(result.run_id, user)  # authorises

        if result.status not in (ResultStatus.FAILED, ResultStatus.ERROR):
            raise ValidationError(
                f"This test {result.status.value}. Only failures need a bug report."
            )

        if not ai_available():
            raise ValidationError(
                "Drafting a bug report needs an AI provider. Add a key to .env "
                "and restart the API."
            )

        analysis = self.analyses.latest_for_result(result_id)
        steps = self._steps_for(result)

        try:
            client = get_llm_client()
            response = client.complete_model(
                load_prompt(
                    "bug_report",
                    case_name=result.case_name,
                    browser=result.browser.value,
                    base_url=(run.project.base_url if run.project else "unknown"),
                    steps=self._describe_steps(steps),
                    failed_step=(
                        result.failed_step if result.failed_step is not None else "unknown"
                    ),
                    error_message=result.error_message or "(none recorded)",
                    stack_trace=(result.stack_trace or "(none recorded)")[:MAX_TRACE],
                    analysis=self._describe_analysis(analysis),
                ),
                DraftedBug,
                system=SYSTEM,
                # Reasoning models spend thinking tokens from the same budget
                # as the answer; too small and the JSON is cut off mid-report.
                max_tokens=12000,
            )
        except LLMError as exc:
            raise ValidationError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bug drafting failed unexpectedly")
            raise ValidationError(f"Could not draft a bug report: {exc}") from exc

        drafted = response.parsed
        if not isinstance(drafted, DraftedBug):
            raise ValidationError("The model returned no usable bug report.")

        bug = self.bugs.create(
            project_id=run.project_id,
            result_id=result.id,
            analysis_id=analysis.id if analysis else None,
            created_by_id=user.id,
            title=_line(drafted.title, 255) or f"{result.case_name} failed",
            description=_text(drafted.description),
            steps_to_reproduce=[
                _line(step, 500) for step in drafted.steps_to_reproduce[:MAX_STEPS] if step
            ],
            expected=_text(drafted.expected),
            actual=_text(drafted.actual),
            environment={
                "browser": result.browser.value,
                "url": run.project.base_url if run.project else None,
                "run_id": run.id,
                "test": result.case_name,
                "ran_at": run.started_at.isoformat() if run.started_at else None,
            },
            # The analysis already judged how bad this is, and it saw the same
            # evidence. Prefer it over a second opinion formed in isolation.
            severity=severity_of(analysis.severity.value if analysis else drafted.severity),
            priority=severity_of(analysis.priority.value if analysis else drafted.priority),
            status=BugStatus.DRAFT,
        )
        self.db.commit()
        return bug

    # ------------------------------------------------------------------
    def get(self, bug_id: int, user: User) -> BugReport:
        bug = self.bugs.get(bug_id)
        if bug is None:
            raise NotFound(f"Bug report {bug_id} not found")

        try:
            self.execution.codegen.recording_service.project_service.get(
                bug.project_id, user
            )
        except NotFound:
            raise NotFound(f"Bug report {bug_id} not found") from None
        return bug

    def for_result(self, result_id: int, user: User) -> BugReport | None:
        result = self.results.get_full(result_id)
        if result is None:
            raise NotFound(f"Result {result_id} not found")
        self.execution.get(result.run_id, user)  # authorises
        return self.bugs.for_result(result_id)

    def set_status(self, bug_id: int, status: BugStatus, user: User) -> BugReport:
        bug = self.get(bug_id, user)
        self.bugs.update(bug, status=status)
        self.db.commit()
        return bug

    # ------------------------------------------------------------------
    def list_for_project(self, project_id: int, user: User) -> list[BugReport]:
        """Every bug drafted against this project, newest first."""
        self.execution.codegen.recording_service.project_service.get(project_id, user)
        return self.bugs.list_for_project(project_id, limit=MAX_EXPORT)

    def export_all(self, project_id: int, user: User) -> tuple[bytes, str]:
        """Every bug in the project as one workbook, and what to call the file.

        Two sources, and the sheet does not distinguish between them because the
        reader does not care:

        - **Reports somebody drafted.** These carry written prose and a triage
          status, and are the better row wherever one exists.
        - **Failures nobody has got to yet.** Still bugs — they are red right
          now — so they are written from what the run already knows: the test,
          the error, its steps, and the analysis if one was run.

        The second half is the point. Requiring sixteen clicks on "Draft a bug
        report" before anyone can see their sixteen bugs makes the export a
        reward for filing rather than a view of the project, and the one thing
        a bug register must never do is leave out a bug.

        Only what is failing *now*. A test that was red in March and is green
        today is not a bug, and one red for nine runs running is one bug rather
        than nine.
        """
        project = self.execution.codegen.recording_service.project_service.get(
            project_id, user
        )

        drafted = self.bugs.list_for_project(project_id, limit=MAX_EXPORT)
        covered = {bug.result_id for bug in drafted if bug.result_id}
        failures = [
            result
            for result in self.results.latest_failures_for_project(project_id)
            if result.id not in covered
        ]

        rows = [_row_from_bug(bug) for bug in drafted]
        rows += self._rows_from_failures(failures)

        if not rows:
            raise ValidationError(
                "Nothing to report — no test in this project is currently "
                "failing. Run the suite first."
            )

        workbook = build_bug_workbook(rows[:MAX_EXPORT], project_name=project.name)
        stem = "".join(
            c if c.isalnum() else "-" for c in project.name.lower()
        ).strip("-") or "project"
        return workbook, f"{stem}-bug-report.xlsx"

    def _rows_from_failures(self, failures: list) -> list[BugRow]:
        """One row per failing test, not one per browser.

        A test red in Chrome and Firefox is one bug that affects two browsers,
        and a register that splits it in two makes a suite look twice as broken
        as it is. The browsers are named in their own column instead.
        """
        grouped: dict[int, list] = {}
        for result in failures:
            grouped.setdefault(result.test_case_id, []).append(result)

        rows: list[BugRow] = []
        for results in grouped.values():
            first = results[0]
            analysis = self.analyses.latest_for_result(first.id)
            rows.append(
                BugRow(
                    title=_undrafted_title(first, analysis),
                    severity=(
                        severity_of(analysis.severity.value)
                        if analysis
                        else Severity.MEDIUM
                    ),
                    priority=(
                        severity_of(analysis.priority.value)
                        if analysis
                        else Severity.MEDIUM
                    ),
                    # Not DRAFT: nobody has drafted it. It is open in the sense
                    # that matters — the test is red and nothing has been
                    # decided about it — and the Reviewed column says which.
                    status=BugStatus.OPEN,
                    case_name=first.case_name,
                    browsers=", ".join(sorted({r.browser.value for r in results})),
                    environment={"failed at step": first.failed_step}
                    if first.failed_step is not None
                    else {},
                    steps_to_reproduce=[
                        step.description for step in self._steps_for(first)
                    ],
                    expected=(
                        analysis.expected
                        if analysis and analysis.expected
                        else "The test's final check passes."
                    ),
                    actual=(
                        analysis.actual
                        if analysis and analysis.actual
                        else _text(first.error_message or "The test failed.")
                    ),
                    description=(
                        analysis.root_cause
                        if analysis
                        else "Not analysed yet. Open the failure in AutoQA and "
                        "choose “Explain this failure” for a diagnosis."
                    ),
                    reported_on=first.created_at,
                    drafted=False,
                )
            )
        return rows

    # ------------------------------------------------------------------
    def _steps_for(self, result) -> list:
        if result.test_case_id is None:
            return []
        case = self.cases.get_with_steps(result.test_case_id)
        return list(case.steps) if case else []

    def _describe_steps(self, steps) -> str:
        if not steps:
            return "(the test's steps were not recorded)"
        lines = []
        for step in steps:
            line = f"{step.sequence}. {step.description}"
            if getattr(step, "input_data", None):
                line += f"  (entered: {str(step.input_data)[:80]!r})"
            lines.append(line)
        return "\n".join(lines)

    def _describe_analysis(self, analysis) -> str:
        if analysis is None:
            return "(no analysis has been run on this failure)"
        return (
            f"Verdict: {'application bug' if analysis.is_product_bug else 'test problem'}\n"
            f"Category: {analysis.category.value}\n"
            f"Confidence: {analysis.confidence:.0%}\n"
            f"Root cause: {analysis.root_cause}\n"
            f"Suggested fix: {analysis.suggested_fix}"
        )


def _line(value: str, limit: int) -> str:
    """One line, no control characters — this ends up in a ticket title."""
    text = " ".join(str(value or "").split())
    return "".join(ch for ch in text if ch.isprintable())[:limit]


def _text(value: str) -> str:
    return str(value or "").strip()[:4000]


def _row_from_bug(bug: BugReport) -> BugRow:
    """A drafted report as a register row.

    Everything here was written when the report was drafted and copied off the
    run, so it still reads correctly after that run is deleted — which is why
    `case_name` falls back rather than following a relationship that may be
    gone.
    """
    environment = bug.environment if isinstance(bug.environment, dict) else {}
    return BugRow(
        title=bug.title,
        severity=bug.severity,
        priority=bug.priority,
        status=bug.status,
        case_name=getattr(bug.result, "case_name", "") if bug.result else "",
        browsers=str(environment.get("browser") or ""),
        environment=environment,
        steps_to_reproduce=list(bug.steps_to_reproduce or []),
        expected=bug.expected,
        actual=bug.actual,
        description=bug.description,
        reported_on=bug.created_at,
        drafted=True,
    )


def _undrafted_title(result, analysis) -> str:
    """A scannable line for a failure nobody has written up.

    The analysis names what went wrong in a person's words, which is exactly
    what a title wants. Without one the test's own name is the honest fallback:
    it says what should work, and that it is in this sheet says it does not.
    """
    if analysis and analysis.root_cause:
        return _line(analysis.root_cause, 255)
    return _line(f"{result.case_name} is failing", 255)
