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
from app.reports import mantis


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
    #: The page as it looked when the test gave up. Only the Word report can
    #: show it — a spreadsheet cell is the wrong place for a picture — but it is
    #: carried on the row so both exports are built from one description of a
    #: bug rather than two that can drift apart.
    screenshot: bytes | None = None

#: The team's own bug-report template, column for column. Not Mantis: this
#: sheet is the one they already circulate, and a register that arrives in a
#: different shape than the one on everybody's screen gets re-typed into it.
#:
#: The Word document is Mantis's Report Issue form, because that is what it is
#: for - filling in the tracker. Two files, two audiences, and the difference is
#: deliberate rather than drift.
#:
#: "Serverity" is their spelling. Corrected here it would stop matching the
#: template somebody pastes into.
COLUMNS = [
    "Bug ID",
    "Bug Summary",
    "Serverity",
    "Steps to Reproduce",
    "Expected Result",
    "Actual Results",
    "Browser/OS used",
    "Status",
    "Test case ID",
    "Comments/Screen shots",
]

#: Their template's own words for how bad it is.
_SEVERITY_WORD = {
    Severity.CRITICAL: "Blocker",
    Severity.HIGH: "High",
    Severity.MEDIUM: "Medium",
    Severity.LOW: "Low",
}

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

#: Per column, in `COLUMNS` order. The prose columns carry the reading.
_WIDTHS = [10, 46, 12, 44, 34, 34, 18, 12, 16, 30]

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


def _device(bug: BugRow) -> str:
    """What Mantis calls OS. The same value the document puts in `Device used`,
    read the same way, so the two files cannot disagree about it."""
    environment = bug.environment if isinstance(bug.environment, dict) else {}
    return str(environment.get("os") or environment.get("platform") or "")


def _rows(bugs: list[BugRow], *, project_name: str) -> list[list[str]]:
    """One row per bug, in `COLUMNS` order."""
    return [
        [
            f"{index:03d}",
            bug.title,
            _SEVERITY_WORD.get(bug.severity, "Medium"),
            _steps(bug),
            bug.expected,
            bug.actual,
            _browser_os(bug),
            _STATUS_TEXT.get(bug.status, str(bug.status)),
            bug.case_name,
            _comments(bug),
        ]
        for index, bug in enumerate(bugs, 1)
    ]


def _steps(bug: BugRow) -> str:
    """Numbered, one per line - the column a developer actually works from.

    A bug nobody can reproduce gets closed, so this is the part that decides
    whether the row was worth writing down.
    """
    return "\n".join(
        f"{i}. {step}" for i, step in enumerate(bug.steps_to_reproduce or [], 1)
    )


def _browser_os(bug: BugRow) -> str:
    """One cell, because the template asks for one: `chromium / Windows 11`."""
    environment = bug.environment if isinstance(bug.environment, dict) else {}
    system = environment.get("os") or environment.get("platform") or ""
    return " / ".join(part for part in (bug.browsers, str(system)) if part)


def _comments(bug: BugRow) -> str:
    """What the template's last column is for, and what we honestly have.

    Their example is a screenshot URL. AutoQA has the picture rather than a
    link to one - it is embedded in the Word report - so this says where to
    find it instead of leaving the column blank as though there were nothing.
    """
    notes = []
    if not bug.drafted:
        notes.append("Raised automatically from a failing test; not yet reviewed.")
    if bug.screenshot:
        notes.append("Screenshot in the Word report.")
    environment = bug.environment if isinstance(bug.environment, dict) else {}
    notes += [
        f"{key.replace('_', ' ')}: {value}"
        for key, value in environment.items()
        if value not in (None, "") and key not in ("browser", "os", "platform")
    ]
    return "\n".join(notes)


def _header_block(bugs: list[BugRow], *, project_name: str) -> list[tuple[str, str]]:
    """The five lines their template opens with.

    Module Name is left blank on purpose: a project can have several and
    nothing in a run says which one a failure belongs to. Blank is a box
    somebody fills in; a guess is one they have to check.
    """
    return [
        ("Project Name", project_name),
        ("Module Name", ""),
        ("Description", f"{len(bugs)} bug(s) found by automated tests."),
        ("Bug  Reported by", "QA Team"),
        ("Reported Date", _date(datetime.now())),
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
    title.value = f"© {project_name} | eLuminous Technologies"
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

    header_row = 8  # five header lines, then a blank

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
