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
        assert [a["sequence"] for a in actions] == list(range(len(actions)))
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
