"""Execution records.

Three tables, and the shape of the middle one is the important decision:

    TestRun          one click of "Run" — spans every case and every browser
      TestResult     ONE ROW PER (case, browser) — the cross-browser matrix
        Artifact     screenshot, video, log; the file is on disk, not in here

`test_results` is keyed on (run, case, browser) rather than just (run, case)
because "passes in Chromium, fails in WebKit" is the single most useful thing
this product can tell a QA engineer, and it is unrepresentable if a case has
only one result per run.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
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
from app.models.enums import ArtifactType, Browser, ResultStatus, RunStatus

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.test_case import TestCase, TestSuite
    from app.models.user import User


def _enum(enum_cls, name: str) -> SAEnum:
    """Native PG enum storing values, not member names."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class TestRun(Base, TimestampMixin):
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    suite_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_suites.id", ondelete="SET NULL"), index=True
    )
    triggered_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), default=RunStatus.QUEUED, nullable=False, index=True
    )

    # What was asked for. Kept even after the suite changes, so an old run
    # still explains itself.
    browsers: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    case_ids: Mapped[list[int]] = mapped_column(JSONB, default=list, nullable=False)
    headless: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Pause between actions, in milliseconds. Stored on the run rather than
    # read from config at execution time so an old run still explains why it
    # took four minutes.
    slow_mo_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # The test pytest is inside right now, for the "Running: ..." line. Cleared
    # when the run ends. A live field on the run rather than a status on the
    # result, because a test that has started has no result yet.
    current_test: Mapped[str | None] = mapped_column(String(255))
    workspace_path: Mapped[str | None] = mapped_column(String(1024))
    error_message: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True))

    project: Mapped["Project"] = relationship()
    suite: Mapped["TestSuite | None"] = relationship()
    triggered_by: Mapped["User | None"] = relationship()
    results: Mapped[list["TestResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="TestResult.id"
    )

    def __repr__(self) -> str:
        return f"<TestRun {self.id} {self.status.value} {self.passed}/{self.total}>"


class TestResult(Base, TimestampMixin):
    __tablename__ = "test_results"
    __table_args__ = (
        # One row per case per browser. Also makes a retry idempotent: the
        # runner upserts rather than piling up duplicates.
        UniqueConstraint("run_id", "test_case_id", "browser", name="uq_result_case_browser"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_cases.id", ondelete="SET NULL"), index=True
    )

    # Denormalised on purpose: a result must stay readable after its case is
    # regenerated or deleted. History that dissolves is not history.
    case_name: Mapped[str] = mapped_column(String(255), nullable=False)
    function_name: Mapped[str] = mapped_column(String(255), nullable=False)

    browser: Mapped[Browser] = mapped_column(_enum(Browser, "browser"), nullable=False)
    status: Mapped[ResultStatus] = mapped_column(
        _enum(ResultStatus, "result_status"), nullable=False, index=True
    )

    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    # Which step number the failure happened on, when we can work it out —
    # the difference between "it failed" and "it failed clicking Login".
    failed_step: Mapped[int | None] = mapped_column(Integer)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    run: Mapped["TestRun"] = relationship(back_populates="results")
    test_case: Mapped["TestCase | None"] = relationship()
    artifacts: Mapped[list["ExecutionArtifact"]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<TestResult {self.case_name} {self.browser.value} {self.status.value}>"


class ExecutionArtifact(Base, TimestampMixin):
    __tablename__ = "execution_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    result_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_results.id", ondelete="CASCADE"), index=True
    )

    type: Mapped[ArtifactType] = mapped_column(
        _enum(ArtifactType, "artifact_type"), nullable=False
    )
    # Relative to settings.storage_dir, never absolute: the database must stay
    # portable across machines, and an absolute path from someone else's laptop
    # is worse than useless.
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    result: Mapped["TestResult | None"] = relationship(back_populates="artifacts")

    def __repr__(self) -> str:
        return f"<ExecutionArtifact {self.type.value} {self.file_path}>"
