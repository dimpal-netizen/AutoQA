"""Recording routes.

The first three are what the Chrome extension calls: start, upload batches
while recording, stop.
"""

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.recording import (
    ActionBatchIn,
    ActionBatchResult,
    RecordedActionRead,
    RecordedActionUpdate,
    RecordingLaunch,
    RecordingProgress,
    RecordingSessionCreate,
    RecordingSessionDetail,
    RecordingSessionLive,
    RecordingSessionRead,
    RecordingSessionStop,
)
from app.services import browser_recorder
from app.services.recording_service import RecordingService

router = APIRouter(tags=["recordings"])


# --- launch a real browser ----------------------------------------------
@router.post(
    "/projects/{project_id}/recordings/launch",
    response_model=RecordingSessionLive,
    status_code=status.HTTP_201_CREATED,
)
async def launch_recording(
    project_id: int, data: RecordingLaunch, db: DbSession, user: CurrentUser
) -> RecordingSessionLive:
    """Open a URL in a browser with the recorder injected, and start recording.

    This is how you record a site we do not own: the page cannot inject a
    recorder across origins, so Playwright does it from outside.
    """
    service = RecordingService(db)
    # Named after the project, not the host it points at. "Recording of
    # homeske-dev.betaeserver.com" restated the project's own URL, so a page
    # already headed "Report Problem" carried a second title saying nothing new
    # - and three recordings of one site were indistinguishable from each other.
    project = service.project_service.get(project_id, user)
    session = service.start(
        project_id,
        RecordingSessionCreate(
            name=data.name or project.name,
            start_url=data.url,
            extension_version="playwright-0.1.0",
        ),
        user,
    )

    await browser_recorder.launch(
        session_id=session.id,
        project_id=session.project_id,
        project_name=session.project.name,
        session_name=session.name,
        url=str(data.url),
        headless=data.headless,
    )

    db.refresh(session)
    return RecordingSessionLive.model_validate(session).model_copy(
        update={"browser_open": True}
    )


@router.post("/recordings/{session_id}/close", response_model=RecordingSessionRead)
async def close_recording(
    session_id: int, db: DbSession, user: CurrentUser
) -> RecordingSessionRead:
    """Stop a launched browser from our web app rather than from its own panel."""
    service = RecordingService(db)
    service.get(session_id, user)  # permission check

    await browser_recorder.close(session_id)

    db.expire_all()
    return RecordingSessionRead.model_validate(service.get(session_id, user))


# --- extension-facing ---------------------------------------------------
@router.post(
    "/projects/{project_id}/recordings",
    response_model=RecordingSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def start_recording(
    project_id: int, data: RecordingSessionCreate, db: DbSession, user: CurrentUser
) -> RecordingSessionRead:
    """Begin a session. Returns the id the extension posts actions against."""
    return RecordingSessionRead.model_validate(
        RecordingService(db).start(project_id, data, user)
    )


@router.post("/recordings/{session_id}/actions", response_model=ActionBatchResult)
def upload_actions(
    session_id: int, batch: ActionBatchIn, db: DbSession, user: CurrentUser
) -> ActionBatchResult:
    """Append a batch of actions.

    Idempotent: an action whose sequence is already stored is skipped, so the
    extension can safely retry a batch after a dropped connection.
    """
    return RecordingService(db).add_actions(session_id, batch, user)


@router.get("/recordings/{session_id}/progress", response_model=RecordingProgress)
def recording_progress(
    session_id: int, db: DbSession, user: CurrentUser
) -> RecordingProgress:
    """Where the recording is up to.

    The extension asks this whenever a page it is recording (re)loads, so a
    new document continues the sequence numbers instead of starting again at
    zero and colliding with what is already stored.
    """
    return RecordingService(db).progress(session_id, user)


@router.post("/recordings/{session_id}/stop", response_model=RecordingSessionRead)
def stop_recording(
    session_id: int, data: RecordingSessionStop, db: DbSession, user: CurrentUser
) -> RecordingSessionRead:
    return RecordingSessionRead.model_validate(RecordingService(db).stop(session_id, data, user))


@router.post("/recordings/{session_id}/discard", response_model=RecordingSessionRead)
def discard_recording(
    session_id: int, db: DbSession, user: CurrentUser
) -> RecordingSessionRead:
    return RecordingSessionRead.model_validate(RecordingService(db).discard(session_id, user))


# --- app-facing ---------------------------------------------------------
@router.get("/recordings", response_model=list[RecordingSessionLive])
def list_recordings(
    db: DbSession,
    user: CurrentUser,
    project_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[RecordingSessionLive]:
    sessions = RecordingService(db).list_for_user(user, project_id, skip=skip, limit=limit)
    live = set(browser_recorder.running_session_ids())
    return [
        RecordingSessionLive.model_validate(s).model_copy(
            update={"browser_open": s.id in live}
        )
        for s in sessions
    ]


@router.get("/recordings/{session_id}", response_model=RecordingSessionDetail)
def get_recording(
    session_id: int, db: DbSession, user: CurrentUser
) -> RecordingSessionDetail:
    """The session plus every action, in order."""
    return RecordingSessionDetail.model_validate(
        RecordingService(db).get(session_id, user, with_actions=True)
    )


@router.get("/recordings/{session_id}/actions", response_model=list[RecordedActionRead])
def list_actions(
    session_id: int, db: DbSession, user: CurrentUser, skip: int = 0, limit: int = 1000
) -> list[RecordedActionRead]:
    actions = RecordingService(db).list_actions(session_id, user, skip=skip, limit=limit)
    return [RecordedActionRead.model_validate(a) for a in actions]


@router.patch(
    "/recordings/{session_id}/actions/{action_id}",
    response_model=RecordedActionRead,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def update_action(
    session_id: int,
    action_id: int,
    data: RecordedActionUpdate,
    db: DbSession,
    user: CurrentUser,
) -> RecordedActionRead:
    """Fix a bad selector, or mark a noisy step as ignored."""
    return RecordedActionRead.model_validate(
        RecordingService(db).update_action(session_id, action_id, data, user)
    )


@router.delete(
    "/recordings/{session_id}/actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def delete_action(session_id: int, action_id: int, db: DbSession, user: CurrentUser) -> None:
    RecordingService(db).delete_action(session_id, action_id, user)


@router.delete("/recordings/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recording(session_id: int, db: DbSession, user: CurrentUser) -> None:
    RecordingService(db).delete(session_id, user)
