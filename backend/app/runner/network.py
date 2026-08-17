"""What the browser could not fetch, read back out of the Playwright trace.

A test that fails waiting for a page to change says only that it waited:

    playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.

which is true and useless. The reason was already on disk. From one real run,
the whole story in a line the report never showed:

       1.6s  POST  200  /api/v1/visits
       1.6s  GET   200  /api/v1/property-types
      17.4s  POST   -1  net::ERR_FAILED   /api/v1/users/auth/login

One request out of a hundred and forty-nine, and it was the login. The page sat
on the form because nothing had come back to it yet - not because the password
was wrong, not because a button moved.

Without this the gap gets filled by guesswork. The failure above was diagnosed
as "an application bug - verify the credentials are valid", raised at 85%
confidence against a login that works, while the evidence sat unread in a file
AutoQA had saved itself.
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: The entry Playwright writes its network log to inside a trace zip.
_NETWORK_ENTRY = "trace.network"

#: Enough to see a pattern, few enough to stay readable next to the error. A
#: page that lost its connection entirely fails hundreds of requests, and the
#: fourth one says nothing the third did not.
MAX_REPORTED = 3


@dataclass(frozen=True)
class FailedRequest:
    method: str
    url: str
    reason: str

    def __str__(self) -> str:
        return f"{self.method} {self.url} -> {self.reason}"


def failed_requests(trace: Path) -> list[FailedRequest]:
    """Every request in the trace that never got an answer, in time order.

    A status of -1 is Playwright's way of saying the request failed rather than
    returned: no code, no headers, no body. An HTTP error is not one of these -
    a 500 came back, and the page had something to react to.

    Never raises. A trace that is missing, truncated by a killed run, or written
    by a version that names things differently must not turn one unexplained
    failure into two.
    """
    try:
        with zipfile.ZipFile(trace) as archive:
            if _NETWORK_ENTRY not in archive.namelist():
                return []
            raw = archive.read(_NETWORK_ENTRY).decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile):
        logger.debug("Could not read the network log in %s", trace, exc_info=True)
        return []

    found: list[tuple[float, FailedRequest]] = []
    seen: set[tuple[str, str]] = set()

    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            snapshot = json.loads(line).get("snapshot") or {}
        except json.JSONDecodeError:
            continue

        request = snapshot.get("request") or {}
        response = snapshot.get("response") or {}
        url = request.get("url")
        reason = response.get("_failureText")
        if not url or not reason or response.get("status") not in (None, -1):
            continue

        method = str(request.get("method") or "GET")
        # The same asset retried three times is one fact, not three.
        key = (method, url)
        if key in seen:
            continue
        seen.add(key)
        found.append((float(snapshot.get("_monotonicTime") or 0), FailedRequest(
            method=method, url=url, reason=str(reason)
        )))

    return [request for _, request in sorted(found, key=lambda pair: pair[0])]


def describe(requests: list[FailedRequest]) -> str:
    """The failures as a line to sit under the error, or "" for none.

    Written to be read by whoever opens the failure and by the model that
    explains it, so it states the fact and draws no conclusion: a request that
    never completed may be the cause of the failure, a symptom of it, or an
    advert nobody misses.
    """
    if not requests:
        return ""

    count = len(requests)

    noun = "request" if count == 1 else "requests"
    lines = [f"{count} network {noun} failed during this test:"]
    lines += [f"  {request}" for request in requests[:MAX_REPORTED]]
    if count > MAX_REPORTED:
        lines.append(f"  ... and {count - MAX_REPORTED} more")
    return "\n".join(lines)


def alongside(error_message: str | None, trace: Path) -> str | None:
    """The error with the network evidence under it, or the error untouched.

    The joining lives here rather than at the call site so there is one place
    that decides how the two read together - and so a run with nothing to add
    gets back exactly what it had, rather than a message with a blank line
    grown on the end of it.
    """
    summary = describe(failed_requests(trace))
    if not summary:
        return error_message
    return "\n\n".join(part for part in (error_message, summary) if part).strip()
