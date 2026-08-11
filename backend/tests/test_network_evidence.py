"""Reading the failure out of the trace we already saved.

A test that fails waiting for a page to change says only that it waited:

    playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.

From one real run, the reason was one line in a file AutoQA had written itself:

      17.4s  POST  -1  net::ERR_FAILED  /api/v1/users/auth/login

One request out of a hundred and forty-nine, and it was the login. The page sat
on the form because nothing had come back to it. Unread, the gap got filled by
guesswork instead: "an application bug - verify the credentials are valid",
raised at 85% confidence against a login that works.
"""

import json
import zipfile
from pathlib import Path

import pytest

from app.runner.network import MAX_REPORTED, alongside, describe, failed_requests

TIMEOUT = "playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded."


def entry(url, *, method="GET", status=200, failure=None, at=0.0):
    response = {"status": status}
    if failure is not None:
        response["_failureText"] = failure
    return json.dumps(
        {"snapshot": {"_monotonicTime": at,
                      "request": {"url": url, "method": method},
                      "response": response}}
    )


def trace(tmp_path, lines, *, name="trace.zip", entry_name="trace.network") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry_name, "\n".join(lines))
    return path


# ---------------------------------------------------------------------------
# Reading the log
# ---------------------------------------------------------------------------
def test_a_request_that_never_answered_is_found(tmp_path) -> None:
    """Status -1 is Playwright saying the request failed rather than returned:
    no code, no headers, no body."""
    path = trace(tmp_path, [
        entry("https://app.test/api/visits", method="POST", at=1.6),
        entry("https://api.test/v1/users/auth/login", method="POST",
              status=-1, failure="net::ERR_FAILED", at=17.4),
    ])

    found = failed_requests(path)

    assert [str(r) for r in found] == [
        "POST https://api.test/v1/users/auth/login -> net::ERR_FAILED"
    ]


def test_an_http_error_is_not_one_of_these(tmp_path) -> None:
    """A 500 came back, and the page had something to react to. Reporting it
    here would bury the requests that genuinely went unanswered."""
    path = trace(tmp_path, [
        entry("https://app.test/api/save", method="POST", status=500),
        entry("https://app.test/missing", status=404),
    ])

    assert failed_requests(path) == []


def test_failures_come_back_in_the_order_they_happened(tmp_path) -> None:
    """Which one went first is most of the story when several fail."""
    path = trace(tmp_path, [
        entry("https://app.test/late", status=-1, failure="net::ERR_ABORTED", at=9.0),
        entry("https://app.test/early", status=-1, failure="net::ERR_FAILED", at=1.0),
    ])

    assert [r.url for r in failed_requests(path)] == [
        "https://app.test/early", "https://app.test/late",
    ]


def test_the_same_request_retried_is_one_fact(tmp_path) -> None:
    path = trace(tmp_path, [
        entry("https://app.test/x", status=-1, failure="net::ERR_FAILED", at=t)
        for t in (1.0, 2.0, 3.0)
    ])

    assert len(failed_requests(path)) == 1


# ---------------------------------------------------------------------------
# Never making one unexplained failure into two
# ---------------------------------------------------------------------------
def test_a_missing_trace_is_silent(tmp_path) -> None:
    assert failed_requests(tmp_path / "nothing.zip") == []


def test_a_trace_killed_mid_write_is_silent(tmp_path) -> None:
    """Stopping a run leaves half a zip behind. That is not worth an error of
    its own on top of the failure being explained."""
    path = tmp_path / "half.zip"
    path.write_bytes(b"PK\x03\x04 truncated")

    assert failed_requests(path) == []


def test_a_trace_without_a_network_log_is_silent(tmp_path) -> None:
    assert failed_requests(trace(tmp_path, ["{}"], entry_name="trace.trace")) == []


def test_a_line_that_will_not_parse_is_skipped_not_fatal(tmp_path) -> None:
    """One bad line must not cost the good ones."""
    path = trace(tmp_path, [
        "{ this is not json",
        "",
        entry("https://app.test/x", status=-1, failure="net::ERR_FAILED"),
    ])

    assert len(failed_requests(path)) == 1


# ---------------------------------------------------------------------------
# How it reads
# ---------------------------------------------------------------------------
def test_the_summary_states_the_fact_and_draws_no_conclusion(tmp_path) -> None:
    """A request that never completed may be the cause of the failure, a
    symptom of it, or an advert nobody misses. Saying which is not this job."""
    path = trace(tmp_path, [
        entry("https://api.test/v1/users/auth/login", method="POST",
              status=-1, failure="net::ERR_FAILED"),
    ])

    summary = describe(failed_requests(path))

    assert summary.startswith("1 network request failed during this test:")
    assert "POST https://api.test/v1/users/auth/login -> net::ERR_FAILED" in summary
    for word in ("because", "cause", "bug", "should"):
        assert word not in summary.lower()


def test_a_page_that_lost_its_connection_is_summarised_not_dumped(tmp_path) -> None:
    """Hundreds of failures say nothing the third did not, and an error nobody
    scrolls to the end of is an error nobody reads."""
    path = trace(tmp_path, [
        entry(f"https://app.test/asset-{n}", status=-1,
              failure="net::ERR_INTERNET_DISCONNECTED", at=n)
        for n in range(40)
    ])

    summary = describe(failed_requests(path))

    assert summary.startswith("40 network requests failed")
    assert summary.count("net::ERR_INTERNET_DISCONNECTED") == MAX_REPORTED
    assert f"and {40 - MAX_REPORTED} more" in summary


def test_the_evidence_goes_under_the_error_not_over_it(tmp_path) -> None:
    path = trace(tmp_path, [
        entry("https://api.test/login", method="POST", status=-1,
              failure="net::ERR_FAILED"),
    ])

    joined = alongside(TIMEOUT, path)

    assert joined.startswith(TIMEOUT)
    assert joined.index(TIMEOUT) < joined.index("net::ERR_FAILED")


def test_a_run_with_nothing_to_add_gets_back_what_it_had(tmp_path) -> None:
    """Not the same message with a blank line grown on the end of it."""
    path = trace(tmp_path, [entry("https://app.test/fine")])

    assert alongside(TIMEOUT, path) == TIMEOUT


@pytest.mark.parametrize("original", [None, ""])
def test_an_error_with_no_message_still_gets_the_evidence(tmp_path, original) -> None:
    path = trace(tmp_path, [
        entry("https://api.test/login", status=-1, failure="net::ERR_FAILED"),
    ])

    joined = alongside(original, path)

    assert joined.startswith("1 network request failed")
