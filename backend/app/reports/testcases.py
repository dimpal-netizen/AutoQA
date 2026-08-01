"""Export a suite as a QA test-case sheet.

The layout is the one QA teams already keep by hand in Excel: a small header
block naming the project and module, then one row per test case with the
columns a reviewer expects — ID, pre-requisites, type, priority, positive or
negative, scenario, input data, steps, expected result — followed by the
columns that get filled in during a test cycle.

The point of this file is that AutoQA already knows almost all of it. The steps,
the input data and the expected results come from the generated test; the
category says whether a case is positive or negative; and if you point it at a
run, the Actual Results, Status and Execution Date columns come back filled in
too. What is left blank is what a human is supposed to decide: retesting, peer
review and comments.

CSV rather than .xlsx because it needs no dependency, opens in Excel by
double-clicking, and pastes cleanly into a team's existing styled template —
which is where this data usually has to end up anyway.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from app.models.enums import CaseCategory, ResultStatus
from app.models.test_case import TestCase, TestSuite
from app.models.test_run import TestResult, TestRun

COLUMNS = [
    "Test Case ID",
    "Pre-requisites",
    "Type",
    "Test Priority",
    "Positive/Negative",
    "Description / Scenario to be Tested",
    "Input Data",
    "Test Steps",
    "Expected Results",
    "Actual Results",
    "Status",
    "Test Execution Date",
    "Retesting Status",
    "Retesting Date",
    "Peer Review",
    "Comments",
]

# A recorded or positive case asserts something should work; the rest assert
# the application refuses something. That is exactly the Positive/Negative
# split a QA sheet wants, so it is derived rather than stored twice.
_NEGATIVE = {CaseCategory.NEGATIVE, CaseCategory.EDGE, CaseCategory.SECURITY}

# Security cases are the one group that is not plain functional testing.
_TYPE = {CaseCategory.SECURITY: "Security"}

_STATUS_TEXT = {
    ResultStatus.PASSED: "Pass",
    ResultStatus.FAILED: "Fail",
    ResultStatus.ERROR: "Fail",
    ResultStatus.SKIPPED: "Not executed",
    ResultStatus.FLAKY: "Pass (flaky)",
}


def _case_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index:03d}"


def _prefix(project_name: str, suite_name: str) -> str:
    """`Homeske` + `Subscription & Payment` -> `HOM-SP`.

    Initials of the suite give the module part, which is what makes a sheet of
    a hundred rows navigable. Falls back to something stable rather than
    raising if a name has no usable letters in it.
    """
    project_part = "".join(c for c in project_name.upper() if c.isalpha())[:3] or "QA"
    words = [w for w in suite_name.replace("&", " ").split() if w[:1].isalpha()]
    module_part = "".join(w[0].upper() for w in words)[:3] or "TC"
    return f"{project_part}-{module_part}"


def _steps(case: TestCase) -> str:
    """Numbered, one per line — the way the column is read."""
    if not case.steps:
        return ""
    return "\n".join(f"{i}. {s.description}" for i, s in enumerate(case.steps, 1))


def _input_data(case: TestCase) -> str:
    """Only the steps that actually carry a value, labelled by what they fill.

    A column of bare values with no field names is unusable during a manual
    re-test, which is exactly when this sheet gets read.
    """
    parts = [
        f"{s.description}: {s.input_data}" for s in case.steps if s.input_data
    ]
    return "\n".join(parts) if parts else "N/A"


def _expected(case: TestCase) -> str:
    stated = [s.expected_result for s in case.steps if s.expected_result]
    if stated:
        return "\n".join(stated)
    # Every generated case is required to assert something, so an empty column
    # here means the assertions live in steps that did not record prose.
    return "The scenario completes without error."


def _prerequisites(case: TestCase, suite: TestSuite) -> str:
    """What has to be true before the tester starts.

    AutoQA does not store this as a field, so rather than leave the column
    empty it is derived from the first step, which is nearly always the
    navigation that sets the scene.
    """
    if case.steps and case.steps[0].action.value == "navigate":
        target = case.steps[0].input_data or case.steps[0].description
        return f"Application reachable at {target}"
    return f"{suite.name} preconditions met"


def _actual(result: TestResult | None) -> str:
    if result is None:
        return ""
    if result.status is ResultStatus.PASSED:
        return "As expected."
    return (result.error_message or "Failed — see the run for details.").strip()


def _date(value: datetime | None) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def build_testcase_sheet(
    suite: TestSuite,
    cases: list[TestCase],
    *,
    project_name: str,
    designed_by: str = "",
    run: TestRun | None = None,
    results: list[TestResult] | None = None,
) -> str:
    """Render the suite as CSV in the standard QA test-case layout.

    `results` fills the execution columns. Where a case ran on several browsers
    the worst outcome wins, because a sheet has one Status column and a test
    that fails anywhere has not passed.
    """
    worst: dict[str, TestResult] = {}
    for result in results or []:
        current = worst.get(result.function_name)
        # Anything that is not a pass beats a pass; the first non-pass sticks.
        if current is None or (
            current.status is ResultStatus.PASSED
            and result.status is not ResultStatus.PASSED
        ):
            worst[result.function_name] = result

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow([f"{project_name} | {suite.name}"])
    writer.writerow([])
    writer.writerow(["Project Name", project_name])
    writer.writerow(["Module Name", suite.name])
    writer.writerow(["Description", suite.description or ""])
    writer.writerow(["Test Designed By", designed_by])
    writer.writerow(["Creation Date", _date(suite.created_at)])
    writer.writerow([])
    writer.writerow(COLUMNS)

    prefix = _prefix(project_name, suite.name)

    for index, case in enumerate(cases, 1):
        result = worst.get(case.function_name)
        writer.writerow(
            [
                _case_id(prefix, index),
                _prerequisites(case, suite),
                _TYPE.get(case.category, "Functional"),
                case.priority.value.capitalize(),
                "Negative" if case.category in _NEGATIVE else "Positive",
                case.name,
                _input_data(case),
                _steps(case),
                _expected(case),
                _actual(result),
                _STATUS_TEXT.get(result.status, "") if result else "",
                _date(run.finished_at) if run and result else "",
                "",  # Retesting Status — filled during the cycle
                "",  # Retesting Date
                "",  # Peer Review
                "",  # Comments
            ]
        )

    return buffer.getvalue()
