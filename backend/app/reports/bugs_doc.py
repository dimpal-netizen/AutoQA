"""Every bug in a project, as one Word document.

The workbook in `bugs.py` is a register: rows to sort, filter and count. This is
the same bugs written as a document, and the difference that earns it is the
screenshot. A spreadsheet cell cannot hold the picture of the page at the moment
the test gave up, and that picture is the fastest way to tell an application bug
from a test one — the error text says what the test expected, the image says
what was actually on screen.

So the two exports are not formats of the same file, they are different
questions. "What is outstanding, by severity" is a spreadsheet. "Here is bug 3,
with a picture" is a document you attach to a ticket or email to a developer who
has never opened AutoQA.

Both are built from the same `BugRow`, so a bug cannot say one thing in one file
and something else in the other.
"""

from __future__ import annotations

import io
import logging

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from app.models.enums import BugStatus, Severity
from app.reports.bugs import BugRow

logger = logging.getLogger(__name__)

#: Wide enough to read a form on, narrow enough that twenty of them still open.
#: Word scales to the page width anyway; this caps the height it reserves.
SCREENSHOT_WIDTH_INCHES = 6.0

#: The same colours the workbook tints rows with, so a bug that is critical in
#: one file looks critical in the other.
_SEVERITY_RGB = {
    Severity.CRITICAL: RGBColor(0xC0, 0x39, 0x2B),
    Severity.HIGH: RGBColor(0xD3, 0x54, 0x00),
    Severity.MEDIUM: RGBColor(0xB7, 0x79, 0x0C),
    Severity.LOW: RGBColor(0x6C, 0x75, 0x7D),
}

_STATUS_TEXT = {
    BugStatus.DRAFT: "Draft",
    BugStatus.OPEN: "Open",
    BugStatus.RESOLVED: "Resolved",
    BugStatus.WONT_FIX: "Won't fix",
}

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def _field(document, label: str, value: str) -> None:
    """One labelled line. Skipped entirely when there is nothing to say.

    An empty "Expected:" is worse than no line at all — it reads as a tool that
    failed to fill something in rather than a bug that had nothing to add.
    """
    if not str(value or "").strip():
        return
    paragraph = document.add_paragraph()
    run = paragraph.add_run(f"{label}  ")
    run.bold = True
    paragraph.add_run(str(value).strip())


def _screenshot(document, image: bytes | None) -> None:
    """The page when the test gave up, or a line saying there wasn't one.

    Never raises. A screenshot that will not decode — truncated on disk, or a
    format Word declines — must cost that one picture, not the whole document
    for every other bug in it.
    """
    if not image:
        document.add_paragraph(
            "No screenshot was captured for this failure."
        ).runs[0].italic = True
        return

    try:
        document.add_picture(io.BytesIO(image), width=Inches(SCREENSHOT_WIDTH_INCHES))
    except Exception:  # noqa: BLE001 - one bad image must not lose the report
        logger.exception("Could not embed a screenshot in the bug document")
        document.add_paragraph(
            "The screenshot for this failure could not be embedded."
        ).runs[0].italic = True
        return

    document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER


def build_bug_document(bugs: list[BugRow], *, project_name: str) -> bytes:
    """Every bug in the project as a .docx, worst first, screenshots included."""
    ordered = sorted(
        bugs, key=lambda b: (_SEVERITY_ORDER.get(b.severity, 9), b.title)
    )

    document = Document()

    # A little room: the default template's margins waste width a screenshot
    # could be using.
    for section in document.sections:
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    document.add_heading(f"{project_name} — Bug Report", level=0)

    summary = document.add_paragraph()
    summary.add_run(f"{len(ordered)} bug(s). ").bold = True
    awaiting = sum(1 for b in ordered if not b.drafted)
    if awaiting:
        summary.add_run(
            f"{awaiting} have not been reviewed by anyone yet — they are tests "
            "that are failing right now, written up from the run."
        )

    for index, bug in enumerate(ordered, 1):
        document.add_page_break() if index > 1 else None

        heading = document.add_heading(level=1)
        run = heading.add_run(f"{index}. {bug.title}")
        run.font.color.rgb = _SEVERITY_RGB.get(bug.severity, RGBColor(0, 0, 0))

        meta = document.add_paragraph()
        meta.add_run(
            f"{bug.severity.value.capitalize()} severity · "
            f"{bug.priority.value.capitalize()} priority · "
            f"{_STATUS_TEXT.get(bug.status, bug.status.value)} · "
            f"{'Reviewed' if bug.drafted else 'Not reviewed yet'}"
        ).font.size = Pt(9)

        _field(document, "Test case:", bug.case_name)
        _field(document, "Browser:", bug.browsers)
        _field(document, "Reported:", bug.reported_on.strftime("%d-%m-%Y") if bug.reported_on else "")

        if bug.description:
            document.add_heading("What is wrong", level=2)
            document.add_paragraph(bug.description)

        if bug.steps_to_reproduce:
            document.add_heading("Steps to reproduce", level=2)
            for step in bug.steps_to_reproduce:
                document.add_paragraph(str(step), style="List Number")

        document.add_heading("Expected vs actual", level=2)
        _field(document, "Expected:", bug.expected)
        _field(document, "Actual:", bug.actual)

        environment = bug.environment if isinstance(bug.environment, dict) else {}
        details = [
            f"{key.replace('_', ' ')}: {value}"
            for key, value in environment.items()
            if value not in (None, "") and key != "browser"
        ]
        if details:
            document.add_heading("Environment", level=2)
            for line in details:
                document.add_paragraph(line, style="List Bullet")

        # Last, and the reason this format exists at all. The error text says
        # what the test expected; the picture says what was actually on screen,
        # and that is the difference between an application bug and a test one.
        document.add_heading("Screenshot at the moment of failure", level=2)
        _screenshot(document, bug.screenshot)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
