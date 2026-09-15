"""The cookie that lets a signed-in user open the server's screen.

nginx asks /auth/watch-check before serving anything under /record/, with
whatever cookies the browser sent. What matters: a signed-in user gets a
cookie, the check accepts exactly that cookie, and nothing else - not a
missing one, not an access token, not a forged one - gets through.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.auth import WATCH_COOKIE, WATCH_COOKIE_PATH
from app.core.config import settings
from app.core.security import create_access_token
from tests.conftest import register_user

API = settings.API_V1_PREFIX
pytestmark = pytest.mark.integration


@pytest.fixture
def signed_in(client: TestClient) -> dict[str, str]:
    tokens = register_user(client)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_a_signed_in_user_is_given_the_cookie(client: TestClient, signed_in) -> None:
    response = client.post(f"{API}/auth/watch-cookie", headers=signed_in)

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{WATCH_COOKIE}=")
    assert f"Path={WATCH_COOKIE_PATH}" in cookie      # never sent to the API itself
    assert "HttpOnly" in cookie                       # never readable by page scripts
    assert "SameSite=lax" in cookie.lower().replace("samesite=lax", "SameSite=lax")


def test_the_cookie_is_secure_behind_https(client: TestClient, signed_in) -> None:
    response = client.post(
        f"{API}/auth/watch-cookie",
        headers={**signed_in, "X-Forwarded-Proto": "https"},
    )

    assert "Secure" in response.headers["set-cookie"]


def test_nobody_else_gets_one(client: TestClient) -> None:
    assert client.post(f"{API}/auth/watch-cookie").status_code == 401


def test_the_check_accepts_the_cookie_it_issued(client: TestClient, signed_in) -> None:
    issued = client.post(f"{API}/auth/watch-cookie", headers=signed_in)
    token = issued.cookies[WATCH_COOKIE]

    response = client.get(f"{API}/auth/watch-check", cookies={WATCH_COOKIE: token})

    assert response.status_code == 204


def test_the_check_refuses_everything_else(client: TestClient, signed_in) -> None:
    assert client.get(f"{API}/auth/watch-check").status_code == 401

    # An access token is not a watch token, even for the same user.
    me = client.get(f"{API}/auth/me", headers=signed_in).json()
    response = client.get(
        f"{API}/auth/watch-check", cookies={WATCH_COOKIE: create_access_token(me["id"])}
    )
    assert response.status_code == 401

    response = client.get(f"{API}/auth/watch-check", cookies={WATCH_COOKIE: "not.a.token"})
    assert response.status_code == 401
