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


def generate(selectors) -> dict[str, str]:
    ir = build_ir(recording(selectors), suite_name="Login", start_url="https://x.test/login")
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
