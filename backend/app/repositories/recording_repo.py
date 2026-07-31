"""Recording queries."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from app.models.recording import RecordedAction, RecordingSession
from app.repositories.base import BaseRepository


class RecordingRepository(BaseRepository[RecordingSession]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, RecordingSession)

    def get_with_actions(self, session_id: int) -> RecordingSession | None:
        stmt = (
            select(RecordingSession)
            .where(RecordingSession.id == session_id)
            .options(selectinload(RecordingSession.actions))
        )
        return self.db.scalars(stmt).first()

    def list_for_projects(
        self, project_ids: list[int], skip: int = 0, limit: int = 100
    ) -> list[RecordingSession]:
        if not project_ids:
            return []
        stmt = (
            select(RecordingSession)
            .where(RecordingSession.project_id.in_(project_ids))
            .order_by(RecordingSession.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def add_actions(self, session_id: int, rows: list[dict[str, Any]]) -> int:
        """Insert actions, ignoring ones already stored. Returns how many were new.

        Uses ON CONFLICT DO NOTHING against uq_recorded_action_sequence so a
        client that retries a batch after a network timeout gets the same
        result instead of duplicate steps.
        """
        if not rows:
            return 0

        stmt = (
            pg_insert(RecordedAction)
            .values([{**row, "session_id": session_id} for row in rows])
            .on_conflict_do_nothing(constraint="uq_recorded_action_sequence")
            .returning(RecordedAction.id)
        )
        return len(list(self.db.scalars(stmt)))

    def get_action(self, session_id: int, action_id: int) -> RecordedAction | None:
        stmt = select(RecordedAction).where(
            RecordedAction.id == action_id,
            RecordedAction.session_id == session_id,
        )
        return self.db.scalars(stmt).first()

    def list_actions(
        self, session_id: int, skip: int = 0, limit: int = 1000
    ) -> list[RecordedAction]:
        stmt = (
            select(RecordedAction)
            .where(RecordedAction.session_id == session_id)
            .order_by(RecordedAction.sequence)
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def count_actions(self, session_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(RecordedAction)
            .where(RecordedAction.session_id == session_id)
        )
        return self.db.scalar(stmt) or 0

    def max_timestamp_ms(self, session_id: int) -> int | None:
        stmt = select(func.max(RecordedAction.timestamp_ms)).where(
            RecordedAction.session_id == session_id
        )
        return self.db.scalar(stmt)

    def delete_action(self, action: RecordedAction) -> None:
        self.db.delete(action)
        self.db.flush()
