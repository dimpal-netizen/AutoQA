"""Shared FastAPI dependencies: database session, current user, role checks."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import ROLE_LEVEL, UserRole
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.exceptions import ServiceError

# auto_error=False so a missing header produces our own 401 with a WWW-Authenticate
# header, rather than FastAPI's bare 403.
bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return AuthService(db).get_user_from_access_token(credentials.credentials)
    except ServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: UserRole) -> Callable[[User], User]:
    """Dependency factory for a minimum role.

    Roles are hierarchical, so `require_role(UserRole.QA_ENGINEER)` admits
    qa_engineer, test_manager, and admin.

        @router.post("/users", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    def dependency(user: CurrentUser) -> User:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {minimum.value} role or higher",
            )
        return user

    return dependency
