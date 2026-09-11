"""Authentication and user management.

All the business rules live here — routes just call these methods.
"""

from sqlalchemy.orm import Session

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import RegisterRequest, UserCreate, UserUpdate
from app.services.exceptions import AlreadyExists, Forbidden, NotFound, Unauthorized


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    # ------------------------------------------------------------------
    # Registration & login
    # ------------------------------------------------------------------
    def register(self, data: RegisterRequest) -> User:
        if self.users.email_exists(data.email):
            raise AlreadyExists("That email is already registered")

        # Everyone who signs up gets full access. This is a tool for one QA
        # team, and nobody should have to wait for a promotion before they can
        # create a project and test it. The role column and the checks on it
        # stay, so a tiered model can come back by changing this one line.
        user = self.users.create(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.ADMIN,
            is_active=True,
        )
        self.db.commit()
        return user

    def authenticate(self, email: str, password: str) -> User:
        user = self.users.get_by_email(email)

        # Same error whether the email is unknown or the password is wrong —
        # otherwise this endpoint tells an attacker which emails exist.
        if user is None or not verify_password(password, user.hashed_password):
            raise Unauthorized("Incorrect email or password")

        if not user.is_active:
            raise Forbidden("This account has been deactivated")

        return user

    def issue_tokens(self, user: User) -> tuple[str, str]:
        return create_access_token(user.id), create_refresh_token(user.id)

    def refresh(self, refresh_token: str) -> tuple[User, str, str]:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except TokenError as exc:
            raise Unauthorized(str(exc)) from exc

        user = self.users.get(int(payload["sub"]))
        if user is None or not user.is_active:
            raise Unauthorized("User no longer exists or is inactive")

        access, refresh = self.issue_tokens(user)
        return user, access, refresh

    def get_user_from_access_token(self, token: str) -> User:
        try:
            payload = decode_token(token, expected_type="access")
        except TokenError as exc:
            raise Unauthorized(str(exc)) from exc

        user = self.users.get(int(payload["sub"]))
        if user is None:
            raise Unauthorized("User no longer exists")
        if not user.is_active:
            raise Forbidden("This account has been deactivated")

        return user

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------
    def list_users(self, skip: int = 0, limit: int = 100) -> list[User]:
        return self.users.get_all(skip=skip, limit=limit)

    def get_user(self, user_id: int) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFound(f"User {user_id} not found")
        return user

    def create_user(self, data: UserCreate) -> User:
        if self.users.email_exists(data.email):
            raise AlreadyExists("That email is already registered")

        user = self.users.create(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            is_active=True,
        )
        self.db.commit()
        return user

    def update_user(self, user_id: int, data: UserUpdate, actor: User) -> User:
        user = self.get_user(user_id)
        values = data.model_dump(exclude_unset=True)

        if "password" in values:
            values["hashed_password"] = hash_password(values.pop("password"))

        # Guard against an admin locking everyone out of the instance.
        if user.id == actor.id:
            if values.get("role") not in (None, user.role):
                raise Forbidden("You cannot change your own role")
            if values.get("is_active") is False:
                raise Forbidden("You cannot deactivate yourself")

        user = self.users.update(user, **values)
        self.db.commit()
        return user

    def deactivate_user(self, user_id: int, actor: User) -> User:
        if user_id == actor.id:
            raise Forbidden("You cannot deactivate yourself")

        user = self.get_user(user_id)
        user = self.users.update(user, is_active=False)
        self.db.commit()
        return user
