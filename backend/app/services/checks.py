"""Checks added to a recorded test, which by default has none.

A recording captures what somebody did, not what should have been true
afterwards. The test it produces replays the clicks faithfully and asserts
nothing, so it passes as long as every click found something to click — add a
backpack to a cart that stays empty and it still reports green.

That test is the baseline every other case in the suite is written around, which
makes it the worst one to have no opinion.

Two halves live here and only one of them needs a model. Deciding that a cart
badge should change after "add to cart" is judgement, and `ai/prompts` asks for
it. Putting an accepted check into the right place in the test is arithmetic,
and that is this file — no model, no guessing, and the same `expect` the
recorded assertions have always compiled to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.codegen.converter import StepSpec, TestIR
from app.models.enums import ActionType

logger = logging.getLogger(__name__)

#: What a check may assert. Deliberately the two the converter has always
#: compiled for recorded assertions, rather than the synthesiser's seven: a
#: check is added to a *recording*, and "the password is masked" is not
#: something a recording ever observed.
KINDS = ("visible", "text")


@dataclass(frozen=True)
class Check:
    """One check, as it is stored on the suite and applied to the test."""

    #: The recorded step this goes after. The check is about the state the
    #: application is in once that step has happened.
    after: int
    #: `page_variable.locator_name`, the same way a step names an element.
    target: str
    kind: str
    expected: str = ""

    @property
    def page_var(self) -> str:
        return self.target.split(".", 1)[0]

    @property
    def locator_name(self) -> str:
        return self.target.split(".", 1)[-1]

    def as_dict(self) -> dict:
        return {
            "after": self.after,
            "target": self.target,
            "kind": self.kind,
            "expected": self.expected,
        }


def parse(stored) -> list[Check]:
    """Checks read back off the suite, ignoring anything malformed.

    Tolerant rather than strict: these are re-applied on every rebuild, and one
    bad row from an older shape must not stop a suite regenerating.
    """
    found: list[Check] = []
    for raw in stored or []:
        if not isinstance(raw, dict):
            continue
        target = str(raw.get("target") or "")
        kind = str(raw.get("kind") or "visible").lower()
        if "." not in target or kind not in KINDS:
            continue
        try:
            after = int(raw.get("after", 0))
        except (TypeError, ValueError):
            continue
        found.append(
            Check(
                after=after,
                target=target,
                kind=kind,
                expected=str(raw.get("expected") or ""),
            )
        )
    return found


def page_at(steps, after: int) -> str | None:
    """Which page the test is looking at once step `after` has happened.

    The page of the *next* step that names an element, not the previous one. A
    check belongs to the state a step left behind, and the step that got you
    there is usually the click that navigated away from the old page — so the
    element it named is on the page you have just left.

    Getting this backwards is how a check ends up one page early. From a real
    suite:

        4. Click "Create an Account!"        -> lands on /register
        5. Check "First Name" is visible     <- but that field is on
                                                /register/buyer, one click later

    It compiled, because the element does exist on a page object. It failed on
    every run, because the browser was not there yet. The element existing and
    the element being on screen are different questions, and only the second one
    is what a check asserts.
    """
    for step in steps:
        if step.sequence > after and step.page_var:
            return step.page_var

    # Nothing follows: a check on the last step is about wherever it ended up,
    # which is the last page anything was driven on.
    for step in reversed(steps):
        if step.page_var:
            return step.page_var
    return None


def apply(ir: TestIR, checks: list[Check]) -> TestIR:
    """Insert checks into a recorded test's IR, in place.

    Applied to the IR rather than written into the case, because that case is
    rebuilt from the recording every time the suite is regenerated — a check
    written onto it would last until the next press of a button.

    A check naming an element that no longer exists is dropped rather than
    emitted. Recordings get replaced, elements get renamed, and a check that
    compiles to a locator nobody defines is an ImportError at collection time
    that takes the whole run down with it.
    """
    if not checks:
        return ir

    known = {
        (page_var, locator.name)
        for page_var, page in _pages_by_var(ir)
        for locator in page.locators
    }

    # Read before anything is inserted: `page_at` walks the recorded steps, and
    # inserting a check would put an assertion into the sequence it reads.
    here = {check.after: page_at(ir.steps, check.after) for check in checks}

    # After the highest-numbered step it belongs to, working backwards, so an
    # insertion never shifts the position of one not yet placed.
    for check in sorted(checks, key=lambda c: c.after, reverse=True):
        if (check.page_var, check.locator_name) not in known:
            logger.info(
                "Dropped a check on %s - no such element in this recording",
                check.target,
            )
            continue

        if here[check.after] and check.page_var != here[check.after]:
            logger.info(
                "Dropped a check on %s after step %s - the test is on %s there",
                check.target, check.after, here[check.after],
            )
            continue

        at = _position_after(ir.steps, check.after)
        ir.steps.insert(at, _step(check))

    for index, step in enumerate(ir.steps):
        step.sequence = index

    ir.needs_unhealed = True
    return ir


def _pages_by_var(ir: TestIR):
    """(variable, page) pairs, the way a step names them."""
    from app.codegen.converter import page_variables

    by_class = {page.class_name: page for page in ir.pages}
    return [
        (var, by_class[class_name])
        for var, class_name in page_variables(ir)
        if class_name in by_class
    ]


def _position_after(steps: list[StepSpec], after: int) -> int:
    """Where a check numbered `after` goes.

    Steps are renumbered as they are inserted, so this matches on the sequence
    a step currently carries and falls back to the end — a check whose step has
    since been removed is better at the end than silently first.
    """
    for index, step in enumerate(steps):
        if step.sequence == after:
            return index + 1
    return len(steps)


def _step(check: Check) -> StepSpec:
    """The check as a step, compiling to the same `expect` a recorded one does.

    `unhealed` because this is an observation: healing would let a recorded
    spare answer about whichever element sits where this one used to, which
    turns "the cart shows 1" into a claim about something else entirely.
    """
    observed = f"unhealed({check.page_var}, {check.locator_name!r})"
    label = check.locator_name.replace("_", " ")

    if check.kind == "text" and check.expected:
        code = f"expect({observed}).to_contain_text({check.expected!r})"
        description = f"Check {label} shows {check.expected!r}"
        expected = check.expected
    else:
        code = f"expect({observed}).to_be_visible()"
        description = f"Check {label} is visible"
        expected = f"{label} is visible"

    return StepSpec(
        sequence=0,  # renumbered by `apply`
        action=ActionType.ASSERT,
        code=[code],
        description=description,
        page_var=check.page_var,
        locator_name=check.locator_name,
        expected_result=expected,
        verb="expect_text" if check.kind == "text" and check.expected else "expect_visible",
    )
