"""Turn a recording into a stored test suite."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.ai.enhancer import enhance
from app.codegen.converter import build_ir
from app.codegen.generator import GeneratedCodeError, render
from app.codegen.writer import suite_directory, write_suite
from app.core.config import settings
from app.models.enums import CaseSource, CaseStatus, RecordingStatus
from app.models.test_case import TestSuite
from app.models.user import User
from app.repositories.recording_repo import RecordingRepository
from app.repositories.test_case_repo import (
    GeneratedFileRepository,
    TestCaseRepository,
    TestSuiteRepository,
)
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
        target = suite_directory(
            session.project_id, session.project.name, suite.id, suite_name
        )
        try:
            write_suite(target, {spec.path: spec.content for spec in rendered})
            self.suites.update(suite, output_dir=str(target))
        except OSError:
            # A read-only or full disk must not lose the generated suite —
            # it is still in the database and still runnable.
            logger.exception("Could not write suite %s to %s", suite.id, target)

        self.db.commit()
        return self.suites.get_full(suite.id)  # type: ignore[return-value]

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
