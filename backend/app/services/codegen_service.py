"""Turn a recording into a stored test suite."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.case_generator import DEFAULT_COUNT, GenerationOutcome, generate_cases
from app.ai.enhancer import enhance
from app.codegen.converter import TestIR, build_ir
from app.codegen.generator import GeneratedCodeError, render
from app.codegen.writer import remove_suite_directory, suite_directory, write_suite
from app.core.config import settings
from app.models.enums import (
    FINISHED_RUN_STATUSES,
    CaseCategory,
    CasePriority,
    CaseSource,
    CaseStatus,
    FileType,
    RecordingStatus,
    RunStatus,
)
from app.models.test_case import TestSuite
from app.models.user import User
from app.reports.testcases import build_testcase_sheet
from app.repositories.recording_repo import RecordingRepository
from app.repositories.test_case_repo import (
    GeneratedFileRepository,
    TestCaseRepository,
    TestSuiteRepository,
)
from app.repositories.test_run_repo import TestResultRepository, TestRunRepository
from app.services.exceptions import NotFound, ValidationError
from app.services.recording_service import RecordingService

logger = logging.getLogger(__name__)

GENERATOR = "deterministic_v1"


class CodegenService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.suites = TestSuiteRepository(db)
        self.cases = TestCaseRepository(db)
        self.files = GeneratedFileRepository(db)
        self.recordings = RecordingRepository(db)
        self.recording_service = RecordingService(db)

    def generate_from_recording(
        self, recording_id: int, user: User, *, name: str | None = None
    ) -> TestSuite:
        """Build a suite from a finished recording, checking permissions first."""
        session = self.recording_service.get(recording_id, user)
        return self._generate(session, created_by_id=user.id, name=name)

    def autogenerate(self, session, *, created_by_id: int | None) -> TestSuite | None:
        """Generate right after a recording stops.

        Called from the stop paths, which have already authorised the caller.
        Never raises: a codegen problem must not make stopping a recording
        fail, or the user would lose the recording as well as the code.
        """
        if not settings.AUTO_GENERATE_ON_STOP:
            return None

        try:
            return self._generate(session, created_by_id=created_by_id, name=None)
        except ValidationError as exc:
            # Nothing worth generating (an empty recording, usually).
            logger.info("Recording %s: skipped autogeneration - %s", session.id, exc)
        except Exception:
            logger.exception("Recording %s: autogeneration failed", session.id)
        return None

    def _generate(
        self, session, *, created_by_id: int | None, name: str | None
    ) -> TestSuite:
        """Build a suite from a finished recording.

        Regenerating replaces the previous output rather than piling up
        duplicates — the recording is the source of truth, not the code.
        """
        recording_id = session.id

        if session.status is RecordingStatus.RECORDING:
            raise ValidationError(
                "This recording is still running. Stop it before generating code."
            )

        actions = self.recordings.list_actions(recording_id, limit=10_000)
        usable = [a for a in actions if not a.is_ignored]
        if not usable:
            raise ValidationError("This recording has no actions to generate from.")

        suite_name = (name or session.name).strip() or f"Recording {recording_id}"

        ir = build_ir(
            [
                {
                    "action_type": a.action_type.value,
                    "url": a.url,
                    "frame_path": a.frame_path,
                    "selectors": a.selectors,
                    "element": a.element,
                    "payload": a.payload,
                    "is_ignored": a.is_ignored,
                }
                for a in actions
            ],
            suite_name=suite_name,
            start_url=session.start_url,
        )

        # AI pass: better names and descriptions on code that already works.
        # `enhance` never raises and never writes code, so the worst case here
        # is that the deterministic output above is what gets saved.
        polish = enhance(ir)
        if polish.skipped:
            logger.info("Recording %s: no AI enhancement (%s)", recording_id, polish.skipped)
        suite_name = polish.title or suite_name

        try:
            rendered = render(ir, browser_info=session.browser_info)
        except GeneratedCodeError as exc:
            # A template bug, not a user error. Surface it plainly instead of
            # storing code that will not import.
            logger.exception("Codegen produced invalid Python for recording %s", recording_id)
            raise ValidationError(f"Generated code was not valid Python: {exc}") from exc

        generator = f"{GENERATOR}+{polish.model}" if polish.applied else GENERATOR
        description = polish.description or (
            f"Generated from recording {recording_id} ({len(usable)} actions)"
        )

        suite = self.suites.get_by_recording(recording_id)
        if suite is None:
            suite = self.suites.create(
                project_id=session.project_id,
                recording_id=recording_id,
                created_by_id=created_by_id,
                name=suite_name,
                description=description,
                source=CaseSource.RECORDING,
                generator=generator,
            )
        else:
            # Runs first: they are about the cases that are about to go, and
            # delete_run needs the suite row intact to authorise itself.
            self._discard_runs(suite)
            self.suites.delete_generated(suite)
            self.suites.update(
                suite, name=suite_name, description=description, generator=generator
            )

        test_file = next(f for f in rendered if f.path == ir.file_path)
        case = self.cases.create(
            suite_id=suite.id,
            project_id=session.project_id,
            name=suite_name,
            description=(
                (polish.description + " " if polish.description else "")
                + f"{len(ir.steps)} steps across {len(ir.pages)} page(s)."
                + (
                    f" {ir.fragile_count} step(s) use a fragile selector."
                    if ir.fragile_count
                    else ""
                )
            ),
            function_name=ir.function_name,
            file_path=ir.file_path,
            code=test_file.content,
            source=CaseSource.RECORDING,
            status=CaseStatus.DRAFT,
            category=CaseCategory.RECORDED,
            priority=CasePriority.HIGH,
            generated_by=GENERATOR,
            tags=["recorded"],
            is_enabled=True,
            version=1,
        )

        for step in ir.steps:
            self.cases.add_step(
                test_case_id=case.id,
                sequence=step.sequence,
                action=step.action,
                description=step.description,
                locator=(
                    f"{step.page_var}.{step.locator_name}"
                    if step.page_var and step.locator_name
                    else None
                ),
                input_data=step.input_data,
                expected_result=step.expected_result,
                selector_strategy=step.strategy,
            )

        for spec in rendered:
            if spec.path == ir.file_path:
                continue  # the test module lives on the case, not as a file row
            self.files.create(
                suite_id=suite.id,
                project_id=session.project_id,
                file_type=spec.file_type,
                path=spec.path,
                content=spec.content,
                language="python" if spec.path.endswith(".py") else "ini",
                version=1,
                meta={},
            )

        # Put the scripts on disk. This is the copy a QA Engineer opens in
        # VS Code to review and edit; the database copy is what gets executed
        # and regenerated.
        target = suite_directory(session.project.name, suite_name)
        if self.suites.output_dir_taken(str(target), excluding=suite.id):
            target = suite_directory(
                session.project.name, suite_name, disambiguator=suite.id
            )

        previous = suite.output_dir
        try:
            write_suite(target, {spec.path: spec.content for spec in rendered})
            self.suites.update(suite, output_dir=str(target))

            # A rename moves the folder. Remove the old one, or `generated/`
            # accumulates a directory for every name the suite has ever had.
            if previous and previous != str(target):
                remove_suite_directory(Path(previous))
        except OSError:
            # A read-only or full disk must not lose the generated suite —
            # it is still in the database and still runnable.
            logger.exception("Could not write suite %s to %s", suite.id, target)

        self.db.commit()
        return self.suites.get_full(suite.id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # AI test case generation
    # ------------------------------------------------------------------
    def generate_cases(
        self, suite_id: int, user: User, *, count: int = DEFAULT_COUNT
    ) -> tuple[TestSuite, GenerationOutcome]:
        """Add positive, negative, edge and security cases around the recording.

        Replaces any previously generated cases rather than appending, so
        pressing the button twice gives a fresh set instead of thirty
        near-duplicates. The recorded case is never touched.
        """
        suite = self.get_suite(suite_id, user)

        recorded_ir = self._recorded_ir(suite)
        if recorded_ir is None:
            raise ValidationError(
                "This suite has no recording to generate test cases from."
            )

        outcome = generate_cases(recorded_ir, count=count)
        if outcome.skipped:
            raise ValidationError(outcome.skipped)
        if not outcome.cases:
            raise ValidationError(
                "The model returned no usable test cases. "
                + (f"Rejected: {outcome.rejected[0]}" if outcome.rejected else "")
            )

        # Out with the previous generation, in with this one.
        for case in list(suite.cases):
            if case.category is not CaseCategory.RECORDED:
                self.cases.delete(case)
        self.db.flush()

        browser_info = suite.recording.browser_info if suite.recording else {}
        for synthesised in outcome.cases:
            self._store_case(suite, synthesised, browser_info, outcome.model)

        self._refresh_files(suite, recorded_ir)
        self._discard_runs(suite)

        self.db.commit()
        suite = self.suites.get_full(suite.id)  # type: ignore[assignment]
        self._rewrite_folder(suite)
        return suite, outcome

    def _discard_runs(self, suite: TestSuite) -> None:
        """Throw away runs that tested code this regeneration has replaced.

        A verdict is about a particular version of a test. Once the cases are
        rewritten, "1 passed" is a statement about a file that no longer
        exists — and because deleting a case sets its results' test_case_id to
        NULL, the result cannot even say which case it was about any more.
        Keeping that on screen next to the new cases invites reading it as
        their result.

        A run still going is left alone. It is writing to its own directory and
        will finish against the files it started with; deleting it underneath
        itself is the one thing worse than a stale verdict.
        """
        from app.services.execution_service import ExecutionService

        execution = ExecutionService(self.db)
        for run in TestRunRepository(self.db).list_for_suite(suite.id):
            if run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
                logger.info("Suite %s: keeping run %s, still going", suite.id, run.id)
                continue
            try:
                execution.delete_run(run.id, self._owner_of(suite))
            except Exception:
                logger.exception("Could not discard run %s", run.id)

    @staticmethod
    def _owner_of(suite: TestSuite):
        """Whoever owns the project. Regeneration has already been authorised,
        and delete_run re-checks against a user rather than trusting a flag."""
        return suite.project.owner

    def _refresh_files(self, suite: TestSuite, ir: TestIR) -> None:
        """Re-render the page objects and config from the IR the cases used.

        Without this, the two halves of a suite come from two different runs of
        the generator. The cases are synthesised from an IR rebuilt just now;
        the page objects are whatever was stored the day the suite was first
        created. Any change to how page objects are named desynchronises them,
        and the result is not a subtle mismatch — the test module cannot be
        imported at all:

            ImportError: No module named 'pages.agent_details_page'
            (on disk: pages/agent_details_cmru9ht1z001a01l61v2hpc2u_page.py)

        pytest reports that as `collection failure`, which says nothing about
        the cause and takes the whole run down with it.

        A conftest the user has edited is left alone. Regenerating cases should
        not silently discard someone's fixtures.
        """
        try:
            rendered = render(ir)
        except GeneratedCodeError:
            logger.exception("Could not re-render supporting files for suite %s", suite.id)
            return

        existing = {f.path: f for f in suite.files}

        for spec in rendered:
            if spec.path == ir.file_path:
                continue  # the recorded test lives on its case, not as a file

            current = existing.get(spec.path)
            if current is None:
                self.files.create(
                    suite_id=suite.id,
                    project_id=suite.project_id,
                    file_type=spec.file_type,
                    path=spec.path,
                    content=spec.content,
                    language="python" if spec.path.endswith(".py") else "ini",
                    version=1,
                    meta={},
                )
            elif current.file_type is not FileType.CONFTEST:
                self.files.update(
                    current, content=spec.content, version=current.version + 1
                )

        # Page objects for pages that no longer exist would still be written to
        # disk and imported by nothing — harmless, but they are the same stale
        # files this method exists to remove.
        fresh = {spec.path for spec in rendered}
        for path, stored in existing.items():
            if path not in fresh and stored.file_type is FileType.PAGE_OBJECT:
                self.files.delete(stored)

        self.db.flush()

    def _recorded_ir(self, suite: TestSuite) -> TestIR | None:
        """Rebuild the IR for the recording behind this suite.

        Rebuilt rather than stored: the IR is derived data, and keeping a
        serialised copy in the database would be one more thing to migrate
        every time the converter changes.
        """
        if suite.recording_id is None:
            return None

        actions = self.recordings.list_actions(suite.recording_id, limit=10_000)
        if not actions:
            return None

        return build_ir(
            [
                {
                    "action_type": a.action_type.value,
                    "url": a.url,
                    "frame_path": a.frame_path,
                    "selectors": a.selectors,
                    "element": a.element,
                    "payload": a.payload,
                    "is_ignored": a.is_ignored,
                }
                for a in actions
            ],
            suite_name=suite.name,
            start_url=suite.recording.start_url,
        )

    def _store_case(
        self, suite: TestSuite, synthesised, browser_info: dict, model: str
    ) -> None:
        rendered = render(synthesised.ir, browser_info=browser_info)
        module = next(f for f in rendered if f.path == synthesised.ir.file_path)

        case = self.cases.create(
            suite_id=suite.id,
            project_id=suite.project_id,
            name=synthesised.name,
            description=synthesised.description,
            function_name=synthesised.ir.function_name,
            file_path=synthesised.ir.file_path,
            code=module.content,
            source=CaseSource.RECORDING,
            status=CaseStatus.DRAFT,
            category=synthesised.category,
            priority=synthesised.priority,
            generated_by=model or "ai",
            tags=[synthesised.category.value],
            is_enabled=True,
            version=1,
        )

        for step in synthesised.ir.steps:
            self.cases.add_step(
                test_case_id=case.id,
                sequence=step.sequence,
                action=step.action,
                description=step.description,
                locator=(
                    f"{step.page_var}.{step.locator_name}"
                    if step.page_var and step.locator_name
                    else None
                ),
                input_data=step.input_data,
                expected_result=step.expected_result,
                selector_strategy=step.strategy,
            )

    def _rewrite_folder(self, suite: TestSuite) -> None:
        """Refresh the folder on disk so every case has a file to open."""
        if not suite.output_dir:
            return

        bundle = {f.path: f.content for f in suite.files}
        for case in suite.cases:
            bundle[case.file_path] = case.code

        try:
            write_suite(Path(suite.output_dir), bundle)
        except OSError:
            logger.exception("Could not refresh %s", suite.output_dir)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def get_suite(self, suite_id: int, user: User) -> TestSuite:
        suite = self.suites.get_full(suite_id)
        if suite is None:
            raise NotFound(f"Test suite {suite_id} not found")

        # Reuse the project rules; 404 rather than 403 so we don't confirm the
        # suite exists to someone who cannot see its project.
        try:
            self.recording_service.project_service.get(suite.project_id, user)
        except NotFound:
            raise NotFound(f"Test suite {suite_id} not found") from None

        return suite

    def export_testcases(
        self, suite_id: int, user: User, *, run_id: int | None = None
    ) -> tuple[str, str]:
        """The suite as a QA test-case sheet, plus a filename.

        Defaults to the suite's most recent finished run so the execution
        columns arrive filled in — that is the version a QA lead actually
        wants, and asking them to find a run id first would be busywork.

        Imported here rather than at module scope: execution imports codegen,
        so taking the dependency the other way round at import time would be a
        cycle.
        """
        from app.services.execution_service import ExecutionService

        suite = self.get_suite(suite_id, user)

        run = None
        results: list = []
        execution = ExecutionService(self.db)

        if run_id is not None:
            run = execution.get(run_id, user)
        else:
            runs = execution.list_runs(user, suite_id=suite_id, limit=10)
            run = next((r for r in runs if r.status in FINISHED_RUN_STATUSES), None)

        if run is not None:
            results = TestResultRepository(self.db).list_for_run(run.id)

        csv_text = build_testcase_sheet(
            suite,
            list(suite.cases),
            project_name=suite.project.name if suite.project else "",
            designed_by=user.full_name or user.email,
            run=run,
            results=results,
        )

        stem = "".join(
            c if c.isalnum() else "_" for c in f"{suite.name}"
        ).strip("_") or f"suite_{suite.id}"
        return csv_text, f"test_cases_{stem}.csv"

    def list_suites(
        self, user: User, project_id: int | None = None, skip: int = 0, limit: int = 100
    ) -> list[TestSuite]:
        projects = self.recording_service.project_service
        if project_id is not None:
            projects.get(project_id, user)
            project_ids = [project_id]
        else:
            project_ids = [p.id for p in projects.list_for_user(user, skip=0, limit=1000)]

        return self.suites.list_for_projects(project_ids, skip=skip, limit=limit)

    def delete_suite(self, suite_id: int, user: User) -> None:
        suite = self.get_suite(suite_id, user)
        self.suites.delete(suite)
        self.db.commit()

    def bundle(self, suite_id: int, user: User) -> dict[str, str]:
        """Every file as {path: content} — what Phase 5 will write to disk."""
        suite = self.get_suite(suite_id, user)
        files = {f.path: f.content for f in suite.files}
        for case in suite.cases:
            files[case.file_path] = case.code
        return files
