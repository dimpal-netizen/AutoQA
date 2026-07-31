"""Password hashing and JWT — no database needed."""

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_same_password_hashes_differently() -> None:
    # Each hash uses a fresh salt, so identical passwords must not collide.
    assert hash_password("hunter2000") != hash_password("hunter2000")


def test_long_password_does_not_crash() -> None:
    # bcrypt raises above 72 bytes; we truncate instead.
    long_password = "a" * 200
    assert verify_password(long_password, hash_password(long_password))


def test_verify_rejects_a_corrupt_hash() -> None:
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_access_token_round_trip() -> None:
    payload = decode_token(create_access_token(42), expected_type="access")

    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_refresh_token_is_rejected_as_an_access_token() -> None:
    # Without the type check, a refresh token would work as an access token and
    # quietly extend its lifetime from minutes to days.
    with pytest.raises(TokenError, match="Expected an? access token"):
        decode_token(create_refresh_token(42), expected_type="access")


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(TokenError, match="invalid"):
        decode_token("not.a.token")
