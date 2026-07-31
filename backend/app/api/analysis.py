"""AI failure analysis — Workflow 3."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.analysis import AnalysisRead
from app.services.analysis_service import AnalysisService

router = APIRouter(tags=["analysis"])


@router.post(
    "/results/{result_id}/analyze",
    response_model=AnalysisRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def analyse_result(result_id: int, db: DbSession, user: CurrentUser) -> AnalysisRead:
    """Explain one failure: root cause, suggested fix, severity, confidence.

    On demand rather than automatic. A run can fail thirteen times at once and
    every analysis costs money; spending it without being asked is not a
    default anyone should discover from their bill.
    """
    return AnalysisRead.model_validate(AnalysisService(db).analyse_result(result_id, user))


@router.get("/results/{result_id}/analysis", response_model=AnalysisRead | None)
def get_analysis(result_id: int, db: DbSession, user: CurrentUser) -> AnalysisRead | None:
    analysis = AnalysisService(db).get_for_result(result_id, user)
    return AnalysisRead.model_validate(analysis) if analysis else None


@router.post(
    "/runs/{run_id}/analyze",
    response_model=list[AnalysisRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def analyse_run(run_id: int, db: DbSession, user: CurrentUser) -> list[AnalysisRead]:
    """Explain every failure in a run that has not been explained yet."""
    analyses = AnalysisService(db).analyse_run(run_id, user)
    return [AnalysisRead.model_validate(a) for a in analyses]
