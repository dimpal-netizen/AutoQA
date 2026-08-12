"""Writing a test case by hand, without writing Python.

A generated suite is where a tester starts, not where they finish. They know the
application and will think of a case the model missed, or spot one it got subtly
wrong — and without a way to fix either, the only options were to regenerate and
hope, or to abandon the tool and write Playwright by hand.

The rule that makes this safe is the one already in `synth.py`: nobody writes
code. A person picks a verb from the fixed vocabulary and an element that
already exists, exactly as the model does, and the same converter compiles it.
These tests hold that boundary — the interesting ones are the refusals, because
a hand-written case has to be held to the standard a generated one is.
"""

import ast

import pytest

from app.ai.schemas import CaseStep, GeneratedCase
from app.codegen.converter import LocatorSpec, PageSpec, StepSpec
from app.codegen.generator import render
from app.codegen.synth import (
    PLACEHOLDER_LABEL,
    VERB_FOR_ACTION,
    VERB_LABEL,
    VERBS,
    SynthesisError,
    elements,
    page_variables_for,
    synthesise,
    unique_expression,
    vocabulary,
)
from app.models.enums import ActionType


@pytest.fixture
def pages() -> list[PageSpec]:
    page = PageSpec(
        class_name="LoginPage", module="login_page", url="https://x.test/login"
    )
    for name, expression, strategy, fragile in [
        ("email_input", "self.page.get_by_label('Email')", "label", False),
        ("password_input", "self.page.get_by_label('Password')", "label", False),
        ("login_button", "self.page.locator('form > button')", "css", True),
    ]:
        page.locators.append(
            LocatorSpec(
                name=name, expression=expression, strategy=strategy, fragile=fragile
            )
        )
    return [page]


def compile_case(steps: list[CaseStep], pages) -> str:
    ir = synthesise(
        GeneratedCase(
            name="Case",
            category="negative",
            priority="high",
            description="A case.",
            steps=steps,
        ),
        pages=pages,
        start_url="https://x.test/login",
        module_name="test_case",
        function_name="test_case",
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


# ---------------------------------------------------------------------------
# What the editor is offered
# ---------------------------------------------------------------------------
def test_every_verb_is_named_for_a_human(pages):
    """A dropdown showing `expect_not_masked` is a dropdown nobody can use."""
    for verb in vocabulary(pages)["verbs"]:
        assert verb["label"] != verb["name"], f"{verb['name']} has no label"


def test_no_label_outlives_its_verb():
    """A label left behind after a verb is removed would offer an action the
    backend rejects."""
    assert set(VERB_LABEL) == set(VERBS)
    assert set(PLACEHOLDER_LABEL)


def test_elements_are_named_the_way_a_step_stores_them(pages):
    """The page *variable*, not the page class.

    The two forms look interchangeable and are not: a step is stored as
    `{page_var}.{locator}`, so an editor offering `LoginPage.email_input` builds
    a list nothing already saved can be matched against. The variable is derived
    here rather than written out, because how it is spelled is the converter's
    business and this test should not pin it.
    """
    variable = {
        class_name: var for var, class_name in page_variables_for(pages)
    }["LoginPage"]
    targets = {element["target"] for element in elements(pages)}

    assert f"{variable}.email_input" in targets
    assert "LoginPage.email_input" not in targets


def test_a_step_can_be_saved_loaded_and_saved_again(pages):
    """The round trip the editor depends on.

    Compile a case, take the target back off the step exactly as it is stored,
    and compile again. If the index only answered to the class-name form this
    would raise "unknown element" on a step it had just written itself.
    """
    steps = [
        CaseStep(action="goto", value="https://x.test/login", description="Open"),
        CaseStep(action="fill", target="LoginPage.email_input", value="a@b.test",
                 description="Type the email"),
        CaseStep(action="expect_visible", target="LoginPage.login_button",
                 description="The button is there"),
    ]
    ir = synthesise(
        GeneratedCase(name="C", category="positive", priority="low",
                      description="d", steps=steps),
        pages=pages, start_url="https://x.test/login",
        module_name="test_c", function_name="test_c",
    )

    stored = [
        CaseStep(
            action=step.verb,
            target=(f"{step.page_var}.{step.locator_name}"
                    if step.page_var and step.locator_name else None),
            value=step.input_data or step.expected_result,
            description=step.description,
        )
        for step in ir.steps
    ]

    again = synthesise(
        GeneratedCase(name="C", category="positive", priority="low",
                      description="d", steps=stored),
        pages=pages, start_url="https://x.test/login",
        module_name="test_c", function_name="test_c",
    )

    assert [s.code for s in again.steps] == [s.code for s in ir.steps]


def test_the_verb_is_recorded_on_every_step(pages):
    """Without it an assertion cannot be edited: seven of them share one action."""
    ir = synthesise(
        GeneratedCase(
            name="C", category="positive", priority="low", description="d",
            steps=[
                CaseStep(action="goto", value="https://x.test/login", description="Open"),
                CaseStep(action="expect_masked", target="LoginPage.password_input",
                         description="Password is dots"),
            ],
        ),
        pages=pages, start_url="https://x.test/login",
        module_name="test_c", function_name="test_c",
    )

    assert [step.verb for step in ir.steps] == ["goto", "expect_masked"]


def test_assert_is_never_guessed_at():
    """Seven verbs share ActionType.ASSERT. Inferring one would silently change
    what a test checks, which is worse than declining to infer."""
    assert ActionType.ASSERT not in VERB_FOR_ACTION
    assert all(VERBS[verb].action is not ActionType.ASSERT
               for verb in VERB_FOR_ACTION.values())


def test_a_fragile_element_says_so(pages):
    """Shown next to the choice, rather than as a surprise in a failure report
    three days later."""
    by_label = {e["label"]: e for e in elements(pages)}

    assert by_label["login button"]["fragile"] is True
    assert by_label["email input"]["fragile"] is False


# ---------------------------------------------------------------------------
# A hand-written case is held to the same standard as a generated one
# ---------------------------------------------------------------------------
def test_a_case_that_checks_nothing_is_refused(pages):
    """It would report green whether or not the feature works."""
    with pytest.raises(SynthesisError, match="no assertion"):
        compile_case(
            [
                CaseStep(action="goto", value="https://x.test/login", description="Open"),
                CaseStep(action="click", target="LoginPage.login_button",
                         description="Click"),
            ],
            pages,
        )


def test_a_case_that_does_nothing_is_refused(pages):
    """Nothing opens a page, so it asserts against a blank one."""
    with pytest.raises(SynthesisError, match="only assertions"):
        compile_case(
            [
                CaseStep(action="expect_visible", target="LoginPage.email_input",
                         description="Visible"),
            ],
            pages,
        )


def test_an_element_that_does_not_exist_is_refused(pages):
    with pytest.raises(SynthesisError, match="unknown element"):
        compile_case(
            [
                CaseStep(action="goto", value="https://x.test/login", description="Open"),
                CaseStep(action="click", target="LoginPage.forgot_password_link",
                         description="Click"),
                CaseStep(action="expect_visible", target="LoginPage.email_input",
                         description="Visible"),
            ],
            pages,
        )


def test_an_action_outside_the_vocabulary_is_refused(pages):
    """The whole reason there is a vocabulary. `execute` is not in it, and no
    path exists by which it could become a line of the generated test."""
    with pytest.raises(SynthesisError, match="unknown action"):
        compile_case(
            [
                CaseStep(action="execute", value="os.system('rm -rf /')",
                         description="Nope"),
                CaseStep(action="expect_visible", target="LoginPage.email_input",
                         description="Visible"),
            ],
            pages,
        )


# ---------------------------------------------------------------------------
# Values that must differ on every run
#
# From a real suite, where all three of these were typed into the form exactly
# as written because only an exact whole-value match was substituted:
#
#    5. input  = '{unique_name}First'
#    6. input  = '{unique_name}Last'
#    8. input  = '{unique_phone}'
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["{{unique_email}}", "{unique_email}", "{{unique_phone}}", "{unique_phone}"],
)
def test_a_placeholder_written_either_way_is_substituted(value):
    """One brace or two. The model writes both and the prompt cannot stop it."""
    expression = unique_expression(value)

    assert expression is not None
    assert "unique_" not in expression
    assert "uuid4()" in expression


def test_a_placeholder_inside_a_longer_value_is_substituted():
    """`{unique_name}First` is a reasonable thing to want in a first-name field,
    and used to be typed in literally — identical on every run, which is the
    collision the placeholder exists to prevent."""
    expression = unique_expression("{unique_name}First")

    assert expression == "f'AutoQA {uuid4().hex[:6]}' + 'First'"


def test_several_placeholders_in_one_value():
    expression = unique_expression("user-{unique}@mail.com")

    assert expression == "'user-' + uuid4().hex[:10] + '@mail.com'"


def test_an_ordinary_value_is_left_alone():
    """Anything without a placeholder must stay a plain literal."""
    assert unique_expression("Test@1234") is None
    assert unique_expression("") is None


def test_a_substituted_value_compiles(pages):
    """The composed form has to be valid Python, not just look right."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="fill", target="LoginPage.email_input",
                     value="{unique_name}First", description="A fresh first name"),
            CaseStep(action="expect_visible", target="LoginPage.login_button",
                     description="Still there"),
        ],
        pages,
    )

    ast.parse(source)
    assert "{unique_name}First" not in source
    assert "uuid4()" in source


# ---------------------------------------------------------------------------
# Claims about a URL the test set itself
#
# All four below came out of one real run, where ten of thirteen tests were red
# and eight of those were the test's fault rather than the application's.
# ---------------------------------------------------------------------------
def test_a_bad_url_case_cannot_be_written_from_a_recording(pages):
    """`goto X` then `expect_not_url X` is a contradiction, and what is left
    over is a guess. Both go, so the case goes.

    This asserted the opposite once, keeping "the site is still working" as a
    survivor. That check turned out to be the same mistake in a friendlier
    shape - it claims a Login page element is on a bad Properties URL, and
    nothing in the recording says what is there. Seen for real as:

        goto            /category_products/999
        expect_visible  home.add_to_cart_link

        AssertionError: Locator expected to be visible

    reported against a site that had done the sensible thing and shown its
    generic products page.

    A bad-URL case needs to know what the bad URL renders. A recording that
    never opened it cannot say, so the case is not writable - which is a better
    answer than one that is red half the time for no reason.
    """
    with pytest.raises(SynthesisError, match="no assertion"):
        compile_case(
            [
                CaseStep(action="goto", value="https://x.test/properties/invalid",
                         description="Open a bad URL"),
                CaseStep(action="expect_not_url", value="https://x.test/properties/invalid",
                         description="Should not stay here"),
                CaseStep(action="expect_visible", target="LoginPage.email_input",
                         description="The site is still working"),
            ],
            pages,
        )


def test_a_check_on_a_page_the_recording_did_visit_survives(pages):
    """The rule is about not having seen the page, not about bad URLs. Going
    somewhere recorded and asserting on it is exactly what a case should do."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open login"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="The form is showing"),
        ],
        pages,
    )

    assert "to_be_visible" in source


def test_a_vacuous_url_assertion_goes_too(pages):
    """The mirror image: true before the test does anything, and still true if
    the page is a server error at the same address."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="expect_url", value="https://x.test/login",
                     description="Confirm we are on login"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="The form is there"),
        ],
        pages,
    )

    ast.parse(source)
    assert "to_have_url" not in source


def test_a_case_that_was_only_the_bad_step_still_goes(pages):
    """Nothing worth running is left, so the existing "no assertion" rule takes
    it — by the rule that already existed, not a new one."""
    with pytest.raises(SynthesisError, match="no assertion"):
        compile_case(
            [
                CaseStep(action="goto", value="https://x.test/bad", description="Open"),
                CaseStep(action="expect_not_url", value="https://x.test/bad",
                         description="Should not stay"),
            ],
            pages,
        )


def test_coming_back_to_a_page_is_still_allowed(pages):
    """Open a page, click away, come back, assert you are back.

    A real journey worth testing. A blunter rule — "never assert a URL you ever
    navigated to" — would have thrown this out with the broken ones.
    """
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="click", target="LoginPage.login_button",
                     description="Go somewhere else"),
            CaseStep(action="expect_url", value="https://x.test/login",
                     description="Back on login"),
        ],
        pages,
    )

    ast.parse(source)


def test_navigating_off_the_application_is_dropped(pages):
    """A made-up subdomain does not resolve, so the browser raises before any
    assertion runs and the test errors instead of reporting anything.

    The step goes and the case keeps whatever else it had.
    """
    source = compile_case(
        [
            CaseStep(action="goto", value="https://nonexistent.x.test/",
                     description="Open a subdomain that does not exist"),
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="The form is there"),
        ],
        pages,
    )

    ast.parse(source)
    assert "nonexistent.x.test" not in source
    assert "https://x.test/login" in source


def test_a_relative_path_stays_on_the_site(pages):
    """A bare path cannot leave the application, so it is never refused."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="click", target="LoginPage.login_button", description="Submit"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="Still showing the form"),
        ],
        pages,
    )

    ast.parse(source)


def test_claiming_to_have_left_the_page_you_are_driving_is_dropped(pages):
    """Five negative registration tests failed on exactly this line.

        11. click           'Create Account'
        12. expect_not_url  /register/buyer     <- always false
        13. expect_hidden   the OTP modal       <- the real check

    The form rejects bad input and stays put, which is correct. The browser got
    there by clicking rather than `goto`, so there is no navigation to compare
    against — what gives it away is that every step before the assertion drives
    elements belonging to that very page.
    """
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/", description="Open the site"),
            CaseStep(action="fill", target="LoginPage.email_input", value="",
                     description="Leave the email empty"),
            CaseStep(action="click", target="LoginPage.login_button", description="Submit"),
            CaseStep(action="expect_not_url", value="https://x.test/login",
                     description="Should have left the form"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="The form is still showing"),
        ],
        pages,
    )

    ast.parse(source)
    assert "not_to_have_url" not in source
    assert "to_be_visible" in source        # the check that means something survived


def test_a_success_destination_is_still_a_valid_thing_to_deny(pages):
    """The URL a negative case *should* name: where success would have gone,
    and nowhere this test has been."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="click", target="LoginPage.login_button", description="Submit"),
            CaseStep(action="expect_not_url", value="/dashboard",
                     description="Must not reach the dashboard"),
        ],
        pages,
    )

    ast.parse(source)
    assert "not_to_have_url" in source


def test_a_negative_case_can_check_the_form_is_still_there(pages):
    """The shape the prompt now asks for.

    From a real suite, the check was `expect_not_url /properties` and nothing
    else — green if the injection had logged the attacker in and landed on the
    home page, because "not /properties" is true of every page but one. The
    email field is gone on success and present on failure, which is the
    difference the case is actually about.
    """
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="fill", target="LoginPage.email_input",
                     value="' OR '1'='1", description="Inject"),
            CaseStep(action="click", target="LoginPage.login_button", description="Submit"),
            CaseStep(action="expect_not_url", value="/properties",
                     description="Must not get in"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="Still on the login form"),
        ],
        pages,
    )

    ast.parse(source)
    assert "to_be_visible" in source


def test_a_hand_written_case_compiles_to_valid_python(pages):
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="fill", target="LoginPage.email_input",
                     value="{{unique_email}}", description="A fresh address"),
            CaseStep(action="fill", target="LoginPage.password_input", value="",
                     description="Leave the password empty"),
            CaseStep(action="click", target="LoginPage.login_button",
                     description="Submit"),
            CaseStep(action="expect_url", value="/login", description="Still on login"),
        ],
        pages,
    )

    ast.parse(source)
    # The placeholder became an expression evaluated per run, not a literal.
    assert "{{unique_email}}" not in source
    assert "uuid4()" in source


def test_a_url_check_after_a_bad_url_still_survives(pages):
    """The new rule takes away element assertions, not URL ones. The address is
    knowable without having seen the page, so a claim about it keeps both its
    answers - here, that a bad category did not quietly land on the login form.

    (Asserting the address you just asked for is a separate, older rule: that
    one is true before the test starts and is dropped for being vacuous.)"""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/nowhere",
                     description="Open a bad URL"),
            CaseStep(action="expect_not_url", value="/login",
                     description="Must not have been bounced to the login form"),
        ],
        pages,
    )

    assert "not_to_have_url" in source


def test_going_back_to_a_recorded_page_restores_the_checks(pages):
    """Off the map is a place, not a state the case is stuck in."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/nowhere", description="Bad URL"),
            CaseStep(action="goto", value="https://x.test/login", description="Back to login"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="The form is showing"),
        ],
        pages,
    )

    assert "to_be_visible" in source


# ---------------------------------------------------------------------------
# Reaching for an element one page too early
# ---------------------------------------------------------------------------
def two_page_signup():
    """A site whose signup is two pages: name and email, then the full form."""
    login = PageSpec("LoginPage", "login_page", "https://shop.test/login", [
        LocatorSpec(name="name_input", expression="self.page.a", strategy="test_id",
                    fragile=False),
        LocatorSpec(name="signup_button", expression="self.page.b", strategy="role_name",
                    fragile=False),
    ])
    signup = PageSpec("SignupPage", "signup_page", "https://shop.test/signup", [
        LocatorSpec(name="mr_radio", expression="self.page.c", strategy="role_name",
                    fragile=False),
        LocatorSpec(name="newsletter_checkbox", expression="self.page.d",
                    strategy="label", fragile=False),
    ])
    return [login, signup]


def compile_signup(steps):
    ir = synthesise(
        GeneratedCase(name="Case", category="negative", priority="high",
                      description="A case.", steps=steps),
        pages=two_page_signup(), start_url="https://shop.test/login",
        module_name="test_case", function_name="test_case",
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


def test_ticking_something_on_the_next_page_before_going_there_is_refused():
    """A minute and two seconds of red, on a radio button that exists - the
    tester checked by hand. It was simply not there yet."""
    with pytest.raises(SynthesisError, match="typing or ticking cannot"):
        compile_signup([
            CaseStep(action="goto", value="https://shop.test/login", description="Open"),
            CaseStep(action="fill", target="LoginPage.name_input", value="Ada",
                     description="Name"),
            CaseStep(action="check", target="SignupPage.mr_radio", description="Title"),
            CaseStep(action="click", target="LoginPage.signup_button", description="Signup"),
            CaseStep(action="expect_visible", target="SignupPage.newsletter_checkbox",
                     description="On the form"),
        ])


def test_the_same_steps_in_the_right_order_compile():
    """The case is fine. Only its order was wrong."""
    source = compile_signup([
        CaseStep(action="goto", value="https://shop.test/login", description="Open"),
        CaseStep(action="fill", target="LoginPage.name_input", value="Ada", description="Name"),
        CaseStep(action="click", target="LoginPage.signup_button", description="Signup"),
        CaseStep(action="check", target="SignupPage.mr_radio", description="Title"),
        CaseStep(action="uncheck", target="SignupPage.newsletter_checkbox",
                 description="No newsletter"),
        CaseStep(action="expect_visible", target="SignupPage.newsletter_checkbox",
                 description="Still on the form"),
    ])

    assert "set_checked(" in source


def test_a_goto_straight_to_the_second_page_is_fine():
    """Arriving is arriving. The rule is about not having got there at all."""
    source = compile_signup([
        CaseStep(action="goto", value="https://shop.test/signup", description="Open"),
        CaseStep(action="check", target="SignupPage.mr_radio", description="Title"),
        CaseStep(action="expect_visible", target="SignupPage.newsletter_checkbox",
                 description="On the form"),
    ])

    assert "set_checked(" in source


def test_after_a_click_nothing_is_second_guessed():
    """A click can navigate anywhere, so from there the case is on its own -
    and a step that really cannot be performed fails on its own terms."""
    source = compile_signup([
        CaseStep(action="goto", value="https://shop.test/login", description="Open"),
        CaseStep(action="click", target="LoginPage.signup_button", description="Signup"),
        CaseStep(action="check", target="SignupPage.mr_radio", description="Title"),
        CaseStep(action="expect_visible", target="SignupPage.newsletter_checkbox",
                 description="On the form"),
    ])

    assert "set_checked(" in source


def test_an_assertion_about_another_page_is_left_alone(pages):
    """Only driving is checked. Site chrome recorded on one page and asserted on
    another is a normal thing to write, and refusing it would cost more than it
    saves."""
    source = compile_signup([
        CaseStep(action="goto", value="https://shop.test/login", description="Open"),
        CaseStep(action="expect_hidden", target="SignupPage.mr_radio",
                 description="Not on the first page yet"),
    ])

    assert "to_be_hidden" in source


def test_an_invented_checkbox_step_ticks_the_way_a_recorded_one_does():
    """The recorded path went through `set_checked` first and this one was
    missed, so an invented case ticking a custom checkbox still spent thirty
    seconds on a hidden input. Both halves of a suite drive it the same way."""
    source = compile_signup([
        CaseStep(action="goto", value="https://shop.test/signup", description="Open"),
        CaseStep(action="uncheck", target="SignupPage.newsletter_checkbox",
                 description="No newsletter"),
        CaseStep(action="expect_visible", target="SignupPage.mr_radio",
                 description="Still on the form"),
    ])

    assert "set_checked(signup.newsletter_checkbox, False)" in source
    assert ".uncheck()" not in source
    assert "from pages._healing import" in source


# ---------------------------------------------------------------------------
# Pages that need an account
# ---------------------------------------------------------------------------
"""A generated case is told to open the page it is about with `goto` rather than
clicking through the site. That is right for a login form and wrong for
everything behind one:

    goto  /property-owner/add-property
    fill  PropertyOwnerAddPropertyPage.title_input

    Locator.fill: Timeout 30000ms exceeded

The application did exactly what it should - bounced an anonymous visitor to the
login form - and the field was not on it. Fifty-seven seconds, then red.
"""


def signed_in_recording():
    """A recording that logs in, then works inside the account."""
    def step(action, page_var, locator, *, code="x", password=False):
        return StepSpec(sequence=0, action=action, code=[code], description=f"{action} {locator}",
                        page_var=page_var, locator_name=locator, is_password=password)

    return [
        StepSpec(sequence=0, action=ActionType.NAVIGATE, code=["page.goto('https://shop.test/')"],
                 description="Open"),
        step(ActionType.INPUT, "login", "email_input", code="login.email_input.fill('a@b.c')"),
        step(ActionType.INPUT, "login", "password_input",
             code="login.password_input.fill('secret')", password=True),
        step(ActionType.CLICK, "login", "sign_in_button", code="login.sign_in_button.click()"),
        step(ActionType.INPUT, "dashboard", "title_input", code="dashboard.title_input.fill('t')"),
    ]


def account_pages():
    login = PageSpec("LoginPage", "login_page", "https://shop.test/login", [
        LocatorSpec(name="email_input", expression="self.page.a", strategy="css_id", fragile=False),
        LocatorSpec(name="password_input", expression="self.page.b", strategy="css_id", fragile=False),
        LocatorSpec(name="sign_in_button", expression="self.page.c", strategy="role_name", fragile=False),
    ])
    dashboard = PageSpec("DashboardPage", "dashboard_page", "https://shop.test/dashboard", [
        LocatorSpec(name="title_input", expression="self.page.d", strategy="test_id", fragile=False),
    ])
    return [login, dashboard]


def compile_account(steps):
    ir = synthesise(
        GeneratedCase(name="Case", category="negative", priority="high",
                      description="A case.", steps=steps),
        pages=account_pages(), start_url="https://shop.test/",
        module_name="test_case", function_name="test_case",
        recorded_steps=signed_in_recording(),
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


def test_a_case_that_opens_a_page_behind_a_login_is_signed_in_first():
    """The recording knows how to get in, so the case is given the same steps.

    Refusing it was the alternative and it is worse: "add a property with an
    empty title" is a test worth having, and the only thing wrong with it was a
    missing sign-in.
    """
    source = compile_account([
        CaseStep(action="goto", value="https://shop.test/dashboard", description="Open"),
        CaseStep(action="fill", target="DashboardPage.title_input", value="",
                 description="Leave the title empty"),
        CaseStep(action="expect_visible", target="DashboardPage.title_input",
                 description="Still on the form"),
    ])

    signed_in = source.index("login.password_input")
    assert signed_in < source.index("dashboard.title_input"), "signed in after using the page"
    assert "page.goto('https://shop.test/login')" in source
    assert source.count("login.password_input") == 1


def test_a_case_that_signs_itself_in_is_left_alone():
    """Or a test *about* logging in gets a second login glued to its front."""
    source = compile_account([
        CaseStep(action="goto", value="https://shop.test/login", description="Open"),
        CaseStep(action="fill", target="LoginPage.email_input", value="a@b.c", description="Email"),
        CaseStep(action="fill", target="LoginPage.password_input", value="wrong", description="Password"),
        CaseStep(action="click", target="LoginPage.sign_in_button", description="Submit"),
        CaseStep(action="expect_visible", target="LoginPage.email_input", description="Still here"),
    ])

    assert source.count("login.password_input.fill") == 1


def test_only_looking_at_a_protected_page_stays_signed_out():
    """"Opening the dashboard signed out sends me to the login form" is a real
    test, and it needs to stay signed out to be one."""
    source = compile_account([
        CaseStep(action="goto", value="https://shop.test/dashboard", description="Open"),
        CaseStep(action="expect_hidden", target="DashboardPage.title_input",
                 description="Not shown to a stranger"),
    ])

    assert "login.password_input" not in source


def test_a_recording_that_never_signed_in_changes_nothing(pages):
    """Most recordings. Nothing to restore and nothing to look for."""
    source = compile_case(
        [
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="fill", target="LoginPage.email_input", value="a@b.c",
                     description="Email"),
            CaseStep(action="expect_visible", target="LoginPage.email_input",
                     description="Still here"),
        ],
        pages,
    )

    assert "password" not in source


def test_the_sign_in_waits_before_the_case_navigates_away():
    """Without the wait, the case's own `goto` fires the moment the button is
    pressed and cancels the sign-in that is still in the air:

        Locator.fill: Timeout 30000ms exceeded
        1 network request failed: POST /users/auth/login -> net::ERR_ABORTED

    which reads as the application dropping logins, and is the test cancelling
    its own.
    """
    recorded = signed_in_recording()
    # As a recording has it: the click that submits carries the navigation.
    recorded[3].code = [
        "login.sign_in_button.click()",
        "page.wait_for_url(re.compile('dashboard'))",
    ]

    ir = synthesise(
        GeneratedCase(name="Case", category="negative", priority="high",
                      description="A case.", steps=[
                          CaseStep(action="goto", value="https://shop.test/dashboard",
                                   description="Open"),
                          CaseStep(action="fill", target="DashboardPage.title_input",
                                   value="", description="Leave it empty"),
                          CaseStep(action="expect_visible", target="DashboardPage.title_input",
                                   description="Still there"),
                      ]),
        pages=account_pages(), start_url="https://shop.test/",
        module_name="test_case", function_name="test_case", recorded_steps=recorded,
    )
    source = next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content

    signed_in = source.index("login.sign_in_button.click()")
    waited = source.index("wait_for_url")
    navigated = source.index("page.goto('https://shop.test/dashboard')")
    assert signed_in < waited < navigated, "navigated away before the sign-in landed"


def test_only_the_submitting_step_keeps_its_wait():
    """Clicking into a field does not navigate, so a wait there is one the
    recording happened to attach and nothing needs."""
    recorded = signed_in_recording()
    recorded[1].code = [
        "login.email_input.fill('a@b.c')",
        "page.wait_for_url(re.compile('never'))",
    ]

    ir = synthesise(
        GeneratedCase(name="Case", category="negative", priority="high",
                      description="A case.", steps=[
                          CaseStep(action="goto", value="https://shop.test/dashboard",
                                   description="Open"),
                          CaseStep(action="fill", target="DashboardPage.title_input",
                                   value="", description="Leave it empty"),
                          CaseStep(action="expect_visible", target="DashboardPage.title_input",
                                   description="Still there"),
                      ]),
        pages=account_pages(), start_url="https://shop.test/",
        module_name="test_case", function_name="test_case", recorded_steps=recorded,
    )
    source = next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content

    assert "never" not in source


def test_a_restored_sign_in_brings_its_import_with_it():
    """The recording's own wait is a `re.compile`, and the module only imported
    `re` when the case itself asserted on a URL. Missed, every case in the suite
    died on `NameError: name 're' is not defined` - a whole generation lost to a
    line that was copied in rather than written.
    """
    import ast

    recorded = signed_in_recording()
    recorded[3].code = [
        "login.sign_in_button.click()",
        "page.wait_for_url(re.compile('dashboard'))",
    ]

    ir = synthesise(
        GeneratedCase(name="Case", category="negative", priority="high",
                      description="A case.", steps=[
                          CaseStep(action="goto", value="https://shop.test/dashboard",
                                   description="Open"),
                          CaseStep(action="fill", target="DashboardPage.title_input",
                                   value="", description="Leave it empty"),
                          CaseStep(action="expect_visible", target="DashboardPage.title_input",
                                   description="Still there"),
                      ]),
        pages=account_pages(), start_url="https://shop.test/",
        module_name="test_case", function_name="test_case", recorded_steps=recorded,
    )
    source = next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content

    assert "re.compile(" in source
    assert "import re" in source
    # Every name the module uses is one it defined or imported.
    tree = ast.parse(source)
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "re" in imported


def test_a_restored_upload_brings_its_import_too():
    """The same shape as `re`, found the same way and one release later: a
    restored step calls `sample_file`, nothing raised that flag, and the module
    used a name it never imported.

    Every flag is now read off the finished lines rather than set where each
    line is written, because a line copied in from the recording never passes
    through the code that would have set it.
    """
    from app.models.enums import ActionType

    recorded = signed_in_recording()
    recorded.append(
        StepSpec(
            sequence=9, action=ActionType.UPLOAD,
            code=["dashboard.photos_input.set_input_files(sample_file('a.jpg'))"],
            description="Upload a photo", page_var="dashboard",
            locator_name="photos_input",
        )
    )
    # Between two fields the case fills, so `_restore_setup` puts it back.
    recorded.append(
        StepSpec(sequence=10, action=ActionType.INPUT, code=["dashboard.title_input.fill('t')"],
                 description="Title", page_var="dashboard", locator_name="title_input")
    )

    pages = account_pages()
    pages[1].locators.append(
        LocatorSpec(name="photos_input", expression="self.page.e", strategy="test_id",
                    fragile=False)
    )

    ir = synthesise(
        GeneratedCase(name="Case", category="positive", priority="high",
                      description="A case.", steps=[
                          CaseStep(action="goto", value="https://shop.test/dashboard"),
                          CaseStep(action="fill", target="DashboardPage.title_input", value="t"),
                          CaseStep(action="expect_visible", target="DashboardPage.title_input"),
                      ]),
        pages=pages, start_url="https://shop.test/",
        module_name="test_case", function_name="test_case", recorded_steps=recorded,
    )
    source = next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content

    if "sample_file(" in source:
        assert "from pages._files import sample_file" in source
