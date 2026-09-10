"""The launch-a-browser-and-record flow, end to end.

Opens a real (headless) Chromium through the service, drives the page the way a
person would, and checks the actions reach the database.

Run with: pytest -m integration
Needs `docker compose up -d` and `playwright install chromium`.
"""

import asyncio
import uuid
from pathlib import Path

import pytest

from app.core.database import session_scope
from app.core.security import hash_password
from app.models.enums import ActionType, RecordingStatus, UserRole
from app.repositories.project_repo import ProjectRepository
from app.repositories.recording_repo import RecordingRepository
from app.repositories.test_case_repo import TestSuiteRepository
from app.repositories.user_repo import UserRepository
from app.services import browser_recorder

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

DEMO_PAGE = (Path(__file__).parent / "fixtures" / "demo_page.html").resolve().as_uri()


@pytest.fixture
def recording_session() -> tuple[int, int]:
    """A user, a project, and an open recording session. Returns (session, project)."""
    with session_scope() as db:
        user = UserRepository(db).create(
            email=f"browser-{uuid.uuid4().hex[:10]}@example.com",
            hashed_password=hash_password("supersecret123"),
            full_name="Browser Test",
            role=UserRole.QA_ENGINEER,
            is_active=True,
        )
        project = ProjectRepository(db).create(
            name=f"Browser {uuid.uuid4().hex[:6]}",
            base_url="https://example.com",
            default_browsers=["chromium"],
            settings={},
            owner_id=user.id,
        )
        session = RecordingRepository(db).create(
            project_id=project.id,
            created_by_id=user.id,
            name="Launched by test",
            start_url=DEMO_PAGE,
            status=RecordingStatus.RECORDING,
            browser_info={},
            action_count=0,
        )
        return session.id, project.id


async def launch(session_id: int, project_id: int, on_page_ready=None) -> None:
    await browser_recorder.launch(
        session_id=session_id,
        project_id=project_id,
        project_name="Browser test",
        session_name="Launched by test",
        url=DEMO_PAGE,
        headless=True,
        on_page_ready=on_page_ready,
    )


def stored_actions(session_id: int) -> list[dict]:
    """Plain dicts — ORM instances would detach when the session closes."""
    with session_scope() as db:
        return [
            {
                "sequence": a.sequence,
                "action_type": a.action_type,
                "url": a.url,
                "selectors": a.selectors,
                "element": a.element,
                "payload": a.payload,
            }
            for a in RecordingRepository(db).list_actions(session_id)
        ]


async def wait_for_actions(session_id: int, count: int, timeout: float = 20.0) -> list[dict]:
    """The recorder uploads on a 2s timer, so poll rather than sleeping blindly."""
    deadline = asyncio.get_running_loop().time() + timeout
    actions: list[dict] = []
    while asyncio.get_running_loop().time() < deadline:
        actions = await asyncio.to_thread(stored_actions, session_id)
        if len(actions) >= count:
            return actions
        await asyncio.sleep(0.5)
    return actions


async def test_launch_records_the_opening_navigation(recording_session) -> None:
    session_id, project_id = recording_session
    await launch(session_id, project_id)
    try:
        actions = await wait_for_actions(session_id, 1)

        assert len(actions) >= 1
        assert actions[0]["action_type"] is ActionType.NAVIGATE
        assert browser_recorder.is_running(session_id)
    finally:
        await browser_recorder.close(session_id)


async def test_interaction_in_the_launched_browser_is_recorded(recording_session) -> None:
    session_id, project_id = recording_session

    def act_like_a_user(page) -> None:
        """Runs on the browser's own thread — see launch(on_page_ready=...)."""
        page.get_by_test_id("email-input").fill("buyer@example.com")
        page.get_by_label("Password").fill("hunter2000")
        page.get_by_test_id("remember-me").check()
        page.get_by_test_id("country-select").select_option("GB")
        page.get_by_test_id("login-submit").click()
        # The recorder buffers keystrokes and uploads on a timer; give it a
        # moment to flush before the assertions start polling.
        page.wait_for_timeout(2500)

    await launch(session_id, project_id, on_page_ready=act_like_a_user)
    try:
        actions = await wait_for_actions(session_id, 6)
        by_type = {a["action_type"]: a for a in actions}

        assert ActionType.INPUT in by_type, "typing was not recorded"
        assert ActionType.CHECK in by_type, "checkbox was not recorded"
        assert ActionType.SELECT in by_type, "dropdown was not recorded"
        assert ActionType.CLICK in by_type, "button click was not recorded"

        # The selector engine must have run inside the launched page.
        email = next(
            a for a in actions
            if a["action_type"] is ActionType.INPUT
            and a["payload"].get("value") == "buyer@example.com"
        )
        assert email["selectors"][0]["strategy"] == "test_id"
        assert email["selectors"][0]["value"] == "email-input"
        assert len(email["selectors"]) >= 3, "fallback candidates were not captured"

        # The password field has no data-testid; it must still resolve to
        # something semantic rather than a brittle CSS path.
        password = next(
            a for a in actions
            if a["action_type"] is ActionType.INPUT
            and a["payload"].get("value") == "hunter2000"
        )
        assert password["selectors"][0]["strategy"] in {"role_name", "label"}

        assert by_type[ActionType.SELECT]["payload"] == {"values": ["GB"]}
        # Unique and ascending, not contiguous. Every document the recorder is
        # injected into - `about:blank` included - is given its own block of
        # numbers, so two live pages cannot be handed the same one. See
        # `_claim_block`; putting the actions in order is the clock's job.
        sequences = [a["sequence"] for a in actions]
        assert len(sequences) == len(set(sequences)), "sequences collided"
        assert sequences == sorted(sequences), "sequences went backwards"
    finally:
        await browser_recorder.close(session_id)


async def test_clicking_an_icon_records_the_control_around_it(recording_session) -> None:
    """`event.target` is the deepest node under the cursor, which is routinely
    not what anyone means. Clicking a logo gives the <svg> inside the link;
    clicking a play button gives the <img> inside the button. Neither icon has a
    name, so the only way left to describe it is where it sits:

        html body header.Navbar-module__Sl14ZG__navbar a...logo svg

    which reads as nothing and breaks the moment anything above it moves. One
    recording of a property site produced four such steps, and every one of them
    was a link or a button with a perfectly good accessible name one level up.
    """
    session_id, project_id = recording_session

    def act_like_a_user(page) -> None:
        page.get_by_label("Homeske home").locator("svg").click()
        page.get_by_label("Play video").locator("img").click()
        page.wait_for_timeout(2500)

    await launch(session_id, project_id, on_page_ready=act_like_a_user)
    try:
        actions = await wait_for_actions(session_id, 3)
        clicks = [a for a in actions if a["action_type"] is ActionType.CLICK]
        recorded = {a["element"]["tag"]: a["element"]["accessible_name"] for a in clicks}

        assert "svg" not in recorded, "recorded the icon, not the link around it"
        assert "img" not in recorded, "recorded the icon, not the button around it"
        assert recorded.get("a") == "Homeske home"
        assert recorded.get("button") == "Play video"

        # And so the selector is one a person would recognise, rather than a
        # path that describes the markup of the day it was recorded.
        assert all(
            a["selectors"][0]["strategy"] not in {"css", "xpath", "nth_child"}
            for a in clicks
        )
    finally:
        await browser_recorder.close(session_id)


async def test_the_recorder_says_which_elements_a_step_revealed(
    recording_session,
) -> None:
    """The one fact a recording cannot be made to give up afterwards.

    Finished, "Close video" looks like any other button - good accessible name,
    real size, clicked once. It is simply not on the page until the video is
    playing, and no amount of reading the recording back will say so. Answered
    at the moment of the click, it is exact, and it is what keeps an invented
    case from opening the page and clicking a button that is not there.
    """
    session_id, project_id = recording_session

    def act_like_a_user(page) -> None:
        page.get_by_test_id("login-submit").click()      # there from the start
        page.get_by_label("Play video").click()          # reveals the next one
        page.get_by_text("Close video", exact=True).click()
        page.wait_for_timeout(2500)

    await launch(session_id, project_id, on_page_ready=act_like_a_user)
    try:
        actions = await wait_for_actions(session_id, 4)
        on_screen = {
            a["element"]["accessible_name"]: a["element"]["was_on_screen"]
            for a in actions
            if a["action_type"] is ActionType.CLICK and a["element"]
        }

        assert on_screen.get("Sign in") is True
        assert on_screen.get("Play video") is True
        assert on_screen.get("Close video") is False, (
            "the play click revealed it; the recorder must say so"
        )
    finally:
        await browser_recorder.close(session_id)


async def test_close_finalises_the_session(recording_session) -> None:
    session_id, project_id = recording_session
    await launch(session_id, project_id)
    await wait_for_actions(session_id, 1)

    result = await browser_recorder.close(session_id)

    assert result["action_count"] >= 1
    assert not browser_recorder.is_running(session_id)

    with session_scope() as db:
        session = RecordingRepository(db).get(session_id)
        assert session.status is RecordingStatus.COMPLETED
        assert session.action_count >= 1


async def test_closing_generates_a_test_suite(recording_session) -> None:
    """The whole point: record in a browser, close it, get runnable code."""
    session_id, project_id = recording_session

    def act_like_a_user(page) -> None:
        page.get_by_test_id("email-input").fill("buyer@example.com")
        page.get_by_test_id("remember-me").check()
        page.get_by_test_id("login-submit").click()
        page.wait_for_timeout(2500)

    await launch(session_id, project_id, on_page_ready=act_like_a_user)
    await wait_for_actions(session_id, 3)
    result = await browser_recorder.close(session_id)

    assert result["suite_id"] is not None, "closing the browser did not generate a suite"

    def read_suite() -> tuple[str, list[str]]:
        with session_scope() as db:
            suite = TestSuiteRepository(db).get_full(result["suite_id"])
            return suite.cases[0].code, [f.path for f in suite.files]

    code, paths = await asyncio.to_thread(read_suite)

    assert "def test_" in code
    assert ".fill('buyer@example.com')" in code
    # Not `.check()`. Sites hide the real input behind a styled box, and
    # Playwright will not act on an element with no size — see `set_checked`.
    assert "set_checked(" in code
    assert "conftest.py" in paths
    assert any(p.startswith("pages/") for p in paths)


async def test_closing_an_unknown_session_raises(recording_session) -> None:
    from app.services.exceptions import NotFound

    with pytest.raises(NotFound):
        await browser_recorder.close(999_999)


async def test_launching_twice_is_rejected(recording_session) -> None:
    from app.services.exceptions import ValidationError

    session_id, project_id = recording_session
    await launch(session_id, project_id)
    try:
        with pytest.raises(ValidationError, match="already open"):
            await launch(session_id, project_id)
    finally:
        await browser_recorder.close(session_id)


# ---------------------------------------------------------------------------
# Numbering across pages
#
# Sequence is an idempotency key before it is an ordering. Working it out per
# page from what had been *stored* is right only while one page is live: open a
# link in a new tab and the new page asks where to continue while the first
# page's actions are still in its own queue, is told zero, and every action it
# uploads collides with one already there. `ON CONFLICT DO NOTHING` drops them
# in silence and the tab contributes nothing to the recording.
#
# Observed exactly that way - a new tab uploaded 0, 1, 2 and all three vanished.
# ---------------------------------------------------------------------------
def test_the_first_page_of_a_recording_numbers_from_zero(recording_session) -> None:
    """The common case, and the one worth keeping readable."""
    session_id, _ = recording_session

    from app.services.browser_recorder import _session_progress

    assert _session_progress(session_id)["nextSequence"] == 0


def test_a_second_page_is_given_numbers_the_first_cannot_reach(
    recording_session,
) -> None:
    """Even though the first page has stored nothing yet, which is precisely
    the moment a new tab asks."""
    session_id, _ = recording_session

    from app.services.browser_recorder import SEQUENCE_BLOCK, _session_progress

    first = _session_progress(session_id)["nextSequence"]
    second = _session_progress(session_id)["nextSequence"]

    assert first == 0
    assert second >= first + SEQUENCE_BLOCK


def test_a_backend_restarted_mid_recording_does_not_reissue_numbers(
    recording_session,
) -> None:
    """Whatever is already stored is accounted for before a block is handed
    out, so the in-process reservation is an optimisation and not the only
    thing keeping numbers apart."""
    session_id, _ = recording_session

    from app.services import browser_recorder

    browser_recorder._store_actions(session_id, [{
        "sequence": 40, "action_type": "click", "timestamp_ms": 10,
        "url": "https://x.test/", "frame_path": [],
        "selectors": [{"strategy": "text", "value": "Go"}],
        "element": {"tag": "button", "attributes": {}}, "payload": {},
    }])
    browser_recorder._high_water.clear()          # as if the process restarted

    assert browser_recorder._session_progress(session_id)["nextSequence"] > 40


def test_a_finished_recording_releases_its_reservation(recording_session) -> None:
    session_id, _ = recording_session

    from app.services import browser_recorder

    browser_recorder._session_progress(session_id)
    assert session_id in browser_recorder._block_start

    browser_recorder._finalise(session_id, None)
    assert session_id not in browser_recorder._block_start
    assert session_id not in browser_recorder._high_water
