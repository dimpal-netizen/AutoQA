"""Somebody else's manual test-case sheet, read and drafted.

Every QA team keeps a spreadsheet of cases a person walks through by hand, and
no two of those sheets look alike: one calls the column "Description", the next
"Scenario", the one after that "Test Case". Getting them into AutoQA meant
retyping each one through the step editor, and nobody was ever going to retype
forty.

Nothing here is saved. The drafts come back in the same shape the editor sends,
so saving one goes through the identical path a typed case does - the same
vocabulary, the same validation, the same generator. An imported case cannot do
anything a hand-written one could not, which is the whole reason it is safe to
accept a file from outside at all.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.ai.case_generator import describe_pages, describe_steps
from app.ai.client import LLMError, ai_available, get_llm_client, load_prompt
from app.ai.schemas import CaseStep, GeneratedCase, ImportedCases, SkippedRow
from app.codegen.synth import SynthesisError, module_for, synthesise
from app.models.user import User
from app.services.codegen_service import CodegenService
from app.services.exceptions import ValidationError

logger = logging.getLogger(__name__)

#: A sheet is somebody's working document, not a payload. Forty cases is a big
#: one; a thousand rows is a different file that has been uploaded by mistake,
#: and reading it would cost a day's worth of requests to say so.
MAX_ROWS = 200

#: Long enough for a "Steps to Execute" cell holding eight numbered lines, short
#: enough that one pasted essay cannot crowd out the other thirty-nine rows.
MAX_CELL = 600


@dataclass
class ImportOutcome:
    """What an upload produced, before anybody agrees to keep it."""

    reading: str = ""
    rows: int = 0
    cases: list[GeneratedCase] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0


def _without_trailing_blanks(row: list[str]) -> list[str]:
    """The row up to its last cell with something in it.

    Only trailing ones. A blank *between* two filled cells is a column the team
    left empty on that row, and dropping it would shift every column after it.
    """
    end = len(row)
    while end and not row[end - 1]:
        end -= 1
    return row[:end]


def read_sheet(data: bytes, filename: str) -> list[list[str]]:
    """The uploaded file as rows of text, header included.

    The header is kept deliberately. Which column is the scenario and which is
    the expected result is the one thing the file will not say twice, and it is
    the first thing that has to be worked out.
    """
    name = (filename or "").lower()

    if name.endswith(".csv") or (not name.endswith((".xlsx", ".xlsm")) and b"," in data[:200]):
        text = data.decode("utf-8-sig", errors="replace")
        rows = [list(row) for row in csv.reader(io.StringIO(text))]
    else:
        try:
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - any unreadable file is one answer
            raise ValidationError(
                "That file could not be opened as a spreadsheet. Save it as "
                ".xlsx or .csv and try again."
            ) from exc
        # The first sheet only. A workbook's other tabs are usually a summary,
        # a pivot, or last quarter's copy, and importing those as test cases
        # would be a surprise nobody asked for.
        rows = [
            ["" if cell is None else str(cell) for cell in row]
            for row in book.worksheets[0].iter_rows(values_only=True)
        ]
        book.close()

    trimmed = [
        # Trailing blanks go. A workbook pads every row out to the width of the
        # widest one, so a sheet with a nine-column header hands the model eight
        # empty cells after every short row - noise it then has to reason past.
        _without_trailing_blanks([cell.strip()[:MAX_CELL] for cell in row])
        for row in rows
        if any(str(cell).strip() for cell in row)
    ]
    if not trimmed:
        raise ValidationError("That file has no rows in it.")
    if len(trimmed) > MAX_ROWS:
        raise ValidationError(
            f"That file has {len(trimmed)} rows. {MAX_ROWS} is the most that can "
            "be read at once - split it, or delete the rows you do not need "
            "automated."
        )
    return trimmed


def as_text(rows: list[list[str]]) -> str:
    """The sheet as the model sees it: numbered rows, tab-separated columns.

    Numbered because a row that cannot be automated has to come back with the
    number the person can find in their own file. Tabs rather than a table
    because a value containing a pipe would quietly become two columns.
    """
    return "\n".join(
        f"{number}\t" + "\t".join(row) for number, row in enumerate(rows, start=1)
    )


#: Column headings that mean each thing, lower-cased. A sheet written for
#: AutoQA rather than for a person will use one of these; a sheet written for a
#: person will use none of them, which is exactly how the two are told apart.
_HEADINGS: dict[str, tuple[str, ...]] = {
    "case": ("test case", "case", "scenario", "test", "name", "title", "test case name"),
    "action": ("action", "verb", "step type", "step action"),
    "target": ("target", "element", "locator", "object"),
    "value": ("value", "data", "input", "test data", "expected"),
}


def _columns(header: list[str]) -> dict[str, int] | None:
    """Which column is which, or None when this is not a vocabulary sheet.

    `action` and `target` both have to be there. A sheet with a column called
    "Action" and nothing to act on is a person's sheet that happens to share a
    word, and reading it this way would produce steps pointing at nothing.
    """
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        name = cell.strip().lower()
        for field_name, aliases in _HEADINGS.items():
            if name in aliases and field_name not in found:
                found[field_name] = index
    return found if {"action", "target"} <= found.keys() else None


def read_without_ai(rows: list[list[str]]) -> list[GeneratedCase] | None:
    """The sheet as test cases, with no model involved, or None.

    Works when the sheet is already written in the vocabulary - a row per step,
    with the action, the element and the value in their own columns:

        Test Case            Action          Target                    Value
        Login works          goto                                      /login
                             fill            LoginPage.email_input     a@b.test
                             click           LoginPage.sign_in_button
                             expect_visible  DashboardPage.heading

    A blank case cell continues the case above it, which is how anybody writing
    this by hand already lays it out.

    Free prose - "enter the email and press Login" - is the other kind of sheet
    and cannot be read this way, because deciding that "press Login" means
    `LoginPage.sign_in_button` is judgement. That one needs the model, and
    `preview` falls back to it.

    Returning None rather than a half-reading is deliberate: a sheet read the
    wrong way produces cases that compile and test the wrong thing.
    """
    if not rows:
        return None
    columns = _columns(rows[0])
    if columns is None:
        return None

    def cell(row: list[str], field_name: str) -> str:
        index = columns.get(field_name)
        return row[index].strip() if index is not None and index < len(row) else ""

    cases: list[GeneratedCase] = []
    for row in rows[1:]:
        action = cell(row, "action").lower()
        if not action:
            continue

        name = cell(row, "case")
        if name or not cases:
            cases.append(
                GeneratedCase(
                    name=name or "Imported test case",
                    category="positive",
                    priority="medium",
                    description="Imported from a spreadsheet.",
                    steps=[],
                )
            )
        cases[-1].steps.append(
            CaseStep(
                action=action,
                target=cell(row, "target") or None,
                value=cell(row, "value") or None,
            )
        )

    return [case for case in cases if case.steps] or None


class ImportService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.codegen = CodegenService(db)

    def preview(
        self, suite_id: int, data: bytes, filename: str, user: User
    ) -> ImportOutcome:
        """Read the sheet against one suite's recording. Saves nothing."""
        suite = self.codegen.get_suite(suite_id, user)
        recorded = self.codegen._recorded_ir(suite)
        if recorded is None or not recorded.pages:
            raise ValidationError(
                "This suite has no recording behind it, so there are no "
                "elements an imported case could refer to."
            )

        rows = read_sheet(data, filename)

        # A sheet already written in the vocabulary needs no model, and that is
        # worth checking first for more than the cost: the reading is exact and
        # the same file always reads the same way. Only a sheet written for a
        # person to follow needs the judgement an AI is here for.
        plain = read_without_ai(rows)
        if plain is not None:
            return self._checked(
                plain,
                recorded,
                suite_id=suite_id,
                rows=len(rows),
                reading=(
                    "Read as a vocabulary sheet - one row per step, with the "
                    "action, element and value in their own columns. No AI was "
                    "needed."
                ),
            )

        if not ai_available():
            raise ValidationError(
                "Reading a sheet needs an AI provider, because no two teams lay "
                "one out the same way. Add a key to .env and restart the API."
            )
        try:
            client = get_llm_client()
        except LLMError as exc:
            raise ValidationError(str(exc)) from exc

        described = describe_pages(recorded.pages)
        if not described:
            raise ValidationError(
                "Every element in this recording can only be found by its "
                "position in the page, so nothing imported against it could be "
                "trusted. Add a data-testid to the controls you want covered "
                "and record again."
            )

        try:
            response = client.complete_model(
                load_prompt(
                    "import_cases",
                    suite_name=recorded.suite_name,
                    start_url=recorded.start_url,
                    pages=described,
                    steps=describe_steps(recorded),
                    sheet=as_text(rows),
                ),
                ImportedCases,
                max_tokens=32000,
            )
        except LLMError as exc:
            raise ValidationError(str(exc)) from exc

        read = response.parsed
        if not isinstance(read, ImportedCases):
            raise ValidationError("The sheet could not be read into test cases.")

        return self._checked(
            read.cases,
            recorded,
            suite_id=suite_id,
            rows=len(rows),
            reading=read.reading,
            skipped=list(read.skipped),
            model=response.model,
            tokens=response.input_tokens + response.output_tokens,
            cost_usd=response.cost_usd,
        )

    def _checked(
        self,
        cases: list[GeneratedCase],
        recorded,
        *,
        suite_id: int,
        rows: int,
        reading: str,
        skipped: list[SkippedRow] | None = None,
        model: str = "",
        tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> ImportOutcome:
        """Compile every draft and keep the ones that survive.

        Both readings come through here, so a hand-written vocabulary sheet is
        held to exactly the rules a model's reading is - an element that does
        not exist, steps in an order that cannot happen, a case that checks
        nothing. Compiled and thrown away, so nothing in the preview can fail
        on save.
        """
        outcome = ImportOutcome(
            reading=reading,
            rows=rows,
            skipped=list(skipped or []),
            model=model,
            tokens=tokens,
            cost_usd=cost_usd,
        )

        taken: set[str] = {recorded.module_name}
        for case in cases:
            why = self._will_not_compile(case, recorded, taken)
            if why is None:
                outcome.cases.append(case)
            else:
                # Back into `skipped` rather than dropped. A row that came back
                # as a case and then vanished is the one thing worse than a row
                # that was never converted: the sheet does not add up, and there
                # is nothing to look at to find out why.
                outcome.skipped.append(
                    SkippedRow(row=0, scenario=case.name, reason=why)
                )

        logger.info(
            "Suite %s: read %d row(s) into %d case(s), %d skipped",
            suite_id, outcome.rows, len(outcome.cases), len(outcome.skipped),
        )
        return outcome

    def _will_not_compile(self, case: GeneratedCase, recorded, taken: set[str]) -> str | None:
        """Why this drafted case cannot become a test, or None if it can.

        Compiled here and thrown away, so the preview offers nothing that would
        fail on save. Every rule the generator enforces applies - an element
        that does not exist, steps in an order that cannot happen, a case that
        checks nothing - and the message it raises is already written for a
        person to read.
        """
        module_name, function_name = module_for(case.name, taken)
        try:
            synthesise(
                case,
                pages=recorded.pages,
                start_url=recorded.start_url,
                module_name=module_name,
                function_name=function_name,
                recorded_steps=recorded.steps,
                unique_values=recorded.unique_values,
            )
        except SynthesisError as exc:
            return str(exc)
        return None
