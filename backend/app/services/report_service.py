"""Building and storing run reports.

A report is written to disk and recorded as an artifact, like a screenshot or a
video — same storage, same download route, same permission check. It is not
generated on the fly per request: a run with a dozen embedded screenshots takes
real work to render, and a report is a snapshot of one moment anyway. Building
it again later would quietly produce a different document.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import ArtifactType, FINISHED_RUN_STATUSES
from app.models.test_run import ExecutionArtifact
from app.models.user import User
from app.reports.builder import build_report
from app.repositories.analysis_repo import AnalysisRepository
from app.repositories.test_run_repo import ArtifactRepository, TestResultRepository
from app.services.exceptions import NotFound, ValidationError
from app.services.execution_service import ExecutionService

logger = logging.getLogger(__name__)


class ReportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.artifacts = ArtifactRepository(db)
        self.results = TestResultRepository(db)
        self.analyses = AnalysisRepository(db)
        self.execution = ExecutionService(db)

    def build(self, run_id: int, user: User) -> ExecutionArtifact:
        """Render a run to a standalone HTML file and store it."""
        run = self.execution.get(run_id, user)

        if run.status not in FINISHED_RUN_STATUSES:
            raise ValidationError(
                "This run is still going. Wait for it to finish before building "
                "a report."
            )

        results = self.results.list_for_run(run_id)
        if not results:
            raise ValidationError("This run has no results to report on.")

        analyses = {a.result_id: a for a in self.analyses.list_for_run(run_id)}

        html = build_report(
            run,
            results,
            analyses=analyses,
            suite_name=run.suite.name if run.suite else f"Run {run.id}",
            project_name=run.project.name if run.project else "",
            base_url=run.project.base_url if run.project else None,
        )

        target = settings.storage_dir / "reports" / f"run-{run_id}.html"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html, encoding="utf-8", newline="\n")
        except OSError as exc:
            logger.exception("Could not write report for run %s", run_id)
            raise ValidationError(f"Could not write the report: {exc}") from exc

        relative = str(target.relative_to(settings.storage_dir)).replace("\\", "/")

        # Rebuilding replaces rather than accumulates: ten identical reports for
        # one run is a list nobody can choose from.
        existing = next(
            (
                a
                for a in self.artifacts.list_for_run(run_id)
                if a.type is ArtifactType.HTML_REPORT
            ),
            None,
        )
        if existing is not None:
            self.artifacts.update(
                existing, file_path=relative, file_size=target.stat().st_size
            )
            artifact = existing
        else:
            artifact = self.artifacts.create(
                run_id=run_id,
                result_id=None,
                type=ArtifactType.HTML_REPORT,
                file_path=relative,
                file_size=target.stat().st_size,
            )

        self.db.commit()
        return artifact

    def latest(self, run_id: int, user: User) -> ExecutionArtifact | None:
        self.execution.get(run_id, user)  # authorises
        return next(
            (
                a
                for a in self.artifacts.list_for_run(run_id)
                if a.type is ArtifactType.HTML_REPORT
            ),
            None,
        )

    def get_artifact(self, artifact_id: int, user: User) -> ExecutionArtifact:
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise NotFound(f"Report {artifact_id} not found")
        self.execution.get(artifact.run_id, user)  # authorises
        return artifact
