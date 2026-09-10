"""Telling a defect from a test that never got to ask.

This is the rule the whole suite's credibility rests on: red means the
application is wrong. A test whose click never reached its element asked the
application nothing, so it has no verdict to report - and reporting it as a
failure sends a developer to look at a page that works. Do that twice and the
next red one gets dismissed too, which is the failure mode that actually costs
something.

One real run of thirteen tests: ten red, and eight of them were AutoQA unable
to act on a control - a checkbox drawn over a hidden input, a menu that was
never opened. Every one filed as a bug against a working site.

The line drawn here is Playwright's own: an assertion that failed is a claim
about the application; an action that could not reach its element is a claim
about nothing.
"""

from pathlib import Path

import pytest

from app.models.enums import ResultStatus
from app.runner.parser import could_not_run, parse_junit

# The two shapes, exactly as Playwright writes them.
HIDDEN = """
tests/test_project.py:39: in test_project
    properties.house.click()
E   playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.
E   Call log:
E     - waiting for get_by_label("House", exact=True).first
E       - locator resolved to <input type="checkbox"/>
E     - attempting click action
E       - element is not visible
"""

AMBIGUOUS = """
E   playwright._impl._errors.Error: Locator.click: Error: strict mode violation:
E   get_by_role("link", name="Home") resolved to 5 elements:
"""

NEVER_APPEARED = """
E   playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.
E   Call log:
E     - waiting for get_by_role("button", name="Submit")
"""

ASSERTION = """
tests/test_login.py:26: in test_login
    expect(unhealed(home, 'house_link')).to_be_visible()
E   AssertionError: Locator expected to be visible
E   Actual value: None
"""

DEAD_LINK = """
E   playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.
E   waiting for navigation to "https://x.test/find-agent" until 'load'
"""


# ---------------------------------------------------------------------------
# Could not act
# ---------------------------------------------------------------------------
def test_an_element_found_and_unusable_is_not_a_defect() -> None:
    """The commonest one by far. Sites hide the real input and draw a box over
    it; Playwright finds the input, refuses to click something invisible, and
    waits thirty seconds. Nothing about the application was ever asked."""
    assert could_not_run("Locator.click: Timeout 30000ms exceeded.", HIDDEN)


def test_a_locator_matching_several_elements_is_not_a_defect() -> None:
    """Playwright refused to guess which one. That is a fact about the
    locator."""
    assert could_not_run(None, AMBIGUOUS)


@pytest.mark.parametrize(
    "verb",
    ["click", "fill", "check", "uncheck", "select_option", "press", "hover",
     "dblclick", "set_input_files"],
)
def test_every_verb_that_drives_the_page_counts(verb: str) -> None:
    """The list has to be the actions, not a sample of them. A new one missed
    here is a whole class of false defect coming back."""
    trace = (
        f"Locator.{verb}: Timeout 30000ms exceeded.\n"
        "  - locator resolved to <input/>\n  - element is not visible"
    )

    assert could_not_run(None, trace)


# ---------------------------------------------------------------------------
# Still a defect
# ---------------------------------------------------------------------------
def test_a_failed_assertion_stays_a_failure() -> None:
    """The test reached the page, made a claim, and the claim was false. That
    is the thing this whole tool exists to find."""
    assert not could_not_run("AssertionError: Locator expected to be visible", ASSERTION)


def test_an_element_that_never_appeared_stays_a_failure() -> None:
    """Deliberately left red, and the reason is worth keeping.

    A page that genuinely does not render its Submit button looks identical to
    a selector that has gone stale - both are "waiting for" with nothing found.
    Between quietly downgrading a real defect and occasionally over-reporting
    one, only the second is recoverable.
    """
    assert not could_not_run(None, NEVER_APPEARED)


def test_a_click_that_did_not_navigate_stays_a_failure() -> None:
    """The click worked. The application did not go where it should have, which
    is a dead link and exactly what a tester wants told."""
    assert not could_not_run(None, DEAD_LINK)


def test_nothing_at_all_is_not_evidence_of_anything() -> None:
    assert not could_not_run(None, None)
    assert not could_not_run("", "")


# ---------------------------------------------------------------------------
# End to end, through the report pytest actually writes
# ---------------------------------------------------------------------------
# CDATA because a real traceback contains `<input .../>` and pytest escapes it;
# unescaped here it would parse as markup and the test would prove nothing.
JUNIT = f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="0" failures="2" skipped="0" tests="2">
    <testcase classname="tests.test_a" name="test_blocked[chromium]" time="30.1">
      <failure message="playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded."><![CDATA[{HIDDEN}]]></failure>
    </testcase>
    <testcase classname="tests.test_a" name="test_real[chromium]" time="1.2">
      <failure message="AssertionError: Locator expected to be visible"><![CDATA[{ASSERTION}]]></failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_the_report_separates_the_two(tmp_path: Path) -> None:
    path = tmp_path / "results.xml"
    path.write_text(JUNIT, encoding="utf-8")

    results = {r.function_name: r for r in parse_junit(path)}

    assert results["test_blocked"].status is ResultStatus.ERROR
    assert results["test_real"].status is ResultStatus.FAILED
    # The evidence survives the reclassification - a blocked test still has to
    # be diagnosable, it just must not be filed as a defect.
    assert "not visible" in results["test_blocked"].stack_trace


# ---------------------------------------------------------------------------
# Whose account of the failure leads
#
# The element diagnosis is an observation made after the fact: it says what was
# true of the element once the step had already failed. `_state` raises only
# after weighing what the application actually said and did. When both are
# present, the verdict is the cause and the diagnosis is a detail - and getting
# that the wrong way round produced a report that read
#
#   ELEMENT_NOT_READY: sign_in_button - it is on the page but was not usable in
#   time â€” ... failed and was NOT retried: HTTP 503 ...
#
# headlined "Blocked", under the words "That is a problem with the test, not
# evidence of a bug in your application" - about a 503 from the application's
# own server.
# ---------------------------------------------------------------------------
def _junit(tmp_path, *, diagnosis: str, trace: str, message: str):
    from app.runner.parser import parse_junit
    from xml.sax.saxutils import escape, quoteattr

    report = tmp_path / "results.xml"
    report.write_text(
        '<?xml version="1.0"?><testsuite>'
        '<testcase name="test_x[chromium]" time="3.0">'
        f'<properties><property name="autoqa_diagnosis" value={quoteattr(diagnosis)}/></properties>'
        f"<failure message={quoteattr(message)}>{escape(trace)}</failure>"
        "</testcase></testsuite>",
        encoding="utf-8",
    )
    return parse_junit(report)[0]


_A_503 = (
    'pages._state.StateConflict: Step 1 (Click "Sign in") failed and was NOT '
    "retried: HTTP 503 from https://app.test/login. That is not a data or state "
    "conflict, so the recorded step stands and this is a real failure."
)
_NOT_READY = (
    "ELEMENT_NOT_READY: sign_in_button - it is on the page but was not usable in time"
)


def test_the_reason_the_test_stopped_leads_the_report(tmp_path: Path) -> None:
    result = _junit(tmp_path, diagnosis=_NOT_READY, trace=_A_503,
                    message="StateConflict: HTTP 503 from https://app.test/login.")

    assert result.error_message.startswith("StateConflict")
    assert "HTTP 503" in result.error_message
    # Kept, because it is still worth knowing - just not first.
    assert _NOT_READY in result.error_message


def test_an_application_that_answered_is_a_failure_not_a_blocked_test(
    tmp_path: Path,
) -> None:
    """`ELEMENT_NOT_READY` maps to blocked, and blocked is reported as "the test
    never got as far as checking anything". That is true of an element nobody
    could reach; it is not true of a step the server answered 503."""
    result = _junit(tmp_path, diagnosis=_NOT_READY, trace=_A_503,
                    message="StateConflict: HTTP 503 from https://app.test/login.")

    assert result.status.value == "failed"


def test_without_a_verdict_the_diagnosis_still_leads(tmp_path: Path) -> None:
    """The other half. When the test has said nothing about why it stopped, what
    the browser found is the best account there is, and it goes first."""
    result = _junit(
        tmp_path,
        diagnosis="ELEMENT_HIDDEN: sign_in_button - it is present but not visible",
        trace="playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.",
        message="TimeoutError: Timeout 30000ms exceeded.",
    )

    assert result.error_message.startswith("ELEMENT_HIDDEN")
    assert result.status.value == "failed"


def test_running_out_of_data_is_still_blocked(tmp_path: Path) -> None:
    """Unchanged, and it must stay that way: the application was willing, the
    fixture is exhausted, and nobody should be sent to debug the application."""
    result = _junit(
        tmp_path,
        diagnosis=_NOT_READY,
        trace='pages._state.NoValidTestData: Step 9 (Click "Add"): the application '
              "refused the recorded data and every comparable alternative tried.",
        message="NoValidTestData: the application refused the recorded data",
    )

    assert result.status.value == "error"
    assert result.error_message.startswith("NoValidTestData")

