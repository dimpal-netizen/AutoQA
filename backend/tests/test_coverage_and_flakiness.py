"""Two questions about a suite that need counting rather than a model.

**What is only covered by the happy path.** A recording walks one route and
everything on it works — that is what a recording is. The value of a suite is
in the cases written around it, so the number worth having is which parts of
the flow have no test except the one that was always going to pass.

**What cannot make its mind up.** A test that always fails is useful. A test
that fails one run in five is poison: nobody can tell whether it found a bug or
had a bad morning, so the habit becomes "run it again" — and that habit gets
applied to every red test, including the ones that were right.
"""

from dataclasses import dataclass, field

from app.codegen.converter import LocatorSpec, PageSpec
from app.models.enums import CaseCategory, ResultStatus
from app.services.coverage import coverage
from app.services.flakiness import MIN_RUNS, flakiness


# ---------------------------------------------------------------------------
# Only the happy path touches it
# ---------------------------------------------------------------------------
@dataclass
class FakeStep:
    locator: str | None


@dataclass
class FakeCase:
    category: CaseCategory = CaseCategory.NEGATIVE
    steps: list = field(default_factory=list)


def pages(*names) -> list[PageSpec]:
    page = PageSpec(class_name="LoginPage", module="login_page", url="https://x.test/login")
    for name in names:
        page.locators.append(
            LocatorSpec(
                name=name,
                expression=f"self.page.get_by_test_id('{name}')",
                strategy="test_id",
                fragile=False,
            )
        )
    return [page]


def case(*locators, category=CaseCategory.NEGATIVE) -> FakeCase:
    return FakeCase(category=category, steps=[FakeStep(loc) for loc in locators])


def test_an_element_no_other_case_drives_is_a_gap():
    found = coverage(
        pages("email_input", "password_input", "reveal_button"),
        [case("login.email_input", "login.password_input")],
    )

    assert found.total == 3
    assert found.touched == 2
    assert [u.element for u in found.untouched] == ["login.reveal_button"]


def test_the_recorded_case_does_not_count_as_cover():
    """It drives everything by definition — the page objects are built from it.

    The first version of this counted it, and reported 100% on every suite in
    the database. The number was arithmetic, not information.
    """
    found = coverage(
        pages("email_input", "password_input"),
        [case("login.email_input", "login.password_input", category=CaseCategory.RECORDED)],
    )

    assert found.percent == 0
    assert len(found.untouched) == 2


def test_a_suite_with_only_a_recording_reports_nothing_covered():
    found = coverage(pages("email_input"), [case(category=CaseCategory.RECORDED)])

    assert found.percent == 0


def test_everything_covered_reports_a_hundred():
    found = coverage(
        pages("email_input"), [case("login.email_input")]
    )

    assert found.percent == 100
    assert found.untouched == []


def test_the_percentage_rounds_down():
    """99 must never read as 100 while something is still missing."""
    found = coverage(
        pages(*[f"field_{i}" for i in range(3)]),
        [case("login.field_0", "login.field_1")],
    )

    assert found.percent == 66  # not 67


def test_incidental_elements_are_not_counted_against_you():
    """Nobody writes a test about the logo, and listing it buries the rest."""
    found = coverage(pages("email_input", "site_logo", "footer_link"), [case()])

    assert found.total == 1
    assert [u.element for u in found.untouched] == ["login.email_input"]


def test_a_brittle_element_is_flagged_and_listed_last():
    """A test written against it is brittle the day it is written, so it is the
    worst thing on the list to send someone at."""
    page = pages("email_input")[0]
    page.locators.append(
        LocatorSpec(name="third_div", expression="x", strategy="xpath", fragile=True)
    )

    found = coverage([page], [case()])

    assert [u.element for u in found.untouched] == [
        "login.email_input",
        "login.third_div",
    ]
    assert found.untouched[-1].fragile is True


def test_a_suite_with_no_elements_does_not_divide_by_zero():
    assert coverage(pages(), []).percent == 100


# ---------------------------------------------------------------------------
# Cannot make its mind up
# ---------------------------------------------------------------------------
@dataclass
class FakeResult:
    status: ResultStatus
    case_name: str = "Register buyer with valid credentials"


def history(*statuses, case_id=1, browser="chromium"):
    """Newest first, as the repository returns them."""
    return {(case_id, browser): [FakeResult(s) for s in statuses]}


PASS, FAIL = ResultStatus.PASSED, ResultStatus.FAILED


def test_a_test_that_changes_its_mind_is_flaky():
    found = flakiness(history(PASS, FAIL, PASS, FAIL))

    assert len(found) == 1
    assert found[0].passed == 2 and found[0].failed == 2
    assert found[0].flips == 3


def test_a_test_that_always_passes_is_not():
    assert flakiness(history(PASS, PASS, PASS, PASS)) == []


def test_a_test_that_always_fails_is_not():
    """It is broken, which is a different and more useful thing to be told."""
    assert flakiness(history(FAIL, FAIL, FAIL)) == []


def test_two_runs_are_not_enough_to_accuse_a_test():
    """One change is likelier to be somebody fixing or breaking something."""
    assert flakiness(history(PASS, FAIL)) == []
    assert len(flakiness(history(PASS, FAIL, PASS))) == 1
    assert MIN_RUNS == 3


def test_skipped_runs_do_not_invent_a_disagreement():
    """A test that did not run says nothing about whether it is reliable."""
    assert flakiness(history(PASS, ResultStatus.SKIPPED, PASS, PASS)) == []


def test_each_browser_is_judged_on_its_own():
    """Green in Chrome and red in WebKit is two stories; averaging hides both."""
    found = flakiness(
        {
            **history(PASS, PASS, PASS, browser="chromium"),
            **history(PASS, FAIL, PASS, browser="webkit"),
        }
    )

    assert [f.browser for f in found] == ["webkit"]


def test_the_worst_offender_is_first():
    """The test that changes its mind most often costs the most attention."""
    found = flakiness(
        {
            (1, "chromium"): [FakeResult(s) for s in (PASS, PASS, PASS, FAIL)],
            (2, "chromium"): [FakeResult(s) for s in (PASS, FAIL, PASS, FAIL)],
        }
    )

    assert [f.test_case_id for f in found] == [2, 1]


def test_the_summary_reads_as_a_sentence():
    found = flakiness(history(PASS, FAIL, PASS))

    assert found[0].summary == "2 passed and 1 failed across 3 runs in chromium"
