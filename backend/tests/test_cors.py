"""CORS must accept the app however you opened it in development.

A mismatch here shows up in the browser as a bare "Failed to fetch" with no
clue that the origin was the problem, so it is worth pinning.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

LOCAL_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://[::1]:3000",
    "http://192.168.1.135:3000",
    "http://10.0.0.5:3000",
    "http://172.16.4.2:3000",
    "http://localhost:5173",  # a different dev server port
]


@pytest.mark.parametrize("origin", LOCAL_ORIGINS)
def test_preflight_allows_local_origins(client: TestClient, origin: str) -> None:
    response = client.options(
        f"{settings.API_V1_PREFIX}/projects/1/recordings/launch",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200, f"{origin} was rejected"
    assert response.headers.get("access-control-allow-origin") == origin


def test_external_origin_is_still_rejected(client: TestClient) -> None:
    response = client.options(
        f"{settings.API_V1_PREFIX}/projects/1/recordings/launch",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_production_uses_the_explicit_list_only() -> None:
    # The permissive regex is a development convenience and must not leak into
    # production, where only CORS_ORIGINS should be honoured.
    production = settings.model_copy(update={"ENVIRONMENT": "production"})

    assert production.cors_origin_regex is None
