"""AI failure analysis — Workflow 3."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.analysis import AnalysisRead, AskAnswer, AskRequest, RunTriageRead
from app.services.analysis_service import AnalysisService
from app.services.ask_service import AskService

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
    response_model=RunTriageRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def analyse_run(run_id: int, db: DbSession, user: CurrentUser) -> RunTriageRead:
    """Explain every unexplained failure in a run, in a single call.

    One request rather than one per failure: cheaper by the number of failures,
    and better, because a model that sees all of them can say which share a
    cause. "16 failed" and "16 failed, 3 causes" are different days.
    """
    result = AnalysisService(db).analyse_run(run_id, user)

    return RunTriageRead(
        analyses=[AnalysisRead.model_validate(a) for a in result.analyses],
        summary=result.summary,
        distinct_causes=result.distinct_causes,
        model=result.model,
        tokens=result.tokens,
        cost_usd=result.cost_usd,
    )


@router.post(
    "/projects/{project_id}/ask",
    response_model=AskAnswer,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def ask_about_results(
    project_id: int, data: AskRequest, db: DbSession, user: CurrentUser
) -> AskAnswer:
    """Answer a question about this project's testing.

    "Why did registration start failing this week?" is the question a tester
    actually has, and the information to answer it was spread across four
    screens. The answer is grounded in stored runs, results, analyses and bugs
    — nothing else — and names what it rests on so it can be checked.
    """
    outcome = AskService(db).ask(
        project_id, data.question, user, history=data.history
    )

    return AskAnswer(
        answer=outcome.answer,
        cites=outcome.cites or [],
        confident=outcome.confident,
        model=outcome.model,
        tokens=outcome.tokens,
        cost_usd=outcome.cost_usd,
    )


@router.post(
    "/results/{result_id}/ask",
    response_model=AskAnswer,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def ask_about_failure(
    result_id: int, data: AskRequest, db: DbSession, user: CurrentUser
) -> AskAnswer:
    """Answer a question about one failure, with its screenshot attached.

    Sits beside the failure rather than at the top of the project, which is what
    makes it usable: the error and the picture are on screen, so the question is
    specific and the answer can point at the same evidence the reader is
    looking at.
    """
    outcome = AskService(db).ask_about_failure(
        result_id, data.question, user, history=data.history
    )

    return AskAnswer(
        answer=outcome.answer,
        cites=outcome.cites or [],
        confident=outcome.confident,
        model=outcome.model,
        tokens=outcome.tokens,
        cost_usd=outcome.cost_usd,
    )
