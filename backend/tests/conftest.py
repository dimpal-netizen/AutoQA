"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """HTTP client for the API. Does not require Postgres or Redis."""
    with TestClient(app) as test_client:
        yield test_client
