"""SQLAlchemy models.

IMPORTANT: every model module must be imported here. Alembic's autogenerate
only sees tables that have been registered on Base.metadata, and that only
happens when the module defining them is imported.

As each phase adds models, add its import below:

    from app.models.user import User            # noqa: F401  (Phase 1)
    from app.models.project import Project      # noqa: F401  (Phase 1)
    from app.models.recording import (          # noqa: F401  (Phase 2)
        RecordingSession, RecordedAction,
    )
"""

from app.core.database import Base  # noqa: F401

__all__ = ["Base"]
