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

A real .xlsx rather than CSV. The columns were never the hard part — the shape
was: wrapped step lists, a frozen header, a filter, and positive and negative
cases tinted apart so a reviewer can see the split without reading. A sheet
handed to a QA lead is read, not parsed.
"""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

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

#: Taken from the sheet this format is copied from: a dark banner, a green
#: header, and the two case kinds tinted apart.
_TITLE_BG = "1F3864"
_HEADER_BG = "217346"
_LABEL_FG = "1F3864"
_POSITIVE_BG = "E8F5E9"
_NEGATIVE_BG = "FDEAEA"

_BORDER = Border(*(Side(style="thin", color="D0D7DE") for _ in range(4)))

#: Wide enough to read without unwrapping. Steps and expected results carry
#: most of the text, so they get most of the width.
_WIDTHS = [14, 26, 12, 12, 14, 40, 26, 42, 42, 30, 12, 16, 14, 14, 14, 22]

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


def _worst_per_case(results: list[TestResult] | None) -> dict[str, TestResult]:
    """One result per test, worst outcome winning.

    A sheet has one Status column, and a test that fails on any browser has not
    passed — so the failure is the row's verdict even when two other browsers
    were green.
    """
    worst: dict[str, TestResult] = {}
    for result in results or []:
        current = worst.get(result.function_name)
        if current is None or (
            current.status is ResultStatus.PASSED
            and result.status is not ResultStatus.PASSED
        ):
            worst[result.function_name] = result
    return worst


def _header_block(
    suite: TestSuite, *, project_name: str, designed_by: str
) -> list[tuple[str, str]]:
    return [
        ("Project Name", project_name),
        ("Module Name", suite.name),
        ("Description", suite.description or ""),
        ("Test Designed By", designed_by),
        ("Creation Date", _date(suite.created_at)),
    ]


def _rows(
    suite: TestSuite,
    cases: list[TestCase],
    *,
    project_name: str,
    run: TestRun | None,
    results: list[TestResult] | None,
) -> list[list[str]]:
    """One row per case, in `COLUMNS` order."""
    worst = _worst_per_case(results)
    prefix = _prefix(project_name, suite.name)

    rows: list[list[str]] = []
    for index, case in enumerate(cases, 1):
        result = worst.get(case.function_name)
        rows.append(
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
    return rows


def build_testcase_workbook(
    suite: TestSuite,
    cases: list[TestCase],
    *,
    project_name: str,
    designed_by: str = "",
    run: TestRun | None = None,
    results: list[TestResult] | None = None,
) -> bytes:
    """The suite as a real .xlsx, formatted the way the sheet is kept by hand.

    CSV carried the same values but none of the shape: every column the same
    width, steps on one unreadable line, and no way to tell a positive case from
    a negative one at a glance. A spreadsheet handed to a QA lead is read, not
    parsed, so the formatting is the deliverable as much as the data is.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Test Cases"

    last_column = get_column_letter(len(COLUMNS))

    # Title band.
    sheet.merge_cells(f"A1:{last_column}1")
    title = sheet["A1"]
    title.value = f"{project_name} — {suite.name}"
    title.font = Font(bold=True, size=12, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor=_TITLE_BG)
    title.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 26

    # Header block: label and value, one per row.
    for offset, (label, value) in enumerate(
        _header_block(suite, project_name=project_name, designed_by=designed_by)
    ):
        row = 2 + offset
        sheet.cell(row=row, column=1, value=label).font = Font(bold=True, color=_LABEL_FG)
        sheet.cell(row=row, column=2, value=value).alignment = Alignment(vertical="center")

    header_row = 8

    for index, name in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=header_row, column=index, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=_HEADER_BG)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _BORDER
    sheet.row_dimensions[header_row].height = 30

    positive = COLUMNS.index("Positive/Negative")

    for offset, values in enumerate(
        _rows(suite, cases, project_name=project_name, run=run, results=results)
    ):
        row = header_row + 1 + offset
        # Tinted by what the case asserts, which is the split a reviewer reads
        # the sheet for. Left uncoloured where it is neither.
        fill = _POSITIVE_BG if values[positive] == "Positive" else _NEGATIVE_BG

        for index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=index, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = _BORDER
            cell.fill = PatternFill("solid", fgColor=fill)

    for index, width in enumerate(_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    # Everything above the first case stays put while the cases scroll, and the
    # header becomes a filter — a hundred-row sheet is unusable without both.
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:{last_column}{header_row + len(cases)}"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
