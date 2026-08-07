"""Drafting bug reports. No network.

A bug report is read by someone who will not open AutoQA, so the guards here
are about what reaches a ticket: a title that fits on one line, reproduction
steps that are actually present, and a severity that agrees with the analysis
rather than contradicting it in the same panel.
"""

import pytest

from app.ai.schemas import DraftedBug
from app.models.enums import BugStatus, Severity
from app.reports.bugs import COLUMNS
from app.services.bug_service import _line, _text

#: Column number by name, so a test says what it reads rather than counting.
COLUMN = {name: i for i, name in enumerate(COLUMNS, start=1)}


def drafted(**overrides) -> DraftedBug:
    base = dict(
        title="Login rejects an email with trailing spaces",
        description="Signing in fails when the email has whitespace around it.",
        steps_to_reproduce=[
            "Open https://example.test/login",
            "Type ' user@example.com ' into the Email field",
            "Type the correct password",
            "Click Login",
        ],
        expected="The user is signed in and taken to the dashboard.",
        actual="The page stays on /login and shows 'Invalid email or password'.",
        severity="high",
        priority="high",
    )
    base.update(overrides)
    return DraftedBug(**base)


# ---------------------------------------------------------------------------
# Text going into a ticket
# ---------------------------------------------------------------------------
def test_a_title_is_forced_onto_one_line():
    """Titles land in a backlog row; a newline there breaks the whole list."""
    messy = _line("Login\n\n  fails   badly\t\tsometimes", 255)

    assert messy == "Login fails badly sometimes"
    assert "\n" not in messy


def test_a_title_is_truncated_to_fit_the_column():
    assert len(_line("x" * 900, 255)) == 255


def test_control_characters_are_stripped():
    assert _line("Login\x00 fails\x07", 255) == "Login fails"


def test_body_text_keeps_its_paragraphs():
    """Unlike the title, a description is allowed to breathe."""
    body = _text("First line.\n\nSecond line.")

    assert "\n\n" in body


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_empty_text_does_not_become_the_string_none(empty):
    assert _text(empty) == ""
    assert _line(empty, 255) == ""


# ---------------------------------------------------------------------------
# The shape of what the model returns
# ---------------------------------------------------------------------------
def test_a_draft_carries_everything_a_developer_needs():
    bug = drafted()

    assert bug.title and bug.description
    assert bug.steps_to_reproduce, "a bug nobody can reproduce gets closed"
    assert bug.expected and bug.actual


def test_reproduction_steps_are_ordered_and_concrete():
    """The steps decide whether a bug is fixed or closed as 'cannot reproduce'."""
    steps = drafted().steps_to_reproduce

    assert steps[0].startswith("Open http")
    assert any("user@example.com" in step for step in steps), (
        "steps must carry the actual values used, not placeholders"
    )


def test_a_drafted_report_starts_as_a_draft():
    """An AI-written ticket nobody reviewed must not look raised."""
    assert BugStatus.DRAFT.value == "draft"
    assert BugStatus.DRAFT is not BugStatus.OPEN


def test_severity_shares_one_vocabulary_with_analysis():
    """The bug and the analysis sit next to each other; two scales would
    contradict each other on the same screen."""
    from app.ai.analyser import severity_of

    assert severity_of("critical") is Severity.CRITICAL
    assert severity_of(drafted().severity) is Severity.HIGH


# ---------------------------------------------------------------------------
# Every bug in one workbook
#
# The per-failure report is a ticket: one problem, handed to one developer.
# A project has dozens, and the questions asked of them are different ones —
# what is still open, what is critical, how much of this is a single browser.
# None of those can be answered by opening tickets one at a time, which was the
# only way to read them.
# ---------------------------------------------------------------------------
def bug(**overrides):
    """One register row. The workbook takes these however they were built."""
    from datetime import datetime

    from app.reports.bugs import BugRow

    base = dict(
        title="Login rejects an email with trailing spaces",
        description="Signing in fails when the email has whitespace around it.",
        steps_to_reproduce=["Open /login", "Type ' a@b.com '", "Click Login"],
        expected="The user is signed in.",
        actual="The page stays on /login.",
        case_name="Login with a valid account",
        browsers="chromium",
        environment={"url": "https://x.test/login"},
        severity=Severity.HIGH,
        priority=Severity.HIGH,
        status=BugStatus.OPEN,
        reported_on=datetime(2026, 8, 6, 11, 0),
        drafted=True,
    )
    base.update(overrides)
    return BugRow(**base)


def workbook(bugs, project_name: str = "Homeske"):
    """Build and read back, so a test asserts on the file rather than the code."""
    import io

    from openpyxl import load_workbook

    from app.reports.bugs import build_bug_workbook

    raw = build_bug_workbook(bugs, project_name=project_name)
    return load_workbook(io.BytesIO(raw)).active


def test_every_bug_gets_a_row():
    sheet = workbook([bug(), bug(), bug()])

    # Eight rows of title and header block, then one per bug.
    assert sheet.max_row == 8 + 3


def test_the_worst_bug_is_the_first_one_you_read():
    """A register sorted by id makes you read all of it to find the argument."""
    sheet = workbook([
        bug(title="Low one", severity=Severity.LOW),
        bug(title="Critical one", severity=Severity.CRITICAL),
        bug(title="Medium one", severity=Severity.MEDIUM),
    ])

    titles = [sheet.cell(row=9 + i, column=2).value for i in range(3)]
    assert titles == ["Critical one", "Medium one", "Low one"]


def test_the_steps_are_numbered_one_per_line():
    """A bug nobody can reproduce gets closed, so this column decides its fate."""
    sheet = workbook([bug()])
    steps = sheet.cell(row=9, column=COLUMN["Steps to Reproduce"]).value

    assert steps.splitlines() == ["1. Open /login", "2. Type ' a@b.com '", "3. Click Login"]


def test_the_counts_a_lead_wants_are_above_the_rows():
    sheet = workbook([
        bug(severity=Severity.CRITICAL, status=BugStatus.OPEN),
        bug(severity=Severity.LOW, status=BugStatus.RESOLVED),
        bug(severity=Severity.HIGH, status=BugStatus.DRAFT),
    ])
    header = {sheet.cell(row=r, column=1).value: sheet.cell(row=r, column=2).value
              for r in range(2, 8)}

    assert header["Total Bugs"] == "3"
    assert header["Open"] == "2"       # draft counts as open; resolved does not
    assert header["Critical & Open"] == "1"


def test_the_browser_is_not_repeated_in_the_environment_column():
    """It has a column of its own, and the width is needed for the rest."""
    sheet = workbook([bug()])

    assert sheet.cell(row=9, column=COLUMN["Browser"]).value == "chromium"
    assert "chromium" not in (
        sheet.cell(row=9, column=COLUMN["Environment"]).value or ""
    )


def test_a_bug_whose_run_was_deleted_still_exports():
    """`result_id` is nulled when a run goes. The steps were copied in already."""
    sheet = workbook([bug(case_name="")])

    # openpyxl reads an empty cell back as None; either way the column is blank
    # rather than the export having failed.
    assert not sheet.cell(row=9, column=COLUMN["Test Case"]).value
    assert sheet.cell(row=9, column=COLUMN["Steps to Reproduce"]).value


def test_the_sheet_filters_and_freezes_so_it_can_be_triaged():
    """"Show me open criticals" is the question this file exists to answer."""
    sheet = workbook([bug() for _ in range(5)])

    from openpyxl.utils import get_column_letter

    assert sheet.freeze_panes == "A9"
    # Derived, so adding a column moves the filter instead of breaking it.
    last = get_column_letter(len(COLUMNS))
    assert sheet.auto_filter.ref == f"A8:{last}13"


def test_a_project_name_with_no_letters_still_produces_ids():
    sheet = workbook([bug()], project_name="123 456")

    assert sheet.cell(row=9, column=1).value == "QA-BUG-001"


# ---------------------------------------------------------------------------
# A failure nobody has written up is still a bug
#
# The export used to hold only the reports somebody had clicked "Draft a bug
# report" on, so a project with sixteen red tests and no clicks exported
# nothing — the button answered "draft one first", which made the register a
# reward for filing rather than a view of the project.
# ---------------------------------------------------------------------------
class FakeStep:
    def __init__(self, description: str) -> None:
        self.description = description
        self.input_data = None


class FakeFailure:
    def __init__(self, case_id: int, browser: str, **overrides) -> None:
        from datetime import datetime

        from app.models.enums import Browser, ResultStatus

        self.id = case_id * 10 + len(browser)
        self.test_case_id = case_id
        self.browser = Browser(browser)
        self.status = ResultStatus.FAILED
        self.case_name = overrides.get("case_name", "Successful registration")
        self.error_message = overrides.get("error_message", "AssertionError: hidden")
        self.failed_step = overrides.get("failed_step", 7)
        self.created_at = datetime(2026, 8, 6, 9, 0)


class FakeAnalysis:
    def __init__(self, **overrides) -> None:
        base = dict(
            expected="The one-time-password popup should have opened.",
            actual="The form stayed put with a red message under Mobile Number.",
            root_cause="The phone number is rejected for the selected country.",
            severity=Severity.CRITICAL,
            priority=Severity.HIGH,
        )
        base.update(overrides)
        for key, value in base.items():
            setattr(self, key, value)


def service_with(failures, analyses=None, steps=None):
    """A BugService with only the parts `_rows_from_failures` touches."""
    from app.services.bug_service import BugService

    service = BugService.__new__(BugService)
    found = analyses or {}
    service.analyses = type("A", (), {"latest_for_result": lambda _s, rid: found.get(rid)})()
    service._steps_for = lambda _result: steps or []
    return service


def test_a_failure_nobody_drafted_becomes_a_row():
    service = service_with([])
    rows = service._rows_from_failures([FakeFailure(1, "chromium")])

    assert len(rows) == 1
    assert rows[0].drafted is False
    assert rows[0].case_name == "Successful registration"


def test_one_bug_not_one_per_browser():
    """Red in two browsers is one bug affecting two, not two bugs."""
    service = service_with([])
    rows = service._rows_from_failures([
        FakeFailure(1, "chromium"), FakeFailure(1, "firefox")
    ])

    assert len(rows) == 1
    assert rows[0].browsers == "chromium, firefox"


def test_the_analysis_writes_the_row_when_there_is_one():
    failure = FakeFailure(1, "chromium")
    service = service_with([], analyses={failure.id: FakeAnalysis()})
    row = service._rows_from_failures([failure])[0]

    assert row.title == "The phone number is rejected for the selected country."
    assert row.expected.startswith("The one-time-password popup")
    assert row.severity is Severity.CRITICAL


def test_without_an_analysis_the_row_still_says_something_useful():
    """No AI has run, and the export must not wait for one."""
    service = service_with([], steps=[FakeStep("Open the form"), FakeStep("Submit")])
    row = service._rows_from_failures([FakeFailure(1, "chromium")])[0]

    assert "Successful registration" in row.title
    assert row.actual == "AssertionError: hidden"
    assert row.steps_to_reproduce == ["Open the form", "Submit"]
    assert row.severity is Severity.MEDIUM


def test_an_undrafted_row_says_it_has_not_been_reviewed():
    """"Nobody has looked at this" is not the same as "triaged and left open"."""
    service = service_with([])
    sheet = workbook(service._rows_from_failures([FakeFailure(1, "chromium")]))

    assert sheet.cell(row=9, column=COLUMN["Reviewed"]).value == "Not yet"


def test_a_drafted_row_says_it_has_been():
    sheet = workbook([bug(drafted=True)])

    assert sheet.cell(row=9, column=COLUMN["Reviewed"]).value == "Yes"


def test_the_header_counts_what_is_still_unreviewed():
    service = service_with([])
    rows = [bug(drafted=True)] + service._rows_from_failures([FakeFailure(1, "chromium")])
    sheet = workbook(rows)
    header = {sheet.cell(row=r, column=1).value: sheet.cell(row=r, column=2).value
              for r in range(2, 8)}

    assert header["Total Bugs"] == "2"
    assert header["Awaiting Review"] == "1"


# ---------------------------------------------------------------------------
# The same bugs as a Word document
#
# Not another format of the spreadsheet — a different question. The register
# answers "what is outstanding, by severity". This answers "here is bug 3, with
# a picture", which is what gets attached to a ticket. The screenshot is the
# whole reason it exists: the error text says what the test expected, the image
# says what was actually on screen, and that is the difference between an
# application bug and a test one.
# ---------------------------------------------------------------------------
#: The smallest thing Word will accept as a picture: a 1x1 PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100fdff03fa0000000049454e44ae426082"
)


def document(bugs, project_name: str = "Homeske"):
    """Build and read back, so a test asserts on the file rather than the code."""
    import io

    from docx import Document

    from app.reports.bugs_doc import build_bug_document

    return Document(io.BytesIO(build_bug_document(bugs, project_name=project_name)))


def text_of(doc) -> str:
    return "\n".join(p.text for p in doc.paragraphs)


def test_the_screenshot_is_in_the_document():
    """The one thing a spreadsheet cell cannot hold."""
    doc = document([bug(screenshot=PNG)])

    assert len(doc.inline_shapes) == 1


def test_every_bug_brings_its_own_screenshot():
    doc = document([bug(screenshot=PNG), bug(screenshot=PNG), bug(screenshot=PNG)])

    assert len(doc.inline_shapes) == 3


def test_a_failure_with_no_screenshot_says_so_rather_than_going_quiet():
    """A missing picture is worth a sentence; a blank space reads as a bug."""
    doc = document([bug(screenshot=None)])

    assert "No screenshot was captured" in text_of(doc)


def test_an_unreadable_image_costs_one_picture_not_the_report():
    """Truncated on disk, or a format Word declines. The other bugs still ship."""
    doc = document([bug(title="First", screenshot=b"not an image"), bug(title="Second", screenshot=PNG)])

    assert "could not be embedded" in text_of(doc)
    assert "Second" in text_of(doc)
    assert len(doc.inline_shapes) == 1


def test_the_worst_bug_is_the_first_one_you_read_here_too():
    doc = document([
        bug(title="Low one", severity=Severity.LOW),
        bug(title="Critical one", severity=Severity.CRITICAL),
    ])
    headings = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]

    assert headings[0].endswith("Critical one")


def test_the_prose_a_developer_needs_is_all_there():
    doc = document([bug()])
    body = text_of(doc)

    assert "Login rejects an email with trailing spaces" in body
    assert "The user is signed in." in body        # expected
    assert "The page stays on /login." in body     # actual
    assert "Open /login" in body                   # steps to reproduce


def test_an_empty_field_does_not_leave_a_dangling_label():
    """"Expected:" with nothing after it reads as a tool that failed to fill in."""
    doc = document([bug(expected="", case_name="")])
    body = text_of(doc)

    assert "Expected:" not in body
    assert "Test case:" not in body


def test_an_undrafted_bug_says_nobody_has_reviewed_it():
    doc = document([bug(drafted=False)])

    assert "Not reviewed yet" in text_of(doc)


def test_the_summary_counts_what_nobody_has_looked_at():
    doc = document([bug(drafted=True), bug(drafted=False)])

    assert "2 bug(s)." in text_of(doc)
    assert "1 have not been reviewed" in text_of(doc)


def test_both_exports_are_built_from_the_same_row():
    """One description of a bug, so the two files cannot drift apart."""
    from app.reports.bugs import BugRow
    from app.reports.bugs_doc import build_bug_document

    one = bug()
    assert isinstance(one, BugRow)
    assert build_bug_document([one], project_name="P")
    assert workbook([one])
