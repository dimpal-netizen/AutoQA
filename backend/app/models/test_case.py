"""Generated test assets.

A TestSuite is everything produced from one recording (or, later, one agent
run). It holds TestCases — the runnable pytest modules — and GeneratedFiles,
which are the supporting page objects, conftest, and config.

TestSteps are the same actions in human-readable form, so a Manual QA Engineer
can review what a test does without reading Python.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import (
    ActionType,
    CaseCategory,
    CasePriority,
    CaseSource,
    CaseStatus,
    FileType,
)

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.recording import RecordingSession
    from app.models.user import User


def _enum(enum_cls, name: str) -> SAEnum:
    """Native PG enum storing values, not member names."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class TestSuite(Base, TimestampMixin):
    __tablename__ = "test_suites"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recording_id: Mapped[int | None] = mapped_column(
        ForeignKey("recording_sessions.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[CaseSource] = mapped_column(
        _enum(CaseSource, "case_source"), default=CaseSource.RECORDING, nullable=False
    )
    # Which generator produced this — "deterministic_v1" today, an AI model
    # id from Phase 4. Kept so output can be traced back and compared.
    generator: Mapped[str] = mapped_column(String(64), default="deterministic_v1", nullable=False)
    # Folder the scripts were written to, for opening in VS Code. Stored rather
    # than recomputed so the path stays valid if the setting later changes.
    output_dir: Mapped[str | None] = mapped_column(String(1024))

    project: Mapped["Project"] = relationship()
    recording: Mapped["RecordingSession | None"] = relationship()
    created_by: Mapped["User | None"] = relationship()
    cases: Mapped[list["TestCase"]] = relationship(
        back_populates="suite", cascade="all, delete-orphan", order_by="TestCase.id"
    )
    files: Mapped[list["GeneratedFile"]] = relationship(
        back_populates="suite", cascade="all, delete-orphan", order_by="GeneratedFile.path"
    )

    def __repr__(self) -> str:
        return f"<TestSuite {self.id} {self.name!r}>"


class TestCase(Base, TimestampMixin):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    suite_id: Mapped[int] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalised so listing a project's cases doesn't need a join.
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    function_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped[CaseSource] = mapped_column(
        _enum(CaseSource, "case_source"), default=CaseSource.RECORDING, nullable=False
    )
    category: Mapped[CaseCategory] = mapped_column(
        _enum(CaseCategory, "case_category"),
        default=CaseCategory.RECORDED,
        nullable=False,
        index=True,
    )
    priority: Mapped[CasePriority] = mapped_column(
        _enum(CasePriority, "case_priority"), default=CasePriority.MEDIUM, nullable=False
    )
    # What produced this case: the deterministic converter, or a model. Kept so
    # a suite can say honestly which of its tests were invented rather than
    # recorded.
    generated_by: Mapped[str] = mapped_column(String(64), default="recording", nullable=False)

    status: Mapped[CaseStatus] = mapped_column(
        _enum(CaseStatus, "case_status"), default=CaseStatus.DRAFT, nullable=False, index=True
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    suite: Mapped["TestSuite"] = relationship(back_populates="cases")
    steps: Mapped[list["TestStep"]] = relationship(
        back_populates="test_case", cascade="all, delete-orphan", order_by="TestStep.sequence"
    )

    def __repr__(self) -> str:
        return f"<TestCase {self.id} {self.function_name}>"


class TestStep(Base):
    """One step in plain English, for review by someone who doesn't read Python."""

    __tablename__ = "test_steps"
    __table_args__ = (UniqueConstraint("test_case_id", "sequence", name="uq_test_step_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    test_case_id: Mapped[int] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    action: Mapped[ActionType] = mapped_column(_enum(ActionType, "action_type"), nullable=False)
    # The word from the synthesiser's vocabulary this step was authored with.
    # `action` cannot stand in for it: seven distinct assertions all store as
    # ActionType.ASSERT, so a step read back for editing would lose which one it
    # was. Null on recorded steps, which were never authored from a vocabulary.
    verb: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # The locator expression this step compiles to, e.g. get_by_test_id("x").
    locator: Mapped[str | None] = mapped_column(String(1024))
    input_data: Mapped[str | None] = mapped_column(Text)
    expected_result: Mapped[str | None] = mapped_column(Text)
    # Kept so the UI can warn about steps built on a fragile selector.
    selector_strategy: Mapped[str | None] = mapped_column(String(32))

    test_case: Mapped["TestCase"] = relationship(back_populates="steps")

    def __repr__(self) -> str:
        return f"<TestStep {self.sequence} {self.action.value}>"


class GeneratedFile(Base, TimestampMixin):
    """A supporting file: page object, conftest, pytest.ini."""

    __tablename__ = "generated_files"
    __table_args__ = (UniqueConstraint("suite_id", "path", name="uq_generated_file_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    suite_id: Mapped[int] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_type: Mapped[FileType] = mapped_column(_enum(FileType, "file_type"), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="python", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    suite: Mapped["TestSuite"] = relationship(back_populates="files")

    def __repr__(self) -> str:
        return f"<GeneratedFile {self.path}>"
