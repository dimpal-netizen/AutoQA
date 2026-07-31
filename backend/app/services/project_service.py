"""Project business logic."""

from sqlalchemy.orm import Session

from app.models.enums import ROLE_LEVEL, UserRole
from app.models.project import Project
from app.models.user import User
from app.repositories.project_repo import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.exceptions import AlreadyExists, Forbidden, NotFound


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)

    def list_for_user(self, user: User, skip: int = 0, limit: int = 100) -> list[Project]:
        # Test managers and admins oversee the whole instance, so they see
        # every project. Everyone else sees only their own.
        if ROLE_LEVEL[user.role] >= ROLE_LEVEL[UserRole.TEST_MANAGER]:
            return self.projects.list_all(skip=skip, limit=limit)
        return self.projects.get_by_owner(user.id, skip=skip, limit=limit)

    def get(self, project_id: int, user: User) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFound(f"Project {project_id} not found")

        self._assert_can_view(project, user)
        return project

    def create(self, data: ProjectCreate, owner: User) -> Project:
        if self.projects.name_taken_by_owner(owner.id, data.name):
            raise AlreadyExists(f"You already have a project named '{data.name}'")

        project = self.projects.create(
            name=data.name,
            base_url=str(data.base_url),
            description=data.description,
            default_browsers=[b.value for b in data.default_browsers],
            settings=data.settings,
            owner_id=owner.id,
        )
        self.db.commit()
        return project

    def update(self, project_id: int, data: ProjectUpdate, user: User) -> Project:
        project = self.get(project_id, user)
        self._assert_can_edit(project, user)

        values = data.model_dump(exclude_unset=True)

        if "name" in values and self.projects.name_taken_by_owner(
            project.owner_id, values["name"], exclude_id=project.id
        ):
            raise AlreadyExists(f"A project named '{values['name']}' already exists")

        if "base_url" in values and values["base_url"] is not None:
            values["base_url"] = str(values["base_url"])
        if "default_browsers" in values and values["default_browsers"] is not None:
            values["default_browsers"] = [b.value for b in values["default_browsers"]]

        project = self.projects.update(project, **values)
        self.db.commit()
        return project

    def delete(self, project_id: int, user: User) -> None:
        project = self.get(project_id, user)
        self._assert_can_edit(project, user)

        self.projects.delete(project)
        self.db.commit()

    # ------------------------------------------------------------------
    # Access rules
    # ------------------------------------------------------------------
    def _assert_can_view(self, project: Project, user: User) -> None:
        if project.owner_id == user.id:
            return
        if ROLE_LEVEL[user.role] >= ROLE_LEVEL[UserRole.TEST_MANAGER]:
            return
        # 404 rather than 403 — telling a stranger "this exists but isn't yours"
        # leaks which project ids are real.
        raise NotFound(f"Project {project.id} not found")

    def _assert_can_edit(self, project: Project, user: User) -> None:
        if project.owner_id == user.id:
            return
        if user.role is UserRole.ADMIN:
            return
        raise Forbidden("Only the project owner or an admin can change this project")
