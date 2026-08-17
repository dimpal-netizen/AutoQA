"""One recording, cut into the tests a person actually performed.

A recording is not one test. Somebody sits down, tries logging in with just an
email, gets an error, dismisses it, tries again with a wrong password, gets
another error, and then goes off to register instead. That is four things they
tested, and until now it became a single test case fifty-one steps long that
replays the whole afternoon top to bottom.

Which is worse than it sounds. Run as one case it passes or fails as one thing,
so a broken login and a broken registration are indistinguishable; and every
step after the first failure is meaningless, because the page is no longer where
the recording assumed.

So the recording is cut where the person started over. Two signals say that, and
both are things they did rather than things inferred about them:

  * **A field filled twice.** Typing into Email, submitting, then typing into
    Email again is somebody having another go. Nobody fills the same box twice
    inside one attempt.

  * **An error dismissed.** Clicking Dismiss or Close on a message and then
    carrying on ends whatever was being tried - the application has answered.

Deliberately nothing cleverer. A rule that split on navigation would cut a
successful login in half, because arriving at the dashboard is the *result* of
the test rather than the start of a new one. A recording with no repeats stays
one case, which is the right answer for a recording of one journey.
"""

from __future__ import annotations

from typing import Any

from app.models.enums import ActionType

#: Words on a control that closes an error and hands the form back. Clicking one
#: ends the attempt: whatever was being tried has been answered.
DISMISSES = ("dismiss", "close", "try again", "got it")

#: Below this, a segment is not a test - it is the tail of the one before it.
#: Two actions of a person clicking about after an error is not a scenario, and
#: shipping it as a case means a red row nobody can act on.
MIN_ACTIONS = 3


def split(actions: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The recording, in the order it happened, cut where somebody started over.

    Returns at least one segment for any non-empty recording. Segments too
    short to be a test are folded back into the one before them rather than
    dropped - the actions happened, and losing them would make the last case a
    lie about what was done.

    Nothing is filtered but the actions the recorder already marked as noise.
    The opening navigation stays in the first segment: it cannot become a
    segment of its own, because a cut only happens when there is something to
    cut away from.
    """
    usable = [a for a in actions if not a.get("is_ignored")]
    if not usable:
        return []

    segments: list[list[dict[str, Any]]] = []
    # What each segment typed into, kept alongside it: a cut is only honest if
    # the segment after it fills the form itself. See `_merge_corrections`.
    typed: list[set[str]] = []
    current: list[dict[str, Any]] = []
    filled: set[str] = set()
    answered = False

    for action in usable:
        kind = _kind(action)
        name = _element_key(action)
        starts_over = (kind is ActionType.INPUT and name in filled) or (
            answered and kind in (ActionType.INPUT, ActionType.CLICK)
        )

        if starts_over and current:
            segments.append(current)
            typed.append(filled)
            current, filled, answered = [], set(), False

        current.append(action)

        if kind is ActionType.INPUT:
            filled.add(name)
        if kind is ActionType.CLICK and _is_dismissal(action):
            answered = True

    if current:
        segments.append(current)
        typed.append(filled)

    return _merge_stubs(_merge_corrections(segments, typed))


def _merge_corrections(segments: list[list], typed: list[set[str]]) -> list[list]:
    """Fold back a segment that only corrects a field, rather than starting over.

    The rule that cuts on a field being filled twice is right about a login
    form, where filling Email again means having another go. On a registration
    form it is wrong, and wrong in the way that produces exactly the test nobody
    wants:

        somebody fills eight fields, submits, is told the mobile number is
        invalid, corrects *just the mobile number*, and submits again.

    Cut there and the second half becomes a case that opens the form, types one
    field, submits, and waits thirty seconds for a confirmation that cannot
    arrive - because the other seven fields are empty. Blocked, every run,
    saying nothing about the application.

    The tell is that the second segment types into fewer fields than the first.
    A real second attempt fills the form again; a correction touches only what
    was wrong. So a segment whose fields are a subset of the one before it is
    not a test of its own - it is the rest of that one.
    """
    merged: list[list] = []
    kept: list[set[str]] = []

    for segment, fields in zip(segments, typed):
        correction = (
            bool(kept)
            and bool(fields)
            and fields < kept[-1]  # strictly fewer of the same boxes
        )
        if correction:
            merged[-1].extend(segment)
            kept[-1] = kept[-1] | fields
        else:
            merged.append(list(segment))
            kept.append(set(fields))

    return merged


def _merge_stubs(segments: list[list]) -> list[list]:
    """Fold segments too short to stand alone into their predecessor."""
    merged: list[list] = []
    for segment in segments:
        if len(segment) < MIN_ACTIONS and merged:
            merged[-1].extend(segment)
        else:
            merged.append(segment)

    # A leading stub has no predecessor to join, so it takes the next one.
    if len(merged) > 1 and len(merged[0]) < MIN_ACTIONS:
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged


def _kind(action: dict[str, Any]) -> ActionType | None:
    try:
        return ActionType(action.get("action_type"))
    except ValueError:
        return None


def _element_key(action: dict[str, Any]) -> str:
    """What this action drove, stable enough to recognise the same box twice.

    Read off the element rather than the selector list: the recorder ranks
    selectors per action, so the same field can be described by a test id one
    time and a placeholder the next, and comparing those would miss the repeat
    this whole module turns on.
    """
    element = action.get("element") or {}
    attributes = element.get("attributes") or {}
    return str(
        attributes.get("data-testid")
        or attributes.get("id")
        or attributes.get("name")
        or element.get("accessible_name")
        or attributes.get("placeholder")
        or f"{element.get('tag')}:{element.get('text')}"
    )


def _is_dismissal(action: dict[str, Any]) -> bool:
    element = action.get("element") or {}
    label = str(
        element.get("accessible_name") or element.get("text") or ""
    ).strip().lower()
    # Whole words: a "Close account" button is not a dismissal, and neither is
    # a link to a page called "Disclosures".
    return any(label == word or label.startswith(f"{word} ") for word in DISMISSES)


def as_tests(ir, starts: list[str]):
    """The one IR, sliced into one runnable test per segment.

    Sliced rather than rebuilt. The pages and their locator names are shared -
    every case says `login.email_input` and means the same element - because
    building an IR per segment would number the properties independently and a
    case would import something the page object does not have.

    Each slice opens its own page. Segment two of a login recording begins
    "type into Email", which is true only if you are already on the login form;
    run on its own it would fail on the first line for a reason that has nothing
    to do with the application. `starts` says where each segment was when it
    began, and a `goto` is put in front of any slice that does not already have
    one.

    Yields `(number, TestIR)`. The IRs share `pages` with the original by
    reference, which is the point - and means none of them may mutate it.
    """
    from dataclasses import replace

    from app.codegen.converter import TestIR
    from app.codegen.selectors import snake_case
    from app.models.enums import ActionType

    numbers = sorted({step.segment for step in ir.steps})

    for number in numbers:
        steps = [step for step in ir.steps if step.segment == number]
        if not steps:
            continue

        start = starts[number] if number < len(starts) else ir.start_url
        if steps[0].action is not ActionType.NAVIGATE:
            steps = [_opening(start)] + steps

        # Renumbered from zero: `sequence` is what the test-case sheet prints
        # and what "stopped at step 4" counts, and a case whose steps start at
        # 27 reads as though the first twenty-six went missing.
        steps = [replace(step, sequence=index) for index, step in enumerate(steps)]

        suffix = "" if len(numbers) == 1 else f"_{number + 1}"
        function_name = snake_case(
            f"test_{ir.suite_name}{suffix}", fallback=f"test_recorded{suffix}"
        )

        slice_ir = TestIR(
            suite_name=ir.suite_name,
            function_name=function_name,
            module_name=function_name,
            start_url=start,
            pages=ir.pages,
            steps=steps,
            fragile_count=sum(1 for step in steps if step.fragile),
            needs_regex=ir.needs_regex,
            needs_uuid=ir.needs_uuid,
            needs_unhealed=ir.needs_unhealed,
            needs_set_checked=ir.needs_set_checked,
            needs_reveal=ir.needs_reveal,
            needs_sample_file=ir.needs_sample_file,
            unique_values=ir.unique_values,
        )
        yield number, slice_ir


def _opening(url: str):
    """A `goto` for a slice that starts mid-flow."""
    from app.codegen.converter import StepSpec
    from app.codegen.selectors import py_str
    from app.models.enums import ActionType

    return StepSpec(
        sequence=0,
        action=ActionType.NAVIGATE,
        code=[f"page.goto({py_str(url)})"],
        description=f"Open {url}",
        expected_result="The page loads",
    )
