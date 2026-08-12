"""Real files for a test to upload, shared by every project.

A browser never tells a page where a chosen file lives - a security rule, not an
oversight - so a recording of somebody adding a property holds the name of their
photograph and nothing else. AutoQA builds a plain 800x600 image in its place,
which uploads correctly and is enough to get past the form.

It is still a grey rectangle. A site that resizes the photograph, checks it, or
shows it back on the listing afterwards deserves a photograph, and a test that
asserts the listing displays its images cannot be written against a placeholder.

So AutoQA keeps a handful. Upload them once and every upload step everywhere
uses them, in turn, without anybody wiring a step to a file by hand - a
photograph is a photograph, and keeping a separate copy per project would mean
uploading the same six pictures again for each one.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.project import SampleFile
from app.services.exceptions import NotFound, ValidationError

logger = logging.getLogger(__name__)

#: Big enough for a photograph off a phone, small enough that a video dropped in
#: by mistake is refused rather than copied into every run's workspace.
MAX_BYTES = 10 * 1024 * 1024

#: A library, not an asset pipeline. A hundred covers a listing form asking for
#: ten photographs, ten times over.
MAX_FILES = 100

#: What a file input will accept often enough to be worth keeping. Anything
#: else is rare, and the generated placeholder still covers it.
ALLOWED = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(filename: str) -> str:
    """A filename that cannot escape the folder it is written into.

    An uploaded name is somebody else's string. `../../conftest.py` would
    overwrite the suite it was meant to be used by, and a name with a slash in
    it would land somewhere nobody looks. Accents are folded rather than
    dropped, so `chale.jpg` stays recognisable.
    """
    stem = Path(filename.replace("\\", "/")).name
    folded = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    cleaned = _UNSAFE.sub("-", folded).strip("-.")
    return cleaned or "sample"


class SampleFileService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self) -> list[SampleFile]:
        return self.db.query(SampleFile).order_by(SampleFile.id).all()

    def add(self, filename: str, data: bytes) -> SampleFile:
        if not data:
            raise ValidationError("That file is empty.")
        if len(data) > MAX_BYTES:
            raise ValidationError(
                f"{safe_name(filename)} is too big. "
                f"{MAX_BYTES // (1024 * 1024)} MB is the most a sample file can be - "
                "these are copied into every run."
            )

        name = safe_name(filename)
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED:
            raise ValidationError(
                f"{name} is not a kind of file a test can upload. "
                f"Use one of: {', '.join(sorted(ALLOWED))}."
            )

        existing = self.db.query(SampleFile).count()
        if existing >= MAX_FILES:
            raise ValidationError(
                f"There are already {existing} sample files, which is the limit. "
                "Delete some first."
            )

        record = SampleFile(
            filename=name,
            content_type=ALLOWED[suffix],
            size=len(data),
            file_path="",  # needs the id, set below
        )
        self.db.add(record)
        self.db.flush()

        # The id in the path, so two people uploading `photo.jpg` do not
        # overwrite each other while the name they chose still survives.
        relative = f"samples/{record.id}-{name}"
        destination = settings.storage_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

        record.file_path = relative
        self.db.commit()
        self.db.refresh(record)
        logger.info("Added sample file %s (%d bytes)", name, len(data))
        return record

    def remove(self, file_id: int) -> None:
        record = self.db.get(SampleFile, file_id)
        if record is None:
            raise NotFound(f"Sample file {file_id} not found")

        path = settings.storage_dir / record.file_path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # The row goes either way. A file left behind is untidy; a row
            # pointing at nothing is a run that fails looking for it.
            logger.exception("Could not delete %s", path)

        self.db.delete(record)
        self.db.commit()


def load_all(db: Session) -> dict[str, bytes]:
    """Every sample file there is, keyed by the name to upload it under.

    Read at the point a suite is written or run rather than held anywhere, so
    adding a photograph takes effect on the next run without regenerating
    anything.

    A row whose file has gone missing is skipped rather than raised on: the
    others are still usable, and a run that stops because one photograph was
    deleted from disk is a worse answer than one that uses the other forty-nine.
    """
    records = db.query(SampleFile).order_by(SampleFile.id).all()

    files: dict[str, bytes] = {}
    for record in records:
        path = settings.storage_dir / record.file_path
        try:
            files[record.filename] = path.read_bytes()
        except OSError:
            logger.warning("Sample file %s is missing from %s", record.id, path)
    return files
