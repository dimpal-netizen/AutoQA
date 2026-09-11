"""Running tests and reading the results."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.config import settings
from app.models.enums import UserRole
from app.repositories.test_run_repo import ArtifactRepository, TestResultRepository
from app.runner.executor import has_display
from app.schemas.test_run import (
    ResultDetail,
    ResultRead,
    RunCreate,
    RunDetail,
    RunRead,
)
from app.services.codegen_service import CodegenService
from app.services.exceptions import NotFound
from app.services.execution_service import ExecutionService

router = APIRouter(tags=["runs"])


class RunCapabilities(BaseModel):
    #: Can a run be watched live here? True on a desktop, false on a server
    #: with no screen - where every run goes headless and is watched
    #: afterwards through its video and trace instead.
    can_watch: bool


@router.get("/runs/capabilities", response_model=RunCapabilities)
def run_capabilities(user: CurrentUser) -> RunCapabilities:  # noqa: ARG001 - signed in only
    return RunCapabilities(can_watch=has_display())


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
    return [_named(run) for run in runs]


def _named(run) -> RunRead:
    """A run with its project and suite named.

    Read here rather than left to the caller: a page listing every run across
    every project would otherwise make one request per row to find out what it
    belongs to, and the relationships are already loaded.
    """
    return RunRead.model_validate(run).model_copy(
        update={
            "project_name": run.project.name if run.project else "",
            # Empty when the suite has been deleted. A run outlives what it ran,
            # which is the point of keeping it.
            "suite_name": run.suite.name if run.suite else "",
        }
    )


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


@router.get("/suites/{suite_id}/case-status", response_model=list[ResultRead])
def suite_case_status(
    suite_id: int, db: DbSession, user: CurrentUser
) -> list[ResultRead]:
    """The most recent result for each test case in this suite.

    Not the same as the last run's results. Running one case gives a run of
    one, and reading the suite's health off it reports every other case as
    unknown — this answers "where does each case currently stand", which is
    what a status column and a pass count both need.
    """
    CodegenService(db).get_suite(suite_id, user)  # authorises
    return [
        ResultRead.model_validate(r)
        for r in TestResultRepository(db).latest_per_case(suite_id)
    ]


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def delete_run(run_id: int, db: DbSession, user: CurrentUser) -> None:
    """Remove a run, its results, and the screenshots and videos it produced."""
    ExecutionService(db).delete_run(run_id, user)


@router.get("/results/{result_id}/artifacts", response_model=list[ResultRead])
def get_result(result_id: int, db: DbSession, user: CurrentUser) -> list[ResultRead]:
    result = TestResultRepository(db).get_full(result_id)
    if result is None:
        raise NotFound(f"Result {result_id} not found")

    ExecutionService(db).get(result.run_id, user)  # authorises
    return [ResultRead.model_validate(result)]


@router.get("/results/{result_id}", response_model=ResultDetail)
def get_result_detail(
    result_id: int, db: DbSession, user: CurrentUser
) -> ResultDetail:
    """One failure, with enough around it to be read on its own page.

    Everything about a failure used to have to fit inside an expanded row of the
    run's table — the error, the analysis, the bug draft, the screenshot, the
    recording and the trace, stacked under a row of a table. It stopped fitting,
    so a failure gets a page, and a page needs its own heading, its own way back
    and the context the surrounding table used to supply.
    """
    results = TestResultRepository(db)

    result = results.get_full(result_id)
    if result is None:
        raise NotFound(f"Result {result_id} not found")

    run = ExecutionService(db).get(result.run_id, user)  # authorises

    return ResultDetail(
        **ResultRead.model_validate(result).model_dump(),
        run_id=run.id,
        run_status=run.status,
        project_id=run.project_id,
        project_name=run.project.name if run.project else "",
        suite_id=run.suite_id,
        suite_name=run.suite.name if run.suite else "",
        started_at=run.started_at,
        siblings=[
            ResultRead.model_validate(other)
            for other in results.list_for_run(run.id)
            # The same test elsewhere, not the whole run. Matched on the
            # function rather than the case name: names are edited, the module
            # a test lives in is what identifies it across browsers.
            if other.function_name == result.function_name and other.id != result.id
        ],
    )


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
