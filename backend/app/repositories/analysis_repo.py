"""Queries for AI failure analyses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_analysis import AIAnalysis
from app.repositories.base import BaseRepository


class AnalysisRepository(BaseRepository[AIAnalysis]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, AIAnalysis)

    def latest_for_result(self, result_id: int) -> AIAnalysis | None:
        """The most recent analysis, since re-analysing appends rather than
        replaces — an earlier conclusion is worth keeping when a later one
        disagrees."""
        statement = (
            select(AIAnalysis)
            .where(AIAnalysis.result_id == result_id)
            .order_by(AIAnalysis.id.desc())
            .limit(1)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_run(self, run_id: int) -> list[AIAnalysis]:
        statement = (
            select(AIAnalysis)
            .where(AIAnalysis.run_id == run_id)
            .order_by(AIAnalysis.id.desc())
        )
        return list(self.db.execute(statement).scalars().all())
