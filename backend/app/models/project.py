"""Project model — one web application under test."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Which browsers new runs use by default, e.g. ["chromium", "firefox"].
    default_browsers: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: ["chromium"], nullable=False
    )
    # Free-form per-project options (timeouts, viewport, retries...). JSONB because
    # it is only ever read as a whole document, never filtered by key.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner: Mapped["User"] = relationship(back_populates="projects")

    def __repr__(self) -> str:
        return f"<Project {self.id} {self.name}>"
