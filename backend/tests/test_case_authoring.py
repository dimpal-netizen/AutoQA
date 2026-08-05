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
from app.codegen.converter import LocatorSpec, PageSpec
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
def test_the_contradictory_step_goes_and_the_case_stays(pages):
    """`goto X` then `expect_not_url X` is a contradiction.

    The application rendered "Agent not found." at that address, which is
    correct, and the test called it a failure on every run. The impossible step
    is removed; the rest of the case is fine and is kept.
    """
    source = compile_case(
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

    ast.parse(source)
    assert "not_to_have_url" not in source
    assert "to_be_visible" in source          # the real check survived


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
