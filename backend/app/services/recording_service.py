"""Recording business logic."""

from sqlalchemy.orm import Session

from app.models.enums import ROLE_LEVEL, RecordingStatus, UserRole
from app.models.recording import RecordedAction, RecordingSession
from app.models.user import User
from app.repositories.project_repo import ProjectRepository
from app.repositories.recording_repo import RecordingRepository
from app.schemas.recording import (
    ActionBatchIn,
    ActionBatchResult,
    RecordedActionUpdate,
    RecordingSessionCreate,
    RecordingSessionStop,
)
from app.services.exceptions import Forbidden, NotFound, ValidationError
from app.services.project_service import ProjectService


class RecordingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.recordings = RecordingRepository(db)
        self.projects = ProjectRepository(db)
        self.project_service = ProjectService(db)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def start(self, project_id: int, data: RecordingSessionCreate, user: User) -> RecordingSession:
        # Reuses the project access rules rather than restating them, so a user
        # can only record against a project they can actually see.
        self.project_service.get(project_id, user)

        session = self.recordings.create(
            project_id=project_id,
            created_by_id=user.id,
            name=data.name,
            start_url=str(data.start_url),
            status=RecordingStatus.RECORDING,
            browser_info=data.browser_info.model_dump(exclude_none=True),
            extension_version=data.extension_version,
            action_count=0,
        )
        self.db.commit()
        return session

    def get(self, session_id: int, user: User, *, with_actions: bool = False) -> RecordingSession:
        session = (
            self.recordings.get_with_actions(session_id)
            if with_actions
            else self.recordings.get(session_id)
        )
        if session is None:
            raise NotFound(f"Recording {session_id} not found")

        # 404 not 403 — don't confirm the recording exists to someone who
        # cannot see its project.
        try:
            self.project_service.get(session.project_id, user)
        except NotFound:
            raise NotFound(f"Recording {session_id} not found") from None

        return session

    def list_for_user(
        self, user: User, project_id: int | None = None, skip: int = 0, limit: int = 100
    ) -> list[RecordingSession]:
        if project_id is not None:
            self.project_service.get(project_id, user)  # raises if not visible
            project_ids = [project_id]
        else:
            visible = self.project_service.list_for_user(user, skip=0, limit=1000)
            project_ids = [p.id for p in visible]

        return self.recordings.list_for_projects(project_ids, skip=skip, limit=limit)

    def stop(self, session_id: int, data: RecordingSessionStop, user: User) -> RecordingSession:
        session = self.get(session_id, user)
        self._assert_open(session)

        # Trust the extension's clock if it sent one; otherwise fall back to the
        # last action's offset so the duration is never just null.
        duration = data.duration_ms
        if duration is None:
            duration = self.recordings.max_timestamp_ms(session_id)

        session = self.recordings.update(
            session,
            status=RecordingStatus.COMPLETED,
            duration_ms=duration,
            action_count=self.recordings.count_actions(session_id),
        )
        self.db.commit()
        return session

    def discard(self, session_id: int, user: User) -> RecordingSession:
        session = self.get(session_id, user)
        self._assert_open(session)

        session = self.recordings.update(session, status=RecordingStatus.DISCARDED)
        self.db.commit()
        return session

    def delete(self, session_id: int, user: User) -> None:
        session = self.get(session_id, user)
        self._assert_can_edit(session, user)

        self.recordings.delete(session)
        self.db.commit()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def add_actions(self, session_id: int, batch: ActionBatchIn, user: User) -> ActionBatchResult:
        session = self.get(session_id, user)
        self._assert_open(session)

        rows = [
            {
                "sequence": action.sequence,
                "action_type": action.action_type,
                "timestamp_ms": action.timestamp_ms,
                "url": action.url,
                "frame_path": action.frame_path,
                # mode="json" so enums become their string values — JSONB
                # cannot serialise a Python enum.
                "selectors": [s.model_dump(mode="json") for s in action.selectors],
                "element": action.element.model_dump(mode="json") if action.element else None,
                "payload": action.payload,
                "note": action.note,
                "is_ignored": False,
            }
            for action in batch.actions
        ]

        stored = self.recordings.add_actions(session_id, rows)
        total = self.recordings.count_actions(session_id)

        self.recordings.update(session, action_count=total)
        self.db.commit()

        return ActionBatchResult(
            stored=stored,
            skipped_duplicates=len(rows) - stored,
            action_count=total,
        )

    def list_actions(
        self, session_id: int, user: User, skip: int = 0, limit: int = 1000
    ) -> list[RecordedAction]:
        self.get(session_id, user)
        return self.recordings.list_actions(session_id, skip=skip, limit=limit)

    def update_action(
        self, session_id: int, action_id: int, data: RecordedActionUpdate, user: User
    ) -> RecordedAction:
        session = self.get(session_id, user)
        self._assert_can_edit(session, user)

        action = self.recordings.get_action(session_id, action_id)
        if action is None:
            raise NotFound(f"Action {action_id} not found in recording {session_id}")

        values = data.model_dump(exclude_unset=True)
        if "selectors" in values and values["selectors"] is not None:
            values["selectors"] = [s.model_dump(mode="json") for s in data.selectors or []]

        for field, value in values.items():
            setattr(action, field, value)

        self.db.flush()
        self.db.commit()
        self.db.refresh(action)
        return action

    def delete_action(self, session_id: int, action_id: int, user: User) -> None:
        session = self.get(session_id, user)
        self._assert_can_edit(session, user)

        action = self.recordings.get_action(session_id, action_id)
        if action is None:
            raise NotFound(f"Action {action_id} not found in recording {session_id}")

        self.recordings.delete_action(action)
        self.recordings.update(session, action_count=self.recordings.count_actions(session_id))
        self.db.commit()

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    def _assert_open(self, session: RecordingSession) -> None:
        if session.status is not RecordingStatus.RECORDING:
            raise ValidationError(
                f"Recording {session.id} is {session.status.value}; it can no longer be changed"
            )

    def _assert_can_edit(self, session: RecordingSession, user: User) -> None:
        if session.created_by_id == user.id:
            return
        if ROLE_LEVEL[user.role] >= ROLE_LEVEL[UserRole.QA_ENGINEER]:
            return
        raise Forbidden("Only the recorder or a QA engineer can change this recording")
