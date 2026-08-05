"""Build a TestIR from an invented test case.

The counterpart to `converter.py`. That one turns *recorded* actions into a
TestIR; this one turns a *described* case into the same structure, so both end
up in the same templates, the same validator and the same runner.

The rule from `enhancer.py` holds here too, and matters more: the model never
writes code. It picks an action from a fixed vocabulary and points at a locator
that already exists on a page object we generated ourselves. Every reference is
checked before a line is emitted, so a hallucinated element becomes a dropped
step — never a test that crashes on a property that was never there.

The same rule is what makes a *person* able to author a test here. A QA engineer
editing a case picks from the identical vocabulary and the identical element
list, and the identical checks run over what they picked. Nobody writes Python:
not the model, not the tester. That is the only reason it is safe to let a case
be edited at all — a free-text code box would put unreviewed Python into a
subprocess on someone's machine.
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
    # Masking is an attribute, not visibility. A password field is on screen and
    # `to_be_hidden()` is false for it whether or not the characters are shown,
    # so "the password is not displayed" had no way to be expressed — the model
    # reached for expect_hidden and produced a test that could only ever be red.
    "expect_masked": Verb(
        ActionType.ASSERT,
        True,
        False,
        "expect({target}).to_have_attribute('type', 'password')",
    ),
    # After the reveal toggle. A separate case, because it asserts the opposite
    # of the one above and depends on an action having been taken.
    "expect_not_masked": Verb(
        ActionType.ASSERT,
        True,
        False,
        "expect({target}).not_to_have_attribute('type', 'password')",
    ),
}

# What each verb is called in the editor. Kept beside the vocabulary rather than
# in the UI so the two cannot drift: a verb added here shows up in the dropdown
# with a name, and one added without a label is caught by a test rather than
# shipping as a raw identifier.
VERB_LABEL: dict[str, str] = {
    "goto": "Go to URL",
    "fill": "Type into",
    "click": "Click",
    "check": "Tick",
    "uncheck": "Untick",
    "select": "Choose from dropdown",
    "press": "Press key",
    "expect_visible": "Should be visible",
    "expect_hidden": "Should not be on the page",
    "expect_text": "Should contain text",
    "expect_url": "URL should contain",
    "expect_not_url": "URL should not contain",
    "expect_masked": "Should be hidden behind dots",
    "expect_not_masked": "Should be readable, not dots",
}

#: The verb behind a stored step, where the action names it beyond doubt.
#:
#: Every case saved before the editor existed has no verb recorded. Most can be
#: recovered from the action alone, which is the difference between those cases
#: being editable and being frozen until someone regenerates them. ASSERT is
#: deliberately absent — seven verbs share it, and a wrong guess would silently
#: change what a test checks, which is worse than declining to guess.
VERB_FOR_ACTION: dict[ActionType, str] = {
    ActionType.NAVIGATE: "goto",
    ActionType.INPUT: "fill",
    ActionType.CLICK: "click",
    ActionType.CHECK: "check",
    ActionType.UNCHECK: "uncheck",
    ActionType.SELECT: "select",
    ActionType.KEY_PRESS: "press",
}

# Actions that only observe. A case made of nothing but these passes trivially.
_ASSERTIONS = {
    "expect_visible",
    "expect_hidden",
    "expect_text",
    "expect_url",
    "expect_not_url",
    "expect_masked",
    "expect_not_masked",
}

#: Verbs whose value is a URL fragment that gets wrapped in `re.compile`.
_URL_ASSERTIONS = {"expect_url", "expect_not_url"}

#: Values that must differ on every run, and the expression each becomes.
#:
#: A registration test written with a fixed address passes the first time and
#: fails on every run after it, because the account now exists. The steps are
#: right and the result is red, which is the worst way for a test to be wrong —
#: it teaches a tester to distrust the tool rather than the application. It also
#: leaves a real account behind each time, so the app under test fills up with
#: junk that nobody asked for.
#:
#: The suffix is short and the prefix is fixed, so everything a run creates is
#: identifiable and can be cleaned up with one query.
_UNIQUE_VALUES = {
    "{{unique_email}}": "f'autoqa-{uuid4().hex[:10]}@example.test'",
    "{{unique_phone}}": "f'7{uuid4().int % 100_000_000:08d}'",
    "{{unique_name}}": "f'AutoQA {uuid4().hex[:6]}'",
    "{{unique}}": "uuid4().hex[:10]",
}

#: A placeholder anywhere in a value, written either way round.
#:
#: Two things had to be tolerated, because both are what actually arrives. The
#: model writes `{unique_name}` as often as `{{unique_name}}` — one set of braces
#: is the more natural way to write a placeholder, and the prompt asking for two
#: does not reliably get two. And it composes them: `{{unique_name}}First` is a
#: sensible thing to want in a first-name field.
#:
#: Matching the whole value exactly, as this once did, silently failed both. The
#: value did not equal any key, so it was emitted as a string literal and the
#: form was filled in with `{unique_name}First` — every run, identically, which
#: is exactly the collision the placeholders exist to prevent.
#:
#: Longest alternative first: `unique` would otherwise match the start of
#: `unique_email` and leave `_email}}` behind as literal text.
_PLACEHOLDER = re.compile(
    r"\{\{?(unique_email|unique_phone|unique_name|unique)\}?\}"
)


def unique_expression(value: object) -> str | None:
    """A Python expression for `value`, or None if it holds no placeholder.

    The whole value is a placeholder in the ordinary case and the expression is
    returned on its own. A placeholder embedded in surrounding text becomes a
    concatenation — plainer in the generated file than a nested f-string, and
    valid Python whatever the literal parts contain.
    """
    text = str(value)
    if not _PLACEHOLDER.search(text):
        return None

    parts: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(text):
        if match.start() > position:
            parts.append(py_str(text[position : match.start()]))
        parts.append(_UNIQUE_VALUES[f"{{{{{match.group(1)}}}}}"])
        position = match.end()

    if position < len(text):
        parts.append(py_str(text[position:]))

    return parts[0] if len(parts) == 1 else " + ".join(parts)


#: What each placeholder is for, in the editor's own words. A tester writing a
#: sign-up test has no way to guess that a literal address will pass once and
#: then be red forever; offering these by name is how they find out.
PLACEHOLDER_LABEL: dict[str, str] = {
    "{{unique_email}}": "A fresh email address, different every run",
    "{{unique_phone}}": "A fresh phone number, different every run",
    "{{unique_name}}": "A fresh name, different every run",
    "{{unique}}": "A short random string, different every run",
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

    variable_of = {class_name: var for var, class_name in page_variables_for(pages)}
    locators = _locator_index(pages, variable_of)

    steps: list[StepSpec] = []
    used_pages: set[str] = set()
    needs_regex = False
    needs_uuid = False

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

        # The step's human-readable fields keep the value as written. Escaping
        # is a detail of compiling to a regex, and `\?password\=` in a test-case
        # sheet is noise to whoever reads it.
        readable = value

        action = str(raw.action).strip().lower()
        if action in _URL_ASSERTIONS:
            needs_regex = True
            # The value is a fragment of a URL, not a pattern someone wrote.
            # Unescaped it is at best loose and at worst fatal:
            #
            #   re.compile('?password=')  ->  re.error: nothing to repeat
            #
            # which is a generated test that errors before it asserts anything.
            # The quiet version is worse, because it looks fine: the dots in
            # `re.compile('app.example.com')` match any character at all.
            value = re.escape(str(value))

        # A unique value renders as the expression that produces one, so it is
        # evaluated per run rather than baked in as a literal.
        unique = unique_expression(value) if value is not None else None
        if unique is not None:
            needs_uuid = True

        line = verb.render.format(
            target=target_expr or "",
            value=unique
            if unique is not None
            else (py_str(str(value)) if value is not None else ""),
        )

        steps.append(
            StepSpec(
                sequence=len(steps),
                action=verb.action,
                verb=action,
                code=[line],
                description=_clean(getattr(raw, "description", "") or str(raw.action)),
                page_var=page_var,
                locator_name=locator_name,
                input_data=str(readable) if readable is not None and verb.action
                is not ActionType.ASSERT else None,
                expected_result=str(readable)
                if verb.action is ActionType.ASSERT and readable is not None
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
        needs_uuid=needs_uuid,
    )
    return ir


def page_variables_for(pages: list[PageSpec]) -> list[tuple[str, str]]:
    """(variable, ClassName) for a bare page list, mirroring page_variables()."""
    return page_variables(TestIR(suite_name="", function_name="", module_name="", start_url="", pages=pages))


def _locator_index(
    pages: list[PageSpec], variables: dict[str, str] | None = None
) -> dict[str, tuple[str, str]]:
    """Every addressable locator, keyed the way the model is told to write it.

    Matching is case-insensitive and ignores spaces, because "LoginPage.email"
    and "loginpage.email_input" are the same intent expressed sloppily, and
    rejecting the second helps nobody.

    `variables` adds the form a *step* is stored in — `login_page.email_input`,
    the variable rather than the class. Without it a saved step cannot be read
    back in and re-saved, because the name it was written down under is not one
    this index answers to.
    """
    index: dict[str, tuple[str, str]] = {}
    for page in pages:
        variable = (variables or {}).get(page.class_name)
        for locator in page.locators:
            keys = [
                f"{page.class_name}.{locator.name}",
                f"{page.class_name}.{locator.name}".lower(),
                locator.name.lower(),
            ]
            if variable:
                keys.append(f"{variable}.{locator.name}".lower())
            for key in keys:
                index.setdefault(key.replace(" ", ""), (page.class_name, locator.name))
    return index


def elements(pages: list[PageSpec]) -> list[dict[str, object]]:
    """Every element a step is allowed to point at, for the editor's dropdown.

    Returned in the `page_var.locator_name` form steps are stored in, so what
    the editor sends back is what comes out of the database next time.
    """
    variable_of = {class_name: var for var, class_name in page_variables_for(pages)}
    out: list[dict[str, object]] = []

    for page in pages:
        variable = variable_of.get(page.class_name)
        if variable is None:
            continue
        for locator in page.locators:
            out.append(
                {
                    "target": f"{variable}.{locator.name}",
                    "label": locator.name.replace("_", " "),
                    "page": page.class_name,
                    "page_url": page.url,
                    "strategy": locator.strategy,
                    # Both are worth a warning next to the choice rather than a
                    # surprise in a failure report three days later.
                    "fragile": locator.fragile,
                    "ambiguous": locator.ambiguous,
                }
            )
    return out


def vocabulary(pages: list[PageSpec]) -> dict[str, object]:
    """Everything a person needs to author a step, and nothing else.

    The editor cannot offer a free-text action or a free-text element, because
    this is the whole list of both. Anything outside it is not expressible, and
    that limit is the feature — it is what makes a hand-written case as safe as
    a generated one.
    """
    return {
        "verbs": [
            {
                "name": name,
                "label": VERB_LABEL.get(name, name),
                "needs_target": verb.needs_target,
                "needs_value": verb.needs_value,
                "allows_empty": verb.allows_empty,
                "is_assertion": name in _ASSERTIONS,
            }
            for name, verb in VERBS.items()
        ],
        "elements": elements(pages),
        "placeholders": [
            {"token": token, "label": PLACEHOLDER_LABEL.get(token, token)}
            for token in _UNIQUE_VALUES
        ],
        "max_steps": MAX_STEPS,
    }


def _assert_meaningful(steps: list[object]) -> None:
    """Refuse a case that never checks anything, or never does anything.

    A test with no assertion passes whether or not the feature works, which is
    worse than no test: it reports green and hides the bug.

    A test with nothing *but* assertions is the mirror image. It never opens a
    page, so it runs against a blank one and reports on nothing — the comment
    on `_ASSERTIONS` always said as much, but only the first half was enforced.
    """
    actions = {str(getattr(s, "action", "")).strip().lower() for s in steps}

    if not (actions & _ASSERTIONS):
        raise SynthesisError("no assertion; the test would pass even when broken")

    if not (actions - _ASSERTIONS):
        raise SynthesisError("only assertions; the test never opens or does anything")


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
