"""Generic repository.

Every database query in the project lives in a repository. Services call
repositories; they never build a query themselves. That keeps SQL in one place
and lets services be tested against a fake repository with no database.

Repositories do NOT commit — the service decides when a unit of work is done.
"""

from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, db: Session, model: type[ModelType]) -> None:
        self.db = db
        self.model = model

    def get(self, id: int) -> ModelType | None:
        return self.db.get(self.model, id)

    def get_all(self, skip: int = 0, limit: int = 100) -> list[ModelType]:
        stmt = select(self.model).order_by(self.model.id).offset(skip).limit(limit)
        return list(self.db.scalars(stmt))

    def count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(self.model)) or 0

    def create(self, **values: Any) -> ModelType:
        instance = self.model(**values)
        self.db.add(instance)
        self.db.flush()      # assigns the primary key without ending the transaction
        self.db.refresh(instance)
        return instance

    def update(self, instance: ModelType, **values: Any) -> ModelType:
        for field, value in values.items():
            setattr(instance, field, value)
        self.db.flush()
        self.db.refresh(instance)
        return instance

    def delete(self, instance: ModelType) -> None:
        self.db.delete(instance)
        self.db.flush()
