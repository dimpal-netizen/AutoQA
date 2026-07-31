"""SQLAlchemy models.

IMPORTANT: every model module must be imported here. Alembic's autogenerate
only sees tables registered on Base.metadata, and that only happens when the
module defining them is imported.
"""

from app.core.database import Base
from app.models.enums import (
    ELEMENT_ACTIONS,
    ROLE_LEVEL,
    SELECTOR_RANK,
    ActionType,
    ArtifactType,
    BugStatus,
    FailureCategory,
    Browser,
    RecordingStatus,
    ResultStatus,
    RunStatus,
    SelectorStrategy,
    Severity,
    UserRole,
)
from app.models.ai_analysis import AIAnalysis
from app.models.bug_report import BugReport
from app.models.project import Project
from app.models.recording import RecordedAction, RecordingSession
from app.models.test_case import GeneratedFile, TestCase, TestStep, TestSuite
from app.models.test_run import ExecutionArtifact, TestResult, TestRun
from app.models.user import User

__all__ = [
    "AIAnalysis",
    "ELEMENT_ACTIONS",
    "ROLE_LEVEL",
    "SELECTOR_RANK",
    "ActionType",
    "ArtifactType",
    "Base",
    "BugReport",
    "BugStatus",
    "Browser",
    "ExecutionArtifact",
    "FailureCategory",
    "GeneratedFile",
    "Project",
    "RecordedAction",
    "RecordingSession",
    "RecordingStatus",
    "ResultStatus",
    "RunStatus",
    "SelectorStrategy",
    "Severity",
    "TestCase",
    "TestResult",
    "TestRun",
    "TestStep",
    "TestSuite",
    "User",
    "UserRole",
]
