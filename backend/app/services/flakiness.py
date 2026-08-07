"""Which tests give a different answer each time you run them.

A test that always fails is useful: something is broken, go and fix it. A test
that fails one run in five is poison. Nobody can tell whether it found a bug or
just had a bad morning, so the habit becomes "run it again" — and once that
habit exists it gets applied to every red test, including the ones that were
right.

One flaky test is enough to make a whole suite untrustworthy, which is why this
is worth naming rather than leaving people to notice.

`ResultStatus.FLAKY` has been in the enum and rendered in two reports since the
beginning, and nothing ever set it. It still does not: flakiness is a property
of a test's *history*, not of any one result, and writing it onto a row would
be claiming a single run had noticed something it cannot see. It is worked out
here, from the runs, every time it is asked for.

No model is involved. This is counting.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import ResultStatus

#: Verdicts that count as the test having worked.
_GOOD = {ResultStatus.PASSED, ResultStatus.FLAKY}

#: Verdicts that count as the test having failed. SKIPPED is neither — a test
#: that did not run says nothing about whether it is reliable, and counting it
#: either way would invent a disagreement out of a run that never happened.
_BAD = {ResultStatus.FAILED, ResultStatus.ERROR}

#: How many runs a test has to have before this will call it anything. Two runs
#: that disagree is not evidence of unreliability — it is one change, and the
#: likeliest explanation is that somebody fixed or broke something between them.
MIN_RUNS = 3


@dataclass(frozen=True)
class Flaky:
    """One test and browser that cannot make its mind up."""

    test_case_id: int
    browser: str
    case_name: str
    #: How many of the recent runs it was in.
    runs: int
    passed: int
    failed: int
    #: How many times the verdict changed between consecutive runs. One flip is
    #: a test that broke and stayed broken; several is a test nobody can trust.
    flips: int

    @property
    def summary(self) -> str:
        return (
            f"{self.passed} passed and {self.failed} failed across "
            f"{self.runs} runs in {self.browser}"
        )


def flakiness(history: dict[tuple[int, str], list], *, min_runs: int = MIN_RUNS):
    """The tests whose verdict changes without the test changing.

    `history` is {(test case, browser): [results, newest first]}, as
    `history_per_case` returns it.

    The "without the test changing" half is not checked here because it does not
    need to be: editing a case or regenerating a suite discards that suite's
    runs, so everything still on record ran against the code that would run now.
    Two different answers over those runs is the test disagreeing with itself.
    """
    found: list[Flaky] = []

    for (case_id, browser), results in history.items():
        verdicts = [
            r.status in _GOOD
            for r in results
            if r.status in _GOOD or r.status in _BAD
        ]
        if len(verdicts) < min_runs:
            continue

        passed = sum(verdicts)
        failed = len(verdicts) - passed
        if not passed or not failed:
            continue  # consistently green, or consistently red. Both are honest.

        found.append(
            Flaky(
                test_case_id=case_id,
                browser=browser,
                case_name=getattr(results[0], "case_name", ""),
                runs=len(verdicts),
                passed=passed,
                failed=failed,
                flips=sum(
                    1 for a, b in zip(verdicts, verdicts[1:]) if a is not b
                ),
            )
        )

    # Worst first: the test that changes its mind most often is the one costing
    # the most attention.
    found.sort(key=lambda f: (-f.flips, -f.failed, f.case_name))
    return found
