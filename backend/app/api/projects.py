"""Project routes."""

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: DbSession, user: CurrentUser, skip: int = 0, limit: int = 100
) -> list[ProjectRead]:
    """Your projects. Test managers and admins see all of them."""
    projects = ProjectService(db).list_for_user(user, skip=skip, limit=limit)
    return [ProjectRead.model_validate(p) for p in projects]


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def create_project(data: ProjectCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(db).create(data, user))


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: DbSession, user: CurrentUser) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(db).get(project_id, user))


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, data: ProjectUpdate, db: DbSession, user: CurrentUser
) -> ProjectRead:
    return ProjectRead.model_validate(ProjectService(db).update(project_id, data, user))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: DbSession, user: CurrentUser) -> None:
    ProjectService(db).delete(project_id, user)

