"""What we ask the model to return.

These are the shapes handed to `complete_model()`, which makes the provider
validate its own output against them. Everything here is advisory data — names
and prose — never code. The model is never allowed to write a line that ends up
executing; see `enhancer.py` for why.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CodeEnhancement(BaseModel):
    """Naming and documentation improvements for a generated suite."""

    function_name: str | None = Field(
        default=None,
        description="pytest function name, snake_case, starts with test_, under 60 chars",
    )
    title: str | None = Field(
        default=None, description="Short human-readable suite name, under 60 chars"
    )
    description: str | None = Field(
        default=None, description="One or two sentences on what this test verifies"
    )
    step_descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Clearer sentence per step, keyed by the step's sequence number as a string",
    )
    locator_names: dict[str, str] = Field(
        default_factory=dict,
        description='Better page-object property names, keyed by "PageClassName.current_name"',
    )


class CaseStep(BaseModel):
    """One step of an invented test case.

    Note what is *not* here: code. The model chooses an action from a fixed
    vocabulary and points at a locator that already exists on a page object.
    Anything else is rejected, so a hallucinated element becomes a dropped
    step rather than a test that crashes.
    """

    action: str = Field(
        description=(
            "One of: goto, fill, click, check, uncheck, select, press, "
            "expect_visible, expect_hidden, expect_text, expect_url, "
            "expect_not_url"
        )
    )
    target: str | None = Field(
        default=None,
        description='Locator as "PageClassName.property_name". Omit for goto and expect_url.',
    )
    value: str | None = Field(
        default=None, description="Text to type, option to select, key to press, or URL"
    )
    # No `description`. It used to be here, and asking for it was the single
    # most expensive field in the schema: a line of English per step, four to
    # eight steps a case, twelve cases a call - most of a 28,000-token answer
    # that then ran out of room mid-JSON and lost the whole request. On a key
    # allowed twenty requests a day, a request that returns nothing is a large
    # fraction of the day.
    #
    # Nothing was lost by dropping it. "Click the sign in button" is derivable
    # from the action and the element, `converter.py` has always derived it that
    # way for recorded steps, and deriving it here means a recorded step and an
    # invented one finally read alike. See `describe_step` in synth.py.


class GeneratedCase(BaseModel):
    name: str = Field(description="Short sentence describing what this verifies")
    category: str = Field(description="One of: positive, negative, edge, security")
    priority: str = Field(description="One of: critical, high, medium, low")
    description: str = Field(description="Why this test matters, one or two sentences")
    steps: list[CaseStep] = Field(description="The steps, in order")


class GeneratedCases(BaseModel):
    cases: list[GeneratedCase] = Field(default_factory=list)


class SkippedRow(BaseModel):
    """A row of somebody's sheet that could not become an automated test."""

    row: int = Field(description="The row number in the uploaded file")
    scenario: str = Field(description="What that row was about, as written")
    reason: str = Field(
        description=(
            "Why it cannot be automated yet, in one sentence a person can act "
            "on - usually that it needs a flow nobody has recorded"
        )
    )


class ImportedCases(BaseModel):
    """Somebody else's test-case sheet, read and converted.

    `reading` comes back so the person who uploaded the file can see how it was
    understood before anything is saved. A sheet misread by one column produces
    confident nonsense, and the only way to catch that is to say out loud which
    column was taken for what.
    """

    reading: str = Field(
        description=(
            "How the sheet was understood, in one sentence naming the columns "
            "used"
        )
    )
    cases: list[GeneratedCase] = Field(
        default_factory=list, description="The rows that could be automated"
    )
    skipped: list[SkippedRow] = Field(
        default_factory=list,
        description="Rows that could not be, and why. Never drop one silently.",
    )


class DraftedBug(BaseModel):
    """A bug report as the model writes it, before validation."""

    title: str = Field(description="One scannable line stating the broken behaviour")
    description: str = Field(description="Two or three sentences on what is wrong")
    steps_to_reproduce: list[str] = Field(
        description="Numbered actions a person can follow by hand, with real values"
    )
    expected: str = Field(description="What should happen, one sentence")
    actual: str = Field(description="What did happen, one sentence")
    severity: str = Field(description="One of: critical, high, medium, low")
    priority: str = Field(description="One of: critical, high, medium, low")


class ResultsAnswer(BaseModel):
    """An answer to a question about a project's test results."""

    answer: str = Field(
        description="The answer, in plain English, as short as the question allows"
    )
    cites: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the tests, suites or runs the answer rests on, so the "
            "reader can go and look. Empty when it rests on nothing specific."
        ),
    )
    confident: bool = Field(
        description=(
            "False when the stored results do not really support an answer — "
            "too few runs, no analysis, nothing recorded for what was asked"
        )
    )


class TriagedFailure(BaseModel):
    """One failure inside a whole-run triage.

    Carries `number` rather than a test name so the answer can be matched back
    to the exact result it is about. Names repeat — the same test fails in three
    browsers — and matching on prose the model retyped is how an explanation
    ends up filed against the wrong failure.
    """

    number: int = Field(description="The number this failure was listed under")
    test: str = Field(
        default="",
        description=(
            "The name of the test this is about, copied exactly from the list. "
            "Used only to check the numbering did not drift."
        ),
    )
    expected: str = Field(description="What the test was waiting to see, in one sentence")
    actual: str = Field(description="What happened instead, in one sentence")
    root_cause: str = Field(description="Why, in one or two sentences")
    suggested_fix: str = Field(description="The concrete next action, starting with a verb")
    category: str = Field(
        description=(
            "One of: application_bug, test_bug, selector_broken, timing, "
            "environment, test_data, flaky"
        )
    )
    severity: str = Field(description="One of: critical, high, medium, low")
    priority: str = Field(description="One of: critical, high, medium, low")
    confidence: float = Field(ge=0.0, le=1.0, description="How sure you are")
    is_product_bug: bool = Field(
        description="True if the application is broken, false if the test is"
    )
    same_cause_as: list[int] = Field(
        default_factory=list,
        description=(
            "Numbers of other failures in this run with the SAME underlying "
            "cause. Empty when this one stands alone."
        ),
    )


class RunTriage(BaseModel):
    """Every failure in a run, explained together rather than one at a time.

    The grouping is the reason this exists. Six failures with one cause is one
    afternoon's work; six failures with six causes is a week, and no per-failure
    analysis can tell the difference because each one only ever sees itself.
    """

    summary: str = Field(
        description=(
            "What is wrong with this run, in two or three sentences, for someone "
            "deciding whether to ship"
        )
    )
    distinct_causes: int = Field(
        description="How many genuinely different problems these failures represent"
    )
    failures: list[TriagedFailure] = Field(description="One entry per failure listed")


class FailureAnalysis(BaseModel):
    """Workflow 3 output: why a test failed and what to do about it.

    `expected` and `actual` come first deliberately. They are the two facts the
    reader wants before any explanation, and asking for them first makes the
    explanation better too: a model that has just written down both sides of the
    mismatch is far less likely to reason from the traceback alone and miss what
    the screenshot plainly shows.
    """

    expected: str = Field(
        description=(
            "What the test was waiting to see, as a person would describe it. "
            "One sentence, no code. 'The one-time-password popup should have "
            "closed.'"
        )
    )
    actual: str = Field(
        description=(
            "What was on screen instead, read off the screenshot where there is "
            "one. One sentence, no code. 'The popup was still open, with the "
            "code boxes empty.'"
        )
    )
    root_cause: str = Field(description="What actually went wrong, in plain language")
    suggested_fix: str = Field(description="The concrete next action to take")
    category: str = Field(
        description=(
            "One of: application_bug, test_bug, selector_broken, timing, "
            "environment, test_data, flaky"
        )
    )
    severity: str = Field(description="One of: critical, high, medium, low")
    priority: str = Field(description="One of: critical, high, medium, low")
    confidence: float = Field(
        ge=0.0, le=1.0, description="How sure you are, 0.0 to 1.0"
    )
    is_product_bug: bool = Field(
        description="True if the application is broken, false if the test is"
    )
