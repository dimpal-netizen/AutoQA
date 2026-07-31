"""SQLAlchemy models.

IMPORTANT: every model module must be imported here. Alembic's autogenerate
only sees tables registered on Base.metadata, and that only happens when the
module defining them is imported.
"""

from app.core.database import Base
from app.models.enums import ROLE_LEVEL, Browser, UserRole
from app.models.project import Project
from app.models.user import User

__all__ = ["ROLE_LEVEL", "Base", "Browser", "Project", "User", "UserRole"]
