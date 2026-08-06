"""What a generated case is allowed to assert, and how it compiles.

Both cases here came out of a real generated suite.

The first could never run: `re.compile('?password=')` raises before the
assertion is reached, so the test reports as an error rather than telling you
anything about the application.

The second could never pass: `expect(agents_link).to_be_hidden()` on an error
page, where "Agents" is site navigation present on every page. The model had no
verb for "the password is masked" and reached for the nearest thing, which is a
different claim entirely.
"""

import ast
import re

import pytest

from app.ai.schemas import CaseStep, GeneratedCase
from app.codegen.converter import LocatorSpec, PageSpec
from app.codegen.generator import render
from app.codegen.synth import VERBS, SynthesisError, synthesise
from app.models.enums import ActionType


@pytest.fixture
def pages() -> list[PageSpec]:
    page = PageSpec(class_name="LoginPage", module="login_page", url="https://x.test/login")
    for name, expression in [
        ("email_input", "self.page.get_by_label('Email')"),
        ("password_input", "self.page.get_by_label('Password')"),
        ("reveal_button", "self.page.get_by_role('button', name='Show password')"),
        ("login_button", "self.page.get_by_role('button', name='Login')"),
    ]:
        page.locators.append(
            LocatorSpec(name=name, expression=expression, strategy="label", fragile=False)
        )
    return [page]


def build(steps: list[CaseStep], pages) -> str:
    """Synthesise and render, returning the test module source."""
    ir = synthesise(
        GeneratedCase(
            name="Case", category="negative", priority="high",
            description="A case.", steps=steps,
        ),
        pages=pages,
        start_url="https://x.test/login",
        module_name="test_case",
        function_name="test_case",
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


OPEN = CaseStep(action="goto", value="https://x.test/login", description="Open")


# ---------------------------------------------------------------------------
# URL assertions must survive being turned into a regex
# ---------------------------------------------------------------------------
def test_a_url_fragment_with_a_regex_character_still_compiles(pages):
    """`?password=` is not a pattern, it is a query string."""
    code = build(
        [OPEN, CaseStep(action="expect_not_url", value="?password=",
                        description="No password in the URL")],
        pages,
    )
    ast.parse(code)

    pattern = re.search(r"re\.compile\('([^']*)'\)", code).group(1)
    # The generated literal must itself be a valid regex — this is the check
    # that would have caught the real failure.
    re.compile(pattern.encode().decode("unicode_escape"))
    assert re.search(
        pattern.encode().decode("unicode_escape"), "https://x.test/a?password=hunter2"
    )


def test_dots_in_a_host_no_longer_match_any_character(pages):
    code = build(
        [OPEN, CaseStep(action="expect_url", value="app.example.com/home",
                        description="Arrived")],
        pages,
    )
    pattern = re.search(r"re\.compile\('([^']*)'\)", code).group(1)
    compiled = re.compile(pattern.encode().decode("unicode_escape"))

    assert compiled.search("https://app.example.com/home")
    assert not compiled.search("https://appXexampleYcom/home")


@pytest.mark.parametrize(
    "fragment",
    ["?password=", "/a+b", "(checkout)", "price=$5", "a|b", "[id]", "*"],
)
def test_no_url_fragment_can_produce_an_invalid_pattern(fragment, pages):
    code = build(
        [OPEN, CaseStep(action="expect_url", value=fragment, description="x")], pages
    )
    pattern = re.search(r"re\.compile\('([^']*)'\)", code).group(1)
    re.compile(pattern.encode().decode("unicode_escape"))  # raises if not escaped


def test_the_readable_step_keeps_the_unescaped_value(pages):
    r"""`\?password\=` in a test-case sheet is noise to whoever reads it."""
    ir = synthesise(
        GeneratedCase(
            name="Case", category="security", priority="high", description="d",
            steps=[OPEN, CaseStep(action="expect_not_url", value="?password=",
                                  description="No password in the URL")],
        ),
        pages=pages, start_url="https://x.test/login",
        module_name="test_case", function_name="test_case",
    )
    assertion = ir.steps[-1]
    assert assertion.expected_result == "?password="


# ---------------------------------------------------------------------------
# Masking is an attribute, not visibility
# ---------------------------------------------------------------------------
def test_a_masked_password_is_expressible(pages):
    """The verb that did not exist, which is why expect_hidden got misused."""
    code = build(
        [OPEN, CaseStep(action="expect_masked", target="LoginPage.password_input",
                        description="The password is masked")],
        pages,
    )
    ast.parse(code)
    assert "to_have_attribute('type', 'password')" in code
    assert "to_be_hidden" not in code


def test_revealing_the_password_is_a_separate_assertion(pages):
    code = build(
        [
            OPEN,
            CaseStep(action="fill", target="LoginPage.password_input",
                     value="hunter2", description="Type a password"),
            CaseStep(action="click", target="LoginPage.reveal_button",
                     description="Click the eye icon"),
            CaseStep(action="expect_not_masked", target="LoginPage.password_input",
                     description="The password is now readable"),
        ],
        pages,
    )
    ast.parse(code)
    assert "not_to_have_attribute('type', 'password')" in code


def test_both_masking_verbs_count_as_assertions():
    """A case ending in one of these must not be rejected as asserting nothing."""
    from app.codegen.synth import _ASSERTIONS

    assert {"expect_masked", "expect_not_masked"} <= _ASSERTIONS


def test_a_case_of_only_masking_assertions_is_still_rejected(pages):
    """Nothing was done to the app, so nothing was tested."""
    with pytest.raises(SynthesisError):
        build(
            [CaseStep(action="expect_masked", target="LoginPage.password_input",
                      description="Masked")],
            pages,
        )


def test_the_vocabulary_stays_closed():
    """Every verb is renderable and nothing was added by accident."""
    assert set(VERBS) == {
        "goto", "fill", "click", "check", "uncheck", "select", "press",
        "expect_visible", "expect_hidden", "expect_text",
        "expect_url", "expect_not_url", "expect_masked", "expect_not_masked",
    }


def test_an_invented_verb_is_still_refused(pages):
    with pytest.raises(SynthesisError, match="unknown action"):
        build([OPEN, CaseStep(action="expect_greyed_out",
                              target="LoginPage.password_input", description="x")], pages)


# ---------------------------------------------------------------------------
# An assertion asks about one element, so it is never allowed a substitute
#
# `expect_hidden` on the OTP modal was the real check in six generated negative
# tests, and all six were red. The modal's selector carries `isOpen`, so with
# the modal closed it matched nothing — the answer the test wanted — and healing
# then answered with whatever element sat at the recorded fallback path.
# ---------------------------------------------------------------------------
@pytest.fixture
def modal_pages() -> list[PageSpec]:
    """A register page whose OTP modal is only findable by a fragile selector."""
    page = PageSpec(
        class_name="RegisterBuyerPage", module="register_buyer_page",
        url="https://x.test/register/buyer",
    )
    page.locators.append(
        LocatorSpec(
            name="create_account_button",
            expression="self.page.get_by_role('button', name='Create Account')",
            strategy="role_name", fragile=False,
        )
    )
    page.locators.append(
        LocatorSpec(
            name="otp_modal",
            expression="self.page.locator('div.OtpModal__isOpen svg')",
            strategy="css", fragile=True,
        )
    )
    return [page]


DUPLICATE_EMAIL = [
    CaseStep(action="goto", value="https://x.test/register/buyer", description="Open"),
    CaseStep(action="click", target="RegisterBuyerPage.create_account_button",
             description="Submit an address that is already registered"),
    CaseStep(action="expect_visible", target="RegisterBuyerPage.create_account_button",
             description="Still on the form"),
    CaseStep(action="expect_hidden", target="RegisterBuyerPage.otp_modal",
             description="No OTP modal, so the registration was rejected"),
]


def modal_build(steps, modal_pages) -> str:
    ir = synthesise(
        GeneratedCase(name="Duplicate email", category="negative", priority="high",
                      description="d", steps=steps),
        pages=modal_pages, start_url="https://x.test/register/buyer",
        module_name="test_dup", function_name="test_dup",
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


def test_an_absence_check_is_looked_up_without_healing(modal_pages):
    code = modal_build(DUPLICATE_EMAIL, modal_pages)
    ast.parse(code)

    assert "expect(unhealed(register_buyer, 'otp_modal')).to_be_hidden()" in code
    assert "expect(register_buyer.otp_modal)" not in code


def test_a_visibility_check_is_too(modal_pages):
    """The quiet half: a spare would report the wrong element as present."""
    code = modal_build(DUPLICATE_EMAIL, modal_pages)

    assert (
        "expect(unhealed(register_buyer, 'create_account_button')).to_be_visible()"
        in code
    )


def test_the_click_in_the_same_test_still_heals(modal_pages):
    """Healing is right when the test is doing something, not observing."""
    code = modal_build(DUPLICATE_EMAIL, modal_pages)

    assert "register_buyer.create_account_button.click()" in code


@pytest.mark.parametrize(
    "verb", ["expect_visible", "expect_hidden", "expect_masked", "expect_not_masked"]
)
def test_every_assertion_that_names_an_element_opts_out(verb, pages):
    code = build(
        [OPEN, CaseStep(action=verb, target="LoginPage.password_input", description="x")],
        pages,
    )
    ast.parse(code)
    assert "unhealed(login, 'password_input')" in code


def test_expect_text_opts_out_as_well(pages):
    code = build(
        [OPEN, CaseStep(action="expect_text", target="LoginPage.email_input",
                        value="required", description="x")],
        pages,
    )
    assert "expect(unhealed(login, 'email_input')).to_contain_text('required')" in code


def test_a_url_assertion_names_no_element_so_it_needs_nothing(pages):
    code = build(
        [OPEN, CaseStep(action="expect_url", value="/home", description="x")], pages
    )

    assert "unhealed" not in code


def test_the_import_is_only_there_when_it_is_used(pages, modal_pages):
    with_element = modal_build(DUPLICATE_EMAIL, modal_pages)
    url_only = build(
        [OPEN, CaseStep(action="expect_url", value="/home", description="x")], pages
    )

    assert "from pages._healing import unhealed" in with_element
    assert "from pages._healing import unhealed" not in url_only


# ---------------------------------------------------------------------------
# How durable a step's element is has to reach the file that runs it
# ---------------------------------------------------------------------------
def test_a_generated_case_reports_its_fragile_steps(modal_pages):
    """It reported none while driving a CSS locator, so the one warning that
    tells a reader to add a data-testid never appeared on the tests needing it."""
    code = modal_build(DUPLICATE_EMAIL, modal_pages)

    assert "1 step(s) below rely on a fragile selector" in code


def test_an_absence_check_on_a_fragile_element_says_it_can_go_green(modal_pages):
    """It passes when the selector stops matching, which is not the same claim
    as a brittle click — that one goes red, and red gets looked at."""
    code = modal_build(DUPLICATE_EMAIL, modal_pages)

    assert "passes when" in code
    assert "turns it green, not red" in code


def test_a_durable_element_gets_no_warning(pages):
    code = build(
        [OPEN, CaseStep(action="expect_hidden", target="LoginPage.login_button",
                        description="Gone")],
        pages,
    )

    assert "brittle" not in code
    assert "fragile selector" not in code


# ---------------------------------------------------------------------------
# Setup the recording proved was necessary
#
# A generated sign-up case, red on every run:
#
#     fill  first name
#     fill  email
#     fill  mobile number                      <- 10 digits, starting 7
#     click 'Create Account'
#     expect_visible  the one-time-password popup    (i.e. it worked)
#
# The recording did three things between the email and the number: opened the
# country dropdown, searched "ind", chose India. The form validates the number
# against the country and the country defaults to Kenya, so the number was
# rejected every time — a test claiming registration succeeds, going red against
# a form doing exactly the right thing.
#
# Asking the model to keep those steps is a plea. This is a rule.
# ---------------------------------------------------------------------------
@pytest.fixture
def form_pages() -> list[PageSpec]:
    page = PageSpec(class_name="RegisterPage", module="register_page",
                    url="https://x.test/register")
    for name in ("first_name_input", "email_input", "country_button",
                 "country_search_input", "india_option", "mobile_input",
                 "terms_checkbox", "submit_button", "otp_modal"):
        page.locators.append(
            LocatorSpec(name=name, expression=f"self.page.get_by_test_id('{name}')",
                        strategy="test_id", fragile=False)
        )
    return [page]


def recorded_form() -> list:
    """The happy path: the country is chosen between the email and the number."""
    from app.codegen.converter import StepSpec
    from app.models.enums import ActionType as A

    V = "register"
    order = [
        ("first_name_input", A.INPUT, f"{V}.first_name_input.fill('John')"),
        ("email_input", A.INPUT, f"{V}.email_input.fill('a@b.com')"),
        ("country_button", A.CLICK, f"{V}.country_button.click()"),
        ("country_search_input", A.INPUT, f"{V}.country_search_input.fill('ind')"),
        ("india_option", A.CLICK, f"{V}.india_option.click()"),
        ("mobile_input", A.INPUT, f"{V}.mobile_input.fill('9632587412')"),
        ("terms_checkbox", A.CHECK, f"{V}.terms_checkbox.check()"),
        ("submit_button", A.CLICK, f"{V}.submit_button.click()"),
    ]
    return [
        StepSpec(sequence=i, action=action, code=[code], description=f"step {i}",
                 page_var=V, locator_name=name)
        for i, (name, action, code) in enumerate(order)
    ]


def form_build(steps, form_pages) -> str:
    ir = synthesise(
        GeneratedCase(name="Case", category="positive", priority="high",
                      description="d", steps=steps),
        pages=form_pages, start_url="https://x.test/register",
        module_name="test_form", function_name="test_form",
        recorded_steps=recorded_form(),
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


OPEN_FORM = CaseStep(action="goto", value="https://x.test/register", description="Open")


def test_setup_skipped_between_two_fields_is_put_back(form_pages):
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.email_input",
                     value="a@b.com", description="Email"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="click", target="RegisterPage.submit_button",
                     description="Submit"),
            CaseStep(action="expect_visible", target="RegisterPage.otp_modal",
                     description="Registered"),
        ],
        form_pages,
    )
    ast.parse(code)

    assert "register.country_button.click()" in code
    assert "register.india_option.click()" in code


def test_a_field_inside_the_control_comes_back_too(form_pages):
    """Restoring the two clicks without the search leaves a list with no India."""
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.email_input",
                     value="a@b.com", description="Email"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="expect_visible", target="RegisterPage.otp_modal",
                     description="Registered"),
        ],
        form_pages,
    )

    assert "register.country_search_input.fill('ind')" in code


def test_the_restored_steps_land_in_the_recorded_order(form_pages):
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.email_input",
                     value="a@b.com", description="Email"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="expect_visible", target="RegisterPage.otp_modal",
                     description="Registered"),
        ],
        form_pages,
    )

    assert (
        code.index("country_button.click()")
        < code.index("country_search_input.fill")
        < code.index("india_option.click()")
        < code.index("mobile_input.fill")
    )


def test_a_restored_step_says_where_it_came_from(form_pages):
    """A step nobody asked for has to explain itself in the file."""
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.email_input",
                     value="a@b.com", description="Email"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="expect_visible", target="RegisterPage.otp_modal",
                     description="Registered"),
        ],
        form_pages,
    )

    assert "(from the recording)" in code


# --- and what it must never touch --------------------------------------------
def test_a_field_the_case_left_out_stays_left_out(form_pages):
    """"Submit with no email" is a real test. Typing the email back destroys it."""
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.first_name_input",
                     value="John", description="First name"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="click", target="RegisterPage.submit_button",
                     description="Submit"),
            CaseStep(action="expect_visible", target="RegisterPage.email_input",
                     description="Still on the form"),
        ],
        form_pages,
    )

    # The country controls between them are restored...
    assert "register.country_button.click()" in code
    # ...but the email the case deliberately skipped is not.
    assert "email_input.fill" not in code


def test_a_tick_after_the_last_field_is_not_restored(form_pages):
    """"Refused without accepting the terms" drops the tick on purpose."""
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.email_input",
                     value="a@b.com", description="Email"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="click", target="RegisterPage.submit_button",
                     description="Submit"),
            CaseStep(action="expect_visible", target="RegisterPage.terms_checkbox",
                     description="Still on the form"),
        ],
        form_pages,
    )

    assert "terms_checkbox.check()" not in code


def test_a_case_that_already_does_the_setup_is_left_alone(form_pages):
    """No duplicates: it opens the dropdown once, not twice."""
    code = form_build(
        [
            OPEN_FORM,
            CaseStep(action="fill", target="RegisterPage.email_input",
                     value="a@b.com", description="Email"),
            CaseStep(action="click", target="RegisterPage.country_button",
                     description="Country"),
            CaseStep(action="fill", target="RegisterPage.country_search_input",
                     value="ind", description="Search"),
            CaseStep(action="click", target="RegisterPage.india_option",
                     description="India"),
            CaseStep(action="fill", target="RegisterPage.mobile_input",
                     value="9632587412", description="Mobile"),
            CaseStep(action="expect_visible", target="RegisterPage.otp_modal",
                     description="Registered"),
        ],
        form_pages,
    )

    assert code.count("country_button.click()") == 1
    assert "(from the recording)" not in code


def test_a_case_with_no_recording_behind_it_is_unchanged(pages):
    """Hand-authored cases pass no recorded steps, and must still compile."""
    code = build(
        [OPEN, CaseStep(action="fill", target="LoginPage.email_input",
                        value="a@b.com", description="Email"),
         CaseStep(action="expect_visible", target="LoginPage.login_button",
                  description="There")],
        pages,
    )
    ast.parse(code)


# ---------------------------------------------------------------------------
# Data that must not collide with the last run
# ---------------------------------------------------------------------------
SIGNUP = [
    OPEN,
    CaseStep(action="fill", target="LoginPage.email_input",
             value="{{unique_email}}", description="Enter an email"),
    CaseStep(action="click", target="LoginPage.login_button", description="Submit"),
    CaseStep(action="expect_not_url", value="/register", description="Left the form"),
]


def test_a_unique_email_is_generated_per_run_not_baked_in(pages):
    """A fixed address passes once and is red on every run after it."""
    code = build(SIGNUP, pages)
    ast.parse(code)

    assert "uuid4().hex" in code
    assert "from uuid import uuid4" in code
    # The placeholder itself must not survive into the test.
    assert "{{unique_email}}" not in code
    # And it must be an expression, not a quoted literal.
    assert "'{{unique_email}}'" not in code


@pytest.mark.parametrize(
    "token", ["{{unique_email}}", "{{unique_phone}}", "{{unique_name}}", "{{unique}}"]
)
def test_every_placeholder_renders_as_a_live_expression(token, pages):
    code = build(
        [
            OPEN,
            CaseStep(action="fill", target="LoginPage.email_input",
                     value=token, description="Fill"),
            CaseStep(action="expect_not_url", value="/done", description="x"),
        ],
        pages,
    )
    ast.parse(code)
    assert "uuid4()" in code
    assert token not in code


def test_the_generated_email_is_recognisably_ours_and_undeliverable(pages):
    """`.test` is reserved and cannot resolve, so nothing can be mailed to it,
    and the prefix makes every account a run created findable in one query."""
    code = build(SIGNUP, pages)
    line = next(l for l in code.splitlines() if "email_input.fill" in l)
    assert "autoqa-" in line
    assert "@example.test" in line


def test_uuid_is_not_imported_when_nothing_needs_it(pages):
    code = build(
        [
            OPEN,
            CaseStep(action="fill", target="LoginPage.email_input",
                     value="a@b.test", description="Fill"),
            CaseStep(action="expect_not_url", value="/done", description="x"),
        ],
        pages,
    )
    assert "uuid4" not in code


def test_an_ordinary_value_is_still_a_literal(pages):
    """Only the placeholders are special; nothing else is reinterpreted."""
    code = build(
        [
            OPEN,
            CaseStep(action="fill", target="LoginPage.email_input",
                     value="deliberate@example.test", description="Fill"),
            CaseStep(action="expect_not_url", value="/done", description="x"),
        ],
        pages,
    )
    assert "'deliberate@example.test'" in code


def test_the_readable_step_shows_the_placeholder_not_the_expression(pages):
    """A test-case sheet should say the value varies, not print f-string code."""
    ir = synthesise(
        GeneratedCase(name="Case", category="positive", priority="high",
                      description="d", steps=SIGNUP),
        pages=pages, start_url="https://x.test/login",
        module_name="test_case", function_name="test_case",
    )
    # `goto` carries its URL as input_data too, so select the fill.
    fill = next(s for s in ir.steps if s.action is ActionType.INPUT)
    assert fill.input_data == "{{unique_email}}"


def test_a_module_needing_both_imports_gets_both_and_still_parses(pages):
    code = build(
        [
            OPEN,
            CaseStep(action="fill", target="LoginPage.email_input",
                     value="{{unique_email}}", description="Fill"),
            CaseStep(action="expect_url", value="?ref=a+b", description="x"),
        ],
        pages,
    )
    ast.parse(code)
    assert "import re" in code
    assert "from uuid import uuid4" in code
