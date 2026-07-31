"""Running tests and reading the results."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.config import settings
from app.models.enums import UserRole
from app.repositories.test_run_repo import ArtifactRepository, TestResultRepository
from app.schemas.test_run import ResultRead, RunCreate, RunDetail, RunRead
from app.services.exceptions import NotFound
from app.services.execution_service import ExecutionService

router = APIRouter(tags=["runs"])


@router.post(
    "/suites/{suite_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_run(
    suite_id: int, data: RunCreate, db: DbSession, user: CurrentUser
) -> RunRead:
    """Run a suite. Returns immediately — poll the run for progress.

    202, not 201: the run has been accepted, not completed. Browsers take
    minutes, and an HTTP request has no business waiting for them.
    """
    run = ExecutionService(db).start_run(
        suite_id,
        user,
        browsers=[b.value for b in data.browsers] if data.browsers else None,
        case_ids=data.case_ids,
        headless=data.headless,
        slow_mo_ms=data.slow_mo_ms,
    )
    return RunRead.model_validate(run)


@router.get("/runs", response_model=list[RunRead])
def list_runs(
    db: DbSession,
    user: CurrentUser,
    project_id: int | None = None,
    suite_id: int | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[RunRead]:
    runs = ExecutionService(db).list_runs(
        user, project_id=project_id, suite_id=suite_id, skip=skip, limit=limit
    )
    return [RunRead.model_validate(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: int, db: DbSession, user: CurrentUser) -> RunDetail:
    """A run and its full per-browser result matrix."""
    return RunDetail.model_validate(ExecutionService(db).get(run_id, user))


@router.get("/runs/{run_id}/results", response_model=list[ResultRead])
def list_results(run_id: int, db: DbSession, user: CurrentUser) -> list[ResultRead]:
    service = ExecutionService(db)
    service.get(run_id, user)  # authorises, and 404s if not visible
    return [ResultRead.model_validate(r) for r in service.results.list_for_run(run_id)]


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunRead,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def cancel_run(run_id: int, db: DbSession, user: CurrentUser) -> RunRead:
    return RunRead.model_validate(ExecutionService(db).cancel(run_id, user))


@router.get("/results/{result_id}/artifacts", response_model=list[ResultRead])
def get_result(result_id: int, db: DbSession, user: CurrentUser) -> list[ResultRead]:
    result = TestResultRepository(db).get_full(result_id)
    if result is None:
        raise NotFound(f"Result {result_id} not found")

    ExecutionService(db).get(result.run_id, user)  # authorises
    return [ResultRead.model_validate(result)]


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, db: DbSession, user: CurrentUser) -> FileResponse:
    """Stream a screenshot, video, or trace off disk.

    The stored path is relative and re-resolved against storage_dir here, then
    checked to be inside it. A row is data; treating it as a filesystem
    instruction without that check is how a database read becomes an
    arbitrary file read.
    """
    artifact = ArtifactRepository(db).get(artifact_id)
    if artifact is None:
        raise NotFound(f"Artifact {artifact_id} not found")

    ExecutionService(db).get(artifact.run_id, user)  # authorises

    root = settings.storage_dir.resolve()
    path = (root / artifact.file_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise NotFound(f"Artifact {artifact_id} is no longer on disk")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=Path(path).name)
