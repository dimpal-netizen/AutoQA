"""A bug report drafted from a failure.

Written from the test, its steps, the error and — when there is one — the AI
analysis. The point is a ticket a developer can act on without opening AutoQA:
what to do, what should happen, what actually happened, and where.

It starts as a DRAFT. Nobody should discover an AI-written ticket in their
backlog that no human ever read.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum as SAEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import BugStatus, Severity

if TYPE_CHECKING:
    from app.models.ai_analysis import AIAnalysis
    from app.models.project import Project
    from app.models.test_run import TestResult
    from app.models.user import User


def _enum(enum_cls, name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class BugReport(Base, TimestampMixin):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    result_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_results.id", ondelete="SET NULL"), index=True
    )
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_analyses.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # A list of strings, in order. A developer who cannot reproduce it will
    # close it, so this is the part that decides whether the report is useful.
    steps_to_reproduce: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    actual: Mapped[str] = mapped_column(Text, nullable=False)
    # Browser, URL, when it ran. Copied rather than joined, so the ticket still
    # reads correctly after the run is deleted.
    environment: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    severity: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, index=True
    )
    priority: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), nullable=False)
    status: Mapped[BugStatus] = mapped_column(
        _enum(BugStatus, "bug_status"), default=BugStatus.DRAFT, nullable=False, index=True
    )

    project: Mapped["Project"] = relationship()
    result: Mapped["TestResult | None"] = relationship()
    analysis: Mapped["AIAnalysis | None"] = relationship()
    created_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<BugReport {self.id} {self.severity.value} {self.title[:40]!r}>"
