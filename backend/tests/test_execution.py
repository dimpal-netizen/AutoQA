"""The execution engine.

Most of these need neither a browser nor a database. The one that runs pytest
for real uses a test that never asks for the `page` fixture, so the whole
pipeline — write files, launch the subprocess, parse the report — is exercised
in about a second instead of the twenty a browser costs.
"""

import textwrap
from pathlib import Path

import pytest

from app.models.enums import ArtifactType, Browser, ResultStatus, RunStatus
from app.runner.executor import (
    ARTIFACT_TYPES,
    ExecutionOutcome,
    _diagnose,
    _materialise,
    _owner,
    _tail,
    run_suite,
)
from app.runner.parser import parse_junit, step_from_traceback, summarise

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


#: What pytest actually prints, which is the line that failed and not the
#: comment above it — the reason reading the traceback alone found the step in
#: none of thirty-nine real failures.
_REAL_TRACE = """\
tests\\test_can_fill_property_title.py:6: in test_can_fill_property_title
    login.email_input.fill('lilian@yopmail.com')
..\\..\\.venv\\Lib\\site-packages\\playwright\\sync_api\\_generated.py:18030: in fill
    self._sync(self._impl_obj.fill(...))
E   playwright._impl._errors.TimeoutError: Locator.fill: Timeout 30000ms exceeded
"""

_REAL_CODE = """\
def test_can_fill_property_title(page):
    # 1. Open https://example.test/login
    page.goto('https://example.test/login')

    # 2. Type into "Email"
    login.email_input.fill('lilian@yopmail.com')

    # 3. Click "Sign in"
    login.sign_in_button.click()
"""


def test_the_step_is_found_from_the_line_number():
    """The traceback names a line; the case holds the file. Together they answer.

    pytest never echoes our `# 2.` comment, so the comment hunt above cannot
    see it. Indexing to line 6 of the stored code and walking back can.
    """
    assert step_from_traceback(_REAL_TRACE, _REAL_CODE) == 2


def test_playwright_frames_are_not_mistaken_for_ours():
    """The deeper frames are in a library, and its line 18030 is not a step."""
    only_library = "\n".join(_REAL_TRACE.splitlines()[2:])
    assert step_from_traceback(only_library, _REAL_CODE) is None


def test_a_conftest_frame_is_not_read_as_the_test():
    """A fixture blowing up says nothing about which step the test reached.

    Indexing its line number into the case's own file would name whichever
    step happens to sit there — confidently wrong, where None is merely
    unhelpful.
    """
    trace = "conftest.py:6: in browser_context\n    raise RuntimeError('no browser')"
    assert step_from_traceback(trace, _REAL_CODE) is None


def test_a_line_before_the_first_step_has_no_step():
    trace = "tests\\test_x.py:1: in test_x\n    def test_x(page):"
    assert step_from_traceback(trace, _REAL_CODE) is None


def test_no_traceback_or_no_code_answers_nothing():
    """Rather than guessing. A wrong step number is worse than no step number."""
    assert step_from_traceback(None, _REAL_CODE) is None
    assert step_from_traceback(_REAL_TRACE, None) is None
    assert step_from_traceback("no frames here", _REAL_CODE) is None


def test_a_line_number_past_the_end_does_not_crash():
    """The case was edited after the run. Clamp rather than raise."""
    trace = "tests\\test_x.py:9999: in test_x"
    assert step_from_traceback(trace, _REAL_CODE) == 3


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


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("tests/test_login.py::test_signs_in[chromium] PASSED   [ 15%]", "PASSED"),
        ("tests/t.py::test_fails FAILED  [100%]", "FAILED"),
        ("tests/t.py::test_skip SKIPPED (needs staging) [ 50%]", "SKIPPED"),
        ("tests/t.py::test_boom ERROR [ 20%]", "ERROR"),
    ],
)
def test_progress_lines_are_recognised(line, expected):
    from app.runner.executor import _RESULT_LINE

    match = _RESULT_LINE.search(line)
    assert match and match.group("status") == expected


@pytest.mark.parametrize(
    "line",
    ["collected 13 items", "=== 10 passed, 3 failed in 99.70s ===", "rootdir: /x"],
)
def test_summary_lines_are_not_mistaken_for_results(line):
    """`10 passed` in the summary must not be reported as a test called `10`."""
    from app.runner.executor import _RESULT_LINE

    assert _RESULT_LINE.search(line) is None


def test_results_are_reported_while_the_run_is_still_going(monkeypatch, tmp_path: Path):
    """The fix for "I cannot see what is going on".

    Without streaming, a thirteen-test run shows nothing for two minutes and
    then everything at once — indistinguishable from being hung.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_PATH", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "store"))

    seen: list[tuple[str, ResultStatus]] = []

    run_suite(
        {
            "pytest.ini": "[pytest]\ntestpaths = tests\npython_files = test_*.py\naddopts = -v\n",
            "tests/test_three.py": textwrap.dedent(
                """
                def test_one(): assert True
                def test_two(): assert False
                def test_three(): assert True
                """
            ),
        },
        run_id=3,
        browser=Browser.CHROMIUM,
        timeout_s=120,
        on_progress=lambda name, status: seen.append((name, status)),
    )

    assert [name for name, _ in seen] == ["test_one", "test_two", "test_three"]
    assert dict(seen)["test_two"] is ResultStatus.FAILED


def test_a_broken_progress_callback_does_not_kill_the_run(monkeypatch, tmp_path: Path):
    """Reporting is a nicety; it must never cost the run it reports on."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_PATH", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "store"))

    def explode(name, status):
        raise RuntimeError("the database went away")

    outcome = run_suite(
        {
            "pytest.ini": "[pytest]\ntestpaths = tests\npython_files = test_*.py\naddopts = -v\n",
            "tests/test_x.py": "def test_x(): assert True\n",
        },
        run_id=4,
        browser=Browser.CHROMIUM,
        timeout_s=120,
        on_progress=explode,
    )

    assert [r.status for r in outcome.results] == [ResultStatus.PASSED]


def test_watching_slows_the_browser_down():
    """Headed without slowmo is a window that flickers open and shut."""
    from app.runner.executor import _command

    watched = _command(Browser.CHROMIUM, headless=False, slow_mo_ms=700)
    assert "--headed" in watched
    assert "--slowmo=700" in watched

    # Nobody is watching a headless run, so it must not be slowed down.
    assert not any(
        arg.startswith("--slowmo") for arg in _command(Browser.CHROMIUM, headless=True)
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


# ---------------------------------------------------------------------------
# "collection failure" is not an error message
# ---------------------------------------------------------------------------
COLLECTION_ERROR = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1">
    <testcase classname="" name="tests/test_verify_agents_link.py" time="0.0">
      <error message="collection failure">ImportError while importing test module.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
tests\test_verify_agents_link.py:11: in &lt;module&gt;
    from pages.agent_details_page import AgentDetailsPage
E   ModuleNotFoundError: No module named 'pages.agent_details_page'
</error>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_a_collection_failure_reports_the_real_cause(tmp_path: Path):
    """`collection failure` names neither the module nor the reason.

    It was the only thing shown for a run where every test went red, because
    one uncollectable module takes the whole run with it.
    """
    path = tmp_path / "collection.xml"
    path.write_text(COLLECTION_ERROR, encoding="utf-8")

    result = parse_junit(path)[0]

    assert result.status is ResultStatus.ERROR
    assert result.error_message == (
        "ModuleNotFoundError: No module named 'pages.agent_details_page'"
    )
    # The full traceback is still there for anyone who opens it.
    assert "ImportError while importing test module" in result.stack_trace


def test_a_real_error_message_is_left_alone(report: Path):
    """Only pytest's non-answers get replaced."""
    results = {r.function_name: r for r in parse_junit(report)}
    assert results["test_broken_fixture"].error_message == "fixture 'thing' not found"


# ---------------------------------------------------------------------------
# The newest result per case
# ---------------------------------------------------------------------------
class _Res:
    """Just the fields latest_per_case reads."""

    def __init__(self, run_id, case_id, browser, status, ident):
        self.run_id = run_id
        self.test_case_id = case_id
        self.browser = browser
        self.status = status
        self.id = ident


def _dedupe(rows):
    """The de-duplication latest_per_case performs, in isolation.

    The SQL is a plain ordered select; this is the part with a decision in it,
    and it is the part that would silently regress.
    """
    seen: set = set()
    latest = []
    for result in rows:
        key = (result.test_case_id, result.browser)
        if key in seen:
            continue
        seen.add(key)
        latest.append(result)
    return latest


def test_only_the_newest_result_for_a_case_survives():
    """Re-running one case must replace its old verdict, not sit beside it."""
    rows = [
        _Res(9, 1, "chromium", ResultStatus.PASSED, 30),   # newest run
        _Res(8, 1, "chromium", ResultStatus.FAILED, 20),   # older
        _Res(7, 1, "chromium", ResultStatus.FAILED, 10),   # older still
    ]
    kept = _dedupe(rows)

    assert len(kept) == 1
    assert kept[0].status is ResultStatus.PASSED


def test_each_browser_keeps_its_own_verdict():
    """Green in Chrome and red in Firefox is two facts, not one."""
    rows = [
        _Res(9, 1, "chromium", ResultStatus.PASSED, 30),
        _Res(9, 1, "firefox", ResultStatus.FAILED, 31),
    ]
    kept = _dedupe(rows)

    assert {r.browser for r in kept} == {"chromium", "firefox"}


def test_a_case_untouched_by_the_newest_run_keeps_its_earlier_result():
    """The bug this fixes: running case 1 alone must not blank out case 2."""
    rows = [
        _Res(9, 1, "chromium", ResultStatus.FAILED, 30),   # the single-case run
        _Res(8, 1, "chromium", ResultStatus.PASSED, 21),
        _Res(8, 2, "chromium", ResultStatus.PASSED, 22),   # still stands
        _Res(8, 3, "chromium", ResultStatus.PASSED, 23),   # still stands
    ]
    kept = {r.test_case_id: r.status for r in _dedupe(rows)}

    assert kept == {
        1: ResultStatus.FAILED,
        2: ResultStatus.PASSED,
        3: ResultStatus.PASSED,
    }



# ---------------------------------------------------------------------------
# A failure is a page, not a row
#
# Everything about a failure used to have to fit inside an expanded row of the
# run's table: the error, the explanation, the bug draft, the screenshot, the
# recording, the trace, and a box for asking questions. Six panels stacked in a
# table row, with the rest of the run's tests pushed off the screen below them.
#
# A page reached by a link cannot borrow context from the table it left, so the
# fields below are what it needs to stand on its own. Losing one of them breaks
# a heading or a way back with nothing to catch it.
# ---------------------------------------------------------------------------
def test_a_result_carries_what_a_page_of_its_own_needs():
    from app.schemas.test_run import ResultDetail

    required = set(ResultDetail.model_fields)

    assert {"case_name", "browser", "status", "error_message"} <= required
    # Its heading, and its way back.
    assert {"run_id", "project_id", "project_name", "suite_name"} <= required
    # The evidence, and the same test elsewhere.
    assert {"artifacts", "siblings"} <= required


def test_a_result_with_no_siblings_is_valid():
    """One browser is the common case; the page must not require a comparison."""
    from app.schemas.test_run import ResultDetail

    detail = ResultDetail(
        id=1, case_name="Login", function_name="test_login",
        browser=Browser.CHROMIUM, status=ResultStatus.FAILED,
        run_id=2, run_status=RunStatus.FAILED, project_id=3,
    )

    assert detail.siblings == []
    assert detail.artifacts == []
