"""Render a TestIR into files, and refuse to emit anything that won't import.

Generated code is executed later, so a syntax error here becomes a confusing
runtime failure three phases away. Every file is parsed before it is returned.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.codegen.converter import TestIR, page_variables
from app.codegen.selectors import py_str
from app.models.enums import FileType

TEMPLATES = Path(__file__).resolve().parent / "templates"

DEFAULT_VIEWPORT = (1280, 720)


@dataclass
class GeneratedFileSpec:
    path: str
    content: str
    file_type: FileType


class GeneratedCodeError(Exception):
    """A rendered file failed to parse. Never returned to the caller as code."""


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        # StrictUndefined so a template typo fails loudly here instead of
        # silently emitting an empty string into someone's test file.
        undefined=StrictUndefined,
        # Both are needed for indented output: trim_blocks drops the newline
        # after a tag, lstrip_blocks drops the indentation before it. Without
        # the pair, control tags leak whitespace and the emitted Python has
        # everything on one line.
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["pystr"] = py_str
    return env


def render(ir: TestIR, *, browser_info: dict[str, Any] | None = None) -> list[GeneratedFileSpec]:
    """TestIR → the full set of files, each validated."""
    env = _environment()
    page_vars = page_variables(ir)
    modules = {page.class_name: page.module for page in ir.pages}

    files: list[GeneratedFileSpec] = [
        GeneratedFileSpec(
            path=ir.file_path,
            content=env.get_template("test_module.py.j2").render(
                ir=ir, page_vars=page_vars, modules=modules
            ),
            file_type=FileType.TEST,
        )
    ]

    for page in ir.pages:
        files.append(
            GeneratedFileSpec(
                path=f"pages/{page.module}.py",
                content=env.get_template("page_object.py.j2").render(page=page),
                file_type=FileType.PAGE_OBJECT,
            )
        )

    width, height = _viewport(browser_info)
    files.append(
        GeneratedFileSpec(
            path="conftest.py",
            content=env.get_template("conftest.py.j2").render(
                base_url=ir.start_url, viewport_width=width, viewport_height=height
            ),
            file_type=FileType.CONFTEST,
        )
    )
    files.append(
        GeneratedFileSpec(
            path="pytest.ini",
            content=env.get_template("pytest.ini.j2").render(),
            file_type=FileType.CONFIG,
        )
    )

    for spec in files:
        validate(spec)

    return files


def _viewport(browser_info: dict[str, Any] | None) -> tuple[int, int]:
    """Reuse the viewport the recording was made at, so layout matches."""
    viewport = (browser_info or {}).get("viewport") or {}
    try:
        width = int(viewport.get("width") or DEFAULT_VIEWPORT[0])
        height = int(viewport.get("height") or DEFAULT_VIEWPORT[1])
    except (TypeError, ValueError):
        return DEFAULT_VIEWPORT
    # A zero or absurd viewport would make every test fail in a way that looks
    # like an app bug rather than a bad recording.
    if not (320 <= width <= 5120 and 240 <= height <= 5120):
        return DEFAULT_VIEWPORT
    return width, height


def validate(spec: GeneratedFileSpec) -> None:
    """Parse Python files. Raises GeneratedCodeError with the offending line."""
    if not spec.path.endswith(".py"):
        return

    try:
        ast.parse(spec.content, filename=spec.path)
    except SyntaxError as exc:
        line = (spec.content.splitlines() or [""])[max(0, (exc.lineno or 1) - 1)]
        raise GeneratedCodeError(
            f"{spec.path} line {exc.lineno}: {exc.msg}\n  {line.strip()}"
        ) from exc
