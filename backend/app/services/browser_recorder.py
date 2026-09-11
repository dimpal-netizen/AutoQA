"""Launches a real browser and records what the user does in it.

A web page cannot inject a recorder into a different origin — the browser
forbids it. So the backend drives Chromium with Playwright and injects the
recorder itself. That works on any URL, needs no extension, and because
Playwright re-runs init scripts on every navigation, recording survives page
loads.

Actions come back through a Playwright binding rather than an HTTP request, so
the site under test never sees a token and there is no CORS to configure.

WHY THE SYNC API IN A THREAD, NOT ASYNC:
Playwright spawns a Node driver as a subprocess. On Windows, asyncio can only
do that on a ProactorEventLoop, and `uvicorn --reload` runs a SelectorEventLoop
— so the async API dies with a bare NotImplementedError. Rather than depend on
which loop the server happens to pick, each session gets its own thread running
the sync API. Playwright objects are not thread-safe, so that thread owns them
exclusively and the async wrappers below only signal it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from collections.abc import Callable

from playwright.sync_api import Page, sync_playwright

from app.core.config import settings
from app.core.database import session_scope
from app.models.enums import RecordingStatus
from app.repositories.recording_repo import RecordingRepository
from app.schemas.recording import ActionBatchIn
from app.services.exceptions import NotFound, ValidationError

logger = logging.getLogger(__name__)

RECORDER_JS = Path(__file__).resolve().parent.parent / "static" / "recorder.js"

# Guard against a forgotten browser window pinning a Chromium process forever.
MAX_SESSION_SECONDS = 60 * 60


class _ClosingFileHandler(logging.FileHandler):
    """A file handler that does not keep the file open between lines."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        finally:
            self.close()


def _log_to_a_file() -> None:
    """Also write recording diagnostics somewhere they survive the terminal.

    A recorder that stops part-way through is diagnosed from what the page said
    while it was still open, and that goes to the API's stdout - which is a
    console window somebody has already closed by the time they report it, or a
    service with no console at all. Everything else about a run is on disk; this
    should be too.

    Appends, because comparing a working recording with a broken one is most of
    the diagnosis. Small enough not to need rotating: a session writes a handful
    of lines unless something is going wrong, which is exactly when more of them
    are wanted.
    """
    if any(getattr(h, "_autoqa_recorder_log", False) for h in logger.handlers):
        return

    try:
        path = settings.storage_dir / "recorder.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Closed again after every line. A handler that holds the file open
        # pins the directory on Windows, and the volume here is a handful of
        # lines per session - there is nothing to gain by keeping it.
        handler = _ClosingFileHandler(path, encoding="utf-8", delay=True)
    except OSError:
        return  # nowhere to write is not a reason to fail a recording

    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    handler.setLevel(logging.INFO)
    handler._autoqa_recorder_log = True
    logger.addHandler(handler)
    logger.setLevel(min(logger.level or logging.INFO, logging.INFO))
LAUNCH_TIMEOUT_SECONDS = 90
POLL_MS = 250


@dataclass
class _Session:
    session_id: int
    thread: threading.Thread | None = None
    ready: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    stop_requested: threading.Event = field(default_factory=threading.Event)
    error: Exception | None = None
    result: dict[str, Any] | None = None
    duration_ms: int | None = None


# session_id -> live browser thread. Process-local: this is a single-process dev
# feature. If it ever needs to scale out it moves onto a Celery worker.
_sessions: dict[int, _Session] = {}
_lock = threading.Lock()


def is_running(session_id: int) -> bool:
    return session_id in _sessions


def running_session_ids() -> list[int]:
    return list(_sessions)


# ---------------------------------------------------------------------------
# Database access — all of this runs on the browser thread, which is fine
# because SQLAlchemy sessions are created and closed inside each call.
# ---------------------------------------------------------------------------
#: How deep a frame chain is followed before giving up on describing it. Frames
#: nest two or three deep in practice - an advert inside a widget inside a page -
#: and a document that nests further than this is one nobody is going to fix a
#: test against anyway.
MAX_FRAME_DEPTH = 8

#: `id` attributes a framework generated, which change on every build. The same
#: test the injected recorder applies to element ids, applied to frames.
_GENERATED_ID = re.compile(
    r"^:.+:$|^(ember|mui|radix|headless|react|ui|aria)-?\d|[0-9a-f]{8,}|^\d", re.I
)


def _describe_frames(frame) -> list[dict[str, Any]]:
    """The frames between the page and `frame`, outermost first.

    Worked out here rather than in the injected recorder, and that is the whole
    reason frames work at all. A script inside a cross-origin frame cannot see
    the document that holds it - `window.frameElement` throws, by design, and
    that design is a browser security boundary nobody should be trying to get
    around. Playwright sits outside the boundary and can see both sides, so the
    one place able to answer this is here.

    Each frame is described rather than numbered: what it is called, what it is
    titled, what it loads. `frame_root` picks a selector from that at generation
    time, and keeps the index only as a last resort - a page that gains a chat
    widget renumbers every frame after it.

    Best-effort in every part. A frame that will not answer a question about
    itself contributes what it could, and an empty descriptor still carries an
    index, which is enough to reach it.
    """
    chain: list[dict[str, Any]] = []
    current = frame

    for _ in range(MAX_FRAME_DEPTH):
        parent = current.parent_frame
        if parent is None:
            break                       # reached the main frame; we are done
        chain.append(_describe_frame(current, parent))
        current = parent

    chain.reverse()                     # outermost first, the order a browser needs
    return chain


def _describe_frame(frame, parent) -> dict[str, Any]:
    """One frame, from its own properties and its `<iframe>` element."""
    described: dict[str, Any] = {"url": (frame.url or "")[:2048] or None}

    name = frame.name
    if name:
        described["name"] = name[:256]

    try:
        element = frame.frame_element()
    except Exception:  # noqa: BLE001 - detached, or gone between question and answer
        element = None

    if element is not None:
        for key, attribute in (("title", "title"), ("element_id", "id"), ("src", "src")):
            try:
                value = element.get_attribute(attribute)
            except Exception:  # noqa: BLE001 - see above
                continue
            if value and not (attribute == "id" and _GENERATED_ID.search(value)):
                described[key] = value[:2048 if attribute == "src" else 256]

    # Position among its siblings. Last resort, and recorded even when better
    # answers exist - a frame that loses its name in a redesign still has one.
    try:
        described["index"] = list(parent.child_frames).index(frame)
    except (ValueError, Exception):  # noqa: BLE001 - not a child any more
        pass

    return {key: value for key, value in described.items() if value is not None}


def _store_actions(
    session_id: int, raw_actions: list[dict[str, Any]], *, frame: Any = None
) -> dict[str, int]:
    """Validate and persist a batch. Returns the same shape the API returns.

    A batch comes from one frame, because the injected recorder keeps its queue
    in the frame's own JavaScript context. So the frame chain is worked out once
    and stamped on every action in it - and only when the batch came from a
    frame at all, which leaves an action on the page itself with the empty
    `frame_path` it has always had.
    """
    if frame is not None:
        described = _describe_frames(frame)
        if described:
            # The recorder sends `frame_path: []` on every action - it cannot
            # fill it in - so an empty one is stamped, not only a missing one.
            for action in raw_actions:
                if not action.get("frame_path"):
                    action["frame_path"] = described

    # Record what this batch uses before it is written, so a page asking where
    # to continue cannot be told a number this batch is about to take - and so
    # the block it came from counts as spent.
    for action in raw_actions:
        try:
            _high_water[session_id] = max(
                _high_water.get(session_id, -1), int(action["sequence"])
            )
        except (KeyError, TypeError, ValueError):
            continue

    # Reuse the exact schema the extension will post through, so the two paths
    # cannot drift apart.
    batch = ActionBatchIn.model_validate({"actions": raw_actions})

    with session_scope() as db:
        repo = RecordingRepository(db)
        session = repo.get(session_id)
        if session is None:
            raise NotFound(f"Recording {session_id} not found")

        rows = [
            {
                "sequence": action.sequence,
                "action_type": action.action_type,
                "timestamp_ms": action.timestamp_ms,
                "url": action.url,
                "frame_path": [
                    f if isinstance(f, str) else f.model_dump(mode="json", exclude_none=True)
                    for f in action.frame_path
                ],
                "selectors": [s.model_dump(mode="json") for s in action.selectors],
                "element": action.element.model_dump(mode="json") if action.element else None,
                "payload": action.payload,
                "note": action.note,
                "is_ignored": False,
            }
            for action in batch.actions
        ]

        stored = repo.add_actions(session_id, rows)

        total = repo.count_actions(session_id)

        if stored != len(rows):

            # Sequences that were already taken. Silent by design - the

            # upload is idempotent - but silence is exactly what made a

            # recording that stopped growing impossible to explain.

            logger.warning(

                'Recording %s: %s of %s actions were dropped as duplicate sequences (%s)',

                session_id, len(rows) - stored, len(rows),

                [r['sequence'] for r in rows],

            )
        repo.update(session, action_count=total)
        return {"stored": stored, "skipped_duplicates": len(rows) - stored, "action_count": total}


#: The highest sequence each open recording has actually *stored*, remembered in
#: this process as well as in the database.
#:
#: The database alone is not enough, and the gap is small and expensive. A page
#: about to navigate flushes what it has, then the new document asks where to
#: continue - two messages, microseconds apart, the first still being written
#: when the second is answered.
_high_water: dict[int, int] = {}

#: The block each recording's newest page was given.
_block_start: dict[int, int] = {}

#: How many sequence numbers a page is given to itself.
#:
#: Sequence is an idempotency key before it is an ordering, and working it out
#: per page from what had been stored is only ever right while one page is live.
#: Open a link in a new tab and the new page asks where to continue while the
#: first page's actions are still sitting in its own queue, unflushed. It is
#: told zero, numbers from zero, and every action it uploads collides with one
#: already stored - `ON CONFLICT DO NOTHING` then drops them without a word.
#: Observed exactly that way: a new tab uploaded 0, 1, 2 and all three vanished.
#:
#: Ordering does not depend on the block: actions are read back by the clock all
#: the pages share. See `list_actions`.
SEQUENCE_BLOCK = 100_000


def _claim_block(session_id: int) -> int:
    """The first sequence a page starting now may use, reserved for it alone.

    A fresh block every time it is asked, and that is deliberate even though it
    means a recording's sequences are not contiguous. The tempting alternative -
    hand the same block out again until somebody has actually stored something
    in it - reintroduces the whole bug: a new tab asks where to begin *before*
    the page that opened it has flushed, so "nobody has used it yet" is exactly
    the moment two live pages are contending for it.

    Numbers are cheap and contiguity buys nothing. Sequence is an idempotency
    key; the ordering comes from the clock every page shares, so a gap costs
    only the mild surprise of seeing one.
    """
    used = _high_water.get(session_id, -1)
    current = _block_start.get(session_id)

    after = max(used + 1, 0 if current is None else current + SEQUENCE_BLOCK)
    start = -(-after // SEQUENCE_BLOCK) * SEQUENCE_BLOCK if after else 0

    _block_start[session_id] = start
    return start


def _session_progress(session_id: int) -> dict[str, int]:
    """Where the recording is up to — used when a page reloads mid-session."""
    with session_scope() as db:
        repo = RecordingRepository(db)
        count = repo.count_actions(session_id)
        stored = repo.max_timestamp_ms(session_id) or 0
        highest = repo.max_sequence(session_id)

    # Whatever is already stored is accounted for before a block is handed out,
    # so a backend restarted mid-recording does not reissue numbers.
    if highest is not None:
        _high_water[session_id] = max(_high_water.get(session_id, -1), highest)

    return {
        "actionCount": count,
        "nextSequence": _claim_block(session_id),
        "elapsedMs": stored,
    }


def _finalise(session_id: int, duration_ms: int | None) -> dict[str, Any]:
    """Mark the recording complete and turn it into a test suite.

    Reached three ways — Stop in the page panel, Stop in our web app, or the
    user simply closing the window — so the generation hook belongs here
    rather than on any one of them.
    """
    # Imported inside the function: codegen_service pulls in the recording
    # service, which would be a cycle at module level.
    from app.services.codegen_service import CodegenService

    with session_scope() as db:
        repo = RecordingRepository(db)
        session = repo.get(session_id)
        if session is None:
            raise NotFound(f"Recording {session_id} not found")

        total = repo.count_actions(session_id)
        already_finished = session.status is not RecordingStatus.RECORDING
        if not already_finished:
            repo.update(
                session,
                status=RecordingStatus.COMPLETED,
                duration_ms=(
                    duration_ms if duration_ms is not None else repo.max_timestamp_ms(session_id)
                ),
                action_count=total,
            )
            db.commit()

        suite = None
        if not already_finished:
            suite = CodegenService(db).autogenerate(
                session, created_by_id=session.created_by_id
            )

        # The block reservation dies with the recording. Held on to, a process
        # serving a long day of recordings would hand later sessions numbers
        # reserved for earlier ones - harmless, since sequences only have to be
        # unique within a session, but it makes a single-page recording start
        # at some large arbitrary number instead of zero, which is confusing to
        # anybody reading the actions and pointless to keep.
        _high_water.pop(session_id, None)
        _block_start.pop(session_id, None)

        return {
            "id": session_id,
            "action_count": total,
            "duration_ms": session.duration_ms,
            "suite_id": suite.id if suite else None,
        }


# ---------------------------------------------------------------------------
# The browser thread
# ---------------------------------------------------------------------------
def _run_browser(
    state: _Session,
    *,
    project_id: int,
    project_name: str,
    session_name: str,
    url: str,
    headless: bool,
    on_page_ready: Callable[[Page], None] | None,
) -> None:
    """Owns every Playwright object for one recording. Runs on its own thread."""
    session_id = state.session_id
    _log_to_a_file()
    recorder_js = RECORDER_JS.read_text(encoding="utf-8")

    def handle(source: dict, message: dict[str, Any]) -> Any:
        """Everything the injected recorder sends arrives here.

        `source` says which frame called, which is the one fact the injected
        script cannot work out for itself once a cross-origin frame is involved.
        """
        kind = message.get("type")
        try:
            if kind == "hello":
                # The one line that says the recorder came up on a document at
                # all. Without it, a page where nothing is captured and nothing
                # throws is indistinguishable from a page the injected script
                # never ran on - and those want completely different fixes.
                where = ""
                try:
                    frame = source.get("frame")
                    where = (frame.url if frame else "")[:200]
                except Exception:  # noqa: BLE001 - a name is not worth failing for
                    where = "?"
                logger.info("Recording %s: recorder started on %s", session_id, where)
                return {
                    "sessionId": session_id,
                    "sessionName": session_name,
                    "projectId": project_id,
                    "projectName": project_name,
                    **_session_progress(session_id),
                }
            if kind == "actions":
                batch = message["actions"]
                logger.info(
                    "Recording %s: batch of %s (%s) from %s",
                    session_id,
                    len(batch),
                    ", ".join(str(a.get("action_type")) for a in batch[:8]),
                    (batch[0].get("url") if batch else "")[:120],
                )
                return _store_actions(session_id, batch, frame=source.get("frame"))
            if kind == "stop":
                state.duration_ms = message.get("duration_ms")
                # Don't tear the browser down from inside the binding — the page
                # is still awaiting this call. Let the loop below do it.
                state.stop_requested.set()
                return _finalise(session_id, state.duration_ms)
        except Exception:
            logger.exception("Recording %s: failed handling %r", session_id, kind)
            return {"error": True}

        logger.warning("Recording %s: unknown message %r", session_id, kind)
        return {}

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    headless=headless,
                    args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
                )
            except Exception as exc:
                # By far the most common first-run failure, and the raw error is
                # a wall of box-drawing characters in a JSON response.
                if "Executable doesn't exist" in str(exc):
                    raise ValidationError(
                        "Playwright's browsers are not installed. Run: "
                        "poetry run playwright install chromium"
                    ) from exc
                raise ValidationError(f"Could not start a browser: {exc}") from exc

            context = browser.new_context(no_viewport=not headless)

            # expose_binding on the context covers every page and popup and
            # survives navigation; add_init_script re-runs on every document.
            context.expose_binding("__autoqaBridge", handle)
            context.add_init_script("window.__autoqaConfig = { mode: 'bridge' };")
            context.add_init_script(recorder_js)

            # Whatever goes wrong inside the recorded page, said out loud here.
            #
            # A recorder that stops part-way through leaves nothing behind: the
            # page is closed by the time anybody asks, the console went with it,
            # and all that survives is a session shorter than the journey. The
            # only thing that turns that into something diagnosable is having
            # written down what the page said while it was still open.
            #
            # Attached to every page in the context, so a popup or a new tab is
            # covered too, and to pages that appear later rather than only the
            # first one.
            def watch_page(target) -> None:
                target.on(
                    "pageerror",
                    lambda error: logger.warning(
                        "Recording %s: page error: %s", session_id, str(error)[:500]
                    ),
                )
                target.on(
                    "console",
                    lambda message: (
                        logger.warning(
                            "Recording %s: console %s: %s",
                            session_id, message.type, message.text[:500],
                        )
                        if "[AutoQA]" in (message.text or "")
                        else None
                    ),
                )
                target.on(
                    "framenavigated",
                    lambda frame: (
                        logger.info(
                            "Recording %s: navigated to %s", session_id, frame.url[:200]
                        )
                        if frame.parent_frame is None
                        else None
                    ),
                )
                target.on(
                    "close",
                    lambda: logger.info("Recording %s: a page was closed", session_id),
                )

            # `context.on("page")` already fires for `new_page()`, so watching
            # the first page explicitly as well logged everything twice.
            context.on("page", watch_page)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                raise ValidationError(f"Could not open {url}: {exc}") from exc

            # Runs on this thread, because Playwright objects belong to whoever
            # created them. `launch()` waits for it, which is what makes the
            # tests deterministic.
            if on_page_ready is not None:
                on_page_ready(page)

            state.ready.set()  # launch() can return now

            deadline = time.monotonic() + MAX_SESSION_SECONDS
            while not state.stop_requested.is_set():
                if not browser.is_connected():
                    logger.info("Recording %s: window closed by the user", session_id)
                    break
                if time.monotonic() > deadline:
                    logger.warning("Recording %s: hit the session cap, closing", session_id)
                    break
                try:
                    # Must be a Playwright call, not time.sleep(). The sync API
                    # only dispatches bindings while this thread is inside one,
                    # so sleeping would silently block every upload from the
                    # page for the whole session.
                    page.wait_for_timeout(POLL_MS)
                except Exception:
                    logger.info("Recording %s: page closed", session_id)
                    break

            try:
                state.result = _finalise(session_id, state.duration_ms)
            except Exception:
                logger.exception("Recording %s: could not finalise", session_id)

            for closer in (context.close, browser.close):
                try:
                    closer()
                except Exception:
                    logger.debug("Recording %s: already closed", session_id)

    except Exception as exc:  # noqa: BLE001 — surfaced to launch() below
        state.error = exc
        logger.exception("Recording %s: browser thread failed", session_id)
    finally:
        state.ready.set()  # never leave launch() waiting
        state.finished.set()
        with _lock:
            _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Async API used by the routes
# ---------------------------------------------------------------------------
async def launch(
    *,
    session_id: int,
    project_id: int,
    project_name: str,
    session_name: str,
    url: str,
    headless: bool = False,
    on_page_ready: Callable[[Page], None] | None = None,
) -> None:
    """Open `url` in a browser with the recorder injected.

    Returns once the page is open. Recording continues until the user presses
    Stop, closes the window, or `close()` is called.

    `on_page_ready` is called with the Page on the browser's own thread before
    this returns. Playwright objects belong to the thread that made them, so
    this is the only safe way to script the launched page — used by the tests
    to act as the user.
    """
    with _lock:
        if session_id in _sessions:
            raise ValidationError(f"Recording {session_id} is already open in a browser")
        state = _Session(session_id=session_id)
        _sessions[session_id] = state

    state.thread = threading.Thread(
        target=_run_browser,
        args=(state,),
        kwargs={
            "project_id": project_id,
            "project_name": project_name,
            "session_name": session_name,
            "url": url,
            "headless": headless,
            "on_page_ready": on_page_ready,
        },
        name=f"autoqa-recorder-{session_id}",
        daemon=True,
    )
    state.thread.start()

    opened = await asyncio.to_thread(state.ready.wait, LAUNCH_TIMEOUT_SECONDS)

    if state.error is not None:
        raise state.error
    if not opened:
        state.stop_requested.set()
        raise ValidationError(f"Timed out opening {url}")


async def close(session_id: int) -> dict[str, Any]:
    """Stop from the API side — the user pressed Stop in our web app."""
    state = _sessions.get(session_id)
    if state is None:
        raise NotFound(f"Recording {session_id} is not open in a browser")

    state.stop_requested.set()
    await asyncio.to_thread(state.finished.wait, 30)

    if state.result is not None:
        return state.result
    # The thread could not finalise (rare); do it here so the session is never
    # left stuck in "recording".
    return await asyncio.to_thread(_finalise, session_id, None)


async def close_all() -> None:
    """Called on API shutdown so no orphan Chromium processes are left behind."""
    for session_id in list(_sessions):
        try:
            await close(session_id)
        except Exception:
            logger.exception("Could not close recording %s", session_id)
