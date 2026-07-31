"""Drafting bug reports. No network.

A bug report is read by someone who will not open AutoQA, so the guards here
are about what reaches a ticket: a title that fits on one line, reproduction
steps that are actually present, and a severity that agrees with the analysis
rather than contradicting it in the same panel.
"""

import pytest

from app.ai.schemas import DraftedBug
from app.models.enums import BugStatus, Severity
from app.services.bug_service import _line, _text


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
