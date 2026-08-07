"""Request and response shapes for AI failure analysis."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FailureCategory, Severity


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    result_id: int
    run_id: int
    provider: str
    model: str

    # The mismatch in a person's words. None on analyses written before these
    # were asked for — the UI omits the pair rather than showing empty labels.
    expected: str | None = None
    actual: str | None = None

    root_cause: str
    suggested_fix: str
    category: FailureCategory
    severity: Severity
    priority: Severity
    # The question the reader actually has: raise a bug, or fix the test?
    is_product_bug: bool
    # Shown, never hidden. An analysis the model is unsure of should look
    # unsure, or it sends someone to debug the wrong thing.
    confidence: float

    tokens: int
    cost_usd: float
    created_at: datetime


class AskTurn(BaseModel):
    """One exchange that already happened, sent back so a follow-up works."""

    question: str = Field(max_length=500)
    answer: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    # What has been asked and answered so far. Held by the caller rather than
    # the server: an exchange about a failure is worth having while you are
    # looking at it and worth nothing tomorrow, and storing it would mean a
    # table, a migration and a retention question for something nobody will
    # ever open twice.
    history: list[AskTurn] = Field(default_factory=list, max_length=12)


class AskAnswer(BaseModel):
    """An answer grounded in this project's stored results.

    `cites` names the tests, suites and runs it rests on so the reader can go
    and check, and `confident` is false when the stored history did not really
    support an answer — which is worth showing rather than hiding, because a
    tester acting on a confident wrong answer loses an afternoon.
    """

    answer: str
    cites: list[str] = []
    confident: bool = True
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0


class RunTriageRead(BaseModel):
    """A whole run explained in one pass.

    `summary` and `distinct_causes` only exist because the failures were read
    together. Six red tests with one cause is an afternoon; six with six causes
    is a week, and nothing that looks at a single failure can tell them apart.
    """

    analyses: list[AnalysisRead]
    summary: str
    distinct_causes: int
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
