"""Write a generated suite to disk so it can be opened in VS Code.

The database keeps the code so it can be executed and regenerated; the folder
on disk is the copy a QA Engineer actually reviews and edits.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^0-9a-zA-Z._-]+")

# Everything the generator emits. Anything outside this list is refused, so a
# malformed path can never write outside the suite folder.
ALLOWED_SUFFIXES = {".py", ".ini", ".md", ".json", ".txt"}


def safe_segment(text: str, fallback: str) -> str:
    cleaned = _UNSAFE.sub("-", text).strip("-.")
    return (cleaned[:60] or fallback).lower()


def suite_directory(project_id: int, project_name: str, suite_id: int, suite_name: str) -> Path:
    """Stable, readable location for one suite's files."""
    project_dir = f"{project_id:03d}-{safe_segment(project_name, 'project')}"
    suite_dir = f"{suite_id:03d}-{safe_segment(suite_name, 'suite')}"
    return settings.generated_dir / project_dir / suite_dir


def write_suite(target: Path, files: dict[str, str]) -> list[str]:
    """Write {relative path: content} under `target`. Returns the paths written.

    Files the generator no longer produces are removed, so a suite folder always
    matches the current recording instead of accumulating stale page objects
    from a previous run.
    """
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for relative, content in sorted(files.items()):
        destination = (target / relative).resolve()

        # Refuse anything that escapes the suite folder or has an unexpected
        # extension. Paths come from generated data, so this is not paranoia.
        if not destination.is_relative_to(target):
            logger.error("Refusing to write outside the suite folder: %s", relative)
            continue
        if destination.suffix not in ALLOWED_SUFFIXES:
            logger.error("Refusing to write unexpected file type: %s", relative)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
        written.append(relative)

    _prune(target, {(target / p).resolve() for p in written})
    return written


def _prune(target: Path, keep: set[Path]) -> None:
    """Delete generated files that are no longer part of the suite."""
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in ALLOWED_SUFFIXES:
            continue  # never touch anything we did not create
        if path.resolve() not in keep:
            try:
                path.unlink()
            except OSError:
                logger.debug("Could not remove stale file %s", path)

    # Tidy up directories left empty by pruning (pages/ with nothing in it).
    for directory in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            try:
                directory.rmdir()
            except OSError:
                pass
