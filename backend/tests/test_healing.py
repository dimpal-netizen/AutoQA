"""Finding an element when the first way of finding it has stopped working.

Every element is recorded several ways over. Until now only the best one was
used and the rest were a comment, so a renamed class broke a test that had
three working alternatives written directly above it.

The generation half of this needs no browser. The one test that proves healing
actually heals drives a real page, and is marked integration.
"""

import re
import textwrap
from pathlib import Path

import pytest

from app.codegen.converter import build_ir
from app.codegen.generator import render

BUTTON_WAYS = [
    {"strategy": "role_name", "value": "button|Login", "unique": True, "score": 95},
    {"strategy": "text", "value": "Login", "unique": True, "score": 70},
    {"strategy": "css", "value": "form.login button", "unique": True, "score": 40},
    {"strategy": "xpath", "value": "//body/form[1]/button[1]", "unique": True, "score": 20},
]


def recording(selectors):
    return [
        {
            "action_type": "click",
            "url": "https://x.test/login",
            "frame_path": [],
            "selectors": selectors,
            "element": {"tag": "button", "input_type": None, "role": "button",
                        "accessible_name": "Login", "text": "Login", "attributes": {}},
            "payload": {},
            "is_ignored": False,
        }
    ]


def generate(selectors, recording=None) -> dict[str, str]:
    actions = recording if recording is not None else globals()["recording"](selectors)
    ir = build_ir(actions, suite_name="Login", start_url="https://x.test/login")
    return {f.path: f.content for f in render(ir, browser_info={})}


# ---------------------------------------------------------------------------
# The spares become code, not a comment
# ---------------------------------------------------------------------------
def test_every_recorded_way_reaches_the_page_object():
    """They were already stored — as prose nothing could execute."""
    page_object = generate(BUTTON_WAYS)["pages/login_page.py"]

    assert "get_by_role('button', name='Login', exact=True)" in page_object
    assert "get_by_text('Login', exact=True)" in page_object
    assert "locator('form.login button')" in page_object
    assert "xpath=//body/form[1]/button[1]" in page_object


def test_the_best_way_is_still_tried_first():
    page_object = generate(BUTTON_WAYS)["pages/login_page.py"]
    order = re.findall(r"\('(\w+)', lambda:", page_object)

    assert order[0] == "role_name"
    assert order == sorted(order, key=lambda s: order.index(s))  # order preserved


def test_an_element_with_one_way_stays_a_plain_locator():
    """Nothing to fall back to, so nothing to pay for."""
    only = [{"strategy": "test_id", "value": "login-btn", "unique": True, "score": 100}]
    page_object = generate(only)["pages/login_page.py"]

    assert "heal(" not in page_object
    assert "return self.page.get_by_test_id('login-btn')" in page_object


def test_the_helper_is_only_shipped_when_something_can_heal():
    only = [{"strategy": "test_id", "value": "login-btn", "unique": True, "score": 100}]

    assert "pages/_healing.py" not in generate(only)
    assert "pages/_healing.py" in generate(BUTTON_WAYS)


def test_a_page_object_never_imports_a_helper_that_was_not_shipped():
    """The import and the file are decided by the same question."""
    only = [{"strategy": "test_id", "value": "login-btn", "unique": True, "score": 100}]
    files = generate(only)

    assert "from pages._healing import heal" not in files["pages/login_page.py"]


def test_the_candidates_are_lambdas_so_only_the_first_is_evaluated():
    """Without this every alternative would be looked up on every use."""
    page_object = generate(BUTTON_WAYS)["pages/login_page.py"]
    assert page_object.count("lambda:") == len(BUTTON_WAYS)


def test_everything_generated_is_valid_python():
    import ast

    for path, content in generate(BUTTON_WAYS).items():
        if path.endswith(".py"):
            ast.parse(content)


# ---------------------------------------------------------------------------
# It heals actions, never assertions
#
# A generated negative test read:
#
#     click           'Create Account'
#     expect_visible  'Create Account'      <- still on the form
#     expect_hidden   the OTP modal         <- so registration was rejected
#
# and was red on every run. The modal's recorded selector carries `isOpen` in
# its class, so with the modal closed it matched nothing — the answer the test
# wanted. Healing then reached the positional spare, matched an unrelated svg at
# that path, and `to_be_hidden()` failed on an element that was never the modal.
# Six generated tests reported a bug in a form that was behaving correctly.
# ---------------------------------------------------------------------------
def assertion_recording(kind: str, selectors: list) -> list:
    """A click, then an assertion about the same element."""
    return recording(selectors) + [
        {
            "action_type": "assert",
            "url": "https://x.test/login",
            "frame_path": [],
            "selectors": selectors,
            "element": {"tag": "button", "input_type": None, "role": "button",
                        "accessible_name": "Login", "text": "Login", "attributes": {}},
            "payload": {"kind": kind},
            "is_ignored": False,
        }
    ]


def test_an_assertion_is_looked_up_without_healing():
    ir = build_ir(
        assertion_recording("to_be_visible", BUTTON_WAYS),
        suite_name="Login",
        start_url="https://x.test/login",
    )
    test_module = {f.path: f.content for f in render(ir, browser_info={})}[ir.file_path]

    assert "expect(unhealed(login, 'login_button')).to_be_visible()" in test_module
    assert "expect(login.login_button)" not in test_module


def test_the_action_beside_it_still_heals():
    """Only the observation opts out. The click is still allowed a spare."""
    ir = build_ir(
        assertion_recording("to_be_visible", BUTTON_WAYS),
        suite_name="Login",
        start_url="https://x.test/login",
    )
    test_module = {f.path: f.content for f in render(ir, browser_info={})}[ir.file_path]

    assert "login.login_button.click()" in test_module


def test_a_module_that_asserts_imports_the_helper_and_gets_it():
    files = {
        f.path: f.content
        for f in render(
            build_ir(
                assertion_recording("to_be_visible", BUTTON_WAYS),
                suite_name="Login",
                start_url="https://x.test/login",
            ),
            browser_info={},
        )
    }

    assert "from pages._healing import unhealed" in files["tests/test_login.py"]
    assert "def unhealed(" in files["pages/_healing.py"]


def test_the_helper_ships_even_when_no_element_can_heal():
    """`unhealed` lives in the same file, and a single-candidate suite uses it."""
    only = [{"strategy": "test_id", "value": "login-btn", "unique": True, "score": 100}]
    files = {
        f.path: f.content
        for f in render(
            build_ir(
                assertion_recording("to_be_visible", only),
                suite_name="Login",
                start_url="https://x.test/login",
            ),
            browser_info={},
        )
    }

    assert "heal(" not in files["pages/login_page.py"]  # nothing to heal
    assert "pages/_healing.py" in files  # but unhealed is still imported


def test_a_module_with_no_assertion_does_not_import_the_helper():
    files = {
        f.path: f.content
        for f in render(
            build_ir(recording(BUTTON_WAYS), suite_name="Login",
                     start_url="https://x.test/login"),
            browser_info={},
        )
    }

    assert "unhealed" not in files["tests/test_login.py"]


# ---------------------------------------------------------------------------
# It actually heals — real browser, real page
# ---------------------------------------------------------------------------
PAGE = """
<!doctype html>
<html><body>
  <form class="login">
    <!-- No accessible name of "Login": the first recorded way cannot match. -->
    <button id="submit">Sign in</button>
  </form>
</body></html>
"""


@pytest.mark.integration
def test_it_falls_through_to_a_working_way_and_says_so(tmp_path: Path):
    """The developer renamed the button. Every other way still works.

    Before this change the test stopped here. Now it finds the button by the
    path through the form, clicks it, and warns that the page has changed.
    """
    from playwright.sync_api import sync_playwright

    helper = generate(BUTTON_WAYS)["pages/_healing.py"]
    module = tmp_path / "_healing.py"
    module.write_text(helper, encoding="utf-8")

    import importlib.util

    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    page_file = tmp_path / "page.html"
    page_file.write_text(textwrap.dedent(PAGE), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())

        # Exactly what the generated page object passes in.
        candidates = [
            ("role_name", lambda: page.get_by_role("button", name="Login", exact=True)),
            ("text", lambda: page.get_by_text("Login", exact=True)),
            ("css", lambda: page.locator("form.login button")),
        ]

        with pytest.warns(healing.Healed, match="used css instead"):
            located = healing.heal("login_button", candidates)

        assert located.inner_text() == "Sign in"
        located.click()  # and it is usable, not just found

        browser.close()


@pytest.mark.integration
def test_a_locator_that_now_matches_twice_drives_the_first(tmp_path: Path):
    """From a real replay of a recorded journey, red on a working page:

        Locator.click: Error: strict mode violation:
        get_by_role("link", name="Home", exact=True) resolved to 2 elements

    The recorder saw one match and said so, so the generator did not add
    `.first`. Pages gain elements — a footer nav, a breadcrumb — and a selector
    that was unique on the day is not any more. Playwright then refuses to guess
    and the whole recorded test errors out.
    """
    import importlib.util

    from playwright.sync_api import sync_playwright

    module = tmp_path / "_healing.py"
    module.write_text(generate(BUTTON_WAYS)["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    # The page has grown a second "Home" link since it was recorded.
    page_file = tmp_path / "page.html"
    page_file.write_text(
        "<!doctype html><html><body>"
        '<nav><a href="/">Home</a></nav>'
        '<footer><a href="/">Home</a></footer>'
        "</body></html>",
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())

        candidates = [
            ("role_name", lambda: page.get_by_role("link", name="Home", exact=True)),
        ]

        with pytest.warns(healing.Healed, match="more than one element"):
            located = healing.heal("home_link", candidates)

        # Usable rather than an error — which is the whole point.
        located.click()
        browser.close()


@pytest.mark.integration
def test_no_warning_when_the_first_way_still_works(tmp_path: Path):
    """Healing must be silent when nothing has changed, or the noise makes the
    warning that matters unreadable."""
    import importlib.util
    import warnings

    from playwright.sync_api import sync_playwright

    module = tmp_path / "_healing.py"
    module.write_text(generate(BUTTON_WAYS)["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    page_file = tmp_path / "page.html"
    page_file.write_text(
        '<!doctype html><html><body><form class="login">'
        '<button id="submit">Login</button></form></body></html>',
        encoding="utf-8",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())

        candidates = [
            ("role_name", lambda: page.get_by_role("button", name="Login", exact=True)),
            ("text", lambda: page.get_by_text("Login", exact=True)),
        ]

        with warnings.catch_warnings():
            warnings.simplefilter("error", healing.Healed)  # any warning fails
            located = healing.heal("login_button", candidates)

        assert located.inner_text() == "Login"
        browser.close()


# The registration page with no OTP modal on it. `div.OtpModal__isOpen svg`
# correctly matches nothing; the positional spare matches the dismiss icon, an
# element that has nothing to do with the modal.
NO_MODAL = """
<!doctype html>
<html><body>
  <main>
    <button id="dismiss"><svg width="8" height="8"></svg></button>
    <form><button>Create Account</button></form>
  </main>
</body></html>
"""

# The recorded spare, as `nth_child`. The suite's XPath spare for this element
# read `//body/main[1]/.../svg[1]` and could never have matched: an <svg> is in
# the SVG namespace, and a bare name test in XPath only matches the null one.
# CSS has no such rule, so this is the candidate that did the damage.
MODAL_SPARE = "body > main > button:nth-child(1) > svg:nth-child(1)"


@pytest.mark.integration
def test_an_absent_element_stays_absent_instead_of_healing_to_another(tmp_path: Path):
    """The failure in the report, reproduced and then fixed.

    Without `unhealed` this is `AssertionError: Locator expected to be hidden`
    against a form that had rejected the duplicate email exactly as it should.
    """
    import importlib.util

    from playwright.sync_api import sync_playwright

    module = tmp_path / "_healing.py"
    module.write_text(generate(BUTTON_WAYS)["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)
    healing.PRIMARY_TIMEOUT_MS = 300  # heal() is expected to find nothing

    page_file = tmp_path / "page.html"
    page_file.write_text(textwrap.dedent(NO_MODAL), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())

        class RegisterBuyerPage:
            """Exactly what the generated page object emits for this element."""

            @property
            def otp_modal(self):
                return healing.heal("otp_modal", [
                    ("css", lambda: page.locator("div.OtpModal__isOpen svg")),
                    ("nth_child", lambda: page.locator(MODAL_SPARE)),
                ])

        register_buyer = RegisterBuyerPage()

        # What used to happen: the spare matched the header icon, which is on
        # screen, so the assertion the test cared about could only ever fail.
        with pytest.warns(healing.Healed):
            assert register_buyer.otp_modal.is_visible()

        # What happens now.
        from playwright.sync_api import expect

        expect(healing.unhealed(register_buyer, "otp_modal")).to_be_hidden()

        # And the next lookup heals again — the opt-out lasts one call.
        with pytest.warns(healing.Healed):
            register_buyer.otp_modal.is_visible()

        browser.close()


@pytest.mark.integration
def test_a_vanished_element_fails_a_visibility_check_rather_than_healing(tmp_path: Path):
    """The quiet half. A spare would report the wrong element as present."""
    import importlib.util

    from playwright.sync_api import expect, sync_playwright

    module = tmp_path / "_healing.py"
    module.write_text(generate(BUTTON_WAYS)["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)
    healing.PRIMARY_TIMEOUT_MS = 300

    page_file = tmp_path / "page.html"
    page_file.write_text(textwrap.dedent(PAGE), encoding="utf-8")  # button renamed

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())

        class LoginPage:
            @property
            def login_button(self):
                return healing.heal("login_button", [
                    ("role_name", lambda: page.get_by_role("button", name="Login", exact=True)),
                    ("css", lambda: page.locator("form.login button")),
                ])

        login = LoginPage()

        with pytest.raises(AssertionError):
            expect(healing.unhealed(login, "login_button")).to_be_visible(timeout=300)

        browser.close()


@pytest.mark.integration
def test_when_nothing_matches_the_error_names_the_selector_you_expect(tmp_path: Path):
    """Returning the primary means the failure reads as it always did, rather
    than blaming whichever spare happened to be tried last."""
    import importlib.util

    from playwright.sync_api import sync_playwright

    module = tmp_path / "_healing.py"
    module.write_text(generate(BUTTON_WAYS)["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    page_file = tmp_path / "page.html"
    page_file.write_text("<!doctype html><html><body></body></html>", encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())

        healing.PRIMARY_TIMEOUT_MS = 300  # nothing is coming; do not wait 10s
        healing.SPARE_TIMEOUT_MS = 100

        candidates = [
            ("role_name", lambda: page.get_by_role("button", name="Login", exact=True)),
            ("text", lambda: page.get_by_text("Login", exact=True)),
        ]
        located = healing.heal("login_button", candidates)

        assert "Login" in str(located)  # the primary, not the last spare
        browser.close()


# ---------------------------------------------------------------------------
# A substitute has to be the same kind of thing
# ---------------------------------------------------------------------------
LOGIN_WAYS = [
    {"strategy": "role_name", "value": "button|Login", "unique": True, "score": 95},
    {"strategy": "text", "value": "Login", "unique": False, "score": 78},
    {"strategy": "css", "value": "form fieldset button", "unique": True, "score": 40},
]

#: A header link and a submit button, both called Login. `get_by_text("Login")`
#: finds the link first, because it comes first in the markup.
LOGIN_PAGE = textwrap.dedent("""
    <!doctype html><html><body>
      <header><a href="/login" id="header-link">Login</a></header>
      <main><form><fieldset>
        <button type="button" id="submit">Login</button>
      </fieldset></form></main>
    </body></html>
""")


def button_recording(selectors, tag="button"):
    return [
        {
            "action_type": "click",
            "url": "https://x.test/login",
            "frame_path": [],
            "selectors": selectors,
            "element": {"tag": tag, "input_type": None, "role": tag,
                        "accessible_name": "Login", "text": "Login", "attributes": {}},
            "payload": {},
            "is_ignored": False,
        }
    ]


def test_the_recorded_tag_reaches_the_page_object() -> None:
    """Without it there is nothing to compare a spare against."""
    files = generate(LOGIN_WAYS, recording=button_recording(LOGIN_WAYS))
    page = next(v for k, v in files.items() if k.startswith("pages/") and "_healing" not in k)

    assert "tag='button'" in page


@pytest.mark.integration
def test_a_spare_that_finds_a_link_is_refused_for_a_recorded_button(tmp_path) -> None:
    """The failure this exists to stop, end to end.

    The site header has a Login link and the form has a Login button. When the
    form was slow enough that the primary had not attached in time, healing took
    the text spare, clicked the header link, and went back to the login page.
    The test then waited thirty seconds for a dashboard, and the run reported an
    application bug against a login that works.
    """
    import importlib.util

    from playwright.sync_api import sync_playwright

    files = generate(LOGIN_WAYS, recording=button_recording(LOGIN_WAYS))
    module = tmp_path / "_healing.py"
    module.write_text(files["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    page_file = tmp_path / "login.html"
    page_file.write_text(LOGIN_PAGE, encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())
        healing.PRIMARY_TIMEOUT_MS = 200   # stand in for a form that is slow
        healing.SPARE_TIMEOUT_MS = 200

        # The spare really does find the wrong thing - that is the premise.
        assert page.get_by_text("Login", exact=True).count() == 2
        assert page.get_by_text("Login", exact=True).first.evaluate(
            "e => e.tagName"
        ) == "A"

        located = healing.heal(
            "login_button",
            [
                ("role_name", lambda: page.get_by_role("button", name="Nothing")),
                ("text", lambda: page.get_by_text("Login", exact=True).first),
                ("css", lambda: page.locator("form fieldset button")),
            ],
            tag="button",
        )

        assert located.first.evaluate("e => e.id") == "submit", (
            "healed onto the header link instead of the submit button"
        )
        browser.close()


@pytest.mark.integration
def test_a_spare_of_the_right_kind_is_still_used(tmp_path) -> None:
    """The rule must not switch healing off. A renamed button found another way
    is exactly what healing is for."""
    import importlib.util

    from playwright.sync_api import sync_playwright

    files = generate(LOGIN_WAYS, recording=button_recording(LOGIN_WAYS))
    module = tmp_path / "_healing.py"
    module.write_text(files["pages/_healing.py"], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    page_file = tmp_path / "login.html"
    page_file.write_text(LOGIN_PAGE, encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())
        healing.PRIMARY_TIMEOUT_MS = 200
        healing.SPARE_TIMEOUT_MS = 200

        with pytest.warns(healing.Healed):
            located = healing.heal(
                "login_button",
                [
                    ("role_name", lambda: page.get_by_role("button", name="Gone")),
                    ("css", lambda: page.locator("form fieldset button")),
                ],
                tag="button",
            )

        assert located.first.evaluate("e => e.id") == "submit"
        browser.close()
