"""The files a test uploads, instead of a generated placeholder.

A browser never says where a chosen file lives, so a recording of somebody
adding a property holds the name of their photograph and nothing else. A
generated 800x600 image uploads correctly and gets past the form - but it is a
grey rectangle, so a listing that shows its photographs back has nothing to
show.

Shared rather than per project: a photograph is a photograph, and a copy per
project would mean uploading the same six pictures again for each one.
"""

import pytest

from app.core.config import settings
from app.core.database import session_scope
from app.services.exceptions import ValidationError
from app.models.project import SampleFile
from app.services.sample_file_service import (
    ALLOWED,
    MAX_BYTES,
    SampleFileService,
    load_all,
    safe_name,
)

JPEG = b"\xff\xd8\xff" + b"a photograph" * 40 + b"\xff\xd9"


@pytest.fixture
def db_session():
    """A real session, and every file this test made cleaned up after it.

    Needs Postgres, like everything else here that touches a table. The rules
    about names and sizes need none and are not marked.
    """
    with session_scope() as session:
        yield session
        for record in session.query(SampleFile).all():
            try:
                (settings.storage_dir / record.file_path).unlink(missing_ok=True)
            except OSError:
                pass
            session.delete(record)


# ---------------------------------------------------------------------------
# A name is somebody else's string
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "given, expected",
    [
        ("house.jpg", "house.jpg"),
        ("../../conftest.py", "conftest.py"),
        (r"C:\Users\me\Pictures\front.jpg", "front.jpg"),
        ("photos/kitchen.png", "kitchen.png"),
        ("chalé.jpg", "chale.jpg"),
        ("my photo (2).jpg", "my-photo-2-.jpg"),
        ("...", "sample"),
    ],
)
def test_a_name_cannot_escape_the_folder_it_lands_in(given, expected) -> None:
    """`../../conftest.py` would overwrite the suite it was meant to be used by,
    and a name with a slash in it would land somewhere nobody looks."""
    assert safe_name(given) == expected


def test_every_allowed_kind_has_a_type_to_upload_it_as() -> None:
    """A site may check the extension or the type the browser reports. Both
    have to say the same thing, so neither can be missing."""
    assert all(ALLOWED.values())
    assert ALLOWED[".jpg"] == "image/jpeg"


# ---------------------------------------------------------------------------
# Refusing a file rather than carrying it into every run
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_an_empty_file_is_refused(db_session) -> None:
    with pytest.raises(ValidationError, match="empty"):
        SampleFileService(db_session).add("nothing.jpg", b"")


@pytest.mark.integration
def test_a_kind_no_form_would_take_is_refused(db_session) -> None:
    with pytest.raises(ValidationError, match="not a kind of file"):
        SampleFileService(db_session).add("payload.exe", b"MZ...")


@pytest.mark.integration
def test_something_far_too_big_is_refused(db_session) -> None:
    """A video dropped in by mistake would be copied into every run."""
    with pytest.raises(ValidationError, match="most a sample file can be"):
        SampleFileService(db_session).add("clip.png", b"\x89PNG" + b"x" * MAX_BYTES)


# ---------------------------------------------------------------------------
# Keeping and using them
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_a_file_is_stored_and_comes_back_by_the_name_it_uploads_under(db_session) -> None:
    service = SampleFileService(db_session)
    record = service.add("house front.jpg", JPEG)

    assert record.filename == "house-front.jpg"
    assert record.content_type == "image/jpeg"
    assert record.size == len(JPEG)
    assert load_all(db_session) == {"house-front.jpg": JPEG}


@pytest.mark.integration
def test_two_people_uploading_the_same_name_do_not_overwrite_each_other(db_session) -> None:
    service = SampleFileService(db_session)
    first = service.add("photo.jpg", JPEG)
    second = service.add("photo.jpg", JPEG + b"different")

    assert first.file_path != second.file_path
    assert len(load_all(db_session)) >= 1


@pytest.mark.integration
def test_a_deleted_file_stops_being_offered(db_session) -> None:
    service = SampleFileService(db_session)
    record = service.add("gone.jpg", JPEG)
    service.remove(record.id)

    assert "gone.jpg" not in load_all(db_session)


@pytest.mark.integration
def test_a_row_whose_file_vanished_is_skipped_not_raised_on(db_session) -> None:
    """The others are still usable, and a run that stops because one photograph
    was deleted from disk is a worse answer than one that uses the rest."""
    service = SampleFileService(db_session)
    kept = service.add("kept.jpg", JPEG)
    lost = service.add("lost.jpg", JPEG)
    (settings.storage_dir / lost.file_path).unlink()

    found = load_all(db_session)

    assert "kept.jpg" in found and "lost.jpg" not in found
    assert kept.filename in found
