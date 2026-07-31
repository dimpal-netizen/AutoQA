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
    Browser,
    RecordingStatus,
    SelectorStrategy,
    UserRole,
)
from app.models.project import Project
from app.models.recording import RecordedAction, RecordingSession
from app.models.user import User

__all__ = [
    "ELEMENT_ACTIONS",
    "ROLE_LEVEL",
    "SELECTOR_RANK",
    "ActionType",
    "Base",
    "Browser",
    "Project",
    "RecordedAction",
    "RecordingSession",
    "RecordingStatus",
    "SelectorStrategy",
    "User",
    "UserRole",
]
