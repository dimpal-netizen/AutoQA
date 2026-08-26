"""Waiting for what an action actually does, rather than assuming.

The generator used to make one assumption: a click either navigates, or needs no
wait at all. Every other outcome — a modal, an AJAX re-render, a message, a new
tab — was followed immediately by the next step, which then raced the
application and passed or failed on machine speed.

Worse, the navigation was inferred from *adjacency*: any navigate event that
happened to follow a click was attributed to it. Dismissing a modal was recorded
as navigating to wherever the tester went three steps later.

Now the recorder watches, and the generator waits for what was watched. Nothing
below names an application, a URL or a control — the same six outcomes describe
a shop, an admin console, a booking system and a bank, because none of them is
about what the application is.
"""

import ast

import pytest

from app.codegen.converter import build_ir
from app.codegen.generator import render


def sel(strategy, value, *, unique=True, score=50):
    return {"strategy": strategy, "value": value, "unique": unique, "score": score}


def clicked(url, label, *, outcome=None, navigates=None, tag="button"):
    action = {
        "action_type": "click",
        "url": url,
        "frame_path": [],
        "selectors": [sel("role_name", f"{tag}|{label}", score=95)],
        "element": {
            "tag": tag, "input_type": None, "role": tag,
            "accessible_name": label, "text": label, "attributes": {},
        },
        "payload": {},
        "is_ignored": False,
    }
    if outcome is not None:
        action["response"] = outcome
    if navigates:
        action["_navigates_to"] = navigates
    return action


def body(actions, start="https://app.test/"):
    ir = build_ir(actions, suite_name="Suite", start_url=start)
    return {f.path: f.content for f in render(ir, browser_info={})}[ir.file_path]


def files(actions, start="https://app.test/"):
    ir = build_ir(actions, suite_name="Suite", start_url=start)
    return {f.path: f.content for f in render(ir, browser_info={})}


APP = "https://app.test/"


# ---------------------------------------------------------------------------
# One outcome, one wait
# ---------------------------------------------------------------------------
def test_an_action_that_navigated_waits_for_the_address():
    code = body([clicked(APP, "Continue", outcome={
        "kind": "navigated", "url": "https://app.test/next", "navigated": True,
    })])

    assert "after(page, 'navigated', url=re.compile(" in code
    assert "app\\\\.test/next" in code or "app\\.test/next" in code


def test_an_action_that_opened_a_dialog_waits_for_the_dialog():
    """No modal library is named, and none could be. A dialog is `role=dialog`,
    `role=alertdialog` or `<dialog open>` - by declaration, never by looking
    like one. A class called `modal` is on half the pages on the internet."""
    code = body([clicked(APP, "Delete", outcome={
        "kind": "dialog_opened", "dialog_opened": True, "mutations": 14,
    })])

    assert "after(page, 'dialog_opened')" in code
    assert "wait_for_url" not in code


def test_an_action_that_closed_a_dialog_waits_for_it_to_go():
    code = body([clicked(APP, "Not Now", outcome={
        "kind": "dialog_closed", "dialog_closed": True,
    })])

    assert "after(page, 'dialog_closed')" in code


def test_an_action_answered_on_screen_waits_for_what_it_said():
    """The most specific wait there is - and the only one carrying a sentence
    from this application, which is why it may only ever be a sentence the
    recording actually saw."""
    code = body([clicked(APP, "Apply", outcome={
        "kind": "messages", "messages": ["Discount applied"], "mutations": 6,
    })])

    assert "after(page, 'messages', text='Discount applied')" in code


def test_an_ajax_re_render_waits_for_the_page_to_settle():
    """The general answer, for everything the recorder saw happen but could not
    name. It asks the question worth asking - has the page finished reacting -
    rather than which request finished, which is a fact about an
    implementation."""
    code = body([clicked(APP, "Filter", outcome={
        "kind": "dom_changed", "mutations": 212, "navigated": False,
    })])

    assert "after(page, 'dom_changed')" in code


def test_an_action_that_changed_nothing_waits_for_nothing():
    """`quiet` is a real observation, not a failure to make one. A test that
    insists on waiting for something after an action that did nothing waits for
    ever."""
    code = body([clicked(APP, "Copy", outcome={"kind": "quiet", "mutations": 0})])

    assert "after(" not in code
    assert "wait_for_url" not in code
    assert ".click()" in code


def test_a_navigation_with_nowhere_recorded_waits_for_anywhere_else():
    """An SPA route that leaves no address behind. Weaker than an address, but
    still an observation rather than a guess."""
    code = body([clicked(APP, "Next", outcome={"kind": "navigated", "navigated": True})])

    assert "after(page, 'navigated')" in code


@pytest.mark.parametrize("outcome", ["navigated", "dialog_opened", "messages", "quiet"])
def test_the_same_rules_serve_any_application(outcome):
    """Four unrelated applications, four outcomes, one mechanism. Nothing in
    the generator knows which is which."""
    sites = [
        "https://bank.test/transfers",
        "https://clinic.test/appointments",
        "https://helpdesk.test/tickets",
        "https://warehouse.test/stock",
    ]
    for site in sites:
        code = body([clicked(site, "Go", outcome={
            "kind": outcome, "url": f"{site}/done", "navigated": outcome == "navigated",
            "messages": ["Saved"] if outcome == "messages" else [],
        })], start=site)

        if outcome == "quiet":
            assert "after(" not in code
        else:
            assert f"after(page, '{outcome}'" in code


# ---------------------------------------------------------------------------
# Nothing is assumed, and nothing old is broken
# ---------------------------------------------------------------------------
def test_a_recording_with_no_observation_behaves_exactly_as_before():
    """A recording made before outcomes were captured says nothing either way.
    It must not start waiting on things nobody watched - so the old adjacency
    rule still applies, and only it."""
    code = body([clicked(APP, "Continue", navigates="https://app.test/next")])

    assert "after(page, 'navigated', url=re.compile(" in code


def test_an_old_recording_of_a_click_that_did_not_navigate_still_waits_for_nothing():
    code = body([clicked(APP, "Toggle")])

    assert "after(" not in code


def test_what_was_observed_beats_what_was_adjacent():
    """The bug this replaces. A navigate event that merely *followed* a click
    was attributed to it, so dismissing a modal was recorded as navigating to
    wherever the tester went next."""
    code = body([clicked(APP, "Not Now",
                         outcome={"kind": "dialog_closed", "dialog_closed": True},
                         navigates="https://app.test/somewhere-else")])

    assert "after(page, 'dialog_closed')" in code
    assert "somewhere-else" not in code


def test_a_hover_is_never_given_a_wait():
    """It asserts nothing and exists for the step after it - which is also why
    it needs one, or `normalise` drops it as noise."""
    hover = clicked(APP, "Menu", outcome={"kind": "dom_changed", "mutations": 9})
    hover["action_type"] = "hover"
    code = body([hover, clicked(APP, "Settings", outcome={"kind": "quiet"})])

    assert "reveal(" in code
    assert "after(" not in code


def test_nothing_generated_ever_sleeps():
    """A sleep is a guess: too long on a fast machine, too short on a slow one,
    and wrong in a different direction on every run."""
    generated = files([
        clicked(APP, "A", outcome={"kind": "navigated", "url": "https://app.test/b"}),
        clicked("https://app.test/b", "B", outcome={"kind": "dom_changed", "mutations": 3}),
        clicked("https://app.test/b", "C", outcome={"kind": "dialog_opened"}),
    ])

    for path, content in generated.items():
        if path.endswith(".py"):
            assert "time.sleep" not in content, path
            assert "wait_for_timeout" not in content, path
            ast.parse(content)


def test_the_helper_ships_only_when_something_waits():
    assert "pages/_sync.py" in files([clicked(APP, "Go", outcome={"kind": "dom_changed"})])
    assert "pages/_sync.py" not in files([clicked(APP, "Go", outcome={"kind": "quiet"})])


def test_the_import_follows_the_code_even_on_a_derived_module():
    """Same guarantee as the state helpers: read off the steps, never carried
    as a flag somebody has to remember to copy."""
    from app.codegen.converter import TestIR

    full = build_ir([clicked(APP, "Go", outcome={"kind": "dialog_opened"})],
                    suite_name="Suite", start_url=APP)
    derived = TestIR(
        suite_name="Derived", function_name="test_derived", module_name="test_derived",
        start_url=APP, pages=full.pages, steps=full.steps,
    )

    assert derived.needs_sync
    generated = {f.path: f.content for f in render(derived, browser_info={})}
    assert "from pages._sync import after" in generated["tests/test_derived.py"]
    assert "pages/_sync.py" in generated
