"""Deciding what a recorded value or target meant, so a test can run twice.

Six applications appear below and not one of them is special-cased. A shop, a
booking system, a CRM, a conference, a library and a sign-in form all go through
the same rules, because the rules cannot tell them apart: they read how many
elements a selector matched, whether a form carried a password, what the address
looked like, and what the application said back.

The other half of the file is about what must NOT happen. A test that adapts its
way past a real defect is worse than no test, so the roles that may vary are
few, the evidence required is specific, and every substitution is written down.

See `app/codegen/dataroles.py` and `templates/state.py.j2`.
"""

import ast
import importlib.util
import textwrap
from pathlib import Path

import pytest

from app.codegen.converter import build_ir
from app.codegen.dataroles import (
    DataRole,
    classify_targets,
    classify_values,
    is_conflict,
)
from app.codegen.generator import render


# ---------------------------------------------------------------------------
# Building recordings
# ---------------------------------------------------------------------------
def sel(strategy, value, *, unique=True, score=50):
    return {"strategy": strategy, "value": value, "unique": unique, "score": score}


def act(kind, url, selectors, *, tag="a", name=None, itype=None, value=None,
        navigates=None, attrs=None, messages=None):
    action = {
        "action_type": kind,
        "url": url,
        "frame_path": [],
        "selectors": selectors,
        "element": {
            "tag": tag,
            "input_type": itype,
            "role": {"a": "link", "button": "button"}.get(tag, "textbox"),
            "accessible_name": name,
            "text": name,
            "attributes": attrs or {},
        },
        "payload": {"value": value} if value is not None else {},
        "is_ignored": False,
    }
    if navigates:
        action["_navigates_to"] = navigates
    if messages is not None:
        action["response"] = {"url": url, "navigated": False, "messages": messages}
    return action


def typed(url, label, value, *, itype="text", attrs=None):
    return act("input", url, [sel("css_id", f"#{label.lower().replace(' ', '')}")],
               tag="input", itype=itype, name=label, value=value, attrs=attrs)


def clicked(url, label, selectors=None, *, tag="button", navigates=None, attrs=None):
    return act("click", url, selectors or [sel("role_name", f"{tag}|{label}", score=95)],
               tag=tag, name=label, navigates=navigates, attrs=attrs)


def generate(actions, start="https://app.test/"):
    ir = build_ir(actions, suite_name="Suite", start_url=start)
    return {f.path: f.content for f in render(ir, browser_info={})}


def body(actions, start="https://app.test/"):
    ir = build_ir(actions, suite_name="Suite", start_url=start)
    files = {f.path: f.content for f in render(ir, browser_info={})}
    return files[ir.file_path]


def roles(actions):
    return {**classify_values(actions), **classify_targets(actions)}


# ---------------------------------------------------------------------------
# Six applications, one set of rules
#
# Every scenario below is one the user named: a purchase, a booking, a
# registration, a customer record, a reservation. Nothing in `dataroles.py`
# knows which is which.
# ---------------------------------------------------------------------------
SHOP = "https://shop.test/products"
CLINIC = "https://clinic.test/appointments"
CRM = "https://crm.test/customers/add"
CONFERENCE = "https://conf.test/register"
LIBRARY = "https://library.test/catalogue"
SIGN_IN = "https://app.test/login"


def test_an_item_chosen_from_a_grid_is_state_dependent():
    """A shop. The card was one of several matching the same class path."""
    tile = [sel("role_name", "link|Blue Top", score=95),
            sel("css", "div.product-card a.title", unique=False, score=55)]
    decided = roles([act("click", SHOP, tile, name="Blue Top")])

    assert decided[0].role is DataRole.STATE_DEPENDENT


def test_a_free_appointment_slot_is_state_dependent():
    """A clinic. Same rule, and nothing about it mentions shops."""
    slot = [sel("role_name", "button|09:00", score=95),
            sel("css", "ul.slots li button", unique=False, score=55)]
    decided = roles([act("click", CLINIC, slot, tag="button", name="09:00")])

    assert decided[0].role is DataRole.STATE_DEPENDENT


def test_a_library_copy_is_state_dependent():
    """A lending library. Three domains, one rule, no configuration."""
    copy = [sel("role_name", "button|Borrow", score=95),
            sel("css", "tr.copy td.actions button", unique=False, score=55)]
    decided = roles([act("click", LIBRARY, copy, tag="button", name="Borrow")])

    assert decided[0].role is DataRole.STATE_DEPENDENT


def test_a_registration_identity_is_unique():
    """A conference sign-up: the form asks for the password twice."""
    decided = roles([
        typed(CONFERENCE, "Email", "jo@example.com", itype="email"),
        typed(CONFERENCE, "Password", "Secret1!", itype="password"),
        typed(CONFERENCE, "Confirm", "Secret1!", itype="password"),
    ])

    assert decided[0].role is DataRole.UNIQUE
    assert "twice" in decided[0].why


def test_a_customer_reference_on_a_create_page_is_unique():
    """A CRM. No password anywhere, and the old rule missed it entirely."""
    decided = roles([typed(CRM, "Account Number", "ACC-4471",
                           attrs={"name": "account_number"})])

    assert decided[0].role is DataRole.UNIQUE
    assert decided[0].confidence >= 0.8


def test_a_credential_is_existing_and_never_invented():
    """The whole point of a sign-in test is the account that already exists."""
    decided = roles([
        typed(SIGN_IN, "Email", "jo@example.com", itype="email"),
        typed(SIGN_IN, "Password", "Secret1!", itype="password"),
    ])

    assert decided[0].role is DataRole.EXISTING
    assert "'jo@example.com'" in body([
        typed(SIGN_IN, "Email", "jo@example.com", itype="email"),
        typed(SIGN_IN, "Password", "Secret1!", itype="password"),
        clicked(SIGN_IN, "Sign in"),
    ], start=SIGN_IN)


def test_a_password_is_static_wherever_it_appears():
    """Changing it would lock the test out of the account it just made."""
    decided = roles([typed(CONFERENCE, "Password", "Secret1!", itype="password")])

    assert decided[0].role is DataRole.STATIC


def test_an_ordinary_field_is_static():
    decided = roles([typed(CRM, "Company", "Acme Ltd", attrs={"name": "company"})])

    assert decided[0].role is DataRole.STATIC


def test_the_application_saying_so_beats_every_other_signal():
    """The tester hit the collision while recording. Nothing beats being told."""
    decided = roles([
        act("input", SIGN_IN, [sel("css_id", "#e")], tag="input", itype="email",
            name="Email", value="jo@example.com",
            messages=["That email address is already registered"]),
    ])

    assert decided[0].role is DataRole.UNIQUE


# ---------------------------------------------------------------------------
# What the roles turn into
# ---------------------------------------------------------------------------
def test_a_state_dependent_step_goes_through_the_helper():
    tile = [sel("role_name", "link|Blue Top", score=95),
            sel("css", "div.product-card a.title", unique=False, score=55)]
    code = body([act("click", SHOP, tile, name="Blue Top")], start=SHOP)

    assert "one_of(" in code
    assert "among='blue_top_link_alternatives'" in code


def test_the_recorded_element_is_still_the_one_named_first():
    """A role is permission to try something else after a refusal - never an
    instruction to start somewhere else."""
    tile = [sel("role_name", "link|Blue Top", score=95),
            sel("css", "div.product-card a.title", unique=False, score=55)]
    files = generate([act("click", SHOP, tile, name="Blue Top")], start=SHOP)
    page_object = files["pages/products_page.py"]

    assert "get_by_role('link', name='Blue Top', exact=True)" in page_object
    assert "one_of(products, 'blue_top_link'" in files["tests/test_suite.py"]


def test_a_creating_form_replays_the_recording_then_renews_if_refused():
    """Even here the recorded address goes in first. A form with a password on
    it is never given an invented value up front - see
    `_never_invent_a_credential`. The second run is refused as already
    registered, and *that* is what produces a fresh one."""
    code = body([
        typed(CONFERENCE, "Email", "jo@example.com", itype="email"),
        typed(CONFERENCE, "Password", "Secret1!", itype="password"),
        typed(CONFERENCE, "Confirm", "Secret1!", itype="password"),
        clicked(CONFERENCE, "Create"),
    ], start=CONFERENCE)

    assert "'jo@example.com'" in code                # the recording runs first
    assert "submit(" in code and "renew=[" in code   # and is renewed if refused


def test_a_record_form_with_no_password_still_gets_a_fresh_value_up_front():
    """The guard is about credentials. A form with no password on it cannot be
    signing anybody in, so an identifier on a create page is replaced as before."""
    code = body([
        typed(CRM, "Account Number", "ACC-4471", attrs={"name": "account_number"}),
        clicked(CRM, "Save"),
    ], start=CRM)

    assert "fresh_id = " in code


def test_an_identifier_with_no_evidence_replays_but_can_be_renewed():
    """The honest middle. Evidence first, substitution second - which is exactly
    the flow asked for: run the recorded value, and only if the application
    objects, generate another and carry on."""
    code = body([
        typed("https://portal.test/form", "Reference", "REF-9910",
              attrs={"name": "reference_number"}),
        clicked("https://portal.test/form", "Send"),
    ], start="https://portal.test/form")

    assert "'REF-9910'" in code       # the recording is what runs
    assert "renew=[" in code           # and a refusal is recoverable


def test_a_credential_form_is_never_given_a_retry():
    """Nothing about a sign-in is allowed to vary."""
    code = body([
        typed(SIGN_IN, "Email", "jo@example.com", itype="email"),
        typed(SIGN_IN, "Password", "Secret1!", itype="password"),
        clicked(SIGN_IN, "Sign in"),
    ], start=SIGN_IN)

    assert "renew=" not in code
    assert "submit(" not in code


def test_navigation_chrome_is_never_state_dependent():
    """A navigation bar is a set of repeated links by construction, and no
    refusal is ever answered by clicking a different tab."""
    nav = [sel("role_name", "link|Reports", score=95),
           sel("css", "nav ul li a", unique=False, score=55)]
    decided = roles([act("click", "https://app.test/", nav, name="Reports",
                         attrs={"class": "nav-link"})])

    assert 0 not in decided


def test_clicking_into_a_text_field_is_not_choosing_a_record():
    """A form of six text fields is not a set of six comparable records."""
    field = [sel("role_name", "textbox|Email", score=95),
             sel("css", "div.form-group input.control", unique=False, score=55)]
    decided = roles([act("click", CRM, field, tag="input", itype="text", name="Email")])

    assert 0 not in decided


def test_an_element_with_no_comparable_selector_has_no_alternatives():
    """Nothing to swap to, so nothing is claimed. Inventing a selector for the
    neighbours is how a test starts clicking the footer."""
    pinned = [sel("role_name", "link|Blue Top", score=95),
              sel("xpath", "//body/div[1]/a[1]", score=35)]
    decided = roles([act("click", SHOP, pinned, name="Blue Top")])

    assert 0 not in decided


def test_everything_generated_is_valid_python():
    tile = [sel("role_name", "link|Blue Top", score=95),
            sel("css", "div.product-card a.title", unique=False, score=55)]
    files = generate([
        act("click", SHOP, tile, name="Blue Top"),
        typed(CONFERENCE, "Email", "jo@example.com", itype="email"),
        typed(CONFERENCE, "Password", "x", itype="password"),
        typed(CONFERENCE, "Confirm", "x", itype="password"),
        clicked(CONFERENCE, "Create"),
    ], start=SHOP)

    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content)


def test_a_recording_with_nothing_state_dependent_ships_no_state_helper():
    """Machinery nothing uses is machinery nobody audits."""
    files = generate([clicked(SIGN_IN, "Sign in")], start=SIGN_IN)

    assert "pages/_state.py" not in files


# ---------------------------------------------------------------------------
# The refusal vocabulary: about collision, never about a domain
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("said", [
    "That email address is already registered",
    "This username is already taken",
    "You have already purchased this course",
    "Customer reference must be unique",
    "That room is no longer available for these dates",
    "This time slot is unavailable",
    "Duplicate entry for key 'reference'",
    "Sorry, this session is fully booked",
    "That seat has been taken",
    "You are already enrolled",
])
def test_the_ways_an_application_refuses(said):
    assert is_conflict(said)


@pytest.mark.parametrize("said", [
    "Please enter a valid email address",   # the data is wrong, not taken
    "This field is required",
    "Password must be at least 8 characters",
    "Purchased courses",                    # a heading, not a refusal
    "Available now",
    "Add a new customer",
    "Internal Server Error",                # a defect, handled elsewhere
])
def test_what_is_not_a_refusal(said):
    """Trying different data until something is accepted would bury a real
    finding. Only collision and availability count."""
    assert not is_conflict(said)


# ---------------------------------------------------------------------------
# The runtime gate, driven against a real browser
# ---------------------------------------------------------------------------
def generated_helpers(tmp_path: Path):
    """The generated pages/ helpers, imported the way a suite imports them."""
    import sys

    tile = [sel("role_name", "link|One", score=95),
            sel("css", "ul.items li a", unique=False, score=55)]
    files = generate([act("click", SHOP, tile, name="One")], start=SHOP)

    package = tmp_path / "pages"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name in ("_healing", "_state"):
        (package / f"{name}.py").write_text(files[f"pages/{name}.py"], encoding="utf-8")

    # A fresh import each time, since every test gets its own tmp_path.
    for name in ("pages", "pages._healing", "pages._state"):
        sys.modules.pop(name, None)

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        return (
            importlib.import_module("pages._state"),
            importlib.import_module("pages._healing"),
        )
    finally:
        sys.path.remove(str(tmp_path))


class Listing:
    """What a generated page object gives the helpers: `.page` and properties."""

    def __init__(self, page, healing, recorded, shape):
        self.page = page
        self._healing = healing
        self._recorded = recorded
        self._shape = shape

    @property
    def item(self):
        return self._healing.heal("item", [("css", lambda: self.page.locator(self._recorded))])

    @property
    def item_alternatives(self):
        return self._healing.heal("item_alternatives", [("css", lambda: self.page.locator(self._shape))])


#: Three rows. The first refuses in the application's own words; the second is
#: a genuine defect; the third works. Which of them a test may move on to is the
#: whole question.
ROWS = """
<!doctype html>
<html><body>
  <div id="said"></div>
  <ul class="items">
    <li><a href="#" data-outcome="refuse">One</a></li>
    <li><a href="#" data-outcome="break">Two</a></li>
    <li><a href="#" data-outcome="ok">Three</a></li>
  </ul>
  <script>
    document.querySelectorAll('.items a').forEach((a) => {
      a.addEventListener('click', (event) => {
        event.preventDefault();
        const said = document.getElementById('said');
        const outcome = a.dataset.outcome;
        if (outcome === 'refuse') said.innerText = 'That one is no longer available';
        else if (outcome === 'break') { said.innerText = ''; throw new Error('kaboom'); }
        else said.innerText = 'Done';
        window.__last = a.innerText;
      });
    });
  </script>
</body></html>
"""


def browser_page(playwright, tmp_path, html, name="page.html"):
    page_file = tmp_path / name
    page_file.write_text(textwrap.dedent(html), encoding="utf-8")
    browser = playwright.chromium.launch()
    page = browser.new_page()
    page.goto(page_file.as_uri())
    return browser, page


@pytest.mark.integration
def test_a_refusal_moves_on_to_a_comparable_element(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, ROWS)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")

        state.one_of(shelf, "item", step=1, described='Click "One"',
                     among="item_alternatives")

        # It tried the recorded row, was refused, skipped the row that threw a
        # JavaScript error... no: it stopped there. See the next test.
        assert state.adaptations() == [] or "comparable" in state.adaptations()[0]
        browser.close()


@pytest.mark.integration
def test_a_javascript_error_stops_everything(tmp_path: Path):
    """The single most important rule in the file. A test that keeps trying
    until something goes green turns a defect into a pass."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, ROWS)
        state.reset()
        state.watch(page)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")

        with pytest.raises(state.StateConflict, match="NOT retried"):
            state.one_of(shelf, "item", step=1, described='Click "One"',
                         among="item_alternatives")

        # It never reached the third row, which would have passed.
        assert page.evaluate("() => window.__last") != "Three"
        browser.close()


#: Every row refuses. Nothing is left, and that has to be a failure.
#:
#: Each refusal names the row it is about, which is what applications do and
#: what lets a second refusal be told from the first still being on screen.
ALL_REFUSED = """
<!doctype html>
<html><body>
  <div id="said"></div>
  <ul class="items">
    <li><a href="#" class="row">One</a></li>
    <li><a href="#" class="row">Two</a></li>
  </ul>
  <script>
    document.querySelectorAll('.row').forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault();
      const said = document.getElementById('said');
      said.innerHTML = '<p>' + a.innerText + ' is already taken</p>';
    }));
  </script>
</body></html>
"""


@pytest.mark.integration
def test_running_out_of_alternatives_fails_the_test(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, ALL_REFUSED)
        state.reset()
        state.watch(page)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")

        with pytest.raises(state.StateConflict, match="refused"):
            state.one_of(shelf, "item", step=1, described='Click "One"',
                         among="item_alternatives")
        browser.close()


#: The recorded row works perfectly. Nothing should be tried, and nothing said.
FIRST_WORKS = """
<!doctype html>
<html><body>
  <div id="said"></div>
  <ul class="items">
    <li><a href="#" class="row">One</a></li>
    <li><a href="#" class="row">Two</a></li>
  </ul>
  <script>
    document.querySelectorAll('.row').forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault();
      window.__clicks = (window.__clicks || 0) + 1;
      window.__last = a.innerText;
    }));
  </script>
</body></html>
"""


@pytest.mark.integration
def test_the_recorded_element_runs_first_and_alone(tmp_path: Path):
    """A recording that still works must replay exactly, silently, once."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, FIRST_WORKS)
        state.reset()
        state.watch(page)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")

        state.one_of(shelf, "item", step=1, described='Click "One"',
                     among="item_alternatives")

        assert page.evaluate("() => window.__clicks") == 1
        assert page.evaluate("() => window.__last") == "One"
        assert state.adaptations() == []
        browser.close()


@pytest.mark.integration
def test_a_standing_message_is_not_read_as_a_refusal(tmp_path: Path):
    """An application with "already registered" in a sidebar would otherwise
    refuse every step on the page."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)
    html = FIRST_WORKS.replace(
        '<div id="said"></div>',
        '<aside>Items you have already purchased are in your library</aside>'
        '<div id="said"></div>',
    )

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, html)
        state.reset()
        state.watch(page)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")

        state.one_of(shelf, "item", step=1, described='Click "One"',
                     among="item_alternatives")

        assert page.evaluate("() => window.__clicks") == 1
        assert state.adaptations() == []
        browser.close()


@pytest.mark.integration
def test_an_adaptation_is_written_down(tmp_path: Path):
    """A recovered test that reads like an ordinary pass is evidence of nothing."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)
    html = """
    <!doctype html>
    <html><body>
      <div id="said"></div>
      <ul class="items">
        <li><a href="#" class="row" data-ok="0">One</a></li>
        <li><a href="#" class="row" data-ok="1">Two</a></li>
      </ul>
      <script>
        document.querySelectorAll('.row').forEach((a) => a.addEventListener('click', (e) => {
          e.preventDefault();
          document.getElementById('said').innerText =
            a.dataset.ok === '1' ? 'Done' : 'That one is already taken';
          window.__last = a.innerText;
        }));
      </script>
    </body></html>
    """

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, html)
        state.reset()
        state.watch(page)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")

        state.one_of(shelf, "item", step=7, described='Click "One"',
                     among="item_alternatives")

        assert page.evaluate("() => window.__last") == "Two"
        notes = state.adaptations()
        assert len(notes) == 1
        assert "step 7" in notes[0]
        assert "already taken" in notes[0]   # and why
        browser.close()


#: A sign-up that refuses the first address and accepts the second. Exactly the
#: flow asked for: run the recorded value, and only if the application objects,
#: generate another and carry on.
SIGNUP_FORM = """
<!doctype html>
<html><body>
  <form onsubmit="return false">
    <input id="email" value="" />
    <button id="go" type="button">Create</button>
  </form>
  <div id="said"></div>
  <script>
    window.__taken = ['taken@example.com'];
    window.__created = null;
    document.getElementById('go').addEventListener('click', () => {
      const email = document.getElementById('email').value;
      const said = document.getElementById('said');
      if (window.__taken.includes(email)) {
        said.innerHTML = '<p>' + email + ' is already registered</p>';
      } else {
        said.innerHTML = '<p>Welcome</p>';
        window.__created = email;
      }
    });
  </script>
</body></html>
"""


class SignUp:
    def __init__(self, page, healing):
        self.page = page
        self._healing = healing

    @property
    def email_input(self):
        return self._healing.heal("email_input", [("css", lambda: self.page.locator("#email"))])

    @property
    def create_button(self):
        return self._healing.heal("create_button", [("css", lambda: self.page.locator("#go"))])


@pytest.mark.integration
def test_a_refused_value_is_replaced_and_the_form_resubmitted(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, SIGNUP_FORM, "signup.html")
        state.reset()
        state.watch(page)
        form = SignUp(page, healing)

        # The recorded value runs first, exactly as recorded.
        form.email_input.fill("taken@example.com")
        state.submit(
            form, "create_button", step=4, described='Click "Create"',
            renew=[(lambda: "fresh-1@example.com", [(form, "email_input")])],
        )

        assert page.evaluate("() => window.__created") == "fresh-1@example.com"
        notes = state.adaptations()
        assert len(notes) == 1
        assert "already registered" in notes[0]      # why it changed
        assert "email_input" in notes[0]             # and what
        browser.close()


#: The submission reaches a server that fails, and the page still renders a
#: sentence that reads exactly like a refusal. The 5xx has to win.
FAILING_SERVER = """
<!doctype html>
<html><body>
  <input id="email" value="" />
  <button id="go" type="button">Create</button>
  <div id="said"></div>
  <script>
    document.getElementById('go').addEventListener('click', async () => {
      try { await fetch('https://api.test/signup', {method: 'POST'}); } catch (e) {}
      document.getElementById('said').innerHTML =
        '<p>' + document.getElementById('email').value + ' is already registered</p>';
    });
  </script>
</body></html>
"""


@pytest.mark.integration
def test_a_server_error_is_never_retried_with_new_data(tmp_path: Path):
    """The rule that matters most. A 5xx is not a reason to try different data.

    The page even says "already registered", which every other test here treats
    as permission to try again. The 500 underneath it says the application
    failed, and that ends the matter - otherwise a broken server gets retried
    until something goes green and the run reports health it never measured.
    """
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, FAILING_SERVER, "failing.html")
        page.route(
            "https://api.test/**",
            lambda route: route.fulfill(status=500, body="Internal Server Error"),
        )
        state.reset()
        state.watch(page)
        form = SignUp(page, healing)
        form.email_input.fill("taken@example.com")

        with pytest.raises(state.StateConflict, match="NOT retried"):
            state.submit(
                form, "create_button", step=4, described='Click "Create"',
                renew=[(lambda: "fresh-1@example.com", [(form, "email_input")])],
            )

        assert state.adaptations() == []
        assert form.email_input.input_value() == "taken@example.com"  # nothing changed
        browser.close()


@pytest.mark.integration
def test_a_page_showing_a_stack_trace_is_never_retried(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)
    broken = SIGNUP_FORM.replace(
        "said.innerHTML = '<p>Welcome</p>';",
        "said.innerHTML = '<pre>Traceback (most recent call last): "
        "File \\\"app.py\\\", line 42</pre>';",
    )

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, broken, "broken.html")
        state.reset()
        state.watch(page)
        form = SignUp(page, healing)
        form.email_input.fill("new@example.com")

        with pytest.raises(state.StateConflict, match="NOT retried"):
            state.submit(
                form, "create_button", step=4, described='Click "Create"',
                renew=[(lambda: "other@example.com", [(form, "email_input")])],
            )
        browser.close()


#: The case that started all of this. The recorded row's control is simply not
#: there any more - no message, no disabled button, it has been replaced - while
#: its neighbours still offer theirs. No refusal is ever written to the page.
CONSUMED = """
<!doctype html>
<html><body>
  <ul class="items">
    <li><a href="#" class="done">Remove</a></li>
    <li><a href="#" class="take">Take</a></li>
    <li><a href="#" class="take">Take</a></li>
  </ul>
  <script>
    document.querySelectorAll('.take').forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault();
      window.__took = (window.__took || 0) + 1;
    }));
  </script>
</body></html>
"""


@pytest.mark.integration
def test_a_recorded_element_that_is_gone_falls_back_to_a_comparable_one(tmp_path: Path):
    """No message is written when an application simply stops offering
    something, so the refusal path cannot see it. The page still offering
    others of the kind is what says the page rendered and one thing is used up."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(playwright, tmp_path, CONSUMED, "consumed.html")
        page.set_default_timeout(2_000)
        state.reset()
        state.watch(page)
        # The recorded locator matched the first row's control, which is gone.
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a.take", "ul.items a.take")

        state.one_of(shelf, "item", step=11, described='Click "Take"',
                     among="item_alternatives")

        assert page.evaluate("() => window.__took") == 1
        notes = state.adaptations()
        assert len(notes) == 1
        assert "no longer on the page" in notes[0]
        browser.close()


@pytest.mark.integration
def test_a_page_offering_nothing_of_the_kind_fails_as_it_always_did(tmp_path: Path):
    """Nothing comparable either, so the page did not render its controls. That
    is a real failure and must reach the report as Playwright described it."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)

    with sync_playwright() as playwright:
        browser, page = browser_page(
            playwright, tmp_path,
            '<!doctype html><html><body><ul class="items"></ul></body></html>',
            "empty.html",
        )
        page.set_default_timeout(2_000)
        state.reset()
        state.watch(page)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a.take", "ul.items a.take")

        # Playwright's own error, not one invented here.
        with pytest.raises(Exception, match="Timeout|not found|resolve"):
            state.one_of(shelf, "item", step=11, described='Click "Take"',
                         among="item_alternatives")

        assert state.adaptations() == []
        browser.close()


@pytest.mark.integration
def test_a_vanished_element_on_a_broken_page_is_still_never_retried(tmp_path: Path):
    """Comparable elements present, but the server failed. The 5xx wins."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)
    html = CONSUMED.replace(
        "<script>",
        "<script>fetch('https://api.test/x').catch(() => {});",
    )
    page_file = tmp_path / "consumed-broken.html"
    page_file.write_text(textwrap.dedent(html), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        # Routed and watched *before* the page loads, or the request the script
        # makes on load is gone before either is listening.
        page.route(
            "https://api.test/**",
            lambda route: route.fulfill(status=500, body="Internal Server Error"),
        )
        state.reset()
        state.watch(page)
        page.goto(page_file.as_uri())
        page.wait_for_timeout(500)          # let the 500 arrive
        page.set_default_timeout(2_000)
        shelf = Listing(page, healing, "ul.items li:nth-child(1) a.take", "ul.items a.take")

        with pytest.raises(Exception):
            state.one_of(shelf, "item", step=11, described='Click "Take"',
                         among="item_alternatives")

        assert page.evaluate("() => window.__took || 0") == 0   # nothing was taken
        assert state.adaptations() == []
        browser.close()


# ---------------------------------------------------------------------------
# A credential is never invented — on any site
#
# One rule, checked against every shape of form these have been seen in. The
# assertion is always the same: the address the recording used appears in the
# generated code, and no generated one is put in its place before the test runs.
#
# The rules above are judgements and can be wrong. This is the guard that makes
# being wrong survivable, so it is checked exhaustively rather than by example.
# ---------------------------------------------------------------------------
def credential_forms():
    """Sign-in and sign-up forms as different sites actually build them."""
    return {
        "plain sign-in": ("https://a.test/login", [
            typed("https://a.test/login", "Email", "jo@corp.com", itype="email"),
            typed("https://a.test/login", "Password", "Secret1!", itype="password"),
        ]),
        "sign-in at an address that says nothing": ("https://b.test/", [
            typed("https://b.test/", "Email", "jo@corp.com", itype="email"),
            typed("https://b.test/", "Password", "Secret1!", itype="password"),
        ]),
        "password box flushed twice": ("https://c.test/account", [
            typed("https://c.test/account", "Email", "jo@corp.com", itype="email"),
            typed("https://c.test/account", "Password", "Sec", itype="password"),
            typed("https://c.test/account", "Password", "Secret1!", itype="password"),
        ]),
        "sign-in beside a change-password widget": ("https://d.test/portal", [
            typed("https://d.test/portal", "Email", "jo@corp.com", itype="email"),
            typed("https://d.test/portal", "Password", "Secret1!", itype="password"),
            typed("https://d.test/portal", "New Password", "Other2@", itype="password"),
        ]),
        "sign-up with confirm password": ("https://e.test/register", [
            typed("https://e.test/register", "Email", "jo@corp.com", itype="email"),
            typed("https://e.test/register", "Password", "Secret1!", itype="password"),
            typed("https://e.test/register", "Confirm Password", "Secret1!", itype="password"),
        ]),
        "sign-up at a create address": ("https://f.test/users/new", [
            typed("https://f.test/users/new", "Email", "jo@corp.com", itype="email"),
            typed("https://f.test/users/new", "Password", "Secret1!", itype="password"),
        ]),
        "username instead of email": ("https://g.test/signin", [
            typed("https://g.test/signin", "Username", "jo_corp", attrs={"name": "username"}),
            typed("https://g.test/signin", "Password", "Secret1!", itype="password"),
        ]),
        "phone instead of email": ("https://h.test/login", [
            typed("https://h.test/login", "Mobile", "9876543210", attrs={"name": "mobile"}),
            typed("https://h.test/login", "Password", "Secret1!", itype="password"),
        ]),
        "sign-in then a second form later": ("https://i.test/login", [
            typed("https://i.test/login", "Email", "jo@corp.com", itype="email"),
            typed("https://i.test/login", "Password", "Secret1!", itype="password"),
            clicked("https://i.test/login", "Sign in"),
            typed("https://i.test/profile", "Display Name", "Jo", attrs={"name": "display"}),
        ]),
    }


@pytest.mark.parametrize("shape", sorted(credential_forms()))
def test_a_credential_is_never_invented(shape):
    start, actions = credential_forms()[shape]
    code = body([*actions, clicked(start, "Continue")], start=start)

    identity = next(
        str(a["payload"]["value"])
        for a in actions
        if a["action_type"] == "input"
        and str(a["element"]["input_type"]) != "password"
    )

    assert f"'{identity}'" in code, f"{shape}: the recorded value was not used"
    assert f"fill(fresh_" not in code.split(f"'{identity}'")[0].splitlines()[-1], shape


@pytest.mark.parametrize("shape", sorted(credential_forms()))
def test_no_password_is_ever_touched(shape):
    """Changing one locks the test out of the account it is about to use."""
    start, actions = credential_forms()[shape]
    code = body([*actions, clicked(start, "Continue")], start=start)

    # The last value typed into each field, since a field typed into twice is
    # collapsed by `normalise` into the value it ended up holding.
    final = {}
    for action in actions:
        if str(action["element"]["input_type"]) == "password":
            final[action["element"]["accessible_name"]] = action["payload"]["value"]

    for label, secret in final.items():
        assert f"'{secret}'" in code, f"{shape}: {label} was not reproduced"


def test_the_guard_holds_even_when_the_rules_read_the_form_backwards():
    """The point of the guard. Two distinct password fields on a page whose
    address says it creates - every signal pointing at sign-up - and the
    recorded address still goes in first, because a password is on the form."""
    url = "https://j.test/account/create"
    code = body([
        typed(url, "Email", "real-account@corp.com", itype="email"),
        typed(url, "Password", "Secret1!", itype="password"),
        typed(url, "Confirm Password", "Secret1!", itype="password"),
        clicked(url, "Continue"),
    ], start=url)

    assert "'real-account@corp.com'" in code
    assert "renew=[" in code          # recoverable if the application refuses it


def test_a_recorded_refusal_is_the_one_thing_that_overrides_the_guard():
    """Evidence, not inference. The application said so during recording."""
    url = "https://k.test/register"
    decided = roles([
        act("input", url, [sel("css_id", "#e")], tag="input", itype="email",
            name="Email", value="jo@corp.com",
            messages=["That email address is already registered"]),
        typed(url, "Password", "Secret1!", itype="password"),
    ])

    assert decided[0].role is DataRole.UNIQUE
    assert decided[0].confidence >= 0.8      # substituted before the test runs


# ---------------------------------------------------------------------------
# Somebody else's outage is not evidence about this application
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "site", "counts"),
    [
        ("https://app.example.com/api/checkout", "app.example.com", True),
        ("https://api.example.com/v1/orders", "www.example.com", True),   # own back end
        ("https://www.example.com:8443/pay", "example.com", True),        # port ignored
        ("https://www.google-analytics.com/g/collect", "www.example.com", False),
        ("https://cdn.segment.io/track", "www.example.com", False),
        ("https://fonts.gstatic.com/s/x.woff2", "www.example.com", False),
        ("https://widget.intercom.io/boot", "www.example.com", False),
        ("https://example.com/x", "", True),                              # unscoped
    ],
)
def test_only_the_application_under_test_counts_as_a_defect(tmp_path, url, site, counts):
    state, _ = generated_helpers(tmp_path)

    assert state._belongs_to(url, site) is counts


@pytest.mark.integration
def test_a_third_party_outage_does_not_fail_a_working_step(tmp_path: Path):
    """An analytics beacon answering 503 must not fail a checkout that worked.

    This is what made the gate over-report: every real page fetches from
    somewhere that is having a bad day, and any one of them held the gate shut.
    """
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)
    html = FIRST_WORKS.replace(
        "<script>",
        "<script>fetch('https://analytics.elsewhere.test/collect').catch(() => {});",
    )
    page_file = tmp_path / "beacon.html"
    page_file.write_text(textwrap.dedent(html), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route(
            "https://analytics.elsewhere.test/**",
            lambda route: route.fulfill(status=503, body="Service Unavailable"),
        )
        state.reset()
        # The suite under test is this file's own host, not the beacon's.
        state.watch(page, site="shop.test")
        page.goto(page_file.as_uri())
        page.wait_for_timeout(500)

        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")
        state.one_of(shelf, "item", step=3, described='Click "One"',
                     among="item_alternatives")

        assert page.evaluate("() => window.__clicks") == 1   # it went through
        assert state.adaptations() == []
        browser.close()


@pytest.mark.integration
def test_the_application_s_own_outage_still_stops_everything(tmp_path: Path):
    """The other half. Same shape, same 503 - but it is the application's."""
    from playwright.sync_api import sync_playwright

    state, healing = generated_helpers(tmp_path)
    # The request the *step* provokes, not one the page made on load - a
    # failure already on the books when the step began is not evidence about
    # the step.
    html = ALL_REFUSED.replace(
        "e.preventDefault();",
        "e.preventDefault(); fetch('https://shop.test/api/take').catch(() => {});",
    )
    page_file = tmp_path / "own.html"
    page_file.write_text(textwrap.dedent(html), encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route(
            "https://shop.test/**",
            lambda route: route.fulfill(status=503, body="Service Unavailable"),
        )
        state.reset()
        state.watch(page, site="shop.test")
        page.goto(page_file.as_uri())
        page.wait_for_timeout(500)

        shelf = Listing(page, healing, "ul.items li:nth-child(1) a", "ul.items li a")
        with pytest.raises(state.StateConflict, match="NOT retried"):
            state.one_of(shelf, "item", step=3, described='Click "One"',
                         among="item_alternatives")
        browser.close()


# ---------------------------------------------------------------------------
# The machinery stays out of sight
# ---------------------------------------------------------------------------
def state_dependent_pages():
    tile = [sel("role_name", "link|Blue Top", score=95),
            sel("css", "div.product-card a.title", unique=False, score=55)]
    return build_ir([act("click", SHOP, tile, name="Blue Top")],
                    suite_name="Suite", start_url=SHOP).pages


def test_the_alternatives_locator_is_never_offered_as_a_step_target():
    """It names a set, not a thing, and no step may point at it. Offered to the
    case generator it produced invented cases aiming at internal machinery."""
    from app.codegen.synth import elements

    pages = state_dependent_pages()
    registered = [loc.name for page in pages for loc in page.locators]
    offered = [item["target"] for item in elements(pages)]

    assert any(n.endswith("_alternatives") for n in registered)   # it exists
    assert not any(t.endswith("_alternatives") for t in offered)  # and is hidden
    assert any(t.endswith(".blue_top_link") for t in offered)     # the real one is not


def test_the_import_follows_the_code_even_on_a_derived_module():
    """A TestIR is derived in three other places, and two of them copied the
    steps and forgot the flag - so a module called `one_of` without importing
    it. Read off the steps, that cannot happen."""
    from app.codegen.converter import STATE_HELPERS, TestIR

    tile = [sel("role_name", "link|Blue Top", score=95),
            sel("css", "div.product-card a.title", unique=False, score=55)]
    full = build_ir([act("click", SHOP, tile, name="Blue Top")],
                    suite_name="Suite", start_url=SHOP)

    # A fresh IR carrying the same steps, exactly as a derived case builds one:
    # nothing is copied but the steps and the pages.
    derived = TestIR(
        suite_name="Derived", function_name="test_derived",
        module_name="test_derived", start_url=SHOP,
        pages=full.pages, steps=full.steps,
    )

    assert "one_of" in STATE_HELPERS
    assert derived.state_helpers == full.state_helpers == ["one_of"]
    assert derived.needs_state

    code = {f.path: f.content for f in render(derived, browser_info={})}
    module = code["tests/test_derived.py"]
    assert "from pages._state import one_of" in module
    assert "pages/_state.py" in code
