"""Checks added to a recorded test, which by default has none.

A recording captures what somebody did, not what should have been true
afterwards. From a real suite — twenty-eight steps against a shop: sign in, add
a backpack to the cart, open the menu, sign out — and not one assertion. It
passes as long as every click found something to click, so it would still be
green if the backpack were added to a cart that stays empty.

That test is the baseline every other case is written around, which makes it the
worst one to have no opinion.
"""

import ast

import pytest

from app.codegen.converter import LocatorSpec, PageSpec, StepSpec, TestIR
from app.codegen.generator import render
from app.models.enums import ActionType
from app.services.checks import Check, apply, page_at, parse


def ir_with(*step_descriptions: str) -> TestIR:
    page = PageSpec(class_name="LoginPage", module="login_page", url="https://x.test/")
    for name in ("email_input", "login_button", "welcome_banner", "cart_badge"):
        page.locators.append(
            LocatorSpec(
                name=name,
                expression=f"self.page.get_by_test_id('{name}')",
                strategy="test_id",
                fragile=False,
                candidates=[("test_id", f"self.page.get_by_test_id('{name}')")],
            )
        )

    return TestIR(
        suite_name="Recorded",
        function_name="test_recorded",
        module_name="test_recorded",
        start_url="https://x.test/",
        pages=[page],
        steps=[
            StepSpec(
                sequence=index,
                action=ActionType.CLICK,
                code=[f"login.login_button.click()  # {text}"],
                description=text,
                page_var="login",
                locator_name="login_button",
            )
            for index, text in enumerate(step_descriptions)
        ],
    )


def code_for(ir: TestIR) -> str:
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


# ---------------------------------------------------------------------------
# Putting a check where it belongs
# ---------------------------------------------------------------------------
def test_a_check_lands_after_the_step_it_is_about():
    ir = apply(
        ir_with("Open", "Sign in", "Sign out"),
        [Check(after=1, target="login.welcome_banner", kind="visible")],
    )

    assert [s.description for s in ir.steps] == [
        "Open",
        "Sign in",
        "Check welcome banner is visible",
        "Sign out",
    ]


def test_several_checks_all_land_where_they_belong():
    """Inserting one must not shift the position of one not yet placed."""
    ir = apply(
        ir_with("Open", "Sign in", "Add to cart", "Sign out"),
        [
            Check(after=1, target="login.welcome_banner", kind="visible"),
            Check(after=2, target="login.cart_badge", kind="text", expected="1"),
        ],
    )

    assert [s.description for s in ir.steps] == [
        "Open",
        "Sign in",
        "Check welcome banner is visible",
        "Add to cart",
        "Check cart badge shows '1'",
        "Sign out",
    ]


def test_steps_are_renumbered_after_inserting():
    """Gaps in the numbering would show up in every comment in the file."""
    ir = apply(
        ir_with("Open", "Sign in"),
        [Check(after=0, target="login.email_input", kind="visible")],
    )

    assert [s.sequence for s in ir.steps] == [0, 1, 2]


def test_a_check_after_a_step_that_no_longer_exists_goes_last():
    """Better at the end than silently first, where it would assert about a
    page the test has not reached."""
    ir = apply(
        ir_with("Open", "Sign in"),
        [Check(after=99, target="login.welcome_banner", kind="visible")],
    )

    assert ir.steps[-1].description == "Check welcome banner is visible"


# ---------------------------------------------------------------------------
# What it refuses to emit
# ---------------------------------------------------------------------------
def test_a_check_on_an_element_that_does_not_exist_is_dropped():
    """Recordings get replaced and elements get renamed. A check compiling to a
    locator nobody defines is an ImportError that takes the whole run down."""
    ir = apply(
        ir_with("Open", "Sign in"),
        [Check(after=1, target="login.long_gone", kind="visible")],
    )

    assert len(ir.steps) == 2
    assert "long_gone" not in code_for(ir)


def test_a_check_on_a_page_that_does_not_exist_is_dropped():
    ir = apply(
        ir_with("Open"),
        [Check(after=0, target="nosuchpage.nosuchthing", kind="visible")],
    )

    assert len(ir.steps) == 1


@pytest.mark.parametrize(
    "raw",
    [
        {"after": 1, "target": "no-dot", "kind": "visible"},
        {"after": 1, "target": "login.email_input", "kind": "invented"},
        {"after": "not a number", "target": "login.email_input", "kind": "visible"},
        "not a dict",
        None,
    ],
)
def test_a_malformed_stored_check_is_ignored_rather_than_fatal(raw):
    """These are re-applied on every rebuild — one bad row from an older shape
    must not stop a suite regenerating."""
    assert parse([raw]) == []


def test_good_checks_survive_a_bad_one_beside_them():
    found = parse(
        [
            {"after": 1, "target": "login.email_input", "kind": "visible"},
            {"after": 2, "target": "broken", "kind": "visible"},
        ]
    )

    assert len(found) == 1
    assert found[0].target == "login.email_input"


# ---------------------------------------------------------------------------
# What it compiles to
# ---------------------------------------------------------------------------
def test_the_generated_test_is_valid_python():
    ir = apply(
        ir_with("Open", "Sign in"),
        [
            Check(after=1, target="login.welcome_banner", kind="visible"),
            Check(after=1, target="login.cart_badge", kind="text", expected="1 item"),
        ],
    )

    ast.parse(code_for(ir))


def test_a_check_does_not_heal():
    """An observation asks about *this* element. A recorded spare would answer
    about whichever one sits where it used to."""
    ir = apply(
        ir_with("Open"),
        [Check(after=0, target="login.welcome_banner", kind="visible")],
    )
    code = code_for(ir)

    assert "expect(unhealed(login, 'welcome_banner')).to_be_visible()" in code
    assert "expect(login.welcome_banner)" not in code


def test_a_text_check_compiles_to_a_text_assertion():
    ir = apply(
        ir_with("Open"),
        [Check(after=0, target="login.cart_badge", kind="text", expected="1")],
    )

    assert "to_contain_text('1')" in code_for(ir)


def test_a_text_check_with_nothing_to_look_for_falls_back_to_visible():
    """Better than asserting the element contains an empty string, which is
    true of everything."""
    ir = apply(
        ir_with("Open"),
        [Check(after=0, target="login.cart_badge", kind="text", expected="")],
    )

    assert "to_be_visible()" in code_for(ir)


def test_a_recording_with_no_checks_is_left_exactly_as_it_was():
    before = ir_with("Open", "Sign in")
    after = apply(ir_with("Open", "Sign in"), [])

    assert [s.description for s in after.steps] == [s.description for s in before.steps]


# ---------------------------------------------------------------------------
# The element has to be on the page the test is on
#
# This one got through and failed on a real run. The check compiled, because the
# element does exist on a page object — but the browser had not reached that
# page yet, so it failed every time:
#
#     4. Click "Create an Account!"      -> lands on the choose-account page
#     5. Check "First Name" is visible   <- the field is one click further on
#
# The element existing and the element being on screen are different questions.
# ---------------------------------------------------------------------------
def journey() -> TestIR:
    """Four pages, reached in order, the way the real recording walks them.

    Four and not three, because the failure needed a check pointing *two* pages
    ahead: "Create an Account!" lands on the choose-account page, and the
    first-name field is on the buyer form one click after that.
    """
    pages, steps = [], []
    for index, (cls, module, var, element) in enumerate(
        [
            ("HomePage", "home_page", "home", "login_link"),
            ("LoginPage", "login_page", "login", "create_account_link"),
            ("RegisterPage", "register_page", "register", "buyer_button"),
            ("RegisterBuyerPage", "register_buyer_page", "register_buyer", "first_name_input"),
        ]
    ):
        page = PageSpec(class_name=cls, module=module, url=f"https://x.test/{module}")
        page.locators.append(
            LocatorSpec(
                name=element,
                expression=f"self.page.get_by_test_id('{element}')",
                strategy="test_id",
                fragile=False,
                candidates=[("test_id", f"self.page.get_by_test_id('{element}')")],
            )
        )
        pages.append(page)
        steps.append(
            StepSpec(
                sequence=index,
                action=ActionType.CLICK,
                code=[f"{var}.{element}.click()"],
                description=f"Click {element}",
                page_var=var,
                locator_name=element,
            )
        )

    return TestIR(
        suite_name="Journey", function_name="test_journey", module_name="test_journey",
        start_url="https://x.test/", pages=pages, steps=steps,
    )


def test_a_check_one_page_early_is_dropped():
    """The exact failure from the real run.

    After step 1 the test is on the choose-account page. The first-name field
    is on the buyer form, one click further on — so this compiled and failed
    every time.
    """
    ir = apply(
        journey(),
        [Check(after=1, target="register_buyer.first_name_input", kind="visible")],
    )

    assert not [s for s in ir.steps if s.action is ActionType.ASSERT]


def test_a_check_on_the_page_the_test_reached_is_kept():
    """The one beside it is right, and must survive its neighbour being wrong."""
    ir = apply(
        journey(),
        [
            Check(after=1, target="register_buyer.first_name_input", kind="visible"),
            Check(after=1, target="register.buyer_button", kind="visible"),
        ],
    )
    kept = [s for s in ir.steps if s.action is ActionType.ASSERT]

    assert [s.locator_name for s in kept] == ["buyer_button"]


def test_the_page_after_a_step_is_where_the_next_step_goes():
    """Not the previous one: the step that got you there named an element on
    the page you have just left."""
    steps = journey().steps

    assert page_at(steps, 0) == "login"
    assert page_at(steps, 1) == "register"
    assert page_at(steps, 2) == "register_buyer"


def test_a_check_after_the_last_step_uses_the_page_it_ended_on():
    steps = journey().steps

    assert page_at(steps, 99) == "register_buyer"


def test_a_check_on_the_final_page_still_lands():
    """The commonest useful check of all — "the thing you submitted worked"."""
    ir = apply(
        journey(),
        [Check(after=3, target="register_buyer.first_name_input", kind="visible")],
    )

    assert ir.steps[-1].action is ActionType.ASSERT
