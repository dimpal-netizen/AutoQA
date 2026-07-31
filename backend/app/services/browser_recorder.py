"""Launches a real browser and records what the user does in it.

A web page cannot inject a recorder into a different origin — the browser
forbids it. So the backend drives Chromium with Playwright instead and injects
the recorder itself. That works on any URL, needs no extension, and because
Playwright re-runs init scripts on every navigation, recording survives page
loads.

Actions come back through a Playwright binding rather than an HTTP request, so
the site under test never sees a token and there is no CORS to configure.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.core.database import session_scope
from app.models.enums import RecordingStatus
from app.repositories.recording_repo import RecordingRepository
from app.schemas.recording import ActionBatchIn
from app.services.exceptions import NotFound, ValidationError

logger = logging.getLogger(__name__)

RECORDER_JS = Path(__file__).resolve().parent.parent / "static" / "recorder.js"

# Guard against a forgotten browser window pinning a Chromium process forever.
MAX_SESSION_SECONDS = 60 * 60


@dataclass
class LaunchedBrowser:
    session_id: int
    project_id: int
    project_name: str
    session_name: str
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    started_at: float
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
    closing: bool = False


# session_id -> live browser. Process-local: this is a single-process dev
# feature. Phase 5 moves execution onto Celery workers, and this can move with
# it if we ever need multiple API replicas.
_sessions: dict[int, LaunchedBrowser] = {}


def is_running(session_id: int) -> bool:
    return session_id in _sessions


def running_session_ids() -> list[int]:
    return list(_sessions)


# ---------------------------------------------------------------------------
# Database access (sync SQLAlchemy, so it runs in a worker thread)
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
        last = repo.max_timestamp_ms(session_id)
        return {"actionCount": count, "nextSequence": count, "elapsedMs": last or 0}


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
                duration_ms=duration_ms if duration_ms is not None else repo.max_timestamp_ms(session_id),
                action_count=total,
            )
        return {"id": session_id, "action_count": total, "duration_ms": session.duration_ms}


# ---------------------------------------------------------------------------
# Launching
# ---------------------------------------------------------------------------
async def launch(
    *,
    session_id: int,
    project_id: int,
    project_name: str,
    session_name: str,
    url: str,
    headless: bool = False,
) -> None:
    """Open `url` in a browser with the recorder injected.

    Returns as soon as the page is open; recording continues until the user
    presses Stop, closes the window, or `close()` is called.
    """
    if session_id in _sessions:
        raise ValidationError(f"Recording {session_id} is already open in a browser")

    recorder_js = RECORDER_JS.read_text(encoding="utf-8")

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(
            headless=headless,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(no_viewport=not headless)
    except Exception as exc:
        await playwright.stop()
        # By far the most common first-run failure, and the raw Playwright
        # error is a wall of box-drawing characters in a JSON response.
        if "Executable doesn't exist" in str(exc):
            raise ValidationError(
                "Playwright's browsers are not installed. Run: "
                "poetry run playwright install chromium"
            ) from exc
        raise ValidationError(f"Could not start a browser: {exc}") from exc

    launched = LaunchedBrowser(
        session_id=session_id,
        project_id=project_id,
        project_name=project_name,
        session_name=session_name,
        playwright=playwright,
        browser=browser,
        context=context,
        page=None,  # type: ignore[arg-type]
        started_at=asyncio.get_running_loop().time(),
    )

    async def handle(_source: dict, message: dict[str, Any]) -> Any:
        """Everything the injected recorder sends comes through here."""
        kind = message.get("type")

        if kind == "hello":
            progress = await asyncio.to_thread(_session_progress, session_id)
            return {
                "sessionId": session_id,
                "sessionName": session_name,
                "projectId": project_id,
                "projectName": project_name,
                **progress,
            }

        if kind == "actions":
            return await asyncio.to_thread(_store_actions, session_id, message["actions"])

        if kind == "stop":
            result = await asyncio.to_thread(_finalise, session_id, message.get("duration_ms"))
            # Close out of band: the page is still awaiting this call, and
            # tearing the browser down underneath it would raise.
            asyncio.create_task(_shutdown(session_id))
            return result

        logger.warning("Unknown recorder message: %s", kind)
        return {}

    # expose_binding on the context covers every page and popup, and survives
    # navigation. add_init_script re-runs the recorder on every document.
    await context.expose_binding("__autoqaBridge", handle)
    await context.add_init_script("window.__autoqaConfig = { mode: 'bridge' };")
    await context.add_init_script(recorder_js)

    page = await context.new_page()
    launched.page = page
    _sessions[session_id] = launched

    # If the user just closes the window, finalise rather than leaving the
    # recording stuck in "recording" forever.
    browser.on("disconnected", lambda _: asyncio.create_task(_on_disconnected(session_id)))

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        await _shutdown(session_id)
        raise ValidationError(f"Could not open {url}: {exc}") from exc

    asyncio.create_task(_expire_after_timeout(session_id))


async def _on_disconnected(session_id: int) -> None:
    launched = _sessions.get(session_id)
    if launched is None or launched.closing:
        return
    logger.info("Recording %s: browser window closed by the user", session_id)
    try:
        await asyncio.to_thread(_finalise, session_id, None)
    except Exception:
        logger.exception("Recording %s: could not finalise after disconnect", session_id)
    await _shutdown(session_id)


async def _expire_after_timeout(session_id: int) -> None:
    await asyncio.sleep(MAX_SESSION_SECONDS)
    if session_id in _sessions:
        logger.warning("Recording %s: hit the %ss cap, closing", session_id, MAX_SESSION_SECONDS)
        await close(session_id)


async def close(session_id: int) -> dict[str, Any]:
    """Stop from the API side — the user pressed Stop in our web app."""
    if session_id not in _sessions:
        raise NotFound(f"Recording {session_id} is not open in a browser")

    result = await asyncio.to_thread(_finalise, session_id, None)
    await _shutdown(session_id)
    return result


async def _shutdown(session_id: int) -> None:
    launched = _sessions.pop(session_id, None)
    if launched is None or launched.closing:
        return
    launched.closing = True

    for step, closer in (
        ("context", launched.context.close),
        ("browser", launched.browser.close),
        ("playwright", launched.playwright.stop),
    ):
        try:
            await closer()
        except Exception:
            logger.debug("Recording %s: %s already gone", session_id, step)

    launched.stopped.set()


async def close_all() -> None:
    """Called on API shutdown so no orphan Chromium processes are left behind."""
    for session_id in list(_sessions):
        try:
            await _shutdown(session_id)
        except Exception:
            logger.exception("Could not close recording %s", session_id)
