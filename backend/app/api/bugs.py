"""Bug reports drafted from failures."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.bug import BugRead, BugStatusUpdate
from app.services.bug_service import BugService

router = APIRouter(tags=["bugs"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post(
    "/results/{result_id}/bug-report",
    response_model=BugRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def draft_bug(result_id: int, db: DbSession, user: CurrentUser) -> BugRead:
    """Write a bug report a developer can act on without opening AutoQA.

    Uses the failure analysis when one exists — it saw the same evidence, so a
    second opinion formed in isolation would only disagree with itself.
    """
    return BugRead.model_validate(BugService(db).draft(result_id, user))


@router.get("/results/{result_id}/bug-report", response_model=BugRead | None)
def get_for_result(result_id: int, db: DbSession, user: CurrentUser) -> BugRead | None:
    bug = BugService(db).for_result(result_id, user)
    return BugRead.model_validate(bug) if bug else None


@router.get("/bug-reports/{bug_id}", response_model=BugRead)
def get_bug(bug_id: int, db: DbSession, user: CurrentUser) -> BugRead:
    return BugRead.model_validate(BugService(db).get(bug_id, user))


@router.get("/projects/{project_id}/bug-reports", response_model=list[BugRead])
def list_bugs(project_id: int, db: DbSession, user: CurrentUser) -> list[BugRead]:
    """Every bug drafted against this project, newest first."""
    return [
        BugRead.model_validate(bug)
        for bug in BugService(db).list_for_project(project_id, user)
    ]


@router.get("/projects/{project_id}/bug-report.xlsx")
def export_bugs(project_id: int, db: DbSession, user: CurrentUser) -> Response:
    """Every bug in the project as one workbook, worst severity first.

    The per-failure report is a ticket. This is the register: what is open, what
    is critical, which browser — questions nobody can answer by opening tickets
    one at a time.
    """
    workbook, filename = BugService(db).export_all(project_id, user)

    return Response(
        content=workbook,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch(
    "/bug-reports/{bug_id}",
    response_model=BugRead,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def update_status(
    bug_id: int, data: BugStatusUpdate, db: DbSession, user: CurrentUser
) -> BugRead:
    return BugRead.model_validate(BugService(db).set_status(bug_id, data.status, user))
