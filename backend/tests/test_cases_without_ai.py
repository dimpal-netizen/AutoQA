"""Test cases built from the recording, when there is no model to ask.

The feature these cover is small to describe and easy to get subtly wrong: a
generated case that goes red against an application behaving perfectly costs a
tester an afternoon and teaches them to dismiss the next red one faster. So most
of what is pinned here is not "a case was produced" but "the case produced can
only fail for a real reason".
"""

import ast

import pytest

from app.ai.case_generator import GenerationOutcome, accept_all, describe_pages
from app.codegen.converter import LocatorSpec, PageSpec, StepSpec, TestIR
from app.codegen.generator import render
from app.codegen.recorded_cases import (
    FROM_RECORDING,
    cases_from_recording,
    usable_locators,
    why_nothing,
)
from app.models.enums import ActionType


# ---------------------------------------------------------------------------
# Fixtures — a login recording that goes on to a page behind the login
# ---------------------------------------------------------------------------
def locator(name: str, **overrides) -> LocatorSpec:
    return LocatorSpec(
        name=name,
        expression=f"self.page.get_by_test_id('{name}')",
        strategy=overrides.pop("strategy", "test_id"),
        fragile=False,
        **overrides,
    )


def page(class_name: str, module: str, url: str, names: list[str]) -> PageSpec:
    return PageSpec(
        class_name=class_name,
        module=module,
        url=url,
        locators=[locator(name) for name in names],
    )


def step(
    sequence: int,
    action: ActionType,
    page_var: str,
    locator_name: str,
    *,
    data: str | None = None,
    password: bool = False,
    code: str = "placeholder()",
) -> StepSpec:
    return StepSpec(
        sequence=sequence,
        action=action,
        code=[code],
        description=f"step {sequence}",
        page_var=page_var,
        locator_name=locator_name,
        input_data=data,
        is_password=password,
    )


def opening(url: str = "https://shop.test/login") -> StepSpec:
    return StepSpec(
        sequence=0,
        action=ActionType.NAVIGATE,
        code=[f"page.goto({url!r})"],
        description=f"Open {url}",
    )


@pytest.fixture
def login_page() -> PageSpec:
    return page(
        "LoginPage",
        "login_page",
        "https://shop.test/login",
        ["email_input", "password_input", "sign_in_button"],
    )


@pytest.fixture
def dashboard_page() -> PageSpec:
    return page(
        "DashboardPage",
        "dashboard_page",
        "https://shop.test/dashboard",
        ["heading", "sign_out_button"],
    )


@pytest.fixture
def recording(login_page, dashboard_page) -> TestIR:
    """Sign in, then do something on the page behind the sign-in."""
    return TestIR(
        suite_name="Login",
        function_name="test_login",
        module_name="test_login",
        start_url="https://shop.test/login",
        pages=[login_page, dashboard_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(2, ActionType.INPUT, "login", "password_input",
                 data="Test@1234", password=True),
            step(3, ActionType.CLICK, "login", "sign_in_button"),
            step(4, ActionType.CLICK, "dashboard", "sign_out_button"),
        ],
    )


def accepted(ir: TestIR, *, count: int = 12) -> GenerationOutcome:
    """Everything `cases_from_recording` produced, through the real validator."""
    outcome = GenerationOutcome()
    accept_all(cases_from_recording(ir, count=count), ir, outcome)
    return outcome


def source_of(case) -> str:
    files = render(case.ir, browser_info={})
    return next(f for f in files if f.path == case.ir.file_path).content


def named(outcome: GenerationOutcome, fragment: str):
    return next(c for c in outcome.cases if fragment in c.name)


# ---------------------------------------------------------------------------
# It works at all
# ---------------------------------------------------------------------------
def test_a_recording_alone_produces_cases(recording):
    """The headline. No provider anywhere in this test, and cases come out."""
    outcome = accepted(recording)

    assert outcome.cases
    assert not outcome.rejected


def test_every_case_survives_the_validator_and_is_valid_python(recording):
    """Nothing here may reach a subprocess that `synthesise` would refuse."""
    outcome = accepted(recording)

    for case in outcome.cases:
        ast.parse(source_of(case))


def test_the_fallback_is_not_labelled_as_the_recording():
    """`generated_by` decides what "Run Recorded Test Cases" runs.

    `isRecorded` in lib/types.ts is `generated_by.startsWith("deterministic")`,
    and the button built on it promises "the walkthrough a tester performed...
    nothing a model invented". These cases are built FROM the recording, not BY
    it. Reusing `GENERATOR` would fold them in silently, and nothing on screen
    would say so.
    """
    assert not FROM_RECORDING.startswith("deterministic")


def test_the_same_recording_produces_the_same_cases_twice(recording):
    """A verdict that moves on its own is not a verdict — see ai/client.py."""
    first = cases_from_recording(recording, count=12)
    second = cases_from_recording(recording, count=12)

    def shape(drafts):
        return [
            (d.name, d.category, [(s.action, s.target, s.value) for s in d.steps])
            for d in drafts
        ]

    assert shape(first) == shape(second)


def test_the_count_is_a_ceiling(recording):
    assert len(cases_from_recording(recording, count=3)) == 3


def test_a_batch_spreads_across_the_kinds_of_case(recording):
    """Three cases should not all be the same check on the same form."""
    categories = {d.category for d in cases_from_recording(recording, count=3)}

    assert len(categories) > 1


# ---------------------------------------------------------------------------
# Shape 1 — the page element check
# ---------------------------------------------------------------------------
def test_a_page_check_asserts_every_element_the_recording_found(recording):
    code = source_of(named(accepted(recording), "Login page still shows"))

    for name in ("email_input", "password_input", "sign_in_button"):
        assert f"'{name}'" in code


def test_a_page_behind_the_sign_in_signs_itself_in_first(recording):
    """`_restore_sign_in` will not do this one, by design.

    It fires only when a case *drives* a protected page, and a page check is a
    `goto` followed by assertions. Left alone the case opens /dashboard, gets
    bounced to the login form, and reports every element on the dashboard as
    missing — fifty-seven seconds, then red, against a site behaving correctly.
    """
    code = source_of(named(accepted(recording), "Dashboard page still shows"))

    assert "password_input.fill" in code
    assert code.index("password_input.fill") < code.index("shop.test/dashboard")


def test_the_sign_in_is_not_glued_on_twice(recording):
    """Prepending it ourselves has to trip `_restore_sign_in`'s duplicate guard.

    That guard compares (page_var, locator_name) pairs, and ours are the
    recording's own — so a second login must not appear. A second one would run
    on the dashboard, where there is no email field, and spend thirty seconds
    looking for it.
    """
    code = source_of(named(accepted(recording), "Dashboard page still shows"))

    assert code.count("password_input.fill") == 1


def test_an_element_that_can_only_be_found_by_position_is_never_offered():
    """A case built on one passes or fails on where things happen to sit."""
    positional = page("HomePage", "home_page", "https://shop.test/", ["wrapper_div"])
    positional.locators[0].strategy = "xpath"

    assert usable_locators(positional) == []


@pytest.mark.parametrize(
    "attribute", ["visible", "reachable", "revealed"]
)
def test_an_element_the_recording_only_saw_in_one_state_is_never_offered(attribute):
    """Zero-sized, unreachable cold, or revealed by the step before it.

    All three look like ordinary elements in a finished recording, and all three
    make an invented case wait thirty seconds and then report a bug against a
    page that is fine.
    """
    somewhere = page("HomePage", "home_page", "https://shop.test/", ["close_video"])
    setattr(somewhere.locators[0], attribute, attribute == "revealed")

    assert usable_locators(somewhere) == []


def test_the_deterministic_and_ai_paths_agree_on_what_is_safe(login_page):
    """One definition, so the two halves cannot drift apart."""
    login_page.locators[1].reachable = False

    described = describe_pages([login_page])
    offered = [loc.name for loc in usable_locators(login_page)]

    assert "password_input" not in described
    assert "password_input" not in offered
    assert all(name in described for name in offered)


# ---------------------------------------------------------------------------
# Shape 2 — the empty field
# ---------------------------------------------------------------------------
def test_an_empty_field_case_blanks_only_the_field_under_test(recording):
    code = source_of(named(accepted(recording), "email input is left empty"))

    assert "email_input.fill('')" in code
    assert "password_input.fill('Test@1234')" in code


def test_an_empty_field_case_asserts_the_form_stayed(recording):
    """A submit that worked navigates away and takes the button with it."""
    code = source_of(named(accepted(recording), "email input is left empty"))

    assert "sign_in_button.click()" in code
    assert "to_be_visible()" in code
    assert code.index("sign_in_button.click()") < code.index("to_be_visible()")


def test_a_field_that_was_already_empty_gets_no_case(login_page):
    """Blanking a blank field tests nothing and reads as a real case."""
    ir = TestIR(
        suite_name="Login", function_name="test_login", module_name="test_login",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data=""),
            step(2, ActionType.INPUT, "login", "password_input", data="Test@1234"),
            step(3, ActionType.CLICK, "login", "sign_in_button"),
        ],
    )

    names = [d.name for d in cases_from_recording(ir, count=12)]

    assert not any("email input is left empty" in name for name in names)


def test_a_control_after_the_last_field_is_replayed_too(login_page):
    """`_restore_setup` puts back only what sits *between* two fills.

    A terms checkbox after the last field never comes back, so leaving it out
    means the form is refused for two reasons and the case passes on the
    strength of the one it did not mean to test.
    """
    login_page.locators.append(locator("terms_checkbox"))
    ir = TestIR(
        suite_name="Register", function_name="test_register", module_name="test_register",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(2, ActionType.INPUT, "login", "password_input", data="Test@1234"),
            step(3, ActionType.CHECK, "login", "terms_checkbox"),
            step(4, ActionType.CLICK, "login", "sign_in_button"),
        ],
    )

    code = source_of(named(accepted(ir), "email input is left empty"))

    assert "terms_checkbox" in code


# ---------------------------------------------------------------------------
# Values that cannot be replayed as they were recorded
# ---------------------------------------------------------------------------
def test_a_value_the_converter_made_unique_comes_back_as_a_placeholder(login_page):
    """Otherwise run two is told the address is already registered.

    The form stays put for that reason, and a case claiming "the form was
    refused because the password was empty" goes green having tested nothing.
    Green for the wrong reason is worse than red for the wrong reason: nobody
    ever looks at it again.
    """
    ir = TestIR(
        suite_name="Register", function_name="test_register", module_name="test_register",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(2, ActionType.INPUT, "login", "password_input",
                 data="Test@1234", password=True),
            step(3, ActionType.CLICK, "login", "sign_in_button"),
        ],
        unique_values=[
            ("fresh_email", "f'autoqa-{uuid4().hex[:10]}@shop.test'", "lucy@shop.test")
        ],
    )

    code = source_of(named(accepted(ir), "password input is left empty"))

    assert "uuid4()" in code
    assert "lucy@shop.test" not in code


def test_a_recorded_password_is_never_swapped_for_a_fresh_one(recording):
    """It is not an identity. Change it and the test cannot sign in again."""
    code = source_of(named(accepted(recording), "Dashboard page still shows"))

    assert "Test@1234" in code


# ---------------------------------------------------------------------------
# Forms that cannot be replayed honestly
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("action", [ActionType.UPLOAD, ActionType.DRAG_DROP,
                                    ActionType.HOVER, ActionType.DOUBLE_CLICK])
def test_a_form_with_an_action_outside_the_vocabulary_is_skipped(login_page, action):
    """A replay without it submits a form the recording never submitted.

    The application then refuses it for a reason the case does not name, which
    reads as a bug in the feature under test.
    """
    login_page.locators.append(locator("avatar_input"))
    ir = TestIR(
        suite_name="Profile", function_name="test_profile", module_name="test_profile",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(2, action, "login", "avatar_input"),
            step(3, ActionType.CLICK, "login", "sign_in_button"),
        ],
    )

    names = [d.name for d in cases_from_recording(ir, count=12)]

    assert not any("left empty" in name for name in names)


def test_a_multi_select_is_skipped(login_page):
    """`converter` joins the chosen values with ", " into one string.

    Replayed as `select_option('House, Flat')` that picks an option nobody ever
    chose, and the step fails on its own data.
    """
    login_page.locators.append(locator("property_type_select"))
    ir = TestIR(
        suite_name="Search", function_name="test_search", module_name="test_search",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(2, ActionType.SELECT, "login", "property_type_select",
                 data="House, Flat"),
            step(3, ActionType.CLICK, "login", "sign_in_button"),
        ],
    )

    names = [d.name for d in cases_from_recording(ir, count=12)]

    assert not any("left empty" in name for name in names)


def test_a_form_that_was_never_submitted_is_not_a_form(login_page):
    ir = TestIR(
        suite_name="Login", function_name="test_login", module_name="test_login",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
        ],
    )

    assert not any("left empty" in d.name for d in cases_from_recording(ir, count=12))


def test_a_retried_form_produces_one_case_per_field_not_two(login_page):
    """Somebody who got the password wrong and tried again recorded two runs.

    Both replay to byte-identical cases, and two identical rows under two names
    is a table nobody can act on.
    """
    ir = TestIR(
        suite_name="Login", function_name="test_login", module_name="test_login",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(2, ActionType.INPUT, "login", "password_input", data="wrong"),
            step(3, ActionType.CLICK, "login", "sign_in_button"),
            step(4, ActionType.INPUT, "login", "email_input", data="lucy@shop.test"),
            step(5, ActionType.INPUT, "login", "password_input", data="Test@1234"),
            step(6, ActionType.CLICK, "login", "sign_in_button"),
        ],
    )

    names = [d.name for d in cases_from_recording(ir, count=25)]

    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Shape 4 — the edge values
# ---------------------------------------------------------------------------
def test_over_long_is_offered_where_it_is_provably_invalid(recording):
    """An address past RFC 5321's ceiling is invalid by the same standard the
    recorded one satisfies, so a correct application must refuse it."""
    names = [c.name for c in accepted(recording).cases]

    assert any("email input is far longer" in name for name in names)


def test_over_long_is_not_offered_where_it_would_be_a_guess(login_page):
    """Three hundred characters in a free-text field is invalid by no standard.

    The form accepts it, the case goes red, and one red for nothing teaches a
    tester to dismiss the next one faster.
    """
    login_page.locators.append(locator("first_name_input"))
    ir = TestIR(
        suite_name="Register", function_name="test_register", module_name="test_register",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[
            opening(),
            step(1, ActionType.INPUT, "login", "first_name_input", data="Lucy"),
            step(2, ActionType.CLICK, "login", "sign_in_button"),
        ],
    )

    names = [d.name for d in cases_from_recording(ir, count=25)]

    assert not any("far longer" in name for name in names)


def test_no_case_pads_a_value_with_whitespace(recording):
    """The case everybody reaches for first, and it cannot be written honestly.

    There is no verb for "the field now holds X" — `expect_text` reads
    `textContent`, which is empty for an `<input>` whatever was typed. And if
    the case submits, almost every stack trims the value and accepts it, so
    "the form stayed" is red against a correct application while "the form left"
    is red against one that reasonably refuses. Neither assertion means
    anything.
    """
    for case in accepted(recording).cases:
        for step_spec in case.ir.steps:
            typed = step_spec.input_data or ""
            assert typed == typed.strip() or not typed.strip()


def test_a_value_that_is_only_spaces_is_offered_instead(recording):
    """Empty to any correct application, so it inherits the empty-field case's
    soundness — and it is a real second test: a form checking `if value` and one
    checking `if value.strip()` differ here and nowhere else."""
    code = source_of(named(accepted(recording), "email input contains only spaces"))

    assert "email_input.fill('   ')" in code


# ---------------------------------------------------------------------------
# Nothing to build on
# ---------------------------------------------------------------------------
def test_a_navigation_only_recording_says_so():
    ir = TestIR(
        suite_name="Browse", function_name="test_browse", module_name="test_browse",
        start_url="https://shop.test/", pages=[],
    )

    assert cases_from_recording(ir, count=12) == []
    assert "only navigates" in why_nothing(ir)


def test_a_recording_of_positional_elements_says_what_to_do_about_it():
    positional = page("HomePage", "home_page", "https://shop.test/", ["wrapper_div"])
    positional.locators[0].strategy = "css"
    ir = TestIR(
        suite_name="Browse", function_name="test_browse", module_name="test_browse",
        start_url="https://shop.test/", pages=[positional],
    )

    assert "data-testid" in why_nothing(ir)


def test_a_recording_that_filled_nothing_in_says_what_is_missing(login_page):
    ir = TestIR(
        suite_name="Look", function_name="test_look", module_name="test_look",
        start_url="https://shop.test/login", pages=[login_page],
        steps=[opening(), step(1, ActionType.CLICK, "login", "sign_in_button")],
    )

    # A page check is still possible, so this is not the empty case.
    assert cases_from_recording(ir, count=12)
    assert "never filled in a form" in why_nothing(ir)
