"""Run a generated suite in a subprocess.

Why a subprocess and not an import: the code being run is generated, it opens
real browsers, and it can hang or crash. In-process that takes the API down
with it. Out of process the worst case is a killed child and a recorded error.

Everything about *how* tests run lives in this file. Swapping to a Docker
container per run later means changing `_command()` and nothing above it.

One safety rule, enforced here rather than trusted: files are only ever written
inside the run's own workspace, and the workspace is deleted afterwards.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.models.enums import ArtifactType, Browser, ResultStatus
from app.runner import registry
from app.runner.network import alongside
from app.runner.parser import ParsedResult, parse_junit

logger = logging.getLogger(__name__)

JUNIT_NAME = "results.xml"
ARTIFACT_DIR = "artifacts"

# Extension -> what kind of evidence it is. Anything unrecognised is kept as a
# log rather than dropped; an unexplained file is more useful than no file.
ARTIFACT_TYPES: dict[str, ArtifactType] = {
    ".png": ArtifactType.SCREENSHOT,
    ".jpg": ArtifactType.SCREENSHOT,
    ".jpeg": ArtifactType.SCREENSHOT,
    ".webm": ArtifactType.VIDEO,
    ".mp4": ArtifactType.VIDEO,
    ".zip": ArtifactType.TRACE,
}


@dataclass
class CollectedArtifact:
    type: ArtifactType
    # Relative to settings.storage_dir, so the database stays portable.
    relative_path: str
    size: int
    # Which test it belongs to, worked out from the filename. None means it is
    # a run-level artifact rather than one test's evidence.
    function_name: str | None = None


@dataclass
class ExecutionOutcome:
    """Everything one browser's run produced."""

    browser: Browser
    results: list[ParsedResult] = field(default_factory=list)
    artifacts: list[CollectedArtifact] = field(default_factory=list)
    exit_code: int | None = None
    duration_ms: int = 0
    output: str = ""
    error: str | None = None
    cancelled: bool = False

    @property
    def started(self) -> bool:
        """Whether pytest ran at all, as opposed to failing to launch."""
        return self.error is None


def run_suite(
    bundle: dict[str, str],
    *,
    run_id: int,
    samples: dict[str, bytes] | None = None,
    browser: Browser,
    headless: bool = True,
    base_url: str | None = None,
    timeout_s: int | None = None,
    slow_mo_ms: int = 0,
    on_progress: Callable[[str, ResultStatus], None] | None = None,
    on_started: Callable[[str], None] | None = None,
) -> ExecutionOutcome:
    """Write `bundle` to a fresh workspace, run pytest, collect the evidence.

    `on_progress` is called as each test finishes, parsed from pytest's own
    output while it streams. Without it a thirteen-test run shows nothing for
    two minutes and then everything at once, which is indistinguishable from
    being hung. The JUnit report is still the authority for durations and
    tracebacks; this only makes the wait legible.

    Never raises: a run that cannot start is a recorded outcome with `error`
    set, because the caller has a database row to finish either way.
    """
    timeout_s = timeout_s or settings.RUN_TIMEOUT_SECONDS
    workspace = _workspace(run_id, browser)
    outcome = ExecutionOutcome(browser=browser)
    started = time.monotonic()

    try:
        _materialise(bundle, workspace, samples or {})
    except OSError as exc:
        outcome.error = f"Could not prepare the workspace: {exc}"
        logger.exception("Run %s (%s): workspace failed", run_id, browser.value)
        return outcome

    try:
        outcome.exit_code, output, timed_out = _stream(
            _command(browser, headless=headless, slow_mo_ms=slow_mo_ms),
            cwd=workspace,
            env=_environment(base_url, slow_mo_ms=slow_mo_ms),
            timeout_s=timeout_s,
            run_id=run_id,
            on_progress=on_progress,
            on_started=on_started,
        )
        outcome.output = _tail(output, None)
        if timed_out:
            outcome.error = f"Timed out after {timeout_s}s"
            logger.warning("Run %s (%s): timed out", run_id, browser.value)
    except FileNotFoundError:
        outcome.error = "Python interpreter not found - cannot start pytest"
        logger.exception("Run %s (%s): interpreter missing", run_id, browser.value)
    except OSError as exc:
        outcome.error = f"Could not start pytest: {exc}"
        logger.exception("Run %s (%s): pytest would not start", run_id, browser.value)

    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    outcome.results = parse_junit(workspace / JUNIT_NAME)

    # Collect before cleaning up, or the evidence goes with the workspace.
    # The parsed results are passed in so each file can be tied to the test that
    # produced it — a screenshot nobody can attribute is not evidence.
    try:
        outcome.artifacts = _collect(
            workspace, run_id, browser, [r.function_name for r in outcome.results]
        )
    except OSError:
        logger.exception("Run %s (%s): could not save artifacts", run_id, browser.value)

    _explain_with_the_network(outcome)

    if registry.is_cancelled(run_id):
        # Stopping on purpose is not a failure, and must not be diagnosed as one.
        outcome.cancelled = True
        outcome.error = None
    elif not outcome.results and not outcome.error:
        outcome.error = _diagnose(outcome, browser)

    _cleanup(workspace)
    return outcome


def _explain_with_the_network(outcome: ExecutionOutcome) -> None:
    """Add what the browser could not fetch to the failures that need it.

    The trace is already saved; nothing here reads it back for a test that
    passed, and nothing here decides what the failure means. It puts one fact
    next to the error - see `app/runner/network.py` for why that fact was worth
    going and getting.
    """
    traces = {
        artifact.function_name: settings.storage_dir / artifact.relative_path
        for artifact in outcome.artifacts
        if artifact.type is ArtifactType.TRACE and artifact.function_name
    }
    if not traces:
        return

    for result in outcome.results:
        if result.status not in (ResultStatus.FAILED, ResultStatus.ERROR):
            continue
        trace = traces.get(result.function_name)
        if trace is None:
            continue
        result.error_message = alongside(result.error_message, trace)



# ---------------------------------------------------------------------------
# The pieces
# ---------------------------------------------------------------------------
def _workspace(run_id: int, browser: Browser) -> Path:
    """A fresh directory per (run, browser).

    Per browser, not per run: three browsers write screenshots and video with
    the same filenames, so a shared directory would have them overwriting each
    other's evidence.
    """
    path = settings.workspace_dir / f"run_{run_id}" / browser.value
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _materialise(
    bundle: dict[str, str], workspace: Path, samples: dict[str, bytes] | None = None
) -> None:
    """Write the suite into the workspace, refusing anything outside it."""
    for relative, content in bundle.items():
        destination = (workspace / relative).resolve()
        if not destination.is_relative_to(workspace.resolve()):
            # A path like ../../.ssh/authorized_keys. Generated paths are built
            # by us, but this is cheap and the consequence of being wrong is not.
            logger.error("Refusing to write outside the workspace: %s", relative)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")

    # The project's own files for a test to upload. Beside the suite rather
    # than in the database, because `sample_file` reads them off disk - and a
    # name is somebody else's string, so it is reduced to its last segment
    # before it is joined to anything.
    for name, data in (samples or {}).items():
        leaf = Path(name.replace("\\", "/")).name
        if not leaf or leaf in (".", ".."):
            logger.error("Refusing to write a sample file called %r", name)
            continue
        destination = workspace / "samples" / leaf
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


# "tests/test_login.py::test_signs_in[chromium] PASSED   [ 15%]"
_RESULT_LINE = re.compile(
    r"::(?P<name>[A-Za-z_]\w*)(?:\[[^\]]*\])?\s+"
    r"(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b"
)

# pytest -v writes "tests/test_x.py::test_name " and only appends the status
# when the test ends. Watching the *unfinished* tail is therefore the only way
# to know what is running right now rather than what has just finished.
_STARTED_TAIL = re.compile(r"::(?P<name>[A-Za-z_]\w*)(?:\[[^\]]*\])?\s*$")

_LIVE_STATUS: dict[str, ResultStatus] = {
    "PASSED": ResultStatus.PASSED,
    "XPASS": ResultStatus.PASSED,
    "FAILED": ResultStatus.FAILED,
    "ERROR": ResultStatus.ERROR,
    "SKIPPED": ResultStatus.SKIPPED,
    "XFAIL": ResultStatus.SKIPPED,
}


def _stream(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
    run_id: int,
    on_progress: Callable[[str, ResultStatus], None] | None,
    on_started: Callable[[str], None] | None = None,
) -> tuple[int | None, str, bool]:
    """Run pytest, reporting each test as it starts and as it finishes.

    Reads raw chunks rather than iterating lines. Line iteration only yields
    when a newline arrives, and pytest writes none until a test *ends* — so it
    can say what just finished but never what is running. The unfinished tail
    of the buffer is exactly the test in flight.

    stderr is folded into stdout so the ordering between them survives.
    """
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # Binary and unbuffered: decoding happens here, against a partial
        # buffer that may split mid-character.
        bufsize=0,
        # No shell: the suite name reaches this path from user input, and a
        # shell would make that a command injection.
        shell=False,
    )
    registry.register(run_id, process)

    deadline = time.monotonic() + timeout_s
    collected: list[str] = []
    pending = ""
    announced: str | None = None
    timed_out = False

    def safely(callback, *args) -> None:
        try:
            callback(*args)
        except Exception:
            # A reporting failure must not kill the run it reports on.
            logger.exception("Progress callback failed")

    try:
        while True:
            chunk = process.stdout.read(512) if process.stdout else b""
            if not chunk:
                break

            pending += chunk.decode("utf-8", "replace")
            *complete, pending = pending.split("\n")

            for line in complete:
                collected.append(line + "\n")
                if not on_progress:
                    continue
                match = _RESULT_LINE.search(line)
                status = _LIVE_STATUS.get(match.group("status")) if match else None
                if status is not None:
                    announced = None
                    safely(on_progress, match.group("name"), status)

            # What is left has no newline yet, so pytest is still inside it.
            if on_started:
                started = _STARTED_TAIL.search(pending)
                if started and started.group("name") != announced:
                    announced = started.group("name")
                    safely(on_started, announced)

            if time.monotonic() > deadline:
                timed_out = True
                break
    except Exception:
        logger.exception("Run %s: reading pytest output failed", run_id)
    finally:
        if pending:
            collected.append(pending)
        if timed_out:
            registry.terminate(process)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            registry.terminate(process)
        if process.stdout is not None:
            process.stdout.close()
        registry.unregister(run_id, process)

    return process.returncode, "".join(collected), timed_out


#: The only third-party pytest plugins a generated suite needs. Everything the
#: run relies on beyond these - junitxml, tmp_path, capture - is built into
#: pytest itself and loads whatever `PYTEST_DISABLE_PLUGIN_AUTOLOAD` says.
#:
#: `pytest_base_url` is not optional despite nothing here passing `--base-url`:
#: pytest-playwright asks for a `base_url` fixture, and without the plugin that
#: defines it every test errors on an unknown fixture.
_PLUGINS = ("pytest_playwright.pytest_playwright", "pytest_base_url.plugin")


def _command(browser: Browser, *, headless: bool, slow_mo_ms: int = 0) -> list[str]:
    """The pytest invocation.

    `sys.executable` rather than a bare "pytest": the API may be started from
    any working directory, and this guarantees the interpreter that has
    Playwright installed is the one that runs.
    """
    command = [
        sys.executable,
        "-m",
        "pytest",
        f"--browser={browser.value}",
        f"--junitxml={JUNIT_NAME}",
        f"--output={ARTIFACT_DIR}",
        # A run of generated code should never sit waiting for a debugger or
        # write caches into the user's project.
        "-p",
        "no:cacheprovider",
        "--tb=short",
    ]
    # Load exactly the plugins above and nothing else - see _environment.
    for plugin in _PLUGINS:
        command += ["-p", plugin]
    if not headless:
        command.append("--headed")
    if slow_mo_ms > 0:
        # Playwright drives a browser faster than anyone can follow. Without
        # this, "watch it run" is a window that flickers open and shut.
        command.append(f"--slowmo={slow_mo_ms}")
    return command


def _environment(base_url: str | None, *, slow_mo_ms: int = 0) -> dict[str, str]:
    env = os.environ.copy()
    if slow_mo_ms > 0:
        # Somebody is watching this one. The generated helpers read it to glide
        # the page instead of jumping it - see `_glide` in healing.py.
        env["AUTOQA_WATCH"] = "1"
    if base_url:
        # The generated conftest reads this, so the same suite can be pointed
        # at staging without regenerating anything.
        env["BASE_URL"] = base_url
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # Run the generated suite with only the plugins in `_PLUGINS`.
    #
    # pytest loads every installed `pytest11` entry point by default, and the
    # generated tests run in the API's own interpreter - so they inherit
    # AutoQA's whole dependency tree, pytest plugins and all. Most of that tree
    # is there for the API and has no business in a browser test.
    #
    # This is not tidiness. A plugin that raises while *importing* takes the
    # entire run down before collection, so pytest writes no report at all and
    # every test in the suite is reported blocked - with a traceback pointing
    # into a library the user has never heard of. It happened: `langchain-core`
    # pulls in `langsmith`, whose plugin imports `xxhash`, whose native DLL some
    # Windows machines refuse to load. Nothing there is ours, and none of it is
    # about the application under test.
    #
    # The allowlist is what makes the run depend on the suite instead of on
    # whatever else happens to be installed next to it.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _collect(
    workspace: Path, run_id: int, browser: Browser, functions: list[str]
) -> list[CollectedArtifact]:
    """Move screenshots, video and traces out of the workspace into storage."""
    source = workspace / ARTIFACT_DIR
    if not source.exists():
        return []

    target = settings.storage_dir / "runs" / str(run_id) / browser.value
    target.mkdir(parents=True, exist_ok=True)

    collected: list[CollectedArtifact] = []
    for file in sorted(source.rglob("*")):
        if not file.is_file():
            continue

        kind = ARTIFACT_TYPES.get(file.suffix.lower(), ArtifactType.LOG)
        # Flatten, keeping the parent folder in the name: Playwright nests
        # video under a per-test directory whose name is the only clue about
        # which test it belongs to.
        stem = f"{file.parent.name}_{file.name}" if file.parent != source else file.name
        destination = target / stem

        try:
            shutil.move(str(file), destination)
        except OSError:
            logger.exception("Could not move artifact %s", file)
            continue

        collected.append(
            CollectedArtifact(
                type=kind,
                relative_path=str(destination.relative_to(settings.storage_dir)).replace(
                    "\\", "/"
                ),
                size=destination.stat().st_size,
                function_name=_owner(stem, functions),
            )
        )
    return collected


def _owner(filename: str, functions: list[str]) -> str | None:
    """Which test an artifact belongs to.

    Matched against the functions that actually ran rather than parsed out of
    the filename, because the filename is not ours to predict:
    pytest-playwright slugifies the whole node id with dashes
    (`tests-test-demo-py-test-signs-in-chromium`), our conftest uses the bare
    node name, and neither is stable across versions. Comparing against known
    names survives both.
    """
    if not functions:
        return None

    haystack = filename.replace("-", "_").replace(".", "_").lower()
    # Longest first: `test_login` must not win over `test_login_fails` when both
    # ran and the file belongs to the longer one.
    for function in sorted(functions, key=len, reverse=True):
        if function.lower() in haystack:
            return function
    return None


def _tail(stdout: str | bytes | None, stderr: str | bytes | None, limit: int = 8000) -> str:
    """The end of the output — where pytest puts the summary."""

    def text(value) -> str:
        if value is None:
            return ""
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value

    combined = "\n".join(part for part in (text(stdout), text(stderr)) if part)
    return combined[-limit:]


def _diagnose(outcome: ExecutionOutcome, browser: Browser) -> str | None:
    """Explain an empty run in terms the user can act on."""
    output = outcome.output.lower()

    if "executable doesn't exist" in output or "playwright install" in output:
        return (
            f"{browser.value} is not installed. Run: "
            f"poetry run playwright install {browser.value}"
        )
    if "no tests ran" in output or "collected 0 items" in output:
        return "No tests were found in the generated suite."
    if "error" in output and outcome.exit_code not in (0, 1):
        return f"pytest exited with code {outcome.exit_code} without producing a report."
    return None


def _cleanup(workspace: Path) -> None:
    """Delete the workspace. A failure here is logged, never raised."""
    if not settings.CLEAN_WORKSPACES:
        logger.info("Keeping workspace %s (CLEAN_WORKSPACES is off)", workspace)
        return
    shutil.rmtree(workspace, ignore_errors=True)
