"""Request and response shapes for bug reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import BugStatus, Severity


class BugRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    result_id: int | None
    analysis_id: int | None

    title: str
    description: str
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    environment: dict[str, Any]

    severity: Severity
    priority: Severity
    status: BugStatus
    created_at: datetime
    # Named, so a list spanning every project can group itself without a request
    # per row. Empty on the per-failure lookups, which already know the project.
    project_name: str = ""
    # The test that found it, while the run that produced it still exists.
    case_name: str = ""


class BugStatusUpdate(BaseModel):
    status: BugStatus
