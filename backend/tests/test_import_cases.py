"""Reading a team's own manual test-case sheet.

Every QA team keeps a spreadsheet of cases somebody walks through by hand, and
no two of those sheets look alike: one column is "Description", the next team
calls it "Scenario", the one after that "Test Case". Getting them into AutoQA
meant retyping each one through the step editor, and nobody was ever going to
retype forty.

The reading of the sheet is the only part a model does, because guessing which
column is which is the only part that needs judgement. Everything after it -
what a step may say, which elements exist, whether the case compiles - is the
same validation a typed case goes through, so an imported case cannot do
anything a hand-written one could not.
"""

import io

import pytest
from openpyxl import Workbook

from app.ai.schemas import CaseStep, GeneratedCase
from app.codegen.converter import LocatorSpec, PageSpec, TestIR
from app.services.exceptions import ValidationError
from app.services.import_service import (
    MAX_CELL,
    MAX_ROWS,
    ImportOutcome,
    ImportService,
    as_text,
    read_sheet,
    read_without_ai,
)


def workbook(rows: list[list[object]], *, sheets: int = 1) -> bytes:
    book = Workbook()
    for index in range(sheets):
        sheet = book.active if index == 0 else book.create_sheet()
        source = rows if index == 0 else [["Another tab", "nobody asked for"]]
        for row in source:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


SHEET = [
    ["ID", "Description", "Steps to Execute", "Expected Result"],
    ["TC-1", "Login with valid credentials", "Enter email, enter password, click Login",
     "Dashboard is shown"],
    ["TC-2", "Login with wrong password", "Enter email, enter a bad password, click Login",
     "An error is shown and the form stays"],
]


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------
def test_an_excel_sheet_comes_back_as_rows() -> None:
    rows = read_sheet(workbook(SHEET), "cases.xlsx")

    assert len(rows) == 3
    assert rows[0][:2] == ["ID", "Description"]
    assert rows[1][1] == "Login with valid credentials"


def test_the_header_is_kept() -> None:
    """Which column is the scenario and which is the expected result is the one
    thing the file will not say twice, and it is the first thing that has to be
    worked out."""
    rows = read_sheet(workbook(SHEET), "cases.xlsx")

    assert rows[0] == ["ID", "Description", "Steps to Execute", "Expected Result"]


def test_a_csv_is_read_too() -> None:
    data = b"ID,Description\nTC-1,Login with valid credentials\n"

    rows = read_sheet(data, "cases.csv")

    assert rows[1] == ["TC-1", "Login with valid credentials"]


def test_a_csv_saved_from_excel_keeps_its_first_heading() -> None:
    """Excel writes a byte-order mark, and read as text it turns the first
    column heading into something no rule will match."""
    rows = read_sheet(b"\xef\xbb\xbfID,Description\nTC-1,Login\n", "cases.csv")

    assert rows[0][0] == "ID"


def test_only_the_first_tab_is_read() -> None:
    """A workbook's other tabs are usually a summary, a pivot, or last
    quarter's copy. Importing those as test cases would be a surprise."""
    rows = read_sheet(workbook(SHEET, sheets=3), "cases.xlsx")

    assert len(rows) == 3
    assert not any("Another tab" in cell for row in rows for cell in row)


def test_blank_rows_are_dropped() -> None:
    """Spreadsheets are full of them, and each one would otherwise be offered
    to the model as a test case to convert."""
    rows = read_sheet(workbook([["ID"], [], ["", ""], ["TC-1"]]), "cases.xlsx")

    assert rows == [["ID"], ["TC-1"]]


def test_numbers_survive_as_text_and_empty_cells_stay_empty() -> None:
    """A cell holding 1 is a test id, not an integer, and `None` from an empty
    cell must not reach the model as the word "None"."""
    rows = read_sheet(workbook([["ID", "Note", "Priority"], [1, None, 3]]), "cases.xlsx")

    assert rows[1] == ["1", "", "3"]


# ---------------------------------------------------------------------------
# Refusing the file rather than the rows
# ---------------------------------------------------------------------------
def test_a_file_that_is_not_a_spreadsheet_says_so() -> None:
    with pytest.raises(ValidationError, match="could not be opened"):
        read_sheet(b"this is not a workbook", "cases.xlsx")


def test_an_empty_file_says_so() -> None:
    with pytest.raises(ValidationError, match="no rows"):
        read_sheet(workbook([[], [""]]), "cases.xlsx")


def test_far_too_many_rows_is_the_wrong_file() -> None:
    """A thousand rows is a different file uploaded by mistake, and reading it
    would spend a day's worth of requests to say so."""
    with pytest.raises(ValidationError, match=str(MAX_ROWS)):
        read_sheet(workbook([[f"TC-{n}"] for n in range(MAX_ROWS + 1)]), "cases.xlsx")


def test_one_pasted_essay_cannot_crowd_out_the_other_rows() -> None:
    rows = read_sheet(workbook([["Steps"], ["x" * (MAX_CELL * 3)]]), "cases.xlsx")

    assert len(rows[1][0]) == MAX_CELL


# ---------------------------------------------------------------------------
# How the model sees it
# ---------------------------------------------------------------------------
def test_rows_are_numbered_so_a_skipped_one_can_be_found() -> None:
    """A row that cannot be automated has to come back with the number the
    person can find in their own file."""
    text = as_text(read_sheet(workbook(SHEET), "cases.xlsx"))

    assert text.splitlines()[0].startswith("1\tID")
    assert text.splitlines()[2].startswith("3\tTC-2")


def test_columns_are_separated_by_tabs_not_pipes() -> None:
    """A value containing a pipe would quietly become two columns."""
    text = as_text([["a|b", "c"]])

    assert text == "1\ta|b\tc"


def test_a_blank_between_two_filled_cells_is_kept() -> None:
    """Only trailing blanks go. A gap in the middle is a column the team left
    empty on that row, and dropping it would shift every column after it."""
    rows = read_sheet(workbook([["ID", "Steps", "Expected"], ["TC-1", "", "Dashboard"]]),
                      "cases.xlsx")

    assert rows[1] == ["TC-1", "", "Dashboard"]


# ---------------------------------------------------------------------------
# Reading a sheet with no model at all
# ---------------------------------------------------------------------------
"""A sheet already written in the vocabulary needs no judgement, and reading it
without one is worth more than the saved request: the reading is exact, and the
same file always reads the same way."""

VOCABULARY = [
    ["Test Case", "Action", "Target", "Value"],
    ["Login works", "goto", "", "https://x.test/login"],
    ["", "fill", "LoginPage.email_input", "a@b.test"],
    ["", "click", "LoginPage.sign_in_button", ""],
    ["", "expect_visible", "DashboardPage.heading", ""],
    ["Login is refused", "goto", "", "https://x.test/login"],
    ["", "click", "LoginPage.sign_in_button", ""],
    ["", "expect_visible", "LoginPage.email_input", ""],
]


def test_a_vocabulary_sheet_is_read_with_no_model() -> None:
    cases = read_without_ai(read_sheet(workbook(VOCABULARY), "cases.xlsx"))

    assert cases is not None
    assert [c.name for c in cases] == ["Login works", "Login is refused"]
    assert [s.action for s in cases[0].steps] == ["goto", "fill", "click", "expect_visible"]
    assert cases[0].steps[1].target == "LoginPage.email_input"
    assert cases[0].steps[1].value == "a@b.test"


def test_a_blank_case_cell_continues_the_case_above_it() -> None:
    """Which is how anybody writing this by hand already lays it out."""
    cases = read_without_ai(read_sheet(workbook(VOCABULARY), "cases.xlsx"))

    assert len(cases[0].steps) == 4


def test_an_empty_value_becomes_nothing_rather_than_an_empty_string() -> None:
    """`click` takes no value, and a step carrying "" would be asked to use it."""
    cases = read_without_ai(read_sheet(workbook(VOCABULARY), "cases.xlsx"))

    assert cases[0].steps[2].value is None
    assert cases[0].steps[0].target is None


@pytest.mark.parametrize(
    "header",
    [
        ["Scenario", "Verb", "Element", "Data"],
        ["Name", "Action", "Locator", "Value"],
        ["TEST CASE", "ACTION", "TARGET", "VALUE"],
    ],
)
def test_the_usual_names_for_those_columns_are_recognised(header) -> None:
    cases = read_without_ai(read_sheet(workbook([header, ["A", "click", "P.b", ""]]),
                                       "cases.xlsx"))

    assert cases is not None and cases[0].steps[0].action == "click"


def test_a_sheet_written_for_a_person_is_not_read_this_way() -> None:
    """"Enter the email and press Login" needs judgement to become an element,
    and a half-reading produces cases that compile and test the wrong thing."""
    assert read_without_ai(read_sheet(workbook(SHEET), "cases.xlsx")) is None


def test_an_action_column_with_nothing_to_act_on_is_not_enough() -> None:
    """A person's sheet that happens to share a word."""
    rows = read_sheet(workbook([["Step", "Action", "Expected Result"],
                                ["1", "Click the login button", "Dashboard"]]), "cases.xlsx")

    assert read_without_ai(rows) is None


def test_rows_with_no_action_are_skipped_not_turned_into_steps() -> None:
    """A notes row, or a separator somebody left in."""
    rows = read_sheet(workbook([["Test Case", "Action", "Target"],
                                ["Login works", "click", "P.b"],
                                ["-- end of sprint 4 --", "", ""]]), "cases.xlsx")
    cases = read_without_ai(rows)

    assert len(cases) == 1 and len(cases[0].steps) == 1


# ---------------------------------------------------------------------------
# Compiling the drafts
#
# Until now nothing here called `_checked`, and a NameError sat in its closing
# log line where every import ended up. It cost two paid model calls and a
# 500 before anyone saw it, because the crash lands *after* the reading is
# done - the sheet is understood, the cases are built, and then the request
# dies on the way out.
# ---------------------------------------------------------------------------
def compiles(cases: list, **kwargs) -> ImportOutcome:
    """Run the drafts through the real checker, with no database behind it."""
    page = PageSpec(class_name="LoginPage", module="login_page", url="https://x.test/login")
    page.locators.append(
        LocatorSpec(
            name="email_input",
            expression="self.page.locator('#email')",
            strategy="css_id",
            fragile=False,
        )
    )
    recorded = TestIR(
        suite_name="Login",
        function_name="test_login",
        module_name="test_login",
        start_url="https://x.test/login",
        pages=[page],
    )
    return ImportService(None)._checked(
        cases, recorded, suite_id=7, rows=len(cases), reading="read", **kwargs
    )


def test_an_import_survives_the_walk_out() -> None:
    """The whole outcome, built and returned. No cases needed to prove it."""
    outcome = compiles([])

    assert outcome.rows == 0
    assert outcome.cases == []


def test_a_draft_that_cannot_compile_is_reported_not_dropped() -> None:
    """A row that came back and then vanished is worse than one never read:
    the sheet does not add up and there is nothing to look at to find out why."""
    nonexistent = GeneratedCase(
        name="Click a button nobody has",
        category="positive",
        priority="medium",
        description="Built on an element the recording never saw.",
        steps=[
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(
                action="click",
                target="LoginPage.no_such_button",
                description="Click it",
            ),
        ],
    )

    outcome = compiles([nonexistent])

    assert outcome.cases == []
    assert len(outcome.skipped) == 1
    assert outcome.skipped[0].scenario == "Click a button nobody has"
    assert outcome.skipped[0].reason
