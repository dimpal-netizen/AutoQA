"""Phase 0 smoke tests: the app boots and its config is sane."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_PREFIX}/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == settings.APP_NAME


def test_database_url_is_built_from_parts() -> None:
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.POSTGRES_DB in settings.database_url


def test_list_settings_are_split_on_commas() -> None:
    # Guards the pydantic-settings gotcha: list-typed fields try to JSON-parse
    # env values, so these are stored as strings and split by a property.
    assert settings.default_browsers == ["chromium", "firefox", "webkit"]
    assert all(o.startswith("http") for o in settings.cors_origins)


def test_storage_paths_are_absolute() -> None:
    # These must not depend on the current working directory — Celery workers
    # start from somewhere else than uvicorn does.
    assert settings.storage_dir.is_absolute()
    assert settings.workspace_dir.is_absolute()


@pytest.mark.integration
def test_readiness_reports_dependencies(client: TestClient) -> None:
    """Needs `docker compose up -d`. Run with: pytest -m integration"""
    response = client.get("/health/ready")

    assert response.status_code == 200, response.json()
    assert response.json()["checks"] == {"database": "ok", "redis": "ok"}
