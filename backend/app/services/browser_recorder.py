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
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from collections.abc import Callable

from playwright.sync_api import Page, sync_playwright

from app.core.database import session_scope
from app.models.enums import RecordingStatus
from app.repositories.recording_repo import RecordingRepository
from app.schemas.recording import ActionBatchIn
from app.services.exceptions import NotFound, ValidationError

logger = logging.getLogger(__name__)

RECORDER_JS = Path(__file__).resolve().parent.parent / "static" / "recorder.js"

# Guard against a forgotten browser window pinning a Chromium process forever.
MAX_SESSION_SECONDS = 60 * 60
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
def _store_actions(session_id: int, raw_actions: list[dict[str, Any]]) -> dict[str, int]:
    """Validate and persist a batch. Returns the same shape the API returns."""
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
                "frame_path": action.frame_path,
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
        repo.update(session, action_count=total)
        return {"stored": stored, "skipped_duplicates": len(rows) - stored, "action_count": total}


def _session_progress(session_id: int) -> dict[str, int]:
    """Where the recording is up to — used when a page reloads mid-session."""
    with session_scope() as db:
        repo = RecordingRepository(db)
        count = repo.count_actions(session_id)
        return {
            "actionCount": count,
            "nextSequence": count,
            "elapsedMs": repo.max_timestamp_ms(session_id) or 0,
        }


def _finalise(session_id: int, duration_ms: int | None) -> dict[str, Any]:
    with session_scope() as db:
        repo = RecordingRepository(db)
        session = repo.get(session_id)
        if session is None:
            raise NotFound(f"Recording {session_id} not found")

        total = repo.count_actions(session_id)
        if session.status is RecordingStatus.RECORDING:
            repo.update(
                session,
                status=RecordingStatus.COMPLETED,
                duration_ms=(
                    duration_ms if duration_ms is not None else repo.max_timestamp_ms(session_id)
                ),
                action_count=total,
            )
        return {"id": session_id, "action_count": total, "duration_ms": session.duration_ms}


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
    recorder_js = RECORDER_JS.read_text(encoding="utf-8")

    def handle(_source: dict, message: dict[str, Any]) -> Any:
        """Everything the injected recorder sends arrives here."""
        kind = message.get("type")
        try:
            if kind == "hello":
                return {
                    "sessionId": session_id,
                    "sessionName": session_name,
                    "projectId": project_id,
                    "projectName": project_name,
                    **_session_progress(session_id),
                }
            if kind == "actions":
                return _store_actions(session_id, message["actions"])
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
