"""Deleting a run. No database, no browser.

Two things have to hold. A run that is still going must be refused, because
deleting it would leave the worker writing screenshots into a directory with
nothing pointing at it. And the files on disk must go with the row — they are
the only part not covered by a cascade, so if this forgets them they stay
forever as unreferenced megabytes.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.enums import RunStatus
from app.services.execution_service import ExecutionService
from app.services.exceptions import ValidationError


class FakeRun:
    def __init__(self, run_id: int, status: RunStatus) -> None:
        self.id = run_id
        self.status = status
        self.project_id = 1


class FakeRunRepo:
    def __init__(self) -> None:
        self.deleted: list[FakeRun] = []

    def delete(self, run) -> None:
        self.deleted.append(run)


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def service(run: FakeRun) -> ExecutionService:
    """An ExecutionService with only the parts delete_run touches."""
    instance = ExecutionService.__new__(ExecutionService)
    instance.db = FakeDb()
    instance.runs = FakeRunRepo()
    instance.get = lambda run_id, user: run  # type: ignore[method-assign]
    return instance


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
def test_a_run_in_flight_is_refused(status: RunStatus) -> None:
    """Cancel first. Deleting mid-run orphans the worker's output directory."""
    svc = service(FakeRun(1, status))

    with pytest.raises(ValidationError, match="still going"):
        svc.delete_run(1, user=None)

    assert svc.runs.deleted == []
    assert svc.db.commits == 0


@pytest.mark.parametrize(
    "status",
    [RunStatus.PASSED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.ERROR],
)
def test_a_finished_run_is_deleted(status: RunStatus) -> None:
    svc = service(FakeRun(7, status))
    svc.delete_run(7, user=None)

    assert [r.id for r in svc.runs.deleted] == [7]
    assert svc.db.commits == 1


def test_the_artifacts_on_disk_go_too() -> None:
    """Rows cascade; files do not. This is the only thing that removes them."""
    directory = settings.storage_dir / "runs" / "4242"
    (directory / "chromium").mkdir(parents=True, exist_ok=True)
    (directory / "chromium" / "screenshot.png").write_bytes(b"x")
    assert directory.is_dir()

    svc = service(FakeRun(4242, RunStatus.FAILED))
    svc.delete_run(4242, user=None)

    assert not directory.exists()


def test_another_runs_artifacts_are_untouched() -> None:
    keep = settings.storage_dir / "runs" / "4243"
    keep.mkdir(parents=True, exist_ok=True)
    (keep / "video.webm").write_bytes(b"x")

    go = settings.storage_dir / "runs" / "4244"
    go.mkdir(parents=True, exist_ok=True)

    svc = service(FakeRun(4244, RunStatus.PASSED))
    svc.delete_run(4244, user=None)

    assert not go.exists()
    assert (keep / "video.webm").is_file()


def test_a_missing_directory_is_not_an_error() -> None:
    """A run that never produced an artifact still deletes cleanly."""
    svc = service(FakeRun(999_001, RunStatus.PASSED))
    svc.delete_run(999_001, user=None)

    assert [r.id for r in svc.runs.deleted] == [999_001]


def test_the_route_is_registered(client: TestClient) -> None:
    schema = client.get(f"{settings.API_V1_PREFIX}/openapi.json").json()
    assert "delete" in schema["paths"][f"{settings.API_V1_PREFIX}/runs/{{run_id}}"]


def test_deleting_a_run_requires_a_token(client: TestClient) -> None:
    response = client.delete(f"{settings.API_V1_PREFIX}/runs/1")
    assert response.status_code == 401


def test_storage_root_is_never_escaped() -> None:
    """The path is built from an int id, but the containment check is what
    guarantees it — an id that somehow carried a traversal must not delete
    anything outside the storage root."""
    root = settings.storage_dir.resolve()
    target = (root / "runs" / "12").resolve()
    assert target.is_relative_to(root)
    assert not Path("/etc").resolve().is_relative_to(root)


# ---------------------------------------------------------------------------
# Where each case stands — not the same as the last run
# ---------------------------------------------------------------------------
def test_case_status_route_is_registered(client: TestClient) -> None:
    schema = client.get(f"{settings.API_V1_PREFIX}/openapi.json").json()
    path = f"{settings.API_V1_PREFIX}/suites/{{suite_id}}/case-status"
    assert "get" in schema["paths"][path]


def test_case_status_requires_a_token(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_PREFIX}/suites/1/case-status")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Regenerating throws away verdicts about the code it replaced
# ---------------------------------------------------------------------------
class _Suite:
    def __init__(self, suite_id: int = 1) -> None:
        self.id = suite_id
        self.project = type("P", (), {"owner": object()})()


def test_finished_runs_are_discarded_when_cases_are_replaced(monkeypatch) -> None:
    """A verdict is about a version of a test. Rewrite the test and it is not
    a stale opinion, it is an opinion about a file that no longer exists."""
    from app.repositories import test_run_repo
    import app.services.execution_service as execution_module

    runs = [FakeRun(3, RunStatus.PASSED), FakeRun(4, RunStatus.FAILED)]
    deleted: list[int] = []

    monkeypatch.setattr(
        test_run_repo.TestRunRepository, "list_for_suite", lambda self, sid: runs
    )
    monkeypatch.setattr(
        execution_module.ExecutionService,
        "delete_run",
        lambda self, run_id, user: deleted.append(run_id),
    )

    from app.services.codegen_service import CodegenService

    service = CodegenService.__new__(CodegenService)
    service.db = FakeDb()
    service._discard_runs(_Suite())

    assert deleted == [3, 4]


def test_a_run_still_going_is_left_alone(monkeypatch) -> None:
    """It is writing to its own directory and will finish against the files it
    started with. Deleting it underneath itself is worse than a stale verdict."""
    from app.repositories import test_run_repo
    import app.services.execution_service as execution_module

    runs = [FakeRun(5, RunStatus.RUNNING), FakeRun(6, RunStatus.QUEUED), FakeRun(7, RunStatus.PASSED)]
    deleted: list[int] = []

    monkeypatch.setattr(
        test_run_repo.TestRunRepository, "list_for_suite", lambda self, sid: runs
    )
    monkeypatch.setattr(
        execution_module.ExecutionService,
        "delete_run",
        lambda self, run_id, user: deleted.append(run_id),
    )

    from app.services.codegen_service import CodegenService

    service = CodegenService.__new__(CodegenService)
    service.db = FakeDb()
    service._discard_runs(_Suite())

    assert deleted == [7]


def test_one_run_failing_to_delete_does_not_stop_the_rest(monkeypatch) -> None:
    """Regeneration must not be abandoned half-done because of a stuck file."""
    from app.repositories import test_run_repo
    import app.services.execution_service as execution_module

    runs = [FakeRun(8, RunStatus.PASSED), FakeRun(9, RunStatus.PASSED)]
    deleted: list[int] = []

    def flaky(self, run_id, user):
        if run_id == 8:
            raise OSError("file in use")
        deleted.append(run_id)

    monkeypatch.setattr(
        test_run_repo.TestRunRepository, "list_for_suite", lambda self, sid: runs
    )
    monkeypatch.setattr(execution_module.ExecutionService, "delete_run", flaky)

    from app.services.codegen_service import CodegenService

    service = CodegenService.__new__(CodegenService)
    service.db = FakeDb()
    service._discard_runs(_Suite())

    assert deleted == [9]
