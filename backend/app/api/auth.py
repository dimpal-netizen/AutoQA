"""Auth and user routes.

Routes stay thin: parse input, call one service method, return the result.
Service errors are converted to HTTP responses by the handler in app/main.py.
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.user import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.auth_service import AuthService

router = APIRouter()

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


@auth_router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: DbSession) -> TokenPair:
    """Create an account. Everyone who signs up gets full access."""
    service = AuthService(db)
    user = service.register(data)
    access, refresh = service.issue_tokens(user)
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


@auth_router.post("/login", response_model=TokenPair)
def login(data: LoginRequest, db: DbSession) -> TokenPair:
    service = AuthService(db)
    user = service.authenticate(data.email, data.password)
    access, refresh = service.issue_tokens(user)
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


@auth_router.post("/refresh", response_model=TokenPair)
def refresh_tokens(data: RefreshRequest, db: DbSession) -> TokenPair:
    user, access, refresh = AuthService(db).refresh(data.refresh_token)
    return TokenPair(access_token=access, refresh_token=refresh, user=UserRead.model_validate(user))


@auth_router.get("/me", response_model=UserRead)
def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


# ---------------------------------------------------------------------------
# User management — test_manager and above
# ---------------------------------------------------------------------------
@users_router.get(
    "",
    response_model=list[UserRead],
    dependencies=[Depends(require_role(UserRole.TEST_MANAGER))],
)
def list_users(db: DbSession, skip: int = 0, limit: int = 100) -> list[UserRead]:
    users = AuthService(db).list_users(skip=skip, limit=limit)
    return [UserRead.model_validate(u) for u in users]


@users_router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def create_user(data: UserCreate, db: DbSession) -> UserRead:
    return UserRead.model_validate(AuthService(db).create_user(data))


@users_router.patch(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def update_user(user_id: int, data: UserUpdate, db: DbSession, actor: CurrentUser) -> UserRead:
    return UserRead.model_validate(AuthService(db).update_user(user_id, data, actor))


@users_router.delete(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def deactivate_user(user_id: int, db: DbSession, actor: CurrentUser) -> UserRead:
    """Soft delete — deactivates the account rather than destroying its history."""
    return UserRead.model_validate(AuthService(db).deactivate_user(user_id, actor))


router.include_router(auth_router)
router.include_router(users_router)
