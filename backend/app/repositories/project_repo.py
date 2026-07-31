"""Project queries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, Project)

    def get_by_owner(self, owner_id: int, skip: int = 0, limit: int = 100) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.owner_id == owner_id)
            .order_by(Project.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_all(self, skip: int = 0, limit: int = 100) -> list[Project]:
        stmt = select(Project).order_by(Project.created_at.desc()).offset(skip).limit(limit)
        return list(self.db.scalars(stmt))

    def name_taken_by_owner(self, owner_id: int, name: str, exclude_id: int | None = None) -> bool:
        stmt = select(Project.id).where(
            Project.owner_id == owner_id,
            func.lower(Project.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(Project.id != exclude_id)
        return self.db.scalars(stmt).first() is not None
