"""Controls a person can operate but Playwright refuses to touch.

Almost every site now hides the real `<input type="checkbox">` and draws a
styled box on top of it, so the control the recorder captured is `0x0` pixels.
Playwright will not act on an element with no size — correctly — but it waits
the full thirty seconds first, so a filter that works perfectly in the browser
comes back like this:

    Locator.check: Timeout 30000ms exceeded.
      - locator resolved to <input type="checkbox"/>
      - element is not visible

One recording of a property search produced six red tests this way, all of them
reporting a bug in a filter with nothing wrong with it. That is the failure
these tests exist to keep out: not a test that breaks, a test that lies.

The generation half needs no browser. The one test that proves a hidden checkbox
can actually be ticked drives a real page, and is marked integration.
"""

import importlib.util
import textwrap

import pytest

from app.codegen.converter import build_ir, normalise
from app.codegen.generator import render
from app.codegen.selectors import best_selector, usable_selectors

URL = "https://x.test/properties"

#: What the recorder captures for the styled box a person actually clicks. The
#: `label` candidate is the whole problem: `get_by_label` returns the *form
#: control* a label names, so this renders as a locator for the hidden <input>.
SPAN_WAYS = [
    {"strategy": "label", "value": "House", "unique": True, "score": 90},
    {"strategy": "css", "value": "div details div label span", "unique": False, "score": 40},
]

CHECKBOX_WAYS = [
    {"strategy": "role_name", "value": "checkbox|House", "unique": True, "score": 95},
    {"strategy": "label", "value": "House", "unique": True, "score": 90},
]


def element(tag, *, box, input_type=None, role=None):
    return {
        "tag": tag,
        "input_type": input_type,
        "role": role,
        "accessible_name": "House",
        "text": "House",
        "attributes": {},
        "bounding_box": box,
    }


VISIBLE = {"x": 192.2, "y": 531.4, "width": 18.0, "height": 18.0}
INVISIBLE = {"x": 258.7, "y": 531.4, "width": 0.0, "height": 0.0}


def action(kind, el, selectors):
    return {
        "action_type": kind,
        "url": URL,
        "frame_path": [],
        "selectors": selectors,
        "element": el,
        "payload": {},
        "is_ignored": False,
    }


#: One click on a custom checkbox, exactly as it arrives: the span the person
#: pressed, then the `change` the browser forwarded to the input behind it.
ONE_GESTURE = [
    action("click", element("span", box=VISIBLE), SPAN_WAYS),
    action("uncheck", element("input", box=INVISIBLE, input_type="checkbox",
                              role="checkbox"), CHECKBOX_WAYS),
]


# ---------------------------------------------------------------------------
# get_by_label points somewhere else
# ---------------------------------------------------------------------------
def test_label_is_refused_for_an_element_that_is_not_a_form_control() -> None:
    """`get_by_label("House")` finds the input, never the span it was recorded
    for. Nothing in the eventual failure says the locator changed target, which
    is what makes it worth ruling out at generation time."""
    chosen = best_selector(SPAN_WAYS, element("span", box=VISIBLE))

    assert chosen is not None
    assert chosen.strategy.value != "label"


def test_label_is_kept_for_a_real_form_control() -> None:
    """The rule is about which element `get_by_label` returns, not about labels
    being poor. On an input it returns exactly the right one."""
    kept = usable_selectors(CHECKBOX_WAYS, element("input", box=INVISIBLE,
                                                   input_type="checkbox"))

    assert any(s["strategy"] == "label" for s in kept)


def test_an_unknown_tag_keeps_every_candidate() -> None:
    """Guessing is what caused the problem. With no tag recorded we do not."""
    assert usable_selectors(SPAN_WAYS, None) == SPAN_WAYS
    assert usable_selectors(SPAN_WAYS, {}) == SPAN_WAYS


def test_a_label_is_never_the_last_candidate_taken_away() -> None:
    """A label is a poor description of a span. No locator at all is worse."""
    only = [{"strategy": "label", "value": "House", "unique": True, "score": 90}]

    assert usable_selectors(only, element("span", box=VISIBLE)) == only


def test_the_label_candidate_is_gone_from_the_healing_spares_too() -> None:
    """A candidate that finds a different element is no safer as a fallback:
    healing would reach for it the moment the page shifted."""
    files = render(build_ir(normalise([action("click", element("span", box=VISIBLE),
                                              SPAN_WAYS)]), suite_name="Filters",
                            start_url=URL))
    page = next(f.content for f in files
                if f.path.startswith("pages/") and "_healing" not in f.path)

    assert "get_by_label" not in page


# ---------------------------------------------------------------------------
# One gesture, two recorded actions
# ---------------------------------------------------------------------------
def test_the_visible_stand_in_click_is_dropped() -> None:
    """Two actions, one gesture. The span has nothing to identify it but its
    position in the markup, so left in, the test clicks whichever span comes
    first and ticks the wrong filter — then the toggle behind it times out."""
    steps = normalise(ONE_GESTURE)

    assert [s["action_type"] for s in steps] == ["uncheck"]


def test_a_visible_checkbox_keeps_both_actions() -> None:
    """A checkbox you can see needs no stand-in, so a click before it is a
    separate thing the person did, not a duplicate of this one."""
    steps = normalise([
        action("click", element("span", box=VISIBLE), SPAN_WAYS),
        action("uncheck", element("input", box=VISIBLE, input_type="checkbox"),
               CHECKBOX_WAYS),
    ])

    assert [s["action_type"] for s in steps] == ["click", "uncheck"]


def test_a_click_on_a_different_control_is_not_a_stand_in() -> None:
    """Same page, adjacent, but a different name — two separate filters."""
    other = element("span", box=VISIBLE) | {"accessible_name": "Land", "text": "Land"}
    steps = normalise([
        action("click", other, SPAN_WAYS),
        action("uncheck", element("input", box=INVISIBLE, input_type="checkbox"),
               CHECKBOX_WAYS),
    ])

    assert [s["action_type"] for s in steps] == ["click", "uncheck"]


def test_a_recording_with_no_bounding_box_behaves_as_it_always_did() -> None:
    """Older recordings have no box. Unknown counts as visible: nothing about
    them should change under a fix aimed at what they never recorded."""
    no_box = {k: v for k, v in element("input", box=None, input_type="checkbox").items()
              if k != "bounding_box"}
    steps = normalise([action("click", element("span", box=VISIBLE), SPAN_WAYS),
                       action("uncheck", no_box, CHECKBOX_WAYS)])

    assert [s["action_type"] for s in steps] == ["click", "uncheck"]


# ---------------------------------------------------------------------------
# What gets generated
# ---------------------------------------------------------------------------
def test_the_test_ticks_through_set_checked_not_check() -> None:
    files = render(build_ir(normalise(ONE_GESTURE), suite_name="Filters", start_url=URL))
    body = next(f.content for f in files if f.path.startswith("tests/"))

    assert "set_checked(" in body
    assert ".uncheck()" not in body
    assert "from pages._healing import set_checked" in body


def test_a_suite_with_no_checkbox_does_not_import_the_helper() -> None:
    files = render(build_ir(normalise([action("click", element("button", box=VISIBLE),
                                              [SPAN_WAYS[1]])]), suite_name="Filters",
                            start_url=URL))
    body = next(f.content for f in files if f.path.startswith("tests/"))

    assert "set_checked" not in body


# ---------------------------------------------------------------------------
# It really does tick
# ---------------------------------------------------------------------------
HIDDEN_CHECKBOX = textwrap.dedent("""
    <!doctype html><html><body>
      <label>
        <input type="checkbox" checked style="position:absolute;width:0;height:0;
               opacity:0;pointer-events:none">
        <span style="display:inline-block;width:18px;height:18px;border:1px solid"></span>
        House
      </label>
    </body></html>
""")


@pytest.mark.integration
def test_set_checked_operates_a_checkbox_playwright_will_not_click(tmp_path) -> None:
    """The whole point, against a real browser: `.uncheck()` here raises, and
    `set_checked` unticks the same control by clicking the label — which is what
    the person did when they recorded it."""
    from playwright.sync_api import sync_playwright

    files = render(build_ir(normalise(ONE_GESTURE), suite_name="Filters", start_url=URL))
    module = tmp_path / "_healing.py"
    healing_src = next(f.content for f in files if f.path == "pages/_healing.py")
    module.write_text(healing_src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_healing", module)
    healing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(healing)

    page_file = tmp_path / "filters.html"
    page_file.write_text(HIDDEN_CHECKBOX, encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(page_file.as_uri())
        box = page.get_by_role("checkbox", name="House", exact=True)

        assert box.is_checked()
        with pytest.raises(Exception):
            box.uncheck(timeout=1_000)  # what the old generated code did

        healing.set_checked(box, False)
        assert not box.is_checked()

        # Idempotent: state is read off the input, which needs no visibility.
        healing.set_checked(box, False)
        assert not box.is_checked()

        healing.set_checked(box, True)
        assert box.is_checked()
        browser.close()


# ---------------------------------------------------------------------------
# Gestures aimed at nothing
# ---------------------------------------------------------------------------
def test_a_click_on_a_zero_size_element_is_dropped() -> None:
    """One press on a map pin arrived as three actions, two of them overlays
    with no size. Keeping them does not make the test more faithful - it adds
    two steps that wait thirty seconds each and then report a working property
    listing as broken."""
    steps = normalise([
        action("click", element("div", box={"x": 1, "y": 1, "width": 1198.4,
                                            "height": 0.0}), SPAN_WAYS),
        action("click", element("img", box={"x": 1, "y": 1, "width": 26.0,
                                            "height": 37.0}), SPAN_WAYS),
        action("click", element("area", box=INVISIBLE), SPAN_WAYS),
    ])

    assert len(steps) == 1
    assert steps[0]["element"]["tag"] == "img"


def test_typing_into_a_control_with_no_size_is_kept() -> None:
    """A hidden input is the custom-widget pattern, not a mis-aimed gesture.
    Dropping one would silently change what the test submits."""
    steps = normalise([
        action("input", element("input", box=INVISIBLE, input_type="text"), SPAN_WAYS),
    ])

    assert len(steps) == 1


# ---------------------------------------------------------------------------
# Two elements that answer to the same name
# ---------------------------------------------------------------------------
LINK_WAYS = [{"strategy": "role_name", "value": "link|House", "unique": False, "score": 95}]


def nav_link(href):
    return {
        "tag": "a", "input_type": None, "role": "link",
        "accessible_name": "House", "text": "House",
        "attributes": {"href": href},
        "bounding_box": VISIBLE,
    }


RENT = "/properties?listing-type=FOR_RENT&property-type=HOUSE"
NEW_PROJECT = "/properties?listing-type=NEW_PROJECT&property-type=HOUSE"


def built(actions):
    return build_ir(normalise(actions), suite_name="Nav", start_url=URL)


def test_two_links_with_the_same_name_stay_two_locators() -> None:
    """Both render as get_by_role("link", name="House"). Merged, every step
    aimed at either drives whichever comes first - so the test opened the New
    Projects menu and clicked the Rent item, which was hidden."""
    ir = built([action("click", nav_link(RENT), LINK_WAYS),
                action("click", nav_link(NEW_PROJECT), LINK_WAYS)])
    locators = [loc for page in ir.pages for loc in page.locators]

    assert len(locators) == 2
    assert RENT in locators[0].expression
    assert NEW_PROJECT in locators[1].expression
    assert all(".and_(" in loc.expression for loc in locators[1:])


def test_the_same_element_twice_stays_one_locator() -> None:
    """The recorder captures whatever the element carried at the moment of the
    event, and an element can carry more on one event than another. The email
    field arrived as

        click  {id: "email", name: "email", data-testid: "email-input"}
        input  {data-testid: "email-input"}

    Requiring the two sets to match split one field into `email_input` and
    `email_input_2`, and every step after the first drove a property that was
    the same element twice. Only what they share is compared, and it agrees.
    """
    field = {
        "tag": "input", "input_type": "email", "role": "textbox",
        "accessible_name": "Email address", "text": None,
        "attributes": {"id": "email", "name": "email", "data-testid": "email-input"},
        "bounding_box": VISIBLE,
    }
    partial = field | {"attributes": {"data-testid": "email-input"}}
    ways = [{"strategy": "test_id", "value": "email-input", "unique": True, "score": 99}]
    ir = built([action("click", field, ways), action("input", partial, ways)])

    assert len([loc for page in ir.pages for loc in page.locators]) == 1


def test_an_element_with_nothing_to_identify_it_never_splits() -> None:
    """Unknown is not evidence of difference."""
    bare = {"tag": "a", "role": "link", "accessible_name": "House",
            "text": "House", "attributes": {}, "bounding_box": VISIBLE}
    ir = built([action("click", bare, LINK_WAYS), action("click", bare, LINK_WAYS)])

    assert len([loc for page in ir.pages for loc in page.locators]) == 1


# ---------------------------------------------------------------------------
# Waiting for where the click actually went
# ---------------------------------------------------------------------------
def test_a_navigation_wait_tolerates_the_query_string() -> None:
    """`_clean_url` throws the query away on purpose - a recorded ?token= or
    ?id=cmryim584000q01p42 is one row on one server on one day. But the browser
    still goes to the full address, so waiting for the cleaned one as an exact
    string waits for something that never arrives."""
    import re as _re

    from app.codegen.converter import _arrives_at

    pattern = _re.compile(_arrives_at("https://x.test/properties"))

    assert pattern.match("https://x.test/properties")
    assert pattern.match("https://x.test/properties/")
    assert pattern.match("https://x.test/properties?listing-type=NEW_PROJECT")
    assert pattern.match("https://x.test/properties#results")


def test_a_navigation_wait_is_still_a_real_check() -> None:
    """A deeper path is a different page, and must not satisfy the wait."""
    import re as _re

    from app.codegen.converter import _arrives_at

    pattern = _re.compile(_arrives_at("https://x.test/properties"))

    assert not pattern.match("https://x.test/properties/cmryim584000q01p42kj4ts8q")
    assert not pattern.match("https://x.test/properties-archive")
    assert not pattern.match("https://x.test/")


def test_a_link_carrying_a_record_id_is_not_used_to_tell_elements_apart() -> None:
    """`/properties/cmryim584000q01p42kj4ts8q` is one row on one server on one
    day. Baking it into a locator trades a wrong element today for a broken
    test next week."""
    from app.codegen.selectors import distinguisher

    assert distinguisher({"attributes": {"href": "/properties/cmryim584000q01p42kj4ts8q"}}) is None
    assert distinguisher({"attributes": {"href": "/orders/1042/edit"}}) is None


def test_a_query_string_is_what_the_link_is_for_and_is_kept() -> None:
    from app.codegen.selectors import distinguisher

    href = "/properties?listing-type=NEW_PROJECT&property-type=HOUSE"

    assert distinguisher({"attributes": {"href": href}}) == ("href", href)
    assert distinguisher({"attributes": {"href": "/property-management"}}) is not None


def test_a_test_id_is_preferred_over_a_link() -> None:
    """Both identify it; only one survives a change of route."""
    from app.codegen.selectors import distinguisher

    element = {"attributes": {"href": "/properties?x=1", "data-testid": "house-filter"}}

    assert distinguisher(element) == ("data-testid", "house-filter")


def test_a_record_id_in_a_navigation_wait_becomes_a_wildcard() -> None:
    """The recording added a property and landed on

        /property-owner/my-listings/cmsoao69n001501pd

    so the test waited for that exact listing - the one made during the
    recording, which the test does not create and can never reach. Thirty
    seconds, then red, on a property that had been added perfectly well.
    """
    import re as _re

    from app.codegen.converter import _arrives_at

    pattern = _re.compile(
        _arrives_at("https://x.test/property-owner/my-listings/cmsoao69n001501pd")
    )

    assert pattern.match("https://x.test/property-owner/my-listings/cmsoao69n001501pd")
    assert pattern.match("https://x.test/property-owner/my-listings/a-different-one99")


def test_the_wait_still_says_which_page_it_wanted() -> None:
    """Only the id is a wildcard. Landing on the listings index, or on some
    other page carrying an id, is not arriving where the click said it would."""
    import re as _re

    from app.codegen.converter import _arrives_at

    pattern = _re.compile(
        _arrives_at("https://x.test/property-owner/my-listings/cmsoao69n001501pd")
    )

    assert not pattern.match("https://x.test/property-owner/my-listings")
    assert not pattern.match("https://x.test/property-owner/drafts/cmsoao69n001501pd")


def test_a_path_with_no_id_is_unchanged() -> None:
    import re as _re

    from app.codegen.converter import _arrives_at

    pattern = _re.compile(_arrives_at("https://x.test/properties"))

    assert pattern.match("https://x.test/properties?listing-type=NEW_PROJECT")
    assert not pattern.match("https://x.test/properties/cmryim584000q01p42kj4ts8q")
