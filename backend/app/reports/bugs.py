"""Every bug in a project, as one workbook.

A bug report on its own is a ticket: you open the failure, read it, and act. A
project has dozens, and the questions asked of them are different ones — what
is still open, what is critical, which browser, how much of it landed in the
last cycle. None of those can be answered by opening tickets one at a time,
which until now was the only way.

So this is a register rather than a document: one row per bug, the prose in
columns wide enough to read, and the two things a triage meeting sorts by —
severity and status — visible without opening anything. Handed to a lead or a
developer, it is read, not parsed, so the shape is as much the deliverable as
the data.

The rows come from two places and the sheet does not distinguish between them,
because the reader does not care. A failure someone drafted a report for brings
its written prose and its triage status. A failure nobody has got to yet is
still a bug — it is red right now — so it is written from what the run already
knows: the test, the error, the steps, and the analysis if one was run. Asking
someone to click "Draft a bug report" sixteen times before they can see their
sixteen bugs is a filing task, not a testing one.

Mirrors `testcases.py` deliberately: same title band, same header treatment,
same frozen pane and filter. Two exports from the same tool that look like two
different tools is a small thing that reads as carelessness.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.models.enums import BugStatus, Severity


@dataclass
class BugRow:
    """One row of the register, whatever it was built from.

    A plain shape rather than the ORM model, because half the rows have no row
    in `bug_reports` at all: they are failures nobody has drafted yet, and the
    sheet is the first place anyone will see them written down.
    """

    title: str
    severity: Severity
    priority: Severity
    status: BugStatus
    case_name: str = ""
    browsers: str = ""
    environment: dict = field(default_factory=dict)
    steps_to_reproduce: list[str] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    description: str = ""
    reported_on: datetime | None = None
    #: False when the row was read off a failure rather than written by anyone.
    #: Shown in its own column, because "nobody has looked at this yet" is a
    #: different thing from "someone triaged it and left it open".
    drafted: bool = False

COLUMNS = [
    "Bug ID",
    "Title",
    "Severity",
    "Priority",
    "Status",
    "Reviewed",
    "Test Case",
    "Browser",
    "Environment",
    "Steps to Reproduce",
    "Expected Result",
    "Actual Result",
    "Description",
    "Reported On",
    "Assigned To",
    "Fixed In",
    "Comments",
]

#: The same palette as the test-case sheet, so the two exports look related.
_TITLE_BG = "1F3864"
_HEADER_BG = "217346"
_LABEL_FG = "1F3864"

#: Tinted by severity, because that is what a triage meeting sorts by. Reading
#: down the column is meant to be enough to find the row worth arguing about.
_SEVERITY_BG = {
    Severity.CRITICAL: "F8D7DA",
    Severity.HIGH: "FDEAEA",
    Severity.MEDIUM: "FFF4E5",
    Severity.LOW: "F1F3F5",
}

_BORDER = Border(*(Side(style="thin", color="D0D7DE") for _ in range(4)))

#: Steps, expected and actual carry the text, so they get the width.
_WIDTHS = [12, 44, 12, 12, 14, 11, 30, 12, 30, 46, 34, 34, 40, 14, 16, 14, 24]

_STATUS_TEXT = {
    BugStatus.DRAFT: "Draft",
    BugStatus.OPEN: "Open",
    BugStatus.RESOLVED: "Resolved",
    BugStatus.WONT_FIX: "Won't fix",
}

#: Worst first. A register sorted by id makes you read all of it to find the
#: one that matters; sorted by severity, the top of the sheet is the meeting.
_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def _date(value: datetime | None) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def _bug_id(prefix: str, index: int) -> str:
    return f"{prefix}-BUG-{index:03d}"


def _prefix(project_name: str) -> str:
    """`Homeske` -> `HOM`. Stable rather than raising on a name with no letters."""
    return "".join(c for c in project_name.upper() if c.isalpha())[:3] or "QA"


def _steps(bug: BugRow) -> str:
    """Numbered, one per line — the column a developer actually works from.

    A bug nobody can reproduce gets closed, so this is the part that decides
    whether the row was worth writing down.
    """
    return "\n".join(
        f"{i}. {step}" for i, step in enumerate(bug.steps_to_reproduce or [], 1)
    )


def _environment(bug: BugRow) -> str:
    """Whatever was captured, as `key: value` lines.

    Free-form: on a drafted bug it is the JSON copied off the run, so the keys
    are not fixed and listing them by name would silently drop anything added
    later.
    """
    environment = bug.environment or {}
    if not isinstance(environment, dict):
        return str(environment)
    return "\n".join(
        f"{key.replace('_', ' ')}: {value}"
        for key, value in environment.items()
        # The browser has a column of its own; repeating it here wastes the
        # width that the rest of the environment needs.
        if value not in (None, "") and key != "browser"
    )


def _rows(bugs: list[BugRow], *, project_name: str) -> list[list[str]]:
    """One row per bug, in `COLUMNS` order."""
    prefix = _prefix(project_name)

    rows: list[list[str]] = []
    for index, bug in enumerate(bugs, 1):
        rows.append(
            [
                _bug_id(prefix, index),
                bug.title,
                bug.severity.value.capitalize(),
                bug.priority.value.capitalize(),
                _STATUS_TEXT.get(bug.status, bug.status.value),
                "Yes" if bug.drafted else "Not yet",
                bug.case_name,
                bug.browsers,
                _environment(bug),
                _steps(bug),
                bug.expected,
                bug.actual,
                bug.description,
                _date(bug.reported_on),
                "",  # Assigned To — filled in during triage
                "",  # Fixed In
                "",  # Comments
            ]
        )
    return rows


def _header_block(bugs: list[BugRow], *, project_name: str) -> list[tuple[str, str]]:
    """The counts a lead wants before reading a single row."""
    open_bugs = sum(
        1 for b in bugs if b.status in (BugStatus.DRAFT, BugStatus.OPEN)
    )
    critical = sum(
        1
        for b in bugs
        if b.severity is Severity.CRITICAL
        and b.status in (BugStatus.DRAFT, BugStatus.OPEN)
    )
    return [
        ("Project Name", project_name),
        ("Total Bugs", str(len(bugs))),
        ("Open", str(open_bugs)),
        ("Critical & Open", str(critical)),
        ("Awaiting Review", str(sum(1 for b in bugs if not b.drafted))),
        ("Generated On", _date(datetime.now())),
    ]


def build_bug_workbook(bugs: list[BugRow], *, project_name: str) -> bytes:
    """Every bug in the project as a real .xlsx, worst first."""
    ordered = sorted(
        bugs,
        key=lambda b: (_SEVERITY_ORDER.get(b.severity, 9), b.title),
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bug Reports"

    last_column = get_column_letter(len(COLUMNS))

    # Title band.
    sheet.merge_cells(f"A1:{last_column}1")
    title = sheet["A1"]
    title.value = f"{project_name} — Bug Report"
    title.font = Font(bold=True, size=12, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor=_TITLE_BG)
    title.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 26

    for offset, (label, value) in enumerate(
        _header_block(ordered, project_name=project_name)
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

    for offset, (bug, values) in enumerate(
        zip(ordered, _rows(ordered, project_name=project_name))
    ):
        row = header_row + 1 + offset
        fill = _SEVERITY_BG.get(bug.severity, "FFFFFF")

        for index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=index, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = _BORDER
            cell.fill = PatternFill("solid", fgColor=fill)

    for index, width in enumerate(_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    # Everything above the first bug stays put while the rows scroll, and the
    # header becomes a filter — "show me open criticals" is the question this
    # sheet exists to answer, and it needs both.
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:{last_column}{header_row + len(ordered)}"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
