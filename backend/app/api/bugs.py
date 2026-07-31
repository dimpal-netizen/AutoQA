"""Bug reports drafted from failures."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.bug import BugRead, BugStatusUpdate
from app.services.bug_service import BugService

router = APIRouter(tags=["bugs"])


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


@router.patch(
    "/bug-reports/{bug_id}",
    response_model=BugRead,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def update_status(
    bug_id: int, data: BugStatusUpdate, db: DbSession, user: CurrentUser
) -> BugRead:
    return BugRead.model_validate(BugService(db).set_status(bug_id, data.status, user))
