"""Files a test uploads, instead of a generated placeholder.

Shared by every project. A photograph is a photograph: the same handful serves
every listing form, avatar picker and document upload anybody records, and a
copy per project would mean uploading the same six pictures again for each one.
"""

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.schemas.project import SampleFileRead
from app.services.sample_file_service import SampleFileService

router = APIRouter(prefix="/sample-files", tags=["sample-files"])


@router.get("", response_model=list[SampleFileRead])
def list_sample_files(db: DbSession, user: CurrentUser) -> list[SampleFileRead]:
    return [SampleFileRead.model_validate(f) for f in SampleFileService(db).list()]


@router.post(
    "",
    response_model=SampleFileRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
async def add_sample_file(
    db: DbSession, user: CurrentUser, file: UploadFile = File(...)
) -> SampleFileRead:
    """Keep one file for tests to upload.

    Used from the next run onward, by every upload step in every project.
    Nothing has to be regenerated and no step has to be pointed at a file by
    hand.
    """
    record = SampleFileService(db).add(file.filename or "sample", await file.read())
    return SampleFileRead.model_validate(record)


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.QA_ENGINEER))],
)
def remove_sample_file(file_id: int, db: DbSession, user: CurrentUser) -> None:
    SampleFileService(db).remove(file_id)
