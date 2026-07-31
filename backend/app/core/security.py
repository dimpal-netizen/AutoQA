"""Password hashing and JWT tokens.

Uses bcrypt and PyJWT directly rather than passlib/python-jose: passlib 1.7.4
is incompatible with bcrypt 4.1+ (it reads a private `__about__` attribute that
no longer exists) and both projects are effectively unmaintained.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]

# bcrypt hashes at most 72 bytes and raises on anything longer.
BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Raised when a token is missing, expired, malformed, or the wrong type."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode())
    except ValueError:
        # Stored hash is corrupt or not a bcrypt hash — treat as a failed login.
        return False


def _prepare(password: str) -> bytes:
    """Encode and truncate to bcrypt's 72-byte limit."""
    return password.encode()[:BCRYPT_MAX_BYTES]


def create_access_token(subject: int | str) -> str:
    return _create_token(subject, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(subject: int | str) -> str:
    return _create_token(subject, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def _create_token(subject: int | str, token_type: TokenType, lifetime: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),  # the JWT spec requires `sub` to be a string
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: TokenType = "access") -> dict[str, Any]:
    """Return the token payload, or raise TokenError.

    Checking `type` matters: without it a refresh token would be accepted as an
    access token, silently extending its lifetime to days.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")

    if not payload.get("sub"):
        raise TokenError("Token is missing a subject")

    return payload
