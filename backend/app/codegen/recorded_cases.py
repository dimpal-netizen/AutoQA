"""Test cases built from the recording alone, when there is no model to ask.

`ai/case_generator.py` is right that inventing "a 320-character email address"
from a successful login is judgement, and right to say so rather than pretend.
But a recording is not nothing. It says which pages exist, which elements were
on them, which fields somebody filled in, and which button they pressed to send
it. Three kinds of case follow from those four facts with no judgement at all,
and three kinds of case are worth more than a 422.

This is the "From what I did" button in the generate dialog, expressed as code
instead of as a prompt. That prompt is a fence around the model:

    You may: reuse those steps, in the order they were recorded; stop the flow
    early; leave a field empty that was filled; and change the value typed into
    a field to one the application should refuse.

    You may NOT: add a step that is not in the recording; use an element the
    recorded steps did not use; reorder the steps; or invent a scenario of your
    own.

Everything below stays inside it, and stays inside it by construction rather
than by being asked to.

WHAT IS DELIBERATELY NOT HERE is the recorded journey itself. `segments.py`
already cuts a recording into one test per journey at recording time, and
`generate_cases` preserves those - it deletes every case whose category is not
RECORDED. Re-emitting them here would put two copies of the same walkthrough in
one suite under two names, count them twice in `services/coverage.py`, and leave
the second copy invisible to "Run Recorded Test Cases".

Nothing here imports `app.ai`. Every module under `codegen/` imports only its
own package, the enums and the settings; `ai/` imports `codegen/` and never the
other way round. Keeping that edge pointing one way is what lets this run with
no provider configured at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import zip_longest

from app.codegen.converter import LocatorSpec, PageSpec, StepSpec, TestIR

# Two private names, both borrowed rather than reimplemented, and both from
# inside this package. `_POSITIONAL` and `_bare` are not incidental helpers -
# they are the exact definitions `synthesise` judges a case by. A local copy of
# either would work perfectly until the original changed, and then this module
# would build cases the validator refuses for reasons nothing here could explain.
from app.codegen.selectors import _POSITIONAL as _POSITIONAL_STRATEGIES
from app.codegen.synth import (
    MAX_STEPS,
    VERB_FOR_ACTION,
    _bare,
    page_variables_for,
    sign_in_sequence,
)
from app.models.enums import ActionType

#: Stored as `TestCase.generated_by`.
#:
#: Deliberately not "deterministic_v1", which is what `codegen_service.GENERATOR`
#: calls the recorded cases and would be the obvious thing to reuse. The front
#: end reads a `deterministic` prefix as "this IS the recording" - see
#: `isRecorded` in lib/types.ts - and feeds those ids to the "Run Recorded Test
#: Cases" button, which promises "the walkthrough a tester performed... nothing a
#: model invented". These cases are built FROM the recording, not BY it. Running
#: them under that button would be a lie about what was tested.
FROM_RECORDING = "recorded-actions"

#: Strategies that say where an element sits rather than what it is, as the
#: strings a LocatorSpec carries. Derived from the enum rather than written out
#: again: there were already two copies of this list and a third would be the
#: one that drifts.
_POSITIONAL = {strategy.value for strategy in _POSITIONAL_STRATEGIES}

#: An address, not merely something with an @ in it. Same expression the
#: converter uses to decide a value must be fresh per run.
_LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Locator names that mean a field holds a telephone number.
_PHONE_WORDS = ("phone", "mobile", "tel", "contact")

#: Actions that happen inside a form and contribute nothing to replaying it. A
#: scroll is where somebody's wheel was; an assert is a check they made in
#: assert mode, which belongs to the recorded case rather than to this one.
_PASSED_OVER = {ActionType.SCROLL, ActionType.ASSERT}

#: 313 characters, against RFC 5321's 254-character ceiling and its 64-character
#: local part. Long enough to be invalid by the standard the recorded value
#: satisfies, rather than by a guess about what this particular form accepts.
_TOO_LONG_EMAIL = "a" * 300 + "@example.test"

#: Thirty digits, against E.164's fifteen.
_TOO_LONG_PHONE = "9" * 30

#: Semantically empty to any correct application, and not the same test as
#: leaving the field alone: a form that checks `if value` and one that checks
#: `if value.strip()` differ here and nowhere else.
_ONLY_SPACES = "   "

#: The key from a recorded `press`. `converter._build_step` renders it straight
#: into the line and never into `input_data`, so the line is the only place it
#: survives.
_PRESSED_KEY = re.compile(r"\.press\((['\"])(.*?)\1\)")


# ---------------------------------------------------------------------------
# What may be built on
# ---------------------------------------------------------------------------
def usable_locators(page: PageSpec) -> list[LocatorSpec]:
    """The elements anything new may be built on, in page order.

    Four conditions, and each one exists because a case that ignored it went red
    against an application that was working:

    * **not positional.** An element whose best selector is a CSS path or an
      XPath had no name, no role, no label and no test id. A case built on
      `home.body_section_5_div_1` clicks whatever now sits at that path.
    * **visible.** A control with no width or height cannot be acted on;
      Playwright waits thirty seconds and then fails.
    * **not revealed.** A modal's close button, an item inside a menu that has
      to be opened first. The recorded test reaches these the way the person
      did; a case that opens the page and goes straight there finds nothing.
    * **reachable.** Measured cold by `probe.py`: a Checkout button on an empty
      cart, a field on the second step of a wizard. `True` when no probe ran, so
      a suite generated without one behaves exactly as it did.

    This is the single definition. `ai.case_generator.describe_pages` calls it
    too, so the elements offered to the model and the elements built on without
    one cannot drift apart - and the day they drift is the day the no-AI path
    starts writing the cases the AI path is careful to refuse.
    """
    return [
        locator
        for locator in page.locators
        if locator.strategy not in _POSITIONAL
        and locator.visible
        and not locator.revealed
        and locator.reachable
    ]


# ---------------------------------------------------------------------------
# What a case looks like on the way to `synthesise`
# ---------------------------------------------------------------------------
@dataclass
class DraftStep:
    """One step, in the shape `synthesise` reads off a case.

    Not `ai.schemas.CaseStep`. That model's field descriptions are the prompt
    the model is held to, and nothing here talks to one. `synthesise` is
    duck-typed - it reaches for `.action`, `.target`, `.value` and `.description`
    with `getattr` and never asks what it is holding - which is the same
    property `codegen_service._Authored` already relies on for hand-written
    cases.

    `description` is left None on purpose. `synth.describe_step` writes a better
    one from the verb and the element name than anything phrased here could be,
    and it is the same sentence the recorded cases carry.
    """

    action: str
    target: str | None = None
    value: str | None = None
    description: str | None = None


@dataclass
class Draft:
    """One case, before validation.

    `category` and `priority` are plain strings rather than the enums they name.
    `case_generator._category` does `CaseCategory(str(value).strip().lower())`,
    and from Python 3.11 `str()` on a str-mixin Enum member gives
    "CaseCategory.NEGATIVE" - so handing it the enum makes every case quietly
    come back POSITIVE. `import_service.read_without_ai` passes strings for the
    same reason.
    """

    name: str
    category: str
    priority: str
    description: str
    steps: list[DraftStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The recording, grouped into forms
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Form:
    """A run of recorded steps on one page that filled something in and sent it.

    The same shape `sign_in_sequence` looks for, generalised past the password
    field: find the fills, find the first click or key press after the last of
    them on the same page, and the form is everything up to and including it.
    That function is left alone - it answers a different question (where did
    this recording sign in) and `_restore_sign_in` is built on its exact answer.
    """

    page: PageSpec
    page_var: str
    body: list[StepSpec]      # every replayable step up to and including submit
    fills: list[StepSpec]     # the INPUT steps among them, recorded order
    submit: StepSpec


def _runs(ir: TestIR) -> list[list[StepSpec]]:
    """The steps, cut where the browser moved to a different page.

    Steps with no `page_var` - the navigations, a global Escape, a scroll - are
    skipped rather than treated as a boundary. A `goto` sits between every pair
    of pages by definition, so counting it as a break would cut every run in
    two and leave no form anywhere.
    """
    runs: list[list[StepSpec]] = []
    current: list[StepSpec] = []
    current_var: str | None = None

    for step in ir.steps:
        if step.page_var is None:
            continue
        if step.page_var != current_var:
            if current:
                runs.append(current)
            current, current_var = [], step.page_var
        current.append(step)

    if current:
        runs.append(current)
    return runs


def _forms(ir: TestIR) -> list[_Form]:
    """Every form in the recording that can be replayed, first one per page.

    Deduplicated by page, first run wins. A login recording that failed once and
    tried again holds two runs on `/login`, and both would produce byte-identical
    cases under two different names - twelve rows in the table where six were
    meant, half of them duplicates nobody can tell apart.
    """
    pages_by_var = {var: page.class_name for var, page in _pages(ir)}
    by_class = {page.class_name: page for page in ir.pages}
    ambiguous = _pages_sharing_a_url(ir)

    forms: list[_Form] = []
    claimed: set[str] = set()

    for run in _runs(ir):
        page_var = run[0].page_var or ""
        if page_var in claimed:
            continue

        class_name = pages_by_var.get(page_var)
        page = by_class.get(class_name or "")
        if page is None or not page.url or class_name in ambiguous:
            continue

        form = _form_within(run, page, page_var)
        if form is None:
            continue

        forms.append(form)
        claimed.add(page_var)

    return forms


def _form_within(run: list[StepSpec], page: PageSpec, page_var: str) -> _Form | None:
    """One run as a form, or None when it is not one or cannot be replayed."""
    fills = [index for index, step in enumerate(run) if step.action is ActionType.INPUT]
    if not fills:
        return None

    submitted = next(
        (
            index
            for index in range(fills[-1] + 1, len(run))
            if run[index].action in (ActionType.CLICK, ActionType.KEY_PRESS)
        ),
        None,
    )
    if submitted is None:
        return None  # typed into a form and never sent it

    body = _last_attempt(
        [step for step in run[: submitted + 1] if step.action not in _PASSED_OVER]
    )

    for step in body:
        # An upload, a drag, a hover, a double-click. None of the four can be
        # said in the fourteen-word vocabulary, so a replay without them submits
        # a form the recording never submitted - and the application refuses it
        # for a reason the case does not name, which reads as a bug in the
        # feature under test.
        if step.action not in VERB_FOR_ACTION:
            return None
        if step.locator_name is None:
            return None
        # `converter` joins a multi-select with ", " into one string, so
        # replaying it as `select_option('House, Flat')` chooses an option
        # nobody ever chose and the step fails on its own data.
        if step.action is ActionType.SELECT and "," in (step.input_data or ""):
            return None

    # goto + the body + one assertion. A form with more fields than this is
    # beyond what `synthesise` will accept anyway.
    if len(body) + 2 > MAX_STEPS:
        return None

    return _Form(
        page=page,
        page_var=page_var,
        body=body,
        fills=[step for step in body if step.action is ActionType.INPUT],
        submit=run[submitted],
    )


def _last_attempt(body: list[StepSpec]) -> list[StepSpec]:
    """The final go at a form, when somebody had more than one.

    A wrong password, an error, and another try is one run of steps on one page,
    and taken whole it holds the same field twice:

        fill email · fill password · click Sign in · fill email · fill password
        · click Sign in

    Replayed, that submits the form twice and gives every field two cases with
    identical names. `_forms` deduplicates across separate runs and cannot see
    this one, because it never left the page.

    The tell is `segments.split`'s own, and it is used here for the same reason:
    **a field filled twice**. Nobody fills the same box twice inside one attempt,
    so the second time a field is filled is where the previous attempt ended.

    Deliberately not "cut at the last click before the submit", which looks
    equivalent and is not. A country dropdown is `click · type · click` in the
    middle of a form, and cutting there would throw away every field before it
    and leave a case that submits a mostly-empty form.
    """
    cut = 0
    seen: set[str] = set()
    for index, step in enumerate(body):
        if step.action is not ActionType.INPUT:
            continue
        name = step.locator_name or ""
        if name in seen:
            cut, seen = index, set()
        seen.add(name)
    return body[cut:]


def _pages(ir: TestIR) -> list[tuple[str, PageSpec]]:
    """(variable, page) pairs, the way a step names them."""
    by_class = {page.class_name: page for page in ir.pages}
    return [
        (var, by_class[class_name])
        for var, class_name in page_variables_for(ir.pages)
        if class_name in by_class
    ]


def _pages_sharing_a_url(ir: TestIR) -> set[str]:
    """Pages whose address does not identify them uniquely.

    `_assert_arrived_before_driving` works out where a case is standing by
    looking its `goto` up in `{_bare(page.url): page}`. When two page objects
    reduce to the same address the later one wins, so a case that opens the
    first and then drives it is told it is standing somewhere else - and
    refused, with a message about a page nobody mentioned. Not worth writing a
    case against.
    """
    seen: dict[str, list[str]] = {}
    for page in ir.pages:
        seen.setdefault(_bare(page.url), []).append(page.class_name)
    return {name for names in seen.values() if len(names) > 1 for name in names}


# ---------------------------------------------------------------------------
# Replaying a form
# ---------------------------------------------------------------------------
def _unique_tokens(ir: TestIR) -> dict[str, str]:
    """Recorded value -> the placeholder that regenerates it on every run.

    The converter has already worked out which typed values the application
    would refuse a second time, and worked it out from the field's own
    attributes - see `_fresh_expression`. Replaying the recorded address instead
    means run two is told "that email is already registered", the form stays
    put, and a case claiming "the form was refused because the phone number was
    empty" goes green having tested nothing whatsoever. A case that is green for
    the wrong reason is worse than one that is red for the wrong reason: nobody
    ever looks at it again.
    """
    tokens: dict[str, str] = {}
    for _name, expression, recorded in ir.unique_values:
        tokens[recorded] = (
            "{{unique_email}}"
            if "@" in expression
            else "{{unique_phone}}"
            if "uuid4().int" in expression
            else "{{unique}}"
        )
    return tokens


def _key_of(step: StepSpec) -> str:
    """The key a recorded press sent."""
    for line in step.code:
        found = _PRESSED_KEY.search(line)
        if found:
            return found.group(2)
    return "Enter"


def _replay(
    form: _Form,
    tokens: dict[str, str],
    *,
    swap: tuple[StepSpec, str] | None = None,
) -> list[DraftStep]:
    """The recorded form, step for step, with at most one value changed.

    The *whole* run is replayed, not only the fills. `_restore_setup` puts back
    what a case dropped between two fields it fills, and only that - so a terms
    checkbox after the last field never comes back. Left out, the form is
    refused for two reasons at once and the case passes on the strength of the
    one it did not mean to test.
    """
    steps = [DraftStep(action="goto", value=form.page.url)]

    for step in form.body:
        verb = VERB_FOR_ACTION[step.action]
        target = f"{step.page_var}.{step.locator_name}"
        value: str | None = None

        if verb == "fill":
            recorded = step.input_data or ""
            value = tokens.get(recorded, recorded)
            if swap is not None and step is swap[0]:
                value = swap[1]
        elif verb == "select":
            value = step.input_data
        elif verb == "press":
            value = _key_of(step)

        steps.append(DraftStep(action=verb, target=target, value=value))

    # A submit that worked navigates away and takes the button with it, so this
    # is not the tautology it looks like. It is the difference between the form
    # having refused the value and having accepted it, and it has two real
    # answers - the same reasoning `synth._drop_unverifiable` already relies on
    # to keep exactly this assertion.
    steps.append(
        DraftStep(
            action="expect_visible",
            target=f"{form.submit.page_var}.{form.submit.locator_name}",
        )
    )
    return steps


# ---------------------------------------------------------------------------
# The shapes
# ---------------------------------------------------------------------------
def _page_checks(ir: TestIR) -> list[Draft]:
    """One case per page: everything the recording found there is still there.

    This asserts nothing about behaviour, only that a page somebody opened still
    renders the elements they used on it. Both answers are real - an element
    that stops rendering is a regression, and one that renders is a pass - which
    is more than can be said for most checks written without a model.

    Its honest limit is `reachable`. When `PROBE_PAGES` is off, or the probe
    could not run, every locator claims to be reachable and the only evidence
    left is the recording - which saw one state of the page, on one day, with
    one account.
    """
    sequence, behind, login_var = sign_in_sequence(ir.steps)
    ambiguous = _pages_sharing_a_url(ir)
    sign_in = _sign_in_steps(ir, sequence, login_var)

    drafts: list[Draft] = []
    for page_var, page in _pages(ir):
        if not page.url or page.class_name in ambiguous:
            continue

        locators = usable_locators(page)
        if not locators:
            continue

        # A page the recording only ever saw signed in has to sign in first.
        # `_restore_sign_in` will not do it: it fires only when a case *drives*
        # a protected page, and this one is a `goto` followed by assertions -
        # deliberately, because "opening add-property signed out sends me to the
        # login form" is a real test that has to stay signed out to be one.
        # Left alone, this case opens /dashboard, gets bounced to /login, and
        # reports every element on the dashboard as missing.
        opening: list[DraftStep] = []
        if page_var in behind:
            if not sign_in:
                continue  # cannot get in; a red assertion is worse than no case
            opening = list(sign_in)

        steps = opening + [DraftStep(action="goto", value=page.url)]
        room = MAX_STEPS - len(steps)
        steps += [
            DraftStep(action="expect_visible", target=f"{page_var}.{locator.name}")
            for locator in locators[:room]
        ]

        label = _page_label(page)
        drafts.append(
            Draft(
                name=f"The {label} page still shows every element that was recorded",
                category="positive",
                priority="medium",
                description=(
                    f"Opens {page.url} and checks each of the "
                    f"{min(len(locators), room)} element(s) the recording used on "
                    "it is still on the page. Built from the recording rather "
                    "than invented, so it covers what was touched and nothing "
                    "else."
                ),
                steps=steps,
            )
        )
    return drafts


def _sign_in_steps(
    ir: TestIR, sequence: list[StepSpec], login_var: str | None
) -> list[DraftStep]:
    """The recorded sign-in as draftable steps, or nothing when it cannot be.

    Drafted here rather than left to `_restore_sign_in` for the one case that
    function declines to help - see `_page_checks`. Because these steps drive
    the same `(page_var, locator_name)` pairs the recording signed in with, they
    also trip `_restore_sign_in`'s own duplicate guard, so a case that gets one
    from here never gets a second glued on in front of it.
    """
    if not sequence or login_var is None:
        return []

    login_url = next(
        (page.url for var, page in _pages(ir) if var == login_var and page.url), None
    )
    if login_url is None:
        return []

    steps = [DraftStep(action="goto", value=login_url)]
    for step in sequence:
        if step.action in _PASSED_OVER:
            continue
        if step.action not in VERB_FOR_ACTION or step.locator_name is None:
            return []  # a hover or an upload in the login flow; do not guess

        verb = VERB_FOR_ACTION[step.action]
        value: str | None = None
        if verb == "fill":
            value = step.input_data or ""
        elif verb == "select":
            value = step.input_data
        elif verb == "press":
            value = _key_of(step)

        steps.append(
            DraftStep(
                action=verb,
                target=f"{step.page_var}.{step.locator_name}",
                value=value,
            )
        )
    return steps


def _empty_field_cases(forms: list[_Form], tokens: dict[str, str]) -> list[Draft]:
    """One case per filled field: leave it blank and the form must not go.

    The password field comes first where there is one. It is the single field
    that is required wherever it appears, so if only one of these cases survives
    the `count` cap it should be that one.

    What this cannot know is which of the others are required - nothing the
    recorder captures says so. A field that turns out to be optional lets the
    form through, the button vanishes, and the case goes red. That red is the
    answer rather than a defect in the case, and the description says as much so
    whoever reads the row does not spend an afternoon on it.
    """
    drafts: list[Draft] = []
    for form in forms:
        for step in _password_first(form.fills):
            if not (step.input_data or "").strip():
                continue  # it was already empty; blanking it tests nothing

            drafts.append(
                Draft(
                    name=(
                        f"{_page_label(form.page)} is refused when "
                        f"{_field_label(step)} is left empty"
                    ),
                    category="negative",
                    priority="high",
                    description=(
                        f"Fills in the form exactly as recorded but leaves "
                        f"{_field_label(step)} blank, then submits. Passes when "
                        "the form stays on screen, which is what a rejection "
                        "looks like: a submit that succeeded would navigate away "
                        "and take the button with it. Goes red if the field is "
                        "optional - the recording cannot say which fields are "
                        "required, and that red is the answer."
                    ),
                    steps=_replay(form, tokens, swap=(step, "")),
                )
            )
    return drafts


def _too_long_cases(forms: list[_Form], tokens: dict[str, str]) -> list[Draft]:
    """One case per field where "too long" is provably too long.

    Restricted to email addresses and telephone numbers, and restricted on
    purpose. Those two have a published ceiling, so a value above it is invalid
    by the same standard the recorded value satisfies and a correct application
    must refuse it. Three hundred characters in a description field is invalid
    by no standard at all - the form accepts it, the case goes red, and one red
    for nothing teaches a tester to dismiss the next one faster.
    """
    drafts: list[Draft] = []
    for form in forms:
        for step in form.fills:
            oversized = _too_long_for(step)
            if oversized is None:
                continue

            drafts.append(
                Draft(
                    name=(
                        f"{_page_label(form.page)} is refused when "
                        f"{_field_label(step)} is far longer than the standard allows"
                    ),
                    category="edge",
                    priority="medium",
                    description=(
                        f"Fills in the form as recorded but gives "
                        f"{_field_label(step)} a value of {len(oversized)} "
                        "characters, beyond what the format permits at all. "
                        "Passes when the form stays on screen."
                    ),
                    steps=_replay(form, tokens, swap=(step, oversized)),
                )
            )
    return drafts


def _blank_space_cases(forms: list[_Form], tokens: dict[str, str]) -> list[Draft]:
    """One case per filled field: spaces only, which is empty by any reading.

    This is the whitespace case that can be written honestly. The one everybody
    reaches for first - a *valid* value with spaces around it - cannot be:
    there is no verb for "the field now contains X" (`expect_text` reads
    `textContent`, which is empty for an `<input>` whatever was typed), and if
    the case submits, almost every stack trims the value and accepts it, so
    "the form stayed" is red against a correct application and "the form left"
    is red against one that reasonably refuses. Neither assertion has a meaning.

    A value that is *only* spaces has no such problem. It is empty to any
    correct application, so this inherits the empty-field case's soundness
    exactly - and the difference between the two is a real one: a form checking
    `if value` and a form checking `if value.strip()` behave identically
    everywhere except here.
    """
    drafts: list[Draft] = []
    for form in forms:
        for step in _password_first(form.fills):
            if not (step.input_data or "").strip():
                continue

            drafts.append(
                Draft(
                    name=(
                        f"{_page_label(form.page)} is refused when "
                        f"{_field_label(step)} contains only spaces"
                    ),
                    category="edge",
                    priority="medium",
                    description=(
                        f"Fills in the form as recorded but gives "
                        f"{_field_label(step)} nothing but spaces, which is empty "
                        "to any correct application. Passes when the form stays "
                        "on screen. Carries the same caveat as the empty-field "
                        "case: red means the field was optional."
                    ),
                    steps=_replay(form, tokens, swap=(step, _ONLY_SPACES)),
                )
            )
    return drafts


def _too_long_for(step: StepSpec) -> str | None:
    """An over-long value for this field, or None when none is provably wrong."""
    value = (step.input_data or "").strip()
    name = (step.locator_name or "").lower()

    if _LOOKS_LIKE_EMAIL.match(value):
        return _TOO_LONG_EMAIL
    if value.isdigit() and len(value) >= 7 and any(w in name for w in _PHONE_WORDS):
        return _TOO_LONG_PHONE
    return None


def _password_first(fills: list[StepSpec]) -> list[StepSpec]:
    """The fields, password first, otherwise in the order they were filled."""
    return sorted(fills, key=lambda step: not step.is_password)


def _page_label(page: PageSpec) -> str:
    """"LoginPage" -> "Login"; "PropertyOwnerAddPropertyPage" -> "Property owner add property"."""
    words = re.findall(r"[A-Z][a-z0-9]*", page.class_name)
    if words and words[-1] == "Page":
        words = words[:-1]
    if not words:
        return page.class_name or "the"
    return " ".join([words[0]] + [w.lower() for w in words[1:]])


def _field_label(step: StepSpec) -> str:
    """"email_input" -> "email input"."""
    return (step.locator_name or "the field").replace("_", " ").strip()


# ---------------------------------------------------------------------------
# Putting a batch together
# ---------------------------------------------------------------------------
def cases_from_recording(ir: TestIR, *, count: int) -> list[Draft]:
    """The cases this recording can support on its own, best first.

    Round-robin across the four groups rather than filling the first one and
    then the next. A recording of a nine-field registration form has nine
    empty-field cases in it, and a batch of twelve that is nine of those plus
    three of something else has told you one thing nine times. Taking the n-th
    of each group in turn gives every page and every form a case before any of
    them gets a second.

    Deterministic, and it has to be for the reason `ai/client.py` pins the
    temperature and the seed: pressing the button twice on an unchanged
    recording must rebuild the same suite, or a red test is a fact about the
    tool rather than about the application. Every collection below is a list in
    recorded order or `ir.pages` order, and no set is ever iterated.
    """
    tokens = _unique_tokens(ir)
    forms = _forms(ir)

    groups = [
        _empty_field_cases(forms, tokens),
        _page_checks(ir),
        _too_long_cases(forms, tokens),
        _blank_space_cases(forms, tokens),
    ]

    limit = max(1, count)
    batch: list[Draft] = []
    for row in zip_longest(*groups):
        for draft in row:
            if draft is None:
                continue
            batch.append(draft)
            if len(batch) >= limit:
                return batch
    return batch


def why_nothing(ir: TestIR) -> str:
    """Why this recording supports no case at all, phrased to be acted on.

    Reached only when there is no model either, so this half of the message is
    the half that matters: told just that a key is missing, somebody adds one,
    presses the button again and gets the same empty table.
    """
    if not ir.pages:
        return (
            "only navigates, so there are no elements to write a case against."
        )

    if not any(usable_locators(page) for page in ir.pages):
        return (
            "found every element by its position in the page, so a case built on "
            "one would pass or fail on where things happen to sit rather than on "
            "whether they work. Add a data-testid to the controls you want "
            "covered and record again."
        )

    _, behind, _ = sign_in_sequence(ir.steps)
    if not _forms(ir):
        if behind and all(var in behind for var, _ in _pages(ir)):
            return (
                "never filled in a form and sent it, and every page it saw was "
                "behind the sign-in - there is nothing to open cold and nothing "
                "to submit."
            )
        return (
            "never filled in a form and sent it, so there is nothing to submit "
            "with a field left empty. Record yourself filling something in and "
            "pressing the button that sends it."
        )

    return (
        "did not yield a case that could be compiled. The recording may use "
        "uploads or drag-and-drop, which a generated case cannot reproduce."
    )
