"""Shared pytest fixtures."""

import tempfile
from pathlib import Path

import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core import database
from app.core.config import settings
from app.main import app

TEST_DB_SUFFIX = "_test"


@pytest.fixture(scope="session", autouse=True)
def _isolate_database():
    """Point every test at its own database, created and dropped here.

    Integration tests register users and create projects. Run against the
    development database they leave that behind, so after a few days the Tests
    page is mostly `checkout-flow` suites from `auto-7fc10e` projects that were
    never real. Nobody notices until the app looks broken.

    Skipped silently if Postgres is not running, since most of the suite does
    not need it.
    """
    url = sqlalchemy.engine.make_url(settings.database_url)
    admin_url = url.set(database="postgres")
    test_url = url.set(database=f"{url.database}{TEST_DB_SUFFIX}")

    admin = sqlalchemy.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{test_url.database}"')
            connection.exec_driver_sql(f'CREATE DATABASE "{test_url.database}"')
    except sqlalchemy.exc.OperationalError:
        yield None  # no Postgres; integration tests will skip on their own
        return
    finally:
        admin.dispose()

    original_engine, original_factory = database.engine, database.SessionLocal
    database.engine = sqlalchemy.create_engine(test_url, pool_pre_ping=True)
    database.SessionLocal = sessionmaker(
        bind=database.engine, autocommit=False, autoflush=False
    )
    database.Base.metadata.create_all(database.engine)

    try:
        yield test_url
    finally:
        database.engine.dispose()
        database.engine, database.SessionLocal = original_engine, original_factory
        admin = sqlalchemy.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{test_url.database}"')
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _isolate_runtime_paths():
    """Send everything the tests write to a temp directory.

    autouse and session-scoped because it is not something a test should have
    to remember. Without it the suite writes real generated scripts, run
    workspaces and screenshots into the user's own folders — every test run
    left another `042-auto-7fc10e` next to their actual work, until
    `generated/` was 24 parts debris to 1 part real.

    The paths are patched on the settings object rather than the environment
    because `Settings` is cached and already loaded by the time tests import.
    """
    with tempfile.TemporaryDirectory(prefix="autoqa-tests-") as tmp:
        root = Path(tmp)
        original = (
            settings.GENERATED_PATH,
            settings.STORAGE_PATH,
            settings.WORKSPACE_PATH,
        )
        settings.GENERATED_PATH = str(root / "generated")
        settings.STORAGE_PATH = str(root / "storage")
        settings.WORKSPACE_PATH = str(root / "workspaces")
        try:
            yield root
        finally:
            (
                settings.GENERATED_PATH,
                settings.STORAGE_PATH,
                settings.WORKSPACE_PATH,
            ) = original


@pytest.fixture(scope="session")
def client() -> TestClient:
    """HTTP client for the API. Does not require Postgres or Redis."""
    with TestClient(app) as test_client:
        yield test_client
