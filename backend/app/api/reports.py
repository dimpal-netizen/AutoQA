"""Downloadable run reports."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.schemas.test_run import ArtifactRead
from app.services.exceptions import NotFound
from app.services.report_service import ReportService

router = APIRouter(tags=["reports"])


@router.post(
    "/runs/{run_id}/report",
    response_model=ArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
def build_report(run_id: int, db: DbSession, user: CurrentUser) -> ArtifactRead:
    """Render this run as one self-contained HTML file.

    Everything is inlined — styles and screenshots both — so the file can be
    emailed to someone who has never heard of AutoQA and still render in two
    years.
    """
    return ArtifactRead.model_validate(ReportService(db).build(run_id, user))


@router.get("/runs/{run_id}/report", response_model=ArtifactRead | None)
def latest_report(run_id: int, db: DbSession, user: CurrentUser) -> ArtifactRead | None:
    artifact = ReportService(db).latest(run_id, user)
    return ArtifactRead.model_validate(artifact) if artifact else None


@router.get("/reports/{artifact_id}/download")
def download_report(artifact_id: int, db: DbSession, user: CurrentUser) -> FileResponse:
    artifact = ReportService(db).get_artifact(artifact_id, user)

    root = settings.storage_dir.resolve()
    path = (root / artifact.file_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise NotFound(f"Report {artifact_id} is no longer on disk")

    return FileResponse(
        path,
        media_type="text/html",
        filename=path.name,
        # An attachment, not an inline page. The report embeds error text and
        # AI prose; serving it inline from our own origin would let anything
        # that slipped through escaping run against this domain.
        content_disposition_type="attachment",
    )
