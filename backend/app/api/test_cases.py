"""Code generation and generated test asset routes."""

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.test_case import (
    GenerateCasesRequest,
    GenerateCasesResult,
    GenerateRequest,
    TestSuiteDetail,
    TestSuiteRead,
)
from app.services.codegen_service import CodegenService

router = APIRouter(tags=["test-cases"])


@router.post(
    "/recordings/{recording_id}/generate",
    response_model=TestSuiteDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def generate_from_recording(
    recording_id: int, data: GenerateRequest, db: DbSession, user: CurrentUser
) -> TestSuiteDetail:
    """Turn a recording into Playwright code.

    Deterministic — no AI. Running it again replaces the previous output, so
    the recording stays the source of truth.
    """
    suite = CodegenService(db).generate_from_recording(recording_id, user, name=data.name)
    return TestSuiteDetail.model_validate(suite)


@router.post(
    "/suites/{suite_id}/generate-cases",
    response_model=GenerateCasesResult,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def generate_cases(
    suite_id: int, data: GenerateCasesRequest, db: DbSession, user: CurrentUser
) -> GenerateCasesResult:
    """Invent positive, negative, edge and security cases around the recording.

    Unlike code generation this genuinely needs an AI provider — inventing
    "what if the email is 320 characters" from a successful login is judgement,
    not a lookup. With no key configured it returns 422 saying so.

    The model returns steps, never code: each step names an action from a fixed
    vocabulary and an element that already exists, and the same deterministic
    converter writes the Python.
    """
    suite, outcome = CodegenService(db).generate_cases(suite_id, user, count=data.count)

    return GenerateCasesResult(
        suite=TestSuiteDetail.model_validate(suite),
        generated=len(outcome.cases),
        rejected=outcome.rejected,
        model=outcome.model,
        tokens=outcome.tokens,
        cost_usd=outcome.cost_usd,
    )


@router.get("/suites", response_model=list[TestSuiteRead])
def list_suites(
    db: DbSession,
    user: CurrentUser,
    project_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[TestSuiteRead]:
    suites = CodegenService(db).list_suites(user, project_id, skip=skip, limit=limit)
    return [TestSuiteRead.model_validate(s) for s in suites]


@router.get("/suites/{suite_id}", response_model=TestSuiteDetail)
def get_suite(suite_id: int, db: DbSession, user: CurrentUser) -> TestSuiteDetail:
    """The suite with every generated file and every case's code and steps."""
    return TestSuiteDetail.model_validate(CodegenService(db).get_suite(suite_id, user))


@router.get("/suites/{suite_id}/bundle")
def get_bundle(suite_id: int, db: DbSession, user: CurrentUser) -> dict[str, str]:
    """Every file as {path: content} — what Phase 5 writes to disk to run."""
    return CodegenService(db).bundle(suite_id, user)


@router.delete(
    "/suites/{suite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def delete_suite(suite_id: int, db: DbSession, user: CurrentUser) -> None:
    CodegenService(db).delete_suite(suite_id, user)
