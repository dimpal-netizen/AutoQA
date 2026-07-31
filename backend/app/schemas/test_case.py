"""Schemas for generated test assets."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ActionType,
    CaseCategory,
    CasePriority,
    CaseSource,
    CaseStatus,
    FileType,
)


class GenerateCasesRequest(BaseModel):
    """How many cases to invent around the recorded flow."""

    count: int = Field(default=12, ge=1, le=25)


class GenerateCasesResult(BaseModel):
    """The suite, plus what the model cost and what it got wrong.

    `rejected` is deliberately visible rather than swallowed: a suggestion that
    referenced an element which does not exist is useful signal about the
    recording, not an embarrassment to hide.
    """

    suite: "TestSuiteDetail"
    generated: int
    rejected: list[str] = []
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0


class GenerateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)


class TestStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    action: ActionType
    description: str
    locator: str | None
    input_data: str | None
    expected_result: str | None
    selector_strategy: str | None


class TestCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    suite_id: int
    project_id: int
    name: str
    description: str | None
    function_name: str
    file_path: str
    source: CaseSource
    status: CaseStatus
    category: CaseCategory
    priority: CasePriority
    generated_by: str
    tags: list[str]
    is_enabled: bool
    version: int
    created_at: datetime


class TestCaseDetail(TestCaseRead):
    code: str
    steps: list[TestStepRead]


class GeneratedFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_type: FileType
    path: str
    language: str
    version: int


class GeneratedFileDetail(GeneratedFileRead):
    content: str


class TestSuiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    recording_id: int | None
    name: str
    description: str | None
    source: CaseSource
    generator: str
    # Where the scripts were written, for opening in VS Code.
    output_dir: str | None
    created_at: datetime
    updated_at: datetime


class TestSuiteDetail(TestSuiteRead):
    cases: list[TestCaseDetail]
    files: list[GeneratedFileDetail]


class TestCaseUpdate(BaseModel):
    """Hand edits to generated code. Bumps the version."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    code: str | None = None
    tags: list[str] | None = None
    is_enabled: bool | None = None
