"""Recording models — Workflow 1 entry point.

A RecordingSession is one "hit record, do something, hit stop" run in the
browser. Each RecordedAction is one interaction within it.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
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
from app.models.enums import ActionType, RecordingStatus

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.test_case import TestSuite
    from app.models.user import User


class RecordingSession(Base, TimestampMixin):
    __tablename__ = "recording_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[RecordingStatus] = mapped_column(
        SAEnum(
            RecordingStatus,
            name="recording_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=RecordingStatus.RECORDING,
        nullable=False,
        index=True,
    )

    # user agent, viewport, device pixel ratio, platform — whatever the
    # extension knows about the browser it recorded in.
    browser_info: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    extension_version: Mapped[str | None] = mapped_column(String(32))

    # Denormalised counters so listing recordings doesn't need a COUNT per row.
    action_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    project: Mapped["Project"] = relationship()
    created_by: Mapped["User | None"] = relationship()
    actions: Mapped[list["RecordedAction"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="RecordedAction.sequence",
    )
    # The suite generated from this recording, if any. viewonly because
    # TestSuite owns the foreign key and the lifecycle.
    suite: Mapped["TestSuite | None"] = relationship(
        "TestSuite", uselist=False, viewonly=True
    )

    @property
    def suite_id(self) -> int | None:
        """Lets the UI jump from a recording straight to its generated code."""
        return self.suite.id if self.suite is not None else None

    def __repr__(self) -> str:
        return f"<RecordingSession {self.id} {self.name!r} ({self.status.value})>"


class RecordedAction(Base):
    """One captured interaction.

    No TimestampMixin: these arrive in batches of hundreds and the only time
    that matters is `timestamp_ms`, the offset within the recording.
    """

    __tablename__ = "recorded_actions"
    __table_args__ = (
        # Makes batch upload idempotent — re-sending a batch after a flaky
        # network cannot duplicate rows.
        UniqueConstraint("session_id", "sequence", name="uq_recorded_action_sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[ActionType] = mapped_column(
        SAEnum(
            ActionType, name="action_type", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
    )
    # Milliseconds since the recording started. BigInteger because a long
    # session would overflow a 32-bit int.
    timestamp_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # iframe chain from the top document down to the element, empty for the
    # main frame. Phase 3 turns this into chained frame_locator() calls.
    frame_path: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # Ranked selector candidates, best first. See SelectorStrategy.
    selectors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    # tag, role, accessible name, visible text, attributes, bounding box.
    element: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Action-specific data: {"value": ...} for input, {"key": ...} for
    # key_press, and so on. Shape is validated in the Pydantic schema.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Lets a QA engineer drop a noisy step without deleting the evidence.
    is_ignored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    session: Mapped["RecordingSession"] = relationship(back_populates="actions")

    def __repr__(self) -> str:
        return f"<RecordedAction {self.sequence} {self.action_type.value}>"
