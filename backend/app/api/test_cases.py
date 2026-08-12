"""Code generation and generated test asset routes."""

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import CaseCategory, CasePriority, UserRole
from app.schemas.test_case import (
    CaseStepWrite,
    CaseVocabulary,
    CaseWrite,
    CoverageRead,
    FlakyRead,
    GenerateCasesRequest,
    GenerateCasesResult,
    GenerateRequest,
    ImportPreview,
    SkippedRowRead,
    TestCaseDetail,
    TestSuiteDetail,
    TestSuiteRead,
)
from app.services.codegen_service import CodegenService
from app.services.import_service import ImportService

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


@router.get("/suites/{suite_id}/testcases.xlsx")
def export_testcases(
    suite_id: int, db: DbSession, user: CurrentUser, run_id: int | None = None
) -> Response:
    """The suite as a QA test-case workbook, in the layout teams keep by hand.

    Defaults to the most recent finished run so the Actual Results, Status and
    Execution Date columns come back filled in.
    """
    workbook, filename = CodegenService(db).export_testcases(
        suite_id, user, run_id=run_id
    )

    return Response(
        content=workbook,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/suites/{suite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def delete_suite(suite_id: int, db: DbSession, user: CurrentUser) -> None:
    CodegenService(db).delete_suite(suite_id, user)


# ---------------------------------------------------------------------------
# Writing a case by hand
#
# A generated suite is where a tester starts, not where they finish. They know
# the application and will think of a case the model missed, or spot one it got
# subtly wrong — and until now the only answers were "regenerate and hope" or
# "give up and write Playwright yourself".
#
# What a person may write is exactly what the model may write: an action from
# the fixed vocabulary, an element that already exists, a value. There is no
# route that accepts code, because generated tests run in a subprocess on
# someone's machine and unreviewed Python arriving over HTTP has no business
# going anywhere near it.
# ---------------------------------------------------------------------------
@router.get("/suites/{suite_id}/vocabulary", response_model=CaseVocabulary)
def case_vocabulary(suite_id: int, db: DbSession, user: CurrentUser) -> CaseVocabulary:
    """Every action and element a case in this suite can be built from.

    The element list comes from the recording, so it differs per suite; the
    actions are the same everywhere. Both are served rather than hardcoded in
    the browser, so the dropdown cannot drift from what the backend accepts.
    """
    return CaseVocabulary.model_validate(CodegenService(db).case_vocabulary(suite_id, user))


@router.post(
    "/suites/{suite_id}/cases",
    response_model=TestCaseDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def create_case(
    suite_id: int, data: CaseWrite, db: DbSession, user: CurrentUser
) -> TestCaseDetail:
    """Add a test case nobody generated.

    Compiled by the same converter as every other case, and held to the same
    rules — a case that never asserts anything, or never opens a page, is
    refused with the reason rather than saved as a test that cannot fail.
    """
    case = CodegenService(db).create_case(
        suite_id,
        user,
        name=data.name,
        description=data.description,
        category=data.category,
        priority=data.priority,
        steps=data.steps,
    )
    return TestCaseDetail.model_validate(case)


@router.put(
    "/cases/{case_id}",
    response_model=TestCaseDetail,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def update_case(
    case_id: int, data: CaseWrite, db: DbSession, user: CurrentUser
) -> TestCaseDetail:
    """Rewrite a case's steps, name, category or priority.

    A whole replacement rather than a patch: the steps are an ordered list, and
    expressing "delete step 4 and swap 2 with 3" as a partial update is more
    ways to be wrong than sending the list you want.
    """
    case = CodegenService(db).update_case(
        case_id,
        user,
        name=data.name,
        description=data.description,
        category=data.category,
        priority=data.priority,
        steps=data.steps,
    )
    return TestCaseDetail.model_validate(case)


@router.delete(
    "/cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def delete_case(case_id: int, db: DbSession, user: CurrentUser) -> None:
    """Drop one case. The recorded one is refused — it is the session itself."""
    CodegenService(db).delete_case(case_id, user)


@router.get("/suites/{suite_id}/coverage", response_model=CoverageRead)
def suite_coverage(suite_id: int, db: DbSession, user: CurrentUser) -> CoverageRead:
    """Which elements the recording found that no test in this suite drives.

    The only coverage figure this tool can honestly produce. It cannot see the
    application's code, so it does not claim to: this is "of what we captured
    on the way through, how much is being checked", which is a smaller claim
    and a true one.
    """
    return CoverageRead.model_validate(CodegenService(db).coverage(suite_id, user))


@router.get("/suites/{suite_id}/flaky", response_model=list[FlakyRead])
def suite_flaky(suite_id: int, db: DbSession, user: CurrentUser) -> list[FlakyRead]:
    """Tests here whose verdict changes without the test changing.

    Worked out from the recent runs each time it is asked, rather than written
    onto a result: flakiness is a property of a history, and no single run can
    see it. Worst first — the test that changes its mind most often is the one
    costing the most attention.
    """
    return [
        FlakyRead.model_validate(f) for f in CodegenService(db).flaky(suite_id, user)
    ]


# ---------------------------------------------------------------------------
# Importing a team's own manual test cases
#
# Every QA team keeps a spreadsheet of cases somebody walks through by hand, and
# no two of those sheets look alike. Getting them into AutoQA meant retyping
# each one through the step editor, and nobody was ever going to retype forty.
# ---------------------------------------------------------------------------
@router.post(
    "/suites/{suite_id}/import-cases",
    response_model=ImportPreview,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
async def import_cases(
    suite_id: int, db: DbSession, user: CurrentUser, file: UploadFile = File(...)
) -> ImportPreview:
    """Read a team's manual test-case sheet and draft what can be automated.

    Works out which column is which, says so in `reading` so a misread sheet can
    be caught, and converts the rows whose elements exist in this suite's
    recording.

    **Saves nothing.** The drafts come back in the shape the editor sends, and
    each is saved - if the reader wants it - through the same `create_case` a
    typed one goes through. A row that cannot be automated comes back with the
    reason rather than being dropped, because "needs a recording of the checkout
    flow" is the sentence that says what to do next.
    """
    outcome = ImportService(db).preview(
        suite_id, await file.read(), file.filename or "", user
    )

    return ImportPreview(
        reading=outcome.reading,
        rows=outcome.rows,
        cases=[
            CaseWrite(
                name=case.name,
                description=case.description or None,
                category=_category(case.category),
                priority=_priority(case.priority),
                steps=[
                    CaseStepWrite(action=step.action, target=step.target, value=step.value)
                    for step in case.steps
                ],
            )
            for case in outcome.cases
        ],
        skipped=[SkippedRowRead(**vars(row)) for row in outcome.skipped],
        model=outcome.model,
        tokens=outcome.tokens,
        cost_usd=outcome.cost_usd,
    )


def _category(value: str) -> CaseCategory:
    """A category the model wrote, or the safe default.

    POSITIVE rather than raising: a row that arrived with a misspelt category is
    still a converted test case, and refusing it over a label would throw away
    the conversion that actually mattered.
    """
    try:
        return CaseCategory(str(value).strip().lower())
    except ValueError:
        return CaseCategory.POSITIVE


def _priority(value: str) -> CasePriority:
    try:
        return CasePriority(str(value).strip().lower())
    except ValueError:
        return CasePriority.MEDIUM
