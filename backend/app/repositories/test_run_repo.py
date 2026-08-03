"""Queries for runs, results, and artifacts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import Browser, ResultStatus, RunStatus
from app.models.test_run import ExecutionArtifact, TestResult, TestRun
from app.repositories.base import BaseRepository


class TestRunRepository(BaseRepository[TestRun]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TestRun)

    def get_full(self, run_id: int) -> TestRun | None:
        """A run with its results and their artifacts, in one query each.

        Loaded eagerly because the run detail page always needs all of it, and
        lazy loading here is the classic N+1: one query per result per artifact.
        """
        statement = (
            select(TestRun)
            .where(TestRun.id == run_id)
            .options(
                selectinload(TestRun.results).selectinload(TestResult.artifacts),
                selectinload(TestRun.suite),
            )
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_projects(
        self,
        project_ids: list[int],
        *,
        suite_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[TestRun]:
        if not project_ids:
            return []

        statement = select(TestRun).where(TestRun.project_id.in_(project_ids))
        if suite_id is not None:
            statement = statement.where(TestRun.suite_id == suite_id)

        statement = statement.order_by(TestRun.id.desc()).offset(skip).limit(limit)
        return list(self.db.execute(statement).scalars().all())

    def list_for_suite(self, suite_id: int) -> list[TestRun]:
        """Every run of this suite, newest first. No project filtering — the
        caller has already authorised the suite it is asking about."""
        statement = (
            select(TestRun)
            .where(TestRun.suite_id == suite_id)
            .order_by(TestRun.id.desc())
        )
        return list(self.db.execute(statement).scalars().all())

    def list_stale(self, before: datetime) -> list[TestRun]:
        """Runs still claiming to be in progress that started before `before`.

        The cutoff matters. A naive "everything still running" query looks
        right at startup and is wrong the moment a second process exists: it
        kills runs that are alive and working in another worker. Only a run
        older than its own timeout is provably dead.
        """
        statement = select(TestRun).where(
            TestRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            func.coalesce(TestRun.started_at, TestRun.created_at) < before,
        )
        return list(self.db.execute(statement).scalars().all())


class TestResultRepository(BaseRepository[TestResult]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, TestResult)

    def get_full(self, result_id: int) -> TestResult | None:
        statement = (
            select(TestResult)
            .where(TestResult.id == result_id)
            .options(selectinload(TestResult.artifacts), selectinload(TestResult.run))
        )
        return self.db.execute(statement).scalar_one_or_none()

    def upsert(
        self, *, run_id: int, browser: Browser, test_case_id: int | None, **values
    ) -> TestResult:
        """One row per (run, case, browser), created or updated.

        Written as an upsert so a re-run of a single browser replaces its rows
        instead of violating the unique constraint or duplicating history.
        """
        statement = select(TestResult).where(
            TestResult.run_id == run_id,
            TestResult.browser == browser,
            TestResult.test_case_id == test_case_id,
        )
        existing = self.db.execute(statement).scalar_one_or_none()

        if existing is None:
            return self.create(
                run_id=run_id, browser=browser, test_case_id=test_case_id, **values
            )

        for key, value in values.items():
            setattr(existing, key, value)
        return existing

    def list_for_run(self, run_id: int) -> list[TestResult]:
        statement = (
            select(TestResult)
            .where(TestResult.run_id == run_id)
            .options(selectinload(TestResult.artifacts))
            .order_by(TestResult.case_name, TestResult.browser)
        )
        return list(self.db.execute(statement).scalars().all())

    def latest_per_case(self, suite_id: int) -> list[TestResult]:
        """The most recent result for each test case in a suite.

        "How is this suite doing" is not answerable from the last run alone.
        Running one case produces a run of one, and reading the figures off it
        says "0 passed of 1" while twelve other cases sit there green from
        earlier — accurate about that run, wrong about the suite.

        Ordered newest run first and de-duplicated in Python rather than with a
        window function: a suite has tens of cases, not millions, and the
        readable version is worth more than the clever one here.
        """
        statement = (
            select(TestResult)
            .join(TestRun, TestResult.run_id == TestRun.id)
            .where(
                TestRun.suite_id == suite_id,
                TestResult.test_case_id.is_not(None),
            )
            .order_by(TestResult.run_id.desc(), TestResult.id.desc())
        )

        seen: set[tuple[int, str]] = set()
        latest: list[TestResult] = []
        for result in self.db.execute(statement).scalars():
            # Per case *and* browser: a case green in Chrome and red in Firefox
            # is two facts, and collapsing them would hide the red one.
            key = (result.test_case_id, result.browser.value)  # type: ignore[arg-type]
            if key in seen:
                continue
            seen.add(key)
            latest.append(result)

        return latest

    def list_failures(self, run_id: int) -> list[TestResult]:
        """Failures and errors — what Phase 7's analysis will be pointed at."""
        statement = select(TestResult).where(
            TestResult.run_id == run_id,
            TestResult.status.in_([ResultStatus.FAILED, ResultStatus.ERROR]),
        )
        return list(self.db.execute(statement).scalars().all())


class ArtifactRepository(BaseRepository[ExecutionArtifact]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, ExecutionArtifact)

    def list_for_result(self, result_id: int) -> list[ExecutionArtifact]:
        statement = select(ExecutionArtifact).where(
            ExecutionArtifact.result_id == result_id
        )
        return list(self.db.execute(statement).scalars().all())

    def list_for_run(self, run_id: int) -> list[ExecutionArtifact]:
        """Everything the run produced, newest first — reports included."""
        statement = (
            select(ExecutionArtifact)
            .where(ExecutionArtifact.run_id == run_id)
            .order_by(ExecutionArtifact.id.desc())
        )
        return list(self.db.execute(statement).scalars().all())
