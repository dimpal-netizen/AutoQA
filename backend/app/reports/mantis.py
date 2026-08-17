"""AutoQA's bugs, said in Mantis's words.

The team this is for already keeps its defects in Mantis, and a register that
uses its own vocabulary makes somebody translate every row by hand before it can
be filed - "critical" into which severity, "draft" into which status, and what
is the resolution of a bug nobody has triaged. Two spellings of the same thing
is how a register stops being read.

So the field names, the values and the order below are Mantis's, not ours. The
mapping is one-way and lives here alone: both exports go through it, because a
workbook and a document that disagree about a bug's severity are worse than
either being wrong on its own.

Where Mantis has a field AutoQA cannot know - who it is assigned to, which
version it was fixed in - the value is empty rather than invented. An export
that guesses at an owner is one somebody has to check every row of.
"""

from __future__ import annotations

from app.models.enums import BugStatus, Severity

#: Mantis pads issue ids to seven digits, and its exports carry that form. A
#: register whose ids look like the tracker's can be searched in the tracker.
ID_WIDTH = 7


def issue_id(number: int) -> str:
    """`13` -> `0000013`, the way Mantis writes an id."""
    return str(max(int(number), 0)).rjust(ID_WIDTH, "0")


#: Mantis severities, in its own order of increasing seriousness. AutoQA has
#: four levels and Mantis has eight, so this is a widening: every AutoQA
#: severity has one obvious Mantis word, and none of Mantis's finer
#: distinctions - `tweak` against `text`, say - can be inferred from a test
#: failure without inventing information.
SEVERITY = {
    Severity.CRITICAL: "block",
    Severity.HIGH: "major",
    Severity.MEDIUM: "minor",
    Severity.LOW: "tweak",
}

#: Mantis priorities. Its scale runs none / low / normal / high / urgent /
#: immediate, and `normal` is its default rather than a middle value.
PRIORITY = {
    Severity.CRITICAL: "immediate",
    Severity.HIGH: "high",
    Severity.MEDIUM: "normal",
    Severity.LOW: "low",
}

#: Mantis statuses. A drafted report is `new` - AutoQA wrote it and nobody has
#: looked, which is exactly what new means there. Deliberately not
#: `acknowledged` or `confirmed`: both claim a person has seen it.
STATUS = {
    BugStatus.DRAFT: "new",
    BugStatus.OPEN: "assigned",
    BugStatus.RESOLVED: "resolved",
}

#: Mantis keeps resolution separate from status, and its default for anything
#: not yet dealt with is `open`.
RESOLUTION = {
    BugStatus.DRAFT: "open",
    BugStatus.OPEN: "open",
    BugStatus.RESOLVED: "fixed",
}

#: An automated test is the one reporter that can honestly say this. It ran the
#: same steps and got the same answer, which is what `always` means.
REPRODUCIBILITY = "always"

#: Mantis asks whether an issue is visible outside the team.
VIEW_STATUS = "public"

#: Who filed it. Named rather than left blank so a row in the tracker says
#: where it came from without anybody having to remember.
REPORTER = "AutoQA"

#: Mantis requires a category and every install defines its own. This is the
#: one every web project has, and it is the honest answer for a defect found by
#: driving a browser.
CATEGORY = "Front end issues"


def severity_of(value: Severity | str) -> str:
    return SEVERITY.get(_as(Severity, value), "minor")


def priority_of(value: Severity | str) -> str:
    return PRIORITY.get(_as(Severity, value), "normal")


def status_of(value: BugStatus | str) -> str:
    return STATUS.get(_as(BugStatus, value), "new")


def resolution_of(value: BugStatus | str) -> str:
    return RESOLUTION.get(_as(BugStatus, value), "open")


def _as(enum, value):
    """The enum member, whatever form it arrived in.

    Rows are built from two places - a drafted report and a bare failure - and
    only one of them has been through the ORM. A plain string reaching a lookup
    keyed by enum members misses silently and every row comes back as the
    default, which is the sort of wrong that looks right.
    """
    if isinstance(value, enum):
        return value
    try:
        return enum(str(value).strip().lower())
    except ValueError:
        return None


def description(bug) -> str:
    """Mantis's Description box, with the headings it puts there filled in.

    The form arrives holding `Summary:` / `Expected Result:` / `Actual Result:`
    for the reporter to complete. A test failure knows all three, so they are
    completed here - and the headings stay, so the box still looks like the one
    the team fills in by hand.

    Shared by both exports on purpose. The workbook and the document are the
    same bugs in two shapes, and a Description that reads one way in the sheet
    and another in the document is the sort of difference somebody notices
    while filing and then stops trusting both files over.
    """
    return "\n".join(
        [
            f"Summary: {bug.description or bug.title}",
            "",
            f"Expected Result: {bug.expected}",
            "",
            f"Actual Result: {bug.actual}",
        ]
    )


def additional_information(bug) -> str:
    """Mantis's Additional Information box, with its own headings filled in.

    `Browser Used` and `Device used` are what the team writes there, and a run
    knows both - so they are answered rather than left for somebody to look up.
    The line about the screenshot is Mantis's own wording, and it is conditional
    because promising an attachment that is not there is worse than saying
    nothing.
    """
    environment = bug.environment if isinstance(bug.environment, dict) else {}
    device = environment.get("os") or environment.get("platform") or ""

    lines = [
        f"Browser Used: {bug.browsers}",
        "",
        f"Device used: {device}",
        "",
        "Screen attached with bug if available."
        if bug.screenshot
        else "No screenshot was captured for this failure.",
    ]

    extra = [
        f"{key.replace('_', ' ')}: {value}"
        for key, value in environment.items()
        if value not in (None, "") and key not in ("browser", "os", "platform")
    ]
    if bug.case_name:
        extra.append(f"Found by test: {bug.case_name}")
    if not bug.drafted:
        extra.append("Raised automatically from a failing test; not yet reviewed.")
    if extra:
        lines += [""] + extra

    return "\n".join(lines)


def numbered(steps) -> str:
    """Steps as Mantis numbers them: `1.`, no space, one per line."""
    return "\n".join(f"{i}.{step}" for i, step in enumerate(steps or [], 1))


def fields(bug, *, index: int, project_name: str) -> list[tuple[str, str]]:
    """One bug as Mantis's own fields, in Mantis's own order.

    The single description of what a bug looks like, and the reason both
    exports can be trusted together: the document writes these as rows and the
    workbook writes them as columns, but neither decides what the fields are.
    Two lists would drift - they already did once, and the same bug read one way
    in the sheet and another in the document.

    The order is the tracker's: the identity fields it shows at the top of an
    issue, then the classification dropdowns, then the boxes somebody types
    into. Fields only a person can fill - the profile, who it is assigned to -
    are present and empty, because a form with a row missing is harder to work
    through than one with a row to skip.
    """
    submitted = bug.reported_on.strftime("%Y-%m-%d %H:%M") if bug.reported_on else ""

    return [
        ("ID", issue_id(index)),
        ("Project", project_name),
        ("Category", CATEGORY),
        ("View Status", VIEW_STATUS),
        ("Date Submitted", submitted),
        ("Last Update", submitted),
        ("Reporter", REPORTER),
        ("Assigned To", ""),
        ("Priority", priority_of(bug.priority)),
        ("Severity", severity_of(bug.severity)),
        ("Reproducibility", REPRODUCIBILITY),
        ("Status", status_of(bug.status)),
        ("Resolution", resolution_of(bug.status)),
        ("Select Profile", ""),
        ("Summary", bug.title),
        ("Description", description(bug)),
        ("Steps To Reproduce", numbered(bug.steps_to_reproduce)),
        ("Additional Information", additional_information(bug)),
        ("Tags", "No tags attached."),
    ]


#: The column headings, for a register that lists one bug per row. Taken from
#: `fields` rather than written out again, so a field added there appears in
#: both files or in neither.
def labels() -> list[str]:
    from datetime import datetime

    class _Blank:
        title = description = expected = actual = case_name = browsers = ""
        steps_to_reproduce: list = []
        environment: dict = {}
        reported_on: datetime | None = None
        screenshot = None
        severity = priority = status = None
        drafted = False

    return [label for label, _ in fields(_Blank(), index=0, project_name="")]
