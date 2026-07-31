"""Every Phase 1 route is wired up. Reads the OpenAPI schema — no database."""

from fastapi.testclient import TestClient

from app.core.config import settings

EXPECTED = [
    ("/auth/register", "post"),
    ("/auth/login", "post"),
    ("/auth/refresh", "post"),
    ("/auth/me", "get"),
    ("/users", "get"),
    ("/users", "post"),
    ("/users/{user_id}", "patch"),
    ("/users/{user_id}", "delete"),
    ("/projects", "get"),
    ("/projects", "post"),
    ("/projects/{project_id}", "get"),
    ("/projects/{project_id}", "patch"),
    ("/projects/{project_id}", "delete"),
]


def test_all_phase_1_routes_exist(client: TestClient) -> None:
    schema = client.get(f"{settings.API_V1_PREFIX}/openapi.json").json()
    paths = schema["paths"]

    missing = [
        f"{method.upper()} {path}"
        for path, method in EXPECTED
        if method not in paths.get(f"{settings.API_V1_PREFIX}{path}", {})
    ]
    assert not missing, f"Routes not registered: {missing}"


def test_protected_routes_require_a_token(client: TestClient) -> None:
    for path in ("/auth/me", "/projects", "/users"):
        response = client.get(f"{settings.API_V1_PREFIX}{path}")
        assert response.status_code == 401, f"{path} should require auth"
        assert response.headers.get("www-authenticate") == "Bearer"


def test_bad_token_is_rejected(client: TestClient) -> None:
    response = client.get(
        f"{settings.API_V1_PREFIX}/auth/me",
        headers={"Authorization": "Bearer garbage"},
    )
    assert response.status_code == 401
