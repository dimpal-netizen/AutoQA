"""Read pytest's JUnit XML back into results.

Parsing a machine-readable report is deliberate. The alternative — scraping
pytest's console output — breaks on every version bump, on colour codes, and on
any test that prints something that looks like a result line.

JUnit XML shape we care about:

    <testsuite>
      <testcase classname="tests.test_login" name="test_signs_in" time="2.13"/>
      <testcase name="test_rejects_bad_password" time="0.90">
        <failure message="...">full traceback</failure>
      </testcase>
    </testsuite>

A testcase with no child element passed. One child says how it did not.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.models.enums import ResultStatus

logger = logging.getLogger(__name__)

# "tests/test_login.py:31: AssertionError" — the last frame inside the test file
# is almost always the line a QA engineer wants, not the deepest frame in
# Playwright's internals.
_STEP_HINT = re.compile(r"^\s*#\s*(\d+)\.", re.MULTILINE)


@dataclass
class ParsedResult:
    """One test, one browser, as pytest reported it."""

    function_name: str
    status: ResultStatus
    duration_ms: int
    error_message: str | None = None
    stack_trace: str | None = None
    failed_step: int | None = None


def parse_junit(path: Path) -> list[ParsedResult]:
    """Read a JUnit XML file. Returns [] if it is missing or unreadable.

    Missing is a normal case, not an exception: if pytest crashed before it
    could write a report there is nothing to parse, and the caller already
    handles "no results" by reading the process output instead.
    """
    if not path.exists():
        logger.warning("No JUnit report at %s", path)
        return []

    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError:
        logger.exception("JUnit report at %s is not valid XML", path)
        return []

    results: list[ParsedResult] = []
    for case in root.iter("testcase"):
        results.append(_parse_case(case))
    return results


def _parse_case(case) -> ParsedResult:
    name = case.get("name", "unknown")
    # pytest appends the parametrisation to the node name: test_x[chromium].
    function_name = name.split("[", 1)[0]

    try:
        duration_ms = int(float(case.get("time", "0")) * 1000)
    except ValueError:
        duration_ms = 0

    failure = case.find("failure")
    error = case.find("error")
    skipped = case.find("skipped")

    if failure is not None:
        trace = (failure.text or "")
        return ParsedResult(
            function_name=function_name,
            # Not always FAILED. A test that could not reach its element never
            # asked the application anything, so it has no verdict to report -
            # see `could_not_run`.
            status=(
                ResultStatus.ERROR
                if could_not_run(failure.get("message"), trace)
                else ResultStatus.FAILED
            ),
            duration_ms=duration_ms,
            error_message=_summarise(failure.get("message")),
            stack_trace=trace.strip() or None,
            failed_step=_failed_step(trace),
        )

    if error is not None:
        # A test that could not run at all: a fixture blew up, an import
        # failed, the browser is not installed. Distinct from a failed
        # assertion because the fix is completely different.
        trace = (error.text or "").strip() or None
        return ParsedResult(
            function_name=function_name,
            status=ResultStatus.ERROR,
            duration_ms=duration_ms,
            error_message=_error_summary(error.get("message"), trace),
            stack_trace=trace,
        )

    if skipped is not None:
        return ParsedResult(
            function_name=function_name,
            status=ResultStatus.SKIPPED,
            duration_ms=duration_ms,
            error_message=_summarise(skipped.get("message")),
        )

    return ParsedResult(
        function_name=function_name, status=ResultStatus.PASSED, duration_ms=duration_ms
    )


#: Playwright verbs that *drive* the page. Every one of them needs the element
#: to be there and usable before anything about the application is being asked.
_DRIVING = (
    "click", "dblclick", "fill", "type", "press", "check", "uncheck",
    "select_option", "hover", "set_input_files", "drag_to", "focus", "tap",
    "clear", "select_text",
)

_ACTION_TIMEOUT = re.compile(
    rf"Locator\.(?:{'|'.join(_DRIVING)}): Timeout \d+ms exceeded", re.I
)

#: Playwright's own words for "I found it and could not use it".
_UNUSABLE = (
    "element is not visible",
    "element is not enabled",
    "element is not stable",
    "element is outside of the viewport",
    "intercepts pointer events",
)


def could_not_run(message: str | None, trace: str | None) -> bool:
    """Did this test fail to ask the application anything?

    The distinction this draws is the whole difference between a report a tester
    can act on and one that wastes their afternoon:

      * An **assertion** failed. The test reached the page, made a claim about
        it, and the claim was false. That is a finding about the application,
        and it should be red.

      * An **action** could not reach its element. The test never got as far as
        asking a question, so it has no answer to report - about the
        application or about anything else. Filing that as a defect points a
        developer at a page that works.

    Two shapes qualify, and both are Playwright saying so in its own words.

    A strict mode violation: the locator named more than one element and
    Playwright refused to guess. Nothing about the page is in question.

    An action that timed out on an element it *found*:

        Locator.click: Timeout 30000ms exceeded.
          - locator resolved to <input type="checkbox"/>
          - element is not visible

    "resolved to" is the load-bearing half. An element found and unusable is a
    hidden control, a menu that never opened, a spinner over the button - our
    problem every time. An element never found at all is left as a failure on
    purpose: the page genuinely not rendering its Submit button is a real bug,
    and it looks exactly the same as a selector that has gone stale. Between
    quietly downgrading a real defect and occasionally over-reporting one, only
    the second is recoverable.
    """
    haystack = f"{message or ''}\n{trace or ''}"

    if "strict mode violation" in haystack.lower():
        return True

    if not _ACTION_TIMEOUT.search(haystack):
        return False

    if "locator resolved to" not in haystack.lower():
        return False  # never found it; that may be a real defect

    return any(phrase in haystack.lower() for phrase in _UNUSABLE)


def _summarise(message: str | None) -> str | None:
    """First meaningful line of a pytest message.

    Playwright's assertion errors are pages long. The first line is the part
    that fits in a table and usually says what went wrong.
    """
    if not message:
        return None
    for line in message.splitlines():
        line = line.strip()
        if line:
            return line[:500]
    return None


#: pytest's own words for "this file would not import". They are accurate and
#: say nothing — neither which module, nor why.
_USELESS_ERRORS = {"collection failure", "collection error", "error"}

#: pytest marks the raised exception with a leading `E`. Taking the last one
#: matters: an import failure opens with the prose "ImportError while importing
#: test module." and only names the missing module several lines later.
_RAISED = re.compile(r"^E\s+(\S.*)$", re.M)

#: No `E` marker — a bare traceback. Same rule: the exception is at the bottom.
_EXCEPTION = re.compile(r"^(\w*(?:Error|Exception|Warning)\b.*)$", re.M)


def _error_summary(message: str | None, trace: str | None) -> str | None:
    """The reason a test could not run, rather than pytest's label for it.

    A module that fails to import is reported as `collection failure`, which is
    what the UI then shows next to a red test. It names neither the file nor the
    cause, and one uncollectable module fails the whole run — so that one
    unhelpful string is often the only thing on screen for a dozen tests.

    The traceback underneath does say why:

        E   ModuleNotFoundError: No module named 'pages.agent_details_page'

    so when the message is one of pytest's non-answers, take that line instead.
    """
    summary = _summarise(message)

    if trace and (summary is None or summary.strip().lower() in _USELESS_ERRORS):
        for pattern in (_RAISED, _EXCEPTION):
            found = pattern.findall(trace)
            if found:
                return found[-1].strip()[:500]

    return summary


def _failed_step(trace: str) -> int | None:
    """Which recorded step the failure landed on.

    Generated tests number their steps in comments (`# 3. Click "Login"`), and
    pytest echoes the source line in the traceback. When that comment is
    visible we can say "failed at step 3" instead of just "failed".
    """
    matches = _STEP_HINT.findall(trace)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except ValueError:
        return None


def summarise(results: list[ParsedResult]) -> dict[str, int]:
    """Totals for the run row."""
    counts = {"total": len(results), "passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        if result.status is ResultStatus.PASSED:
            counts["passed"] += 1
        elif result.status is ResultStatus.SKIPPED:
            counts["skipped"] += 1
        else:
            # ERROR counts as failed for the headline number. Nobody reading a
            # summary wants "0 failed" next to a run that did not work.
            counts["failed"] += 1
    return counts
