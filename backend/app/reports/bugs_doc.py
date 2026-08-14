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
from app.reports import mantis
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



def _issue(document, bug: BugRow, *, index: int, project_name: str) -> None:
    """One bug, laid out as Mantis's Report Issue form.

    The form rather than the issue view, because of what this document is for:
    somebody has it open beside the tracker and is filling the form in. Matching
    the view would mean reading fields in one order and typing them in another,
    which is where a field gets missed.

    So the labels, their order, and the little templates Mantis puts inside
    Description and Additional Information are all its own. Every box that has
    an answer arrives filled in; the ones only a person can decide - who to
    assign it to, which profile - are present and blank, because a form with a
    row missing is harder to work through than one with a row to skip.
    """
    heading = document.add_heading(level=1)
    run = heading.add_run(f"{mantis.issue_id(index)}: {bug.title}")
    run.font.color.rgb = _SEVERITY_RGB.get(bug.severity, RGBColor(0, 0, 0))

    rows = mantis.fields(bug, index=index, project_name=project_name)

    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in rows:
        cells = table.add_row().cells
        label_run = cells[0].paragraphs[0].add_run(label)
        label_run.bold = True
        label_run.font.size = Pt(9)
        cells[0].width = Inches(1.9)

        # A paragraph per line. Word renders a string containing newlines as one
        # run on one line, so the steps would arrive as a single sentence and
        # the templated boxes would lose their shape entirely.
        first = True
        for line in str(value or "").splitlines() or [""]:
            paragraph = cells[1].paragraphs[0] if first else cells[1].add_paragraph()
            paragraph.add_run(line).font.size = Pt(9)
            first = False
        cells[1].width = Inches(5.1)

    # Mantis's own last row before submitting, and the reason this format exists
    # rather than the spreadsheet: the error text says what the test expected,
    # the picture says what was actually on screen, and that is the difference
    # between an application bug and a test one.
    document.add_paragraph()
    document.add_paragraph().add_run("Upload Files").bold = True
    _screenshot(document, bug.screenshot)


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
        _issue(document, bug, index=index, project_name=project_name)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
