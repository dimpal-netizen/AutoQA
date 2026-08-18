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
from urllib.parse import urlparse

from app.codegen.converter import (
    LocatorSpec,
    PageSpec,
    StepSpec,
    TestIR,
    page_variables,
    uses_unhealed,
)
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
    # Not `.check()`. Almost every site hides the real <input> and draws a
    # styled box over it, so Playwright refuses to act on it and spends thirty
    # seconds doing so. `set_checked` reads the state off the input and clicks
    # its label instead - see the healing template. Recorded steps went through
    # it first; an invented step ticks the same checkbox and needs it just as
    # much.
    "check": Verb(ActionType.CHECK, True, False, "set_checked({target}, True)"),
    "uncheck": Verb(ActionType.UNCHECK, True, False, "set_checked({target}, False)"),
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
    # Ten digits, because that is what a mobile number is in most of the world
    # and certainly in India, where this was rejected outright:
    #
    #     Enter a valid India phone number.
    #
    # The old expression produced nine - a leading 7 and eight more - so every
    # registration test failed on its own data before it reached anything worth
    # testing. Leading 7 keeps it in the 6-9 range real mobile numbers start at.
    "{{unique_phone}}": "f'7{uuid4().int % 1_000_000_000:09d}'",
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
    recorded_steps: list[StepSpec] | None = None,
    unique_values: list[tuple[str, str, str]] | None = None,
) -> TestIR:
    """Turn one described case into a TestIR reusing `pages`.

    Raises SynthesisError when the case cannot be expressed safely. The caller
    drops that case and keeps the rest — one bad suggestion out of fifteen is
    normal and should not cost the other fourteen.

    `recorded_steps` is the happy path: the one sequence known to work against
    this application. It is used to put back setup the case dropped — see
    `_restore_setup`.

    `unique_values` is what the converter already decided cannot be replayed as
    recorded — see `_fresh_value`. A described case is shown the recorded steps
    and copies the literals out of them, so a value the recording was careful to
    freshen comes straight back:

        national_id_number_passport_number_input.fill('KRA/980/61')

    Eleven generated cases and the recorded one all submitted that, in one run,
    against a form that checks it for duplicates. Whichever ran first registered
    it and the rest were refused — so a case passed or failed on its position in
    the alphabet, and the verdicts moved every run. Doing this here rather than
    asking the model for a placeholder is the difference between a rule and a
    request.
    """
    steps_in = list(getattr(case, "steps", []) or [])
    if not steps_in:
        raise SynthesisError("no steps")
    if len(steps_in) > MAX_STEPS:
        raise SynthesisError(f"{len(steps_in)} steps is beyond the {MAX_STEPS} limit")

    steps_in = _drop_unverifiable(
        steps_in, start_url, pages=pages, name=getattr(case, "name", "?")
    )
    steps_in = _drop_leaving_claims(steps_in, pages, name=getattr(case, "name", "?"))
    _assert_arrived_before_driving(steps_in, pages, name=getattr(case, "name", "?"))

    variable_of = {class_name: var for var, class_name in page_variables_for(pages)}
    locators = _locator_index(pages, variable_of)
    specs = _locator_specs(pages)

    steps: list[StepSpec] = []
    used_pages: set[str] = set()
    needs_regex = False
    needs_uuid = False
    freshened = _freshened(unique_values)

    for index, raw in enumerate(steps_in):
        action = str(getattr(raw, "action", "")).strip().lower()
        verb = VERBS.get(action)
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
        spec: LocatorSpec | None = None

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
            spec = specs.get((class_name, locator_name))

            if action in _ASSERTIONS:
                # An assertion asks about *this* element. Healing would let a
                # recorded spare answer about whichever element sits where this
                # one used to, which turns "the modal is gone" into a failure
                # and "the button has vanished" into a pass. See `unhealed` in
                # pages/_healing.py for the two runs that showed it.
                target_expr = f"unhealed({page_var}, {py_str(locator_name)})"
            else:
                target_expr = f"{page_var}.{locator_name}"

        # The step's human-readable fields keep the value as written. Escaping
        # is a detail of compiling to a regex, and `\?password\=` in a test-case
        # sheet is noise to whoever reads it.
        readable = value

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

        # ...and so does a literal the converter already freshened for the
        # recorded test. The model copied it out of the steps it was shown; it
        # is the same value, in the same field, on the same form, and it stops
        # working for the same reason.
        if unique is None and value is not None:
            unique = freshened.get(str(value))
            if unique is not None:
                # And the comment above the line has to stop naming the value
                # too. `readable` is what the step description and the
                # test-case sheet print, so leaving it alone produced
                #
                #     # Type into national id number: 'KRA/980/61'
                #     ...fill('KRA/' + f'{uuid4().int % 1000:03d}' + ...)
                #
                # a comment describing something the code deliberately does
                # not do. Placeholders have always been described by what they
                # produce rather than by their token; this is the same rule.
                readable = "a fresh value, different every run"

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
                description=_clean(
                    getattr(raw, "description", "")
                    or describe_step(action, locator_name, readable)
                ),
                page_var=page_var,
                locator_name=locator_name,
                # Carried over from the page object rather than left at the
                # default. Without it a generated module claimed no step was
                # fragile while driving two XPath locators, so the one warning
                # that would have told a reader to add a data-testid never
                # appeared on the tests that needed it most.
                strategy=spec.strategy if spec else None,
                fragile=bool(spec and spec.fragile),
                input_data=str(readable) if readable is not None and verb.action
                is not ActionType.ASSERT else None,
                expected_result=str(readable)
                if verb.action is ActionType.ASSERT and readable is not None
                else None,
            )
        )

    _assert_meaningful(steps_in)

    steps = _restore_setup(
        steps,
        recorded_steps or [],
        used_pages,
        {var: class_name for class_name, var in variable_of.items()},
        name=getattr(case, "name", "?"),
    )

    # After `_restore_setup`, deliberately. Signing in adds two `fill` steps of
    # its own, and that rule works by looking at the gaps between the fields a
    # case fills - shown the sign-in it decides the case skipped the whole
    # journey from the login form and restores a click the case does not want.
    steps = _restore_sign_in(
        steps,
        recorded_steps or [],
        pages,
        used_pages,
        {var: class_name for class_name, var in variable_of.items()},
        name=getattr(case, "name", "?"),
    )

    # What the finished steps actually call, read off the lines themselves.
    #
    # Every other flag on the IR is set where the line is written, which works
    # right up until a line arrives from somewhere else. Restoring a recorded
    # sign-in copies the recording's own `wait_for_url(re.compile(...))` in;
    # restoring setup copies its uploads, which call `sample_file`. Neither
    # goes through the code that would have raised the flag, so the module used
    # a name it never imported and every case in the suite died on
    #
    #     NameError: name 're' is not defined
    #
    # once the browser was already open. These lines were not written here -
    # they were copied out of the recorded test verbatim - so reading them is
    # the only honest way to know what they need.
    emitted = chr(10).join(line for step in steps for line in step.code)

    ir = TestIR(
        suite_name=_clean(getattr(case, "name", "Generated test")),
        function_name=function_name,
        module_name=module_name,
        start_url=start_url,
        # Only the pages this case actually touches, so its module does not
        # import page objects it never uses.
        pages=[p for p in pages if p.class_name in used_pages],
        steps=steps,
        needs_regex=needs_regex or "re.compile(" in emitted,
        needs_set_checked="set_checked(" in emitted,
        needs_reveal="reveal(" in emitted,
        needs_sample_file="sample_file(" in emitted,
        needs_uuid=needs_uuid or "uuid4(" in emitted,
        needs_unhealed=uses_unhealed(steps),
    )
    ir.fragile_count = sum(1 for step in steps if step.fragile)
    return ir


def _freshened(
    unique_values: list[tuple[str, str, str]] | None,
) -> dict[str, str]:
    """Recorded literal -> the expression that produces a fresh one per run.

    Keyed on the value rather than on the field, because that is what a
    described case carries. The model is shown "typed: 'KRA/980/61'" and writes
    that string back; which element it puts it in is its own business, and a
    value that must be unique on one field is not suddenly replayable on
    another.
    """
    return {
        recorded: expression
        for _name, expression, recorded in (unique_values or [])
        if recorded
    }


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


def _locator_specs(pages: list[PageSpec]) -> dict[tuple[str, str], LocatorSpec]:
    """The full spec behind each locator, keyed the way `_locator_index` answers.

    `_locator_index` returns only the names, which is all a lookup needs. A step
    also has to carry how durable its element is, and that lives here.
    """
    return {
        (page.class_name, locator.name): locator
        for page in pages
        for locator in page.locators
    }


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

    # A case whose entire evidence is a URL is weak — "did not reach
    # /properties" is true of every page but one — and it is asked for in the
    # prompt instead of refused here. Weak is not the same as provably wrong,
    # and a suite that silently shrinks whenever the model phrases a check
    # loosely is worse than one carrying a check that could be sharper.


def _bare(url: str) -> str:
    """A URL reduced to the part that says which page it is.

    Query strings and fragments are dropped because a page object's url is
    already stored without them, and a trailing slash is not a different page.
    Relative and absolute forms both reduce to the same path, so a case written
    as `/products` matches a page recorded at `https://shop.test/products`.
    """
    parsed = urlparse((url or "").strip())
    return (parsed.path or "/").rstrip("/").lower() or "/"


def _drop_unverifiable(
    steps: list[object],
    start_url: str,
    *,
    pages: list[PageSpec] | None = None,
    name: str = "?",
) -> list[object]:
    """Remove the steps whose verdict could not mean anything, keep the case.

    A step that can only ever report one answer is not a check. It is noise that
    reports as a failure, and it is worse than having no step there at all —
    because a red test on correct behaviour costs a tester an afternoon, and
    teaches them to dismiss the next red test faster.

    Dropping the step rather than the case is deliberate. The rest of the case
    is usually fine, and a suite that quietly shrinks every time the model
    phrases one assertion badly is a suite nobody can reason about. What is left
    still has to pass `_assert_meaningful`, so a case that was *only* the bad
    step still goes — but by the existing rule, not a new one.

    Two kinds go:

    **An assertion about the address the browser is still on.** From a real
    suite, red on every run:

        0. goto            .../agent-details/invalid!id@format
        1. expect_not_url  .../agent-details/invalid!id@format

        Page URL expected not to be '.../agent-details/invalid!id@format'
        Actual value:               '.../agent-details/invalid!id@format'
        - main:
          - paragraph: Agent not found.

    `goto` puts the browser at that address, so the claim is a contradiction and
    the application was right all along — it renders "Agent not found." where
    you asked, which is a normal thing for a site to do. Only the address the
    browser is *still* on is dropped: opening a page, clicking away and coming
    back is a real journey worth asserting, so this looks at the last step that
    could have moved the browser rather than at every `goto` in the case.

    **A `goto` that leaves the application.** A made-up subdomain does not
    resolve, so the browser raises before any assertion runs and the test errors
    instead of reporting anything. A missing host is a DNS question and a
    browser is the wrong instrument for it.

    **An assertion about an element, on a page the recording never visited.**
    From a real suite, red, and reported against a working site:

        goto            /category_products/999
        expect_visible  home.add_to_cart_link

    The recording never opened that address, so nothing is known about what is
    on it - and "Add to cart" was recorded on the Home page, which this is not.
    The claim is a guess about how the site handles a bad URL, and a guess has
    no business being a verdict. The failure it produced said "the application
    displayed the generic Products page", which is a normal thing for a site to
    do with an unknown category.

    Every element assertion after such a `goto` goes. What that leaves is
    usually nothing, so the case is dropped by the existing "checks nothing"
    rule - which is right: a bad-URL case cannot be written from a recording
    that never went there. The URL assertions stay, because the address is
    knowable without having seen the page.

    Note what is deliberately *not* dropped: "it is still visible" about the
    element just clicked. It looks tautological — Playwright only clicks what is
    visible — but it is one of the sharper checks there is:

        1. click           RegisterBuyerPage.create_account_button
        2. expect_visible  RegisterBuyerPage.create_account_button

    A submit that worked navigates away and takes the button with it. Step 2 is
    asking whether the form rejected the address, and it has two real answers.
    """
    host = urlparse(start_url).hostname if start_url else None
    # The start URL counts even when no page object was built from it: the
    # recording opened it, so it is somewhere we have seen.
    known = {_bare(page.url) for page in (pages or [])}
    if known and start_url:
        known.add(_bare(start_url))
    kept: list[object] = []
    moved_by: object | None = None
    # True once the case has navigated somewhere the recording never saw, so
    # nothing is known about what is on screen. Cleared by going back to a page
    # that was recorded.
    off_the_map = False

    for step in steps:
        action = str(getattr(step, "action", "")).strip().lower()
        value = str(getattr(step, "value", "") or "").strip()

        if action == "goto":
            off_the_map = bool(known) and _bare(value) not in known

        # Only the assertions that come straight off that landing are a guess.
        # Once the case does something - clicks, fills - the browser may be
        # anywhere, and a step that could not be performed fails on its own
        # terms rather than being second-guessed here.
        if action and action not in _ASSERTIONS and action != "goto":
            off_the_map = False

        if off_the_map and action in _ASSERTIONS - _URL_ASSERTIONS:
            logger.info(
                "%s: dropped '%s %s' - the recording never opened that address, "
                "so nothing is known about what is on it",
                name, action, str(getattr(step, "target", "") or "")[:80],
            )
            continue

        if action == "goto" and host and value.lower().startswith(("http://", "https://")):
            target = urlparse(value).hostname
            if target and target.lower() != host.lower():
                logger.info(
                    "%s: dropped a step opening %s - not the application under test (%s)",
                    name, target, host,
                )
                continue

        if action in _URL_ASSERTIONS and value and moved_by is not None:
            was = str(getattr(moved_by, "value", "") or "").strip()
            if (
                str(getattr(moved_by, "action", "")).strip().lower() == "goto"
                and was
                and (value in was or was in value)
            ):
                logger.info(
                    "%s: dropped '%s %s' - the browser is still on that address, "
                    "so the answer is fixed before the test runs",
                    name, action, value[:80],
                )
                continue

        kept.append(step)
        if not (action in _ASSERTIONS and action != "goto"):
            moved_by = step  # an observation cannot move the browser

    return kept


#: Verbs that operate the page rather than look at it. Only these are checked
#: for arrival: they need the element to be in front of them right now, and they
#: are the ones that spend thirty seconds finding out it is not.
_DRIVING = {"click", "fill", "check", "uncheck", "select", "press"}

#: Verbs that can leave the page. Everything else - typing, ticking, choosing -
#: leaves the browser exactly where it was, which is what makes "where are we"
#: answerable at all.
_MAY_NAVIGATE = {"click", "press", "goto"}


def _assert_arrived_before_driving(
    steps: list[object], pages: list[PageSpec], *, name: str = "?"
) -> None:
    """Refuse a case that reaches for an element one page too early.

    From a real suite, red for a minute and two seconds:

        0. goto   /login
        1. fill   login.name_input
        2. fill   login.email_address_input
        3. check  signup.mr_radio          <- a /signup element
        4. click  login.signup_button      <- the step that goes to /signup

        Locator.check: Timeout 30000ms exceeded

    The radio button is real and the tester checked it by hand, which is exactly
    why this was worth catching: the failure said nothing was there, and
    something was - just not yet. Steps 3 and 4 are the wrong way round.

    Knowing this offline rests on one fact: `fill`, `check`, `uncheck` and
    `select` cannot navigate. So after a `goto` we know which page the browser
    is on, and we keep knowing until the case clicks or presses something. From
    that point it could be anywhere and nothing here second-guesses it - which
    is why steps 5 onward above are left alone.

    Only driving is checked. An assertion about site chrome recorded on another
    page is a normal thing to write, and refusing it would cost more than it
    saves.
    """
    by_url = {_bare(page.url): page for page in pages}
    by_class = {page.class_name: page for page in pages}

    standing_on: PageSpec | None = None
    for index, step in enumerate(steps):
        action = str(getattr(step, "action", "")).strip().lower()

        if action == "goto":
            standing_on = by_url.get(_bare(str(getattr(step, "value", "") or "")))
            continue

        target = str(getattr(step, "target", "") or "")
        page = by_class.get(target.split(".", 1)[0]) if "." in target else None

        if (
            action in _DRIVING
            and standing_on is not None
            and page is not None
            and page is not standing_on
        ):
            raise SynthesisError(
                f"step {index}: {target} is on {page.url}, but the case is still "
                f"on {standing_on.url} - nothing before it goes there, and "
                f"typing or ticking cannot"
            )

        if action in _MAY_NAVIGATE:
            standing_on = None  # could be anywhere now; stop claiming to know


def _drop_leaving_claims(
    steps: list[object], pages: list[PageSpec], *, name: str = "?"
) -> list[object]:
    """Remove "we must have left this page" when the page is the one in use.

    Five negative registration tests failed on the same line:

        11. click           'Create Account'
        12. expect_not_url  /register/buyer      <- always false
        13. expect_hidden   the OTP modal        <- the real check

    The form rejects an empty email and stays put, which is what a form should
    do. The test called staying a failure. The application was right five times
    over and the run was red five times over.

    `_drop_unverifiable` cannot see this one: the browser reached that page by
    clicking, not by `goto`, so there is no matching navigation to compare
    against. What gives it away instead is the elements — every step before the
    assertion drives `register_buyer.*`, and that page object's own URL is
    `/register/buyer`. A test cannot be filling in a page it has left.

    For a negative case the URL worth naming is the one a *success* would
    reach. That claim has content; this one had none, and step 13 was carrying
    the case on its own the whole time.
    """
    urls = {page.class_name: (page.url or "") for page in pages}
    index = _locator_index(pages)
    kept: list[object] = []
    on_page: str | None = None  # the page whose elements are being driven

    for step in steps:
        action = str(getattr(step, "action", "")).strip().lower()
        value = str(getattr(step, "value", "") or "").strip()

        if action == "expect_not_url" and value and on_page:
            here = urls.get(on_page, "")
            if here and (value in here or here in value):
                logger.info(
                    "%s: dropped 'expect_not_url %s' - the test is driving %s, "
                    "which is that page",
                    name, value[:60], on_page,
                )
                continue

        target = str(getattr(step, "target", "") or "").strip()
        if target:
            found = index.get(target) or index.get(target.lower().replace(" ", ""))
            if found:
                on_page = found[0]

        kept.append(step)

    return kept


def _setup_within(gap: list[StepSpec]) -> list[StepSpec]:
    """Of the recorded steps a case skipped, the ones that were operating a control.

    Clicks, ticks and dropdown choices always count: a case never means to skip
    one, and skipping one leaves the form in a state the recording never tested.

    A `fill` counts only when it sits *between* two of them. That is the shape of
    a control being operated rather than a field being filled in — the country
    dropdown in the recording is `click, type "ind", click India`, and restoring
    the two clicks without the search leaves a list the choice is not visible in.

    A `fill` at the edge of the gap is a field the case did not fill, and it is
    left alone. "Submit with no email address" is a test worth having, and
    helpfully typing the email back in would destroy it — turning a negative case
    into a positive one that contradicts its own name.
    """
    controls = [
        index
        for index, step in enumerate(gap)
        if step.action not in (ActionType.INPUT, ActionType.ASSERT)
    ]
    if not controls:
        return []  # nothing here was a control; the case skipped fields, on purpose

    first, last = controls[0], controls[-1]
    return [
        step
        for index, step in enumerate(gap)
        if step.action is not ActionType.ASSERT
        and (step.action is not ActionType.INPUT or first < index < last)
    ]


def sign_in_sequence(recorded: list[StepSpec]) -> tuple[list[StepSpec], set[str], str | None]:
    """The recorded sign-in, and the pages it unlocked.

    A password field is the one unambiguous marker in a recording. Whatever the
    site calls its login, whatever the button says, typing into
    `input[type="password"]` means an account is being used - and every page the
    recording went on to see, it saw as somebody signed in.

    From one recording of a property site:

        password typed at step 5:  login.password_input

        step   1  home                         open
        step   2  login                        open
        step   7  property_owner_dashboard     BEHIND LOGIN
        step   9  property_owner_add_property  BEHIND LOGIN
        step  78  property_owner_my_listings   BEHIND LOGIN

    Returns the steps that did the signing in, the page variables that need it,
    and the variable of the page it was done on. Empty when the recording never
    signed in, which is most recordings.
    """
    at = next((i for i, step in enumerate(recorded) if step.is_password), None)
    if at is None:
        return [], set(), None

    page = recorded[at].page_var
    submitted = next(
        (
            i
            for i in range(at + 1, len(recorded))
            if recorded[i].page_var == page
            and recorded[i].action in (ActionType.CLICK, ActionType.KEY_PRESS)
        ),
        None,
    )
    if submitted is None:
        return [], set(), None  # typed a password and never sent it; not a sign-in

    # Back to the top of the run of steps on that page: clicking the field,
    # typing the address, and anything else the form needed.
    start = at
    while start > 0 and recorded[start - 1].page_var == page:
        start -= 1

    behind = {
        step.page_var
        for step in recorded[submitted + 1 :]
        if step.page_var and step.page_var != page
    }
    return recorded[start : submitted + 1], behind, page


def _restore_sign_in(
    steps: list[StepSpec],
    recorded: list[StepSpec],
    pages: list[PageSpec],
    used_pages: set[str],
    class_of_var: dict[str, str],
    *,
    name: str = "?",
) -> list[StepSpec]:
    """Sign a case in before it opens a page that needs an account.

    A generated case is told to open the page it is about with `goto` rather
    than clicking through the site, which is right for a login form and wrong
    for everything behind one:

        goto  /property-owner/add-property
        fill  PropertyOwnerAddPropertyPage.title_input

        Locator.fill: Timeout 30000ms exceeded

    The application did exactly what it should - bounced an anonymous visitor to
    the login form - and the field the case wanted was not on it. Fifty-seven
    seconds, then red, against a site behaving correctly.

    The recording knows how to get in, so the case is given the same four steps
    it used. Refusing the case instead was the alternative, and it is worse:
    "add a property with an empty title" is a test worth having, and the only
    thing wrong with it was a missing sign-in.

    A case that signs itself in is left alone, which is what keeps a test *about*
    logging in from having a second login glued to its front. So is one that only
    looks at a protected page without driving it - "opening add-property signed
    out sends me to the login form" is a real test, and it needs to stay signed
    out to be one.
    """
    sequence, behind, login_var = sign_in_sequence(recorded)
    if not sequence or not behind:
        return steps

    # Does the case already sign itself in? Asked by looking at which elements
    # it drives, not at `is_password` - that flag is set by the converter on
    # recorded steps and is never true here, so the question always answered no
    # and every case that wrote its own login got a second one glued in front:
    #
    #     0-5  sign in        (restored)
    #     6-9  sign in again  (the case's own)
    #
    # The second one ran on a dashboard, where there is no email field, and the
    # test spent thirty seconds looking for it.
    signing_in = {
        (step.page_var, step.locator_name)
        for step in sequence
        if step.page_var and step.locator_name
    }
    if any(
        (step.page_var, step.locator_name) in signing_in
        for step in steps
        if step.action is not ActionType.ASSERT
    ):
        return steps

    needs_it = any(
        step.page_var in behind
        and step.action is not ActionType.ASSERT
        for step in steps
    )
    if not needs_it:
        return steps

    login_url = next(
        (page.url for page in pages if page.class_name == class_of_var.get(login_var or "")),
        None,
    )

    out: list[StepSpec] = []
    if login_url:
        out.append(
            StepSpec(
                sequence=0,
                action=ActionType.NAVIGATE,
                verb="goto",
                code=[f"page.goto({py_str(login_url)})"],
                description=f"Sign in first: open {login_url}",
            )
        )
    for position, step in enumerate(sequence):
        # The last one is the click that submits, and its wait stays. Stripped,
        # the case's own `goto` fires the moment the button is pressed and
        # navigates away while the sign-in request is still in the air:
        #
        #     Locator.fill: Timeout 30000ms exceeded
        #     1 network request failed: POST /users/auth/login -> net::ERR_ABORTED
        #
        # which reads as the application dropping logins, and is the test
        # cancelling its own. The waits on the steps before it are dropped:
        # clicking into a field does not navigate, so a wait there is one the
        # recording happened to attach and nothing needs.
        submits = position == len(sequence) - 1
        out.append(
            StepSpec(
                sequence=len(out),
                action=step.action,
                verb=VERB_FOR_ACTION.get(step.action),
                code=[
                    line for line in step.code
                    if submits or "wait_for_url" not in line
                ],
                description=f"{step.description} (signing in, from the recording)",
                page_var=step.page_var,
                locator_name=step.locator_name,
                input_data=step.input_data,
                strategy=step.strategy,
                fragile=step.fragile,
                is_password=step.is_password,
            )
        )
        class_name = class_of_var.get(step.page_var or "")
        if class_name:
            used_pages.add(class_name)

    logger.info(
        "%s: signed in first - the case opens a page the recording only saw "
        "while logged in", name,
    )
    for step in steps:
        step.sequence = len(out)
        out.append(step)
    return out


def _restore_setup(
    steps: list[StepSpec],
    recorded: list[StepSpec],
    used_pages: set[str],
    class_of_var: dict[str, str],
    *,
    name: str = "?",
) -> list[StepSpec]:
    """Put back the setup a case dropped between two fields it fills.

    From a real suite, a case that could never have passed:

        fill  first name
        fill  email
        fill  mobile number      <- 10 digits, starting 7
        ...
        expect_visible  the one-time-password popup   (i.e. it worked)

    The recording did something else between the email and the number: it opened
    the country dropdown, searched for "ind", and chose India. The form
    validates a number against the country, and the country defaults to Kenya —
    so the number was rejected every time and a test claiming registration
    succeeds went red against a form doing exactly the right thing. The three
    steps looked like navigation noise and were load-bearing.

    The recording is the only sequence known to work, so it is the evidence for
    what is load-bearing. This looks at each pair of fields the case fills that
    the recording also filled, in the recording's own order, and restores
    whatever the recording did in between.

    What is restored is decided by `_setup_within`, and what it refuses to
    restore matters as much: leaving a field blank is a legitimate negative test
    and one of the most valuable there is, so a field the case simply did not
    fill is always read as intent.

    Restoring only between two fills is what keeps this narrow. A case testing
    "registration is refused without accepting the terms" drops the tick that
    comes *after* the last field, and nothing here touches it.
    """
    if not recorded:
        return steps

    order = {}
    for position, step in enumerate(recorded):
        if step.page_var and step.locator_name:
            order.setdefault((step.page_var, step.locator_name), position)

    filled = [
        (index, order[(step.page_var, step.locator_name)])
        for index, step in enumerate(steps)
        if step.action is ActionType.INPUT
        and (step.page_var, step.locator_name) in order
    ]

    driven = {
        (step.page_var, step.locator_name)
        for step in steps
        if step.page_var and step.locator_name
    }

    inserts: dict[int, list[StepSpec]] = {}
    for (_, before), (at, after) in zip(filled, filled[1:]):
        if after <= before:
            continue  # the case fills them in a different order; not a gap
        missing = [
            step
            for step in _setup_within(recorded[before + 1 : after])
            if step.page_var
            and step.locator_name
            and (step.page_var, step.locator_name) not in driven
        ]
        if missing:
            inserts[at] = missing
            logger.info(
                "%s: restored %d recorded step(s) before %s.%s - the recording "
                "needed them and the case dropped them",
                name, len(missing), steps[at].page_var, steps[at].locator_name,
            )

    if not inserts:
        return steps

    out: list[StepSpec] = []
    for index, step in enumerate(steps):
        for restored in inserts.get(index, ()):
            out.append(
                StepSpec(
                    sequence=len(out),
                    action=restored.action,
                    verb=VERB_FOR_ACTION.get(restored.action),
                    # The recorded line already refers to the same page objects
                    # this case uses, so it is reused rather than re-derived.
                    # `wait_for_url` is dropped: it belongs to a click that
                    # navigated, and nothing being restored here does.
                    code=[
                        line for line in restored.code
                        if "wait_for_url" not in line
                    ],
                    description=f"{restored.description} (from the recording)",
                    page_var=restored.page_var,
                    locator_name=restored.locator_name,
                    input_data=restored.input_data,
                    strategy=restored.strategy,
                    fragile=restored.fragile,
                )
            )
            # Its page object has to be imported and instantiated, or the
            # restored line names a variable the module never defines.
            class_name = class_of_var.get(restored.page_var or "")
            if class_name:
                used_pages.add(class_name)
        step.sequence = len(out)
        out.append(step)

    return out


def describe_step(action: str, locator_name: str | None, value: object) -> str:
    """One step in plain English, without asking a model to write it.

    The model used to send this with every step, and it was the most expensive
    field in the schema by a wide margin - see `CaseStep`. It is also the most
    mechanical: an action from a fourteen-word vocabulary and an element with a
    name we chose ourselves. There is nothing to interpret.

        click   LoginPage.sign_in_button   ->  Click sign in button
        fill    LoginPage.email_input      ->  Type into email input: 'a@b.c'
        goto                               ->  Go to /login

    Recorded steps have always been described this way, so the two halves of a
    suite now read alike - which they never did while one half was written by a
    model and the other by `converter.py`.

    A placeholder is described by what it produces rather than by its token.
    `Type into email input: '{{unique_email}}'` in a comment above a line that
    reads `uuid4()` looks like a substitution that failed to happen.
    """
    label = VERB_LABEL.get(action, action.replace("_", " ").capitalize())
    readable = (locator_name or "").replace("_", " ").strip()
    if isinstance(value, str):
        # `_PLACEHOLDER` rather than the token strings, so this accepts exactly
        # what the substitution itself accepts - one brace or two - and matches
        # a placeholder embedded in surrounding text. `{unique_name}First` is a
        # real thing to write, and half a token left in a comment reads worse
        # than a whole one.
        value = _PLACEHOLDER.sub(
            lambda m: PLACEHOLDER_LABEL[f"{{{{{m.group(1)}}}}}"].lower(), value
        )

    if readable and value not in (None, ""):
        return f"{label} {readable}: {value!r}"
    if readable:
        return f"{label} {readable}"
    if value not in (None, ""):
        return f"{label} {value}"
    return label


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
