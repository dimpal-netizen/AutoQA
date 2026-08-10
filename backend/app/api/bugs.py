"""Bug reports drafted from failures."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.bug import BugRead, BugStatusUpdate
from app.services.bug_service import BugService

router = APIRouter(tags=["bugs"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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


@router.get("/bug-reports", response_model=list[BugRead])
def list_all_bugs(db: DbSession, user: CurrentUser) -> list[BugRead]:
    """Every bug across every project, newest first.

    For the page that answers "what is outstanding" without picking a project
    first — which is the question somebody has before they know which project
    to open.
    """
    return [_named(bug) for bug in BugService(db).list_all(user)]


@router.get("/projects/{project_id}/bug-reports", response_model=list[BugRead])
def list_bugs(project_id: int, db: DbSession, user: CurrentUser) -> list[BugRead]:
    """Every bug drafted against this project, newest first."""
    return [_named(bug) for bug in BugService(db).list_for_project(project_id, user)]


def _named(bug) -> BugRead:
    """A bug with its project and the test that found it named.

    Read here rather than left to the caller: a page listing every bug would
    otherwise make a request per row to find out what it belongs to.
    """
    return BugRead.model_validate(bug).model_copy(
        update={
            "project_name": bug.project.name if bug.project else "",
            # Null once the run is deleted — the bug outlives it, which is why
            # its steps were copied in when it was drafted.
            "case_name": getattr(bug.result, "case_name", "") if bug.result else "",
        }
    )


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


@router.get("/projects/{project_id}/bug-report.docx")
def export_bugs_document(project_id: int, db: DbSession, user: CurrentUser) -> Response:
    """The same bugs as a Word document, with the screenshot of each failure.

    The spreadsheet is the register — sort, filter, count. This is what you
    attach to a ticket or email to a developer, and the screenshot is why it
    exists: a cell cannot hold the picture of the page at the moment the test
    gave up, and that picture is the fastest way to tell an application bug from
    a test one.
    """
    document, filename = BugService(db).export_all(project_id, user, fmt="docx")

    return Response(
        content=document,
        media_type=DOCX,
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
