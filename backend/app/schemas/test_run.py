"""Request and response shapes for running tests."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ArtifactType, Browser, ResultStatus, RunStatus


class RunCreate(BaseModel):
    """What to run. Every field optional — the default is everything, everywhere."""

    browsers: list[Browser] | None = Field(
        default=None, description="Defaults to the project's browsers"
    )
    case_ids: list[int] | None = Field(
        default=None, description="Defaults to every enabled case in the suite"
    )
    headless: bool = Field(
        default=True, description="Set false to watch the browser as it runs"
    )
    slow_mo_ms: int | None = Field(
        default=None,
        ge=0,
        le=5000,
        description=(
            "Pause between actions while watching. Defaults to the configured "
            "watch speed; ignored when headless."
        ),
    )


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ArtifactType
    file_path: str
    file_size: int | None = None


class ResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_case_id: int | None = None
    case_name: str
    function_name: str
    browser: Browser
    status: ResultStatus
    duration_ms: int | None = None
    current_test: str | None = None
    error_message: str | None = None
    stack_trace: str | None = None
    failed_step: int | None = None
    retries: int = 0
    artifacts: list[ArtifactRead] = []


class RunRead(BaseModel):
    """A run without its results — for lists and for polling."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    suite_id: int | None = None
    status: RunStatus
    browsers: list[str]
    case_ids: list[int]
    headless: bool
    slow_mo_ms: int
    total: int
    passed: int
    failed: int
    skipped: int
    duration_ms: int | None = None
    current_test: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    # Names, so a list of runs from every project can group itself without a
    # request per row. Empty when the run has no suite, which happens after one
    # is deleted — the run is history and outlives what it ran.
    project_name: str = ""
    suite_name: str = ""


class RunDetail(RunRead):
    """A run with the full cross-browser matrix."""

    results: list[ResultRead] = []


class ResultDetail(ResultRead):
    """One result, with enough around it to be a page of its own.

    A failure used to be readable only inside the run that produced it, which is
    why everything about it — the error, the analysis, the bug draft, the
    screenshot, the recording, the trace — had to fit in an expanded table row.
    It stopped fitting. This carries the names and ids a standalone page needs
    for its heading and its way back.
    """

    run_id: int
    run_status: RunStatus
    project_id: int
    project_name: str = ""
    suite_id: int | None = None
    suite_name: str = ""
    started_at: datetime | None = None
    #: The same test in the other browsers. "Passes in Chrome, fails in WebKit"
    #: is the single most useful thing to know about a failure, and it is
    #: invisible to anyone looking at one result on its own.
    siblings: list[ResultRead] = []
