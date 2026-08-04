"""Schemas for generated test assets."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.codegen.synth import VERB_FOR_ACTION
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
    verb: str | None = None
    description: str
    locator: str | None
    input_data: str | None
    expected_result: str | None
    selector_strategy: str | None

    @model_validator(mode="after")
    def _infer_verb(self) -> "TestStepRead":
        """Fill in the vocabulary word for steps saved before it was recorded.

        Every case generated before the editor existed has `verb` null. For most
        actions the word is not in doubt — a CLICK was a click — so inferring it
        makes those cases editable rather than stranding them until someone
        regenerates. ASSERT is left alone: it covers seven different verbs and a
        guess there would quietly change what the test checks.
        """
        if self.verb is None:
            self.verb = VERB_FOR_ACTION.get(self.action)
        return self


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


# ---------------------------------------------------------------------------
# Authoring a case by hand
# ---------------------------------------------------------------------------
class CaseStepWrite(BaseModel):
    """One step as the editor sends it.

    Deliberately the same three fields the model is allowed to send: an action
    from the vocabulary, an element that exists, a value. `description` is what
    the step will read as in the test-case sheet; left out, the action stands in
    for it.
    """

    action: str = Field(max_length=32)
    target: str | None = Field(default=None, max_length=255)
    value: str | None = None
    description: str | None = Field(default=None, max_length=300)


class CaseWrite(BaseModel):
    """A test case a person wrote or edited.

    There is no `code` field, and that is the safeguard rather than an omission.
    Code is compiled from the steps by the same converter that compiles the
    generated cases, so a hand-written test cannot do anything a generated one
    could not — including on the machine that runs it.
    """

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    category: CaseCategory = CaseCategory.POSITIVE
    priority: CasePriority = CasePriority.MEDIUM
    steps: list[CaseStepWrite] = Field(min_length=1)


class VerbRead(BaseModel):
    """One action the editor may offer, and what it needs alongside it."""

    name: str
    label: str
    needs_target: bool
    needs_value: bool
    allows_empty: bool
    is_assertion: bool


class ElementRead(BaseModel):
    """One element a step may point at, named as a step stores it."""

    target: str
    label: str
    page: str
    page_url: str
    strategy: str
    fragile: bool
    ambiguous: bool


class PlaceholderRead(BaseModel):
    token: str
    label: str


class CaseVocabulary(BaseModel):
    """Everything the editor is allowed to build a step out of.

    Sent to the browser rather than hardcoded there: the elements come from the
    recording, so they differ per suite, and the actions are the backend's list
    — a dropdown built from a copy would drift the day a verb is added.
    """

    verbs: list[VerbRead]
    elements: list[ElementRead]
    placeholders: list[PlaceholderRead]
    max_steps: int
