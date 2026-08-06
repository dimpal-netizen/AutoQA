"""Request and response shapes for AI failure analysis."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
