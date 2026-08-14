"""Cutting a recording into the tests a person actually performed.

A recording is not one test. Somebody tries logging in with just an email, gets
an error, dismisses it, tries again with a wrong password, and then goes off to
register instead — four things they tested, which until now became one case
fifty-one steps long.

The rules are deliberately dull, and these are mostly about what must *not*
split: a rule that cuts too eagerly turns one honest test into three that each
start halfway through a flow and fail on an element that is not there yet.
"""

from app.codegen.segments import MIN_ACTIONS, split


def act(kind: str, *, name: str = "", text: str = "", ignored: bool = False) -> dict:
    return {
        "action_type": kind,
        "is_ignored": ignored,
        "element": {
            "accessible_name": name,
            "text": text,
            "attributes": {"name": name} if name else {},
            "tag": "input",
        },
    }


def fill(name: str) -> dict:
    return act("input", name=name)


def click(name: str) -> dict:
    return act("click", name=name)


# ---------------------------------------------------------------------------
# Where it cuts
# ---------------------------------------------------------------------------
def test_a_field_filled_twice_starts_a_new_test():
    """Nobody types into the same box twice inside one attempt."""
    cases = split([
        fill("email"), fill("password"), click("Login"),
        fill("email"), fill("password"), click("Login"),
    ])

    assert len(cases) == 2
    assert len(cases[0]) == 3


def test_dismissing_an_error_ends_the_attempt():
    """The application answered. What comes next is another go."""
    cases = split([
        fill("email"), click("Login"), click("Dismiss"),
        fill("password"), click("Login"), click("Login"),
    ])

    assert len(cases) == 2
    assert cases[0][-1]["element"]["accessible_name"] == "Dismiss"


def test_the_opening_navigation_belongs_to_the_first_test():
    """A recording starts by going somewhere; that is not a test of its own."""
    cases = split([
        act("navigate"), fill("email"), click("Login"), click("Home"),
    ])

    assert len(cases) == 1
    assert cases[0][0]["action_type"] == "navigate"


# ---------------------------------------------------------------------------
# Where it must not
# ---------------------------------------------------------------------------
def test_a_recording_of_one_journey_stays_one_test():
    """The common case, and the one a wrong rule would ruin."""
    cases = split([
        fill("email"), fill("password"), click("Login"),
        click("Dashboard"), click("Profile"),
    ])

    assert len(cases) == 1


def test_navigating_does_not_split():
    """Arriving at the dashboard is the *result* of signing in, not the start
    of something new. A rule that split here would cut every successful login
    in half and leave the second half asserting against a page it never
    reached."""
    cases = split([
        fill("email"), fill("password"), click("Sign in"),
        act("navigate"), click("My account"),
    ])

    assert len(cases) == 1


def test_two_different_fields_are_not_a_repeat():
    cases = split([fill("first_name"), fill("last_name"), click("Save")])

    assert len(cases) == 1


def test_a_close_account_button_is_not_a_dismissal():
    """Matching "close" anywhere in a label would cut here, and the rest of the
    test — the confirm dialog, the check that the account is gone — would
    become a case that starts by confirming something nobody asked for."""
    cases = split([
        click("Settings"), click("Close account"), click("Confirm"), click("OK"),
    ])

    assert len(cases) == 1


def test_ignored_actions_are_left_out():
    """The recorder marks noise; it must not become a seam."""
    cases = split([
        fill("email"), act("scroll", ignored=True), click("Login"),
    ])

    assert len(cases) == 1
    assert len(cases[0]) == 2


# ---------------------------------------------------------------------------
# Segments too small to be a test
# ---------------------------------------------------------------------------
def test_a_stub_is_folded_back_rather_than_shipped():
    """Two clicks after an error is somebody poking about, not a scenario.
    Shipped as a case it is a red row nobody can act on."""
    cases = split([
        fill("email"), fill("password"), click("Login"), click("Dismiss"),
        click("Help"),
    ])

    assert len(cases) == 1
    assert len(cases[0]) == 5, "the actions still happened; none may be dropped"


def test_a_leading_stub_joins_the_test_after_it():
    """It has no predecessor to fold into."""
    cases = split([
        click("Cookies"), click("Dismiss"),
        fill("email"), fill("password"), click("Login"),
    ])

    assert len(cases) == 1


def test_every_action_survives_the_split():
    """The count is the contract: a cut that loses steps makes the last case a
    lie about what was done."""
    actions = [
        fill("email"), click("Login"), click("Dismiss"),
        fill("email"), fill("password"), click("Login"),
        fill("email"), fill("password"), click("Login"),
    ]

    cases = split(actions)

    assert sum(len(case) for case in cases) == len(actions)
    assert len(cases) > 1


def test_an_empty_recording_produces_nothing():
    assert split([]) == []
    assert split([act("scroll", ignored=True)]) == []


def test_the_minimum_is_honoured():
    """Whatever `MIN_ACTIONS` is, no case comes back shorter — except a
    recording that was that short to begin with."""
    actions = [fill("a"), click("x"), click("Dismiss"), fill("a"), click("y")]

    for case in split(actions):
        assert len(case) >= MIN_ACTIONS


# ---------------------------------------------------------------------------
# Correcting a field is not starting over
#
# The rule that cuts on a field filled twice is right about a login form, where
# filling Email again means having another go. On a registration form it is
# wrong, and produces the one test nobody wants: a case that opens the form,
# types one field, submits, and waits thirty seconds for a confirmation that
# cannot arrive because the other seven fields are empty.
# ---------------------------------------------------------------------------
def test_fixing_one_field_of_a_form_does_not_split():
    """Taken from a real recording. The tester filled the form, was told the
    mobile number was invalid, corrected only that, and submitted again."""
    cases = split([
        fill("first_name"), fill("email"), fill("mobile"), fill("password"),
        click("Create Account"),
        fill("mobile"),                      # the correction
        click("Create Account"), click("Close"),
    ])

    assert len(cases) == 1, "the second attempt needs the other fields filled"


def test_filling_the_whole_form_again_does_split():
    """A real second attempt fills the form again — that one stands alone."""
    cases = split([
        fill("email"), fill("password"), click("Login"),
        fill("email"), fill("password"), click("Login"),
    ])

    assert len(cases) == 2


def test_a_correction_keeps_every_action():
    actions = [
        fill("first_name"), fill("mobile"), click("Create Account"),
        fill("mobile"), click("Create Account"),
    ]

    cases = split(actions)

    assert sum(len(case) for case in cases) == len(actions)
