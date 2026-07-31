"""Running generated tests.

Two entry points, deliberately separated:

    start_run()   returns immediately with a queued run
    execute()     does the work, and knows nothing about HTTP

`execute()` is called today from a background thread. When Celery arrives it
will be called from a task instead, and nothing here changes — that is the
whole point of the split.

Cross-browser runs are genuinely parallel: one process per browser, all three
started at once. Sequential would make "test on three browsers" mean "wait
three times as long", which is how cross-browser testing quietly stops
happening.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import session_scope
from app.models.enums import (
    FINISHED_RUN_STATUSES,
    Browser,
    ResultStatus,
    RunStatus,
)
from app.models.test_run import TestRun
from app.models.user import User
from app.repositories.test_run_repo import (
    ArtifactRepository,
    TestResultRepository,
    TestRunRepository,
)
from app.runner.executor import ExecutionOutcome, run_suite
from app.services.codegen_service import CodegenService
from app.services.exceptions import NotFound, ValidationError

logger = logging.getLogger(__name__)


class ExecutionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.runs = TestRunRepository(db)
        self.results = TestResultRepository(db)
        self.artifacts = ArtifactRepository(db)
        self.codegen = CodegenService(db)

    # ------------------------------------------------------------------
    # Starting
    # ------------------------------------------------------------------
    def start_run(
        self,
        suite_id: int,
        user: User,
        *,
        browsers: list[str] | None = None,
        case_ids: list[int] | None = None,
        headless: bool = True,
    ) -> TestRun:
        """Queue a run and return straight away.

        The HTTP request must not wait for browsers to finish, so this creates
        the row, hands the work to a background thread, and responds with a
        run the client can poll.
        """
        suite = self.codegen.get_suite(suite_id, user)

        wanted = [c for c in suite.cases if c.is_enabled]
        if case_ids:
            wanted = [c for c in wanted if c.id in set(case_ids)]
        if not wanted:
            raise ValidationError("This suite has no enabled test cases to run.")

        chosen = self._validate_browsers(browsers)

        run = self.runs.create(
            project_id=suite.project_id,
            suite_id=suite.id,
            triggered_by_id=user.id,
            status=RunStatus.QUEUED,
            browsers=[b.value for b in chosen],
            case_ids=[c.id for c in wanted],
            headless=headless,
            total=len(wanted) * len(chosen),
        )
        self.db.commit()

        self._spawn(run.id)
        return run

    def _validate_browsers(self, browsers: list[str] | None) -> list[Browser]:
        names = browsers or settings.default_browsers
        chosen: list[Browser] = []
        for name in names:
            try:
                browser = Browser(name.strip().lower())
            except ValueError:
                raise ValidationError(
                    f"Unknown browser {name!r}. Choose from: "
                    + ", ".join(b.value for b in Browser)
                ) from None
            if browser not in chosen:
                chosen.append(browser)

        if not chosen:
            raise ValidationError("Choose at least one browser.")
        return chosen

    def _spawn(self, run_id: int) -> None:
        """Run in a daemon thread with its own database session.

        Daemon so a shutdown is not blocked by a run in progress; the run is
        marked failed on the next startup instead of hanging the process.
        """

        def worker() -> None:
            try:
                with session_scope() as db:
                    ExecutionService(db).execute(run_id)
            except Exception:
                logger.exception("Run %s crashed", run_id)
                self._force_error(run_id, "The run crashed unexpectedly.")

        threading.Thread(target=worker, name=f"run-{run_id}", daemon=True).start()

    # ------------------------------------------------------------------
    # Doing the work
    # ------------------------------------------------------------------
    def execute(self, run_id: int) -> None:
        """Run every browser, record every result. Called off the request path."""
        run = self.runs.get_full(run_id)
        if run is None:
            logger.error("Run %s vanished before it started", run_id)
            return
        if run.status in FINISHED_RUN_STATUSES:
            logger.info("Run %s already finished (%s)", run_id, run.status.value)
            return

        bundle, cases = self._prepare(run)
        if bundle is None:
            return

        self.runs.update(run, status=RunStatus.RUNNING, started_at=datetime.now(UTC))
        self.db.commit()

        browsers = [Browser(name) for name in run.browsers]
        base_url = run.project.base_url if run.project else None

        # Each browser gets its own process; the pool bounds how many run at
        # once so three browsers do not become three times the memory on a
        # laptop that cannot spare it.
        with ThreadPoolExecutor(
            max_workers=min(len(browsers), settings.MAX_PARALLEL_BROWSERS),
            thread_name_prefix=f"run{run_id}",
        ) as pool:
            outcomes = list(
                pool.map(
                    lambda browser: run_suite(
                        bundle,
                        run_id=run_id,
                        browser=browser,
                        headless=run.headless,
                        base_url=base_url,
                    ),
                    browsers,
                )
            )

        for outcome in outcomes:
            self._record(run, outcome, cases)

        self._finish(run, outcomes)

    def _prepare(self, run: TestRun) -> tuple[dict[str, str] | None, dict[str, object]]:
        """The files to run, and a lookup from function name back to the case."""
        suite = run.suite
        if suite is None:
            self._fail(run, "The test suite was deleted before the run started.")
            return None, {}

        bundle: dict[str, str] = {file.path: file.content for file in suite.files}
        wanted = set(run.case_ids)
        cases = {case.function_name: case for case in suite.cases if case.id in wanted}

        for case in suite.cases:
            if case.id in wanted:
                bundle[case.file_path] = case.code

        if not cases:
            self._fail(run, "None of the selected test cases still exist.")
            return None, {}

        return bundle, cases

    def _record(
        self, run: TestRun, outcome: ExecutionOutcome, cases: dict[str, object]
    ) -> None:
        """Turn one browser's output into result rows plus their artifacts."""
        by_function: dict[str, int] = {}

        for parsed in outcome.results:
            case = cases.get(parsed.function_name)
            result = self.results.upsert(
                run_id=run.id,
                browser=outcome.browser,
                test_case_id=getattr(case, "id", None),
                case_name=getattr(case, "name", parsed.function_name),
                function_name=parsed.function_name,
                status=parsed.status,
                duration_ms=parsed.duration_ms,
                error_message=parsed.error_message,
                stack_trace=parsed.stack_trace,
                failed_step=parsed.failed_step,
            )
            self.db.flush()  # need the id to attach artifacts
            by_function[parsed.function_name] = result.id

        if not outcome.results:
            # pytest produced nothing. Record a row per case anyway, or the run
            # shows zero results and the user cannot tell what happened.
            self._record_blank(run, outcome, cases)

        for artifact in outcome.artifacts:
            self.artifacts.create(
                run_id=run.id,
                result_id=by_function.get(artifact.function_name or ""),
                type=artifact.type,
                file_path=artifact.relative_path,
                file_size=artifact.size,
            )

        self.db.commit()

    def _record_blank(
        self, run: TestRun, outcome: ExecutionOutcome, cases: dict[str, object]
    ) -> None:
        message = outcome.error or "pytest produced no report."
        for function_name, case in cases.items():
            self.results.upsert(
                run_id=run.id,
                browser=outcome.browser,
                test_case_id=getattr(case, "id", None),
                case_name=getattr(case, "name", function_name),
                function_name=function_name,
                status=ResultStatus.ERROR,
                duration_ms=0,
                error_message=message[:500],
                stack_trace=outcome.output or None,
            )

    def _finish(self, run: TestRun, outcomes: list[ExecutionOutcome]) -> None:
        """Roll the per-browser results up into the run row."""
        results = self.results.list_for_run(run.id)

        passed = sum(1 for r in results if r.status is ResultStatus.PASSED)
        skipped = sum(1 for r in results if r.status is ResultStatus.SKIPPED)
        failed = len(results) - passed - skipped

        errors = [o.error for o in outcomes if o.error]
        if failed and all(r.status is ResultStatus.ERROR for r in results):
            # Nothing actually ran. That is a broken setup, not a failing test,
            # and conflating the two sends people debugging the wrong thing.
            status = RunStatus.ERROR
        elif failed:
            status = RunStatus.FAILED
        else:
            status = RunStatus.PASSED

        finished = datetime.now(UTC)
        self.runs.update(
            run,
            status=status,
            total=len(results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_ms=max((o.duration_ms for o in outcomes), default=0),
            finished_at=finished,
            error_message="; ".join(dict.fromkeys(errors))[:1000] or None,
        )
        self.db.commit()

        logger.info(
            "Run %s finished: %s (%d passed, %d failed, %d skipped)",
            run.id,
            status.value,
            passed,
            failed,
            skipped,
        )

    def _fail(self, run: TestRun, message: str) -> None:
        self.runs.update(
            run,
            status=RunStatus.ERROR,
            error_message=message,
            finished_at=datetime.now(UTC),
        )
        self.db.commit()

    def _force_error(self, run_id: int, message: str) -> None:
        """Last-resort finisher when the worker thread itself died."""
        try:
            with session_scope() as db:
                repo = TestRunRepository(db)
                run = repo.get(run_id)
                if run and run.status not in FINISHED_RUN_STATUSES:
                    repo.update(
                        run,
                        status=RunStatus.ERROR,
                        error_message=message,
                        finished_at=datetime.now(UTC),
                    )
        except Exception:
            logger.exception("Could not mark run %s as errored", run_id)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def get(self, run_id: int, user: User) -> TestRun:
        run = self.runs.get_full(run_id)
        if run is None:
            raise NotFound(f"Run {run_id} not found")

        # 404 rather than 403: someone who cannot see the project should not
        # learn that this run exists.
        try:
            self.codegen.recording_service.project_service.get(run.project_id, user)
        except NotFound:
            raise NotFound(f"Run {run_id} not found") from None

        return run

    def list_runs(
        self,
        user: User,
        *,
        project_id: int | None = None,
        suite_id: int | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[TestRun]:
        projects = self.codegen.recording_service.project_service
        if project_id is not None:
            projects.get(project_id, user)
            project_ids = [project_id]
        else:
            project_ids = [p.id for p in projects.list_for_user(user, skip=0, limit=1000)]

        return self.runs.list_for_projects(
            project_ids, suite_id=suite_id, skip=skip, limit=limit
        )

    def cancel(self, run_id: int, user: User) -> TestRun:
        """Stop waiting on a run.

        Honest about what it does: the pytest process is left to finish or time
        out on its own, and its results are ignored. Killing a browser
        mid-navigation leaves worse debris than letting it end.
        """
        run = self.get(run_id, user)
        if run.status in FINISHED_RUN_STATUSES:
            raise ValidationError(f"This run already {run.status.value}.")

        self.runs.update(
            run,
            status=RunStatus.CANCELLED,
            finished_at=datetime.now(UTC),
            error_message="Cancelled by the user.",
        )
        self.db.commit()
        return run

    @staticmethod
    def reap_orphans() -> int:
        """Fail runs left 'running' by a restart. Called once at startup."""
        try:
            with session_scope() as db:
                repo = TestRunRepository(db)
                orphans = repo.list_active()
                for run in orphans:
                    repo.update(
                        run,
                        status=RunStatus.ERROR,
                        error_message="Interrupted by a server restart.",
                        finished_at=datetime.now(UTC),
                    )
                return len(orphans)
        except Exception:
            logger.exception("Could not reap orphaned runs")
            return 0
