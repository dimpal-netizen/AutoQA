"""User and auth request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole

# bcrypt only hashes the first 72 bytes, so reject longer passwords outright
# rather than silently ignoring the tail.
PASSWORD_MAX = 72


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)


class RegisterRequest(UserBase):
    """Self-service sign-up. No role field: everyone gets full access."""

    password: str = Field(min_length=8, max_length=PASSWORD_MAX)


class UserCreate(UserBase):
    """An admin creating an account, role included."""

    password: str = Field(min_length=8, max_length=PASSWORD_MAX)
    role: UserRole = UserRole.MANUAL_QA


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=PASSWORD_MAX)
    role: UserRole | None = None
    is_active: bool | None = None


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead
