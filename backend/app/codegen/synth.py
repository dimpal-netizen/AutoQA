"""Build a TestIR from an invented test case.

The counterpart to `converter.py`. That one turns *recorded* actions into a
TestIR; this one turns a *described* case into the same structure, so both end
up in the same templates, the same validator and the same runner.

The rule from `enhancer.py` holds here too, and matters more: the model never
writes code. It picks an action from a fixed vocabulary and points at a locator
that already exists on a page object we generated ourselves. Every reference is
checked before a line is emitted, so a hallucinated element becomes a dropped
step — never a test that crashes on a property that was never there.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.codegen.converter import PageSpec, StepSpec, TestIR, page_variables
from app.codegen.selectors import clip_words, py_str, snake_case
from app.models.enums import ActionType

logger = logging.getLogger(__name__)

MAX_STEPS = 30


class SynthesisError(Exception):
    """The described case could not be turned into a valid test."""


@dataclass(frozen=True)
class Verb:
    """One allowed action: how it renders, and what it needs."""

    action: ActionType
    needs_target: bool
    needs_value: bool
    render: str  # format string over {target} and {value}
    # Whether an empty string is a legitimate value. True only for `fill`:
    # clearing a required field and submitting is one of the most valuable
    # negative tests there is, and rejecting it as "missing a value" would make
    # the single most obvious QA check impossible to express.
    allows_empty: bool = False


# The whole vocabulary. Anything outside this cannot be expressed, which is the
# point — it bounds what a generated test is able to do to the app under test.
VERBS: dict[str, Verb] = {
    "goto": Verb(ActionType.NAVIGATE, False, True, "page.goto({value})"),
    "fill": Verb(ActionType.INPUT, True, True, "{target}.fill({value})", allows_empty=True),
    "click": Verb(ActionType.CLICK, True, False, "{target}.click()"),
    "check": Verb(ActionType.CHECK, True, False, "{target}.check()"),
    "uncheck": Verb(ActionType.UNCHECK, True, False, "{target}.uncheck()"),
    "select": Verb(ActionType.SELECT, True, True, "{target}.select_option({value})"),
    "press": Verb(ActionType.KEY_PRESS, True, True, "{target}.press({value})"),
    "expect_visible": Verb(
        ActionType.ASSERT, True, False, "expect({target}).to_be_visible()"
    ),
    "expect_hidden": Verb(
        ActionType.ASSERT, True, False, "expect({target}).to_be_hidden()"
    ),
    "expect_text": Verb(
        ActionType.ASSERT, True, True, "expect({target}).to_contain_text({value})"
    ),
    "expect_url": Verb(
        ActionType.ASSERT, False, True, "expect(page).to_have_url(re.compile({value}))"
    ),
    "expect_not_url": Verb(
        ActionType.ASSERT,
        False,
        True,
        "expect(page).not_to_have_url(re.compile({value}))",
    ),
}

# Actions that only observe. A case made of nothing but these passes trivially.
_ASSERTIONS = {
    "expect_visible",
    "expect_hidden",
    "expect_text",
    "expect_url",
    "expect_not_url",
}


def synthesise(
    case: object,
    *,
    pages: list[PageSpec],
    start_url: str,
    module_name: str,
    function_name: str,
) -> TestIR:
    """Turn one described case into a TestIR reusing `pages`.

    Raises SynthesisError when the case cannot be expressed safely. The caller
    drops that case and keeps the rest — one bad suggestion out of fifteen is
    normal and should not cost the other fourteen.
    """
    steps_in = list(getattr(case, "steps", []) or [])
    if not steps_in:
        raise SynthesisError("no steps")
    if len(steps_in) > MAX_STEPS:
        raise SynthesisError(f"{len(steps_in)} steps is beyond the {MAX_STEPS} limit")

    locators = _locator_index(pages)
    variable_of = {class_name: var for var, class_name in page_variables_for(pages)}

    steps: list[StepSpec] = []
    used_pages: set[str] = set()
    needs_regex = False

    for index, raw in enumerate(steps_in):
        verb = VERBS.get(str(getattr(raw, "action", "")).strip().lower())
        if verb is None:
            raise SynthesisError(f"step {index}: unknown action {getattr(raw, 'action', None)!r}")

        value = getattr(raw, "value", None)
        if verb.needs_value:
            if value is None and verb.allows_empty:
                value = ""  # "clear the field" arrives as an omitted value
            if value is None or (value == "" and not verb.allows_empty):
                raise SynthesisError(f"step {index}: '{raw.action}' needs a value")

        target_expr: str | None = None
        locator_name: str | None = None
        page_var: str | None = None

        if verb.needs_target:
            key = str(getattr(raw, "target", "") or "").strip()
            found = locators.get(key) or locators.get(key.lower().replace(" ", ""))
            if found is None:
                # The single most common bad suggestion: a plausible element
                # that does not exist on any page we generated.
                raise SynthesisError(f"step {index}: unknown element {key!r}")
            class_name, locator_name = found
            page_var = variable_of.get(class_name)
            if page_var is None:
                raise SynthesisError(f"step {index}: no page variable for {class_name}")
            used_pages.add(class_name)
            target_expr = f"{page_var}.{locator_name}"

        if str(raw.action).strip().lower() in ("expect_url", "expect_not_url"):
            needs_regex = True

        line = verb.render.format(
            target=target_expr or "",
            value=py_str(str(value)) if value is not None else "",
        )

        steps.append(
            StepSpec(
                sequence=len(steps),
                action=verb.action,
                code=[line],
                description=_clean(getattr(raw, "description", "") or str(raw.action)),
                page_var=page_var,
                locator_name=locator_name,
                input_data=str(value) if value is not None and verb.action
                is not ActionType.ASSERT else None,
                expected_result=str(value)
                if verb.action is ActionType.ASSERT and value is not None
                else None,
            )
        )

    _assert_meaningful(steps_in)

    ir = TestIR(
        suite_name=_clean(getattr(case, "name", "Generated test")),
        function_name=function_name,
        module_name=module_name,
        start_url=start_url,
        # Only the pages this case actually touches, so its module does not
        # import page objects it never uses.
        pages=[p for p in pages if p.class_name in used_pages],
        steps=steps,
        needs_regex=needs_regex,
    )
    return ir


def page_variables_for(pages: list[PageSpec]) -> list[tuple[str, str]]:
    """(variable, ClassName) for a bare page list, mirroring page_variables()."""
    return page_variables(TestIR(suite_name="", function_name="", module_name="", start_url="", pages=pages))


def _locator_index(pages: list[PageSpec]) -> dict[str, tuple[str, str]]:
    """Every addressable locator, keyed the way the model is told to write it.

    Matching is case-insensitive and ignores spaces, because "LoginPage.email"
    and "loginpage.email_input" are the same intent expressed sloppily, and
    rejecting the second helps nobody.
    """
    index: dict[str, tuple[str, str]] = {}
    for page in pages:
        for locator in page.locators:
            for key in (
                f"{page.class_name}.{locator.name}",
                f"{page.class_name}.{locator.name}".lower(),
                locator.name.lower(),
            ):
                index.setdefault(key.replace(" ", ""), (page.class_name, locator.name))
    return index


def _assert_meaningful(steps: list[object]) -> None:
    """Refuse a case that never checks anything.

    A test with no assertion passes whether or not the feature works, which is
    worse than no test: it reports green and hides the bug.
    """
    actions = {str(getattr(s, "action", "")).strip().lower() for s in steps}
    if not (actions & _ASSERTIONS):
        raise SynthesisError("no assertion; the test would pass even when broken")


def _clean(text: str) -> str:
    """Same neutralising as the enhancer: this lands in comments and docstrings."""
    out = " ".join(str(text).split()).replace("\\", "").replace('"', "'")
    out = "".join(ch for ch in out if ch.isprintable())
    return out[:300].rstrip() or "Step"


def module_for(name: str, taken: set[str]) -> tuple[str, str]:
    """A unique (module_name, function_name) pair derived from a case name.

    Uniqueness is checked against the *final* `test_` prefixed name, not the
    stem. Comparing stems looks equivalent and is not: `taken` holds real module
    names, so a case called "Login" would sail past a check for "login" and
    then write itself over `test_login.py` — the recorded test.
    """
    # Clipped on a word boundary. A flat slice produced names like
    # `test_verify_back_to_search_link_is_not_visible_on_the`, which stops
    # mid-sentence and tells you least at the point you most need it: in a
    # failure report, where the name is all you get.
    stem = clip_words(
        snake_case(re.sub(r"[^0-9a-zA-Z ]+", " ", name), fallback="case"), 48
    )
    stem = stem.strip("_") or "case"

    candidate = f"test_{stem}"
    suffix = 2
    while candidate in taken:
        candidate = f"test_{stem}_{suffix}"
        suffix += 1
    taken.add(candidate)

    return candidate, candidate
