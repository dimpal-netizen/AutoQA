"""What the AI concluded about a failure.

One row per (result, analysis). Attached to a TestResult rather than a run,
because "failed in WebKit only" and "failed everywhere" are different problems
with different causes, and averaging them into one explanation would lose
exactly the distinction worth knowing.

Cost and token count are stored per analysis. Anything that spends money on
your behalf should be able to say how much.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import FailureCategory, Severity

if TYPE_CHECKING:
    from app.models.test_run import TestResult, TestRun


def _enum(enum_cls, name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class AIAnalysis(Base, TimestampMixin):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    # The two sides of the mismatch, in a person's words. Nullable because
    # every analysis stored before these existed has neither, and inventing
    # them from `root_cause` after the fact would be a guess presented as a
    # finding.
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)

    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[FailureCategory] = mapped_column(
        _enum(FailureCategory, "failure_category"), nullable=False, index=True
    )
    severity: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False, index=True
    )
    priority: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), nullable=False
    )
    # The question a QA engineer actually has: do I raise a bug, or fix my test?
    is_product_bug: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    result: Mapped["TestResult"] = relationship(back_populates="analyses")
    run: Mapped["TestRun"] = relationship()

    def __repr__(self) -> str:
        return f"<AIAnalysis {self.id} {self.category.value} {self.severity.value}>"
