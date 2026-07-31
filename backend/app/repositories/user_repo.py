"""User queries."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: Session) -> None:
        super().__init__(db, User)

    def get_by_email(self, email: str) -> User | None:
        # Emails are stored as entered but matched case-insensitively, so
        # "Bob@x.com" and "bob@x.com" are the same account.
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return self.db.scalars(stmt).first()

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def is_first_user(self) -> bool:
        """True when no user exists yet — the first to register becomes admin."""
        return self.count() == 0
