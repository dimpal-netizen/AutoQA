"""Project model - one web application under test, and its sample files."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, Text
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


class SampleFile(Base, TimestampMixin):
    """A real file for tests to upload, instead of a generated placeholder.

    A browser never tells a page where a chosen file lives, so a recording of
    somebody adding a property holds the name of their photograph and nothing
    else. AutoQA builds a plain 800x600 image in its place, which uploads
    correctly - but it is a grey rectangle, and a site that resizes, checks or
    later displays the photograph deserves a photograph.

    Shared, not per project. A photograph is a photograph: the same handful
    serves every listing form, every avatar picker and every document upload
    anybody records, and keeping a separate copy per project would mean
    uploading the same six pictures again for each one.

    The bytes live on disk under `storage_dir`, not here. A row per file with a
    path is a fraction of the size, streams without loading, and keeps the
    database dumpable.
    """

    __tablename__ = "sample_files"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The name a test uploads it under, so a site that reads the extension sees
    # what it expects.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Relative to settings.storage_dir, so the database stays portable.
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)

    def __repr__(self) -> str:
        return f"<SampleFile {self.id} {self.filename}>"
