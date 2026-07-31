"""End-to-end auth and project flows against a real Postgres.

Requires `docker compose up -d`. Run with:
    poetry run pytest -m integration
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def register(client: TestClient, role: str = "qa_engineer") -> dict:
    """Create a user and return its token payload."""
    response = client.post(
        f"{API}/auth/register",
        json={
            "email": unique_email(),
            "password": "supersecret123",
            "full_name": "Test User",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_register_login_and_me(client: TestClient) -> None:
    tokens = register(client)
    email = tokens["user"]["email"]

    login = client.post(f"{API}/auth/login", json={"email": email, "password": "supersecret123"})
    assert login.status_code == 200, login.text

    me = client.get(f"{API}/auth/me", headers=auth_header(login.json()))
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_duplicate_email_is_rejected(client: TestClient) -> None:
    tokens = register(client)

    again = client.post(
        f"{API}/auth/register",
        json={"email": tokens["user"]["email"], "password": "supersecret123"},
    )
    assert again.status_code == 409


def test_login_with_a_wrong_password_fails(client: TestClient) -> None:
    tokens = register(client)

    response = client.post(
        f"{API}/auth/login",
        json={"email": tokens["user"]["email"], "password": "not-the-password"},
    )
    assert response.status_code == 401
    # The message must not reveal whether the email exists.
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_with_an_unknown_email_gives_the_same_error(client: TestClient) -> None:
    response = client.post(
        f"{API}/auth/login", json={"email": unique_email(), "password": "whatever123"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_refresh_returns_new_tokens(client: TestClient) -> None:
    tokens = register(client)

    response = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200

    me = client.get(f"{API}/auth/me", headers=auth_header(response.json()))
    assert me.status_code == 200


def test_access_token_cannot_be_used_to_refresh(client: TestClient) -> None:
    tokens = register(client)

    response = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------
def test_manual_qa_cannot_list_users(client: TestClient) -> None:
    tokens = register(client, role="manual_qa")

    response = client.get(f"{API}/users", headers=auth_header(tokens))
    assert response.status_code == 403
    assert "test_manager" in response.json()["detail"]


def test_manual_qa_cannot_create_a_project(client: TestClient) -> None:
    tokens = register(client, role="manual_qa")

    response = client.post(
        f"{API}/projects",
        headers=auth_header(tokens),
        json={"name": "Nope", "base_url": "https://example.com"},
    )
    assert response.status_code == 403


def test_test_manager_can_list_users(client: TestClient) -> None:
    tokens = register(client, role="test_manager")

    response = client.get(f"{API}/users", headers=auth_header(tokens))
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def test_project_crud(client: TestClient) -> None:
    tokens = register(client, role="qa_engineer")
    headers = auth_header(tokens)
    name = f"Shop {uuid.uuid4().hex[:6]}"

    created = client.post(
        f"{API}/projects",
        headers=headers,
        json={
            "name": name,
            "base_url": "https://shop.example.com",
            "description": "Checkout flows",
            "default_browsers": ["chromium", "firefox"],
        },
    )
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["default_browsers"] == ["chromium", "firefox"]
    assert project["owner_id"] == tokens["user"]["id"]

    fetched = client.get(f"{API}/projects/{project['id']}", headers=headers)
    assert fetched.status_code == 200

    updated = client.patch(
        f"{API}/projects/{project['id']}",
        headers=headers,
        json={"description": "Updated", "default_browsers": ["webkit"]},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated"
    assert updated.json()["default_browsers"] == ["webkit"]

    listed = client.get(f"{API}/projects", headers=headers)
    assert any(p["id"] == project["id"] for p in listed.json())

    assert client.delete(f"{API}/projects/{project['id']}", headers=headers).status_code == 204
    assert client.get(f"{API}/projects/{project['id']}", headers=headers).status_code == 404


def test_duplicate_project_name_for_same_owner_is_rejected(client: TestClient) -> None:
    headers = auth_header(register(client, role="qa_engineer"))
    name = f"Dup {uuid.uuid4().hex[:6]}"
    body = {"name": name, "base_url": "https://example.com"}

    assert client.post(f"{API}/projects", headers=headers, json=body).status_code == 201
    assert client.post(f"{API}/projects", headers=headers, json=body).status_code == 409


def test_another_users_project_is_invisible(client: TestClient) -> None:
    owner_headers = auth_header(register(client, role="qa_engineer"))
    created = client.post(
        f"{API}/projects",
        headers=owner_headers,
        json={"name": f"Private {uuid.uuid4().hex[:6]}", "base_url": "https://example.com"},
    )
    project_id = created.json()["id"]

    stranger_headers = auth_header(register(client, role="qa_engineer"))
    response = client.get(f"{API}/projects/{project_id}", headers=stranger_headers)

    # 404, not 403 — a 403 would confirm the project exists.
    assert response.status_code == 404


def test_invalid_base_url_is_rejected(client: TestClient) -> None:
    headers = auth_header(register(client, role="qa_engineer"))

    response = client.post(
        f"{API}/projects", headers=headers, json={"name": "Bad", "base_url": "not-a-url"}
    )
    assert response.status_code == 422
