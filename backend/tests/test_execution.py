"""The execution engine.

Most of these need neither a browser nor a database. The one that runs pytest
for real uses a test that never asks for the `page` fixture, so the whole
pipeline — write files, launch the subprocess, parse the report — is exercised
in about a second instead of the twenty a browser costs.
"""

import textwrap
from pathlib import Path

import pytest

from app.models.enums import ArtifactType, Browser, ResultStatus
from app.runner.executor import (
    ARTIFACT_TYPES,
    ExecutionOutcome,
    _diagnose,
    _materialise,
    _owner,
    _tail,
    run_suite,
)
from app.runner.parser import parse_junit, summarise

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4">
    <testcase classname="tests.test_login" name="test_signs_in[chromium]" time="2.125"/>
    <testcase classname="tests.test_login" name="test_rejects_bad_password" time="0.900">
      <failure message="AssertionError: Locator expected to be visible&#10;more detail">
    tests/test_login.py:20: in test_rejects_bad_password
        # 3. Click "Login"
        login.login_button.click()
      </failure>
    </testcase>
    <testcase classname="tests.test_login" name="test_broken_fixture" time="0.010">
      <error message="fixture 'thing' not found">collection error</error>
    </testcase>
    <testcase classname="tests.test_login" name="test_not_applicable" time="0.001">
      <skipped message="needs staging"/>
    </testcase>
  </testsuite>
</testsuites>
"""


@pytest.fixture
def report(tmp_path: Path) -> Path:
    path = tmp_path / "results.xml"
    path.write_text(JUNIT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_every_outcome_is_distinguished(report: Path):
    results = {r.function_name: r for r in parse_junit(report)}

    assert results["test_signs_in"].status is ResultStatus.PASSED
    assert results["test_rejects_bad_password"].status is ResultStatus.FAILED
    # A fixture that blew up is not a failing assertion: same red tick, wholly
    # different fix, so they must not collapse into one status.
    assert results["test_broken_fixture"].status is ResultStatus.ERROR
    assert results["test_not_applicable"].status is ResultStatus.SKIPPED


def test_parametrised_names_are_stripped(report: Path):
    """pytest reports test_x[chromium]; the test case is called test_x."""
    assert any(r.function_name == "test_signs_in" for r in parse_junit(report))


def test_durations_and_messages_survive(report: Path):
    failed = next(r for r in parse_junit(report) if r.status is ResultStatus.FAILED)

    assert failed.duration_ms == 900
    assert failed.error_message == "AssertionError: Locator expected to be visible"
    assert "login_button.click()" in failed.stack_trace


def test_the_failing_step_is_identified(report: Path):
    """'Failed at step 3' beats 'failed' — the trace echoes our step comments."""
    failed = next(r for r in parse_junit(report) if r.status is ResultStatus.FAILED)
    assert failed.failed_step == 3


def test_a_missing_report_is_not_an_error(tmp_path: Path):
    """pytest can die before writing one. The caller reads the output instead."""
    assert parse_junit(tmp_path / "nope.xml") == []


def test_a_corrupt_report_is_not_an_error(tmp_path: Path):
    path = tmp_path / "results.xml"
    path.write_text("<testsuite><not closed", encoding="utf-8")
    assert parse_junit(path) == []


def test_errors_count_as_failures_in_the_summary(report: Path):
    counts = summarise(parse_junit(report))

    assert counts == {"total": 4, "passed": 1, "failed": 2, "skipped": 1}


# ---------------------------------------------------------------------------
# Writing the workspace
# ---------------------------------------------------------------------------
def test_files_are_written_where_they_belong(tmp_path: Path):
    _materialise({"tests/test_a.py": "x = 1\n", "conftest.py": "y = 2\n"}, tmp_path)

    assert (tmp_path / "tests" / "test_a.py").read_text() == "x = 1\n"
    assert (tmp_path / "conftest.py").read_text() == "y = 2\n"


def test_a_path_escaping_the_workspace_is_refused(tmp_path: Path):
    workspace = tmp_path / "run"
    workspace.mkdir()
    outside = tmp_path / "stolen.txt"

    _materialise({"../stolen.txt": "should not exist", "ok.py": "pass\n"}, workspace)

    assert not outside.exists()
    assert (workspace / "ok.py").exists()  # the safe file still went through


def test_files_are_written_with_unix_newlines(tmp_path: Path):
    """The same suite runs on Windows and CI; mixed newlines make noisy diffs."""
    _materialise({"a.py": "one\ntwo\n"}, tmp_path)
    assert b"\r\n" not in (tmp_path / "a.py").read_bytes()


# ---------------------------------------------------------------------------
# Attributing evidence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "filename",
    [
        "tests-test-demo-py-test-signs-in-chromium_test-failed-1.png",
        "test_signs_in.png",
        "TESTS-TEST-SIGNS-IN[CHROMIUM].webm",
    ],
)
def test_artifacts_are_matched_to_the_test_that_made_them(filename):
    """Filenames vary by tool and version, so we match on what actually ran."""
    assert _owner(filename, ["test_signs_in", "test_other"]) == "test_signs_in"


def test_the_longest_matching_name_wins():
    """test_login must not claim a file belonging to test_login_fails."""
    functions = ["test_login", "test_login_fails"]
    assert _owner("a-test-login-fails-chromium.png", functions) == "test_login_fails"


def test_an_unattributable_artifact_is_not_guessed():
    assert _owner("summary.log", ["test_a"]) is None
    assert _owner("test_a.png", []) is None


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (".png", ArtifactType.SCREENSHOT),
        (".webm", ArtifactType.VIDEO),
        (".zip", ArtifactType.TRACE),
    ],
)
def test_artifacts_are_classified_by_extension(suffix, expected):
    assert ARTIFACT_TYPES[suffix] is expected


# ---------------------------------------------------------------------------
# Explaining a run that produced nothing
# ---------------------------------------------------------------------------
def test_a_missing_browser_is_explained_with_the_fix():
    outcome = ExecutionOutcome(
        browser=Browser.WEBKIT,
        output="Executable doesn't exist at C:\\...\\webkit-2140\\Playwright.exe",
    )
    message = _diagnose(outcome, Browser.WEBKIT)

    assert "playwright install webkit" in message


def test_an_empty_suite_is_explained():
    outcome = ExecutionOutcome(browser=Browser.CHROMIUM, output="collected 0 items")
    assert "No tests were found" in _diagnose(outcome, Browser.CHROMIUM)


def test_output_is_tailed_not_truncated_from_the_front():
    """pytest puts the summary at the end; keeping the head would lose it."""
    tail = _tail("x" * 20_000 + "SUMMARY", None, limit=100)

    assert tail.endswith("SUMMARY")
    assert len(tail) == 100


# ---------------------------------------------------------------------------
# The whole pipeline, for real
# ---------------------------------------------------------------------------
def test_run_suite_executes_and_reports(monkeypatch, tmp_path: Path):
    """Write files, run pytest, parse the report — no browser involved.

    The tests here never request the `page` fixture, so this stays fast while
    still proving the subprocess plumbing works end to end.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_PATH", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "store"))

    bundle = {
        "pytest.ini": "[pytest]\ntestpaths = tests\npython_files = test_*.py\n",
        "tests/test_maths.py": textwrap.dedent(
            """
            def test_passes():
                assert 1 + 1 == 2

            def test_fails():
                # 2. Check the total
                assert 1 + 1 == 3
            """
        ),
    }

    outcome = run_suite(bundle, run_id=1, browser=Browser.CHROMIUM, timeout_s=120)

    statuses = {r.function_name: r.status for r in outcome.results}
    assert statuses == {
        "test_passes": ResultStatus.PASSED,
        "test_fails": ResultStatus.FAILED,
    }
    assert outcome.error is None
    assert outcome.exit_code == 1  # pytest exits 1 when a test fails


def test_runtime_output_never_lands_inside_the_backend_package():
    """Regression guard for a bug that made the Run button unusable.

    `uvicorn --reload` watches the directory it started from for *.py changes.
    A run writes a whole pytest suite of .py files, so pointing workspaces or
    generated output inside backend/ makes every run restart the server and
    kill itself. The symptom was baffling ("pytest produced no report") and the
    cause invisible, so it is worth pinning.
    """
    from app.core.config import BACKEND_DIR, Settings

    # The configured defaults, not settings.* - conftest points those at a temp
    # directory, which would make this pass without checking anything.
    for name in ("WORKSPACE_PATH", "STORAGE_PATH", "GENERATED_PATH"):
        default = Path(Settings.model_fields[name].default)
        resolved = default if default.is_absolute() else (BACKEND_DIR / default).resolve()

        assert not resolved.is_relative_to(BACKEND_DIR), (
            f"{name} defaults to {resolved}, inside {BACKEND_DIR}. Writing .py "
            f"files there triggers the uvicorn reloader mid-run."
        )


def test_the_workspace_is_deleted_afterwards(monkeypatch, tmp_path: Path):
    """Generated code must not accumulate on the user's disk."""
    from app.core.config import settings

    workspaces = tmp_path / "work"
    monkeypatch.setattr(settings, "WORKSPACE_PATH", str(workspaces))
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "store"))

    run_suite(
        {"pytest.ini": "[pytest]\ntestpaths = tests\n", "tests/test_x.py": "def test_x(): pass\n"},
        run_id=2,
        browser=Browser.CHROMIUM,
        timeout_s=120,
    )

    assert not (workspaces / "run_2" / "chromium").exists()
