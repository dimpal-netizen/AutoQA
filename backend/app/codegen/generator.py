"""Render a TestIR into files, and refuse to emit anything that won't import.

Generated code is executed later, so a syntax error here becomes a confusing
runtime failure three phases away. Every file is parsed before it is returned.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.codegen.converter import TestIR, page_variables
from app.codegen.dataroles import CONFLICT
from app.codegen.selectors import py_doc, py_str
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
    # For recorded text that lands *inside* a docstring rather than in a string
    # literal of its own. See `py_doc`.
    env.filters["pydoc"] = py_doc
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

    def healable(page) -> bool:
        """Has any element more than one recorded way of being found?"""
        return any(len(locator.candidates) > 1 for locator in page.locators)

    for page in ir.pages:
        files.append(
            GeneratedFileSpec(
                path=f"pages/{page.module}.py",
                content=env.get_template("page_object.py.j2").render(
                    page=page, needs_healing=healable(page)
                ),
                file_type=FileType.PAGE_OBJECT,
            )
        )

    # One helper shared by every page object. Emitted only when something can
    # actually heal, so a suite of unique test ids does not carry code it never
    # calls — or when a test asserts on an element, because `unhealed` lives in
    # the same file and a suite of single-candidate locators still imports it.
    # `_state.py` imports `every` from here, so a state-aware suite needs it
    # whether or not any of its locators can heal.
    if any(healable(page) for page in ir.pages) or ir.needs_unhealed or ir.needs_state:
        files.append(
            GeneratedFileSpec(
                path="pages/_healing.py",
                content=env.get_template("healing.py.j2").render(),
                file_type=FileType.HELPER,
            )
        )

    # Only when a step depends on data or state that may have moved on since it
    # was recorded. The conflict vocabulary is handed to the template from
    # `dataroles`, so the half that decides which steps may recover and the half
    # that decides whether a refusal happened can never drift apart.
    if ir.needs_state or ir.needs_instead or ir.selection_point is not None:
        files.append(
            GeneratedFileSpec(
                path="pages/_state.py",
                content=env.get_template("state.py.j2").render(
                    conflict_pattern=CONFLICT.pattern
                ),
                file_type=FileType.HELPER,
            )
        )

    # Only when a step waits for what its action was observed to do. A suite
    # whose every action navigates never imports it.
    if ir.needs_sync:
        files.append(
            GeneratedFileSpec(
                path="pages/_sync.py",
                content=env.get_template("sync.py.j2").render(),
                file_type=FileType.HELPER,
            )
        )

    # Only when something is uploaded: a 9 KB JPEG in a suite that never asks
    # for one is dead weight in every checkout.
    if ir.needs_sample_file:
        files.append(
            GeneratedFileSpec(
                path="pages/_files.py",
                content=env.get_template("files.py.j2").render(),
                file_type=FileType.HELPER,
            )
        )

    width, height = _viewport(browser_info)
    files.append(
        GeneratedFileSpec(
            path="conftest.py",
            content=env.get_template("conftest.py.j2").render(
                base_url=ir.start_url,
                viewport_width=width,
                viewport_height=height,
                needs_state=ir.needs_state,
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


#: Names a generated module can only have because it imported them. Each is
#: brought in by a flag on the IR - `needs_regex`, `needs_uuid`, and so on - and
#: every one of those flags is a chance to emit a line that uses the name while
#: forgetting to ask for it.
#:
#: That is not hypothetical. Restoring a recorded sign-in copied a
#: `wait_for_url(re.compile(...))` into cases that had no URL assertion of their
#: own, `needs_regex` stayed false, and every case in the suite died on
#:
#:     NameError: name 're' is not defined
#:
#: once the browser was already open. `ast.parse` cannot catch it: the file is
#: perfectly good Python, it just refers to something that is not there.
_MUST_BE_IMPORTED = (
    "re", "uuid4", "expect", "sample_file", "set_checked", "reveal", "unhealed",
    "one_of", "submit", "after", "instead", "workflow",
)


def _undefined(source: str) -> list[str]:
    """Which of those the module uses without importing or defining.

    Only that handful is checked. Deciding whether an arbitrary name is bound is
    a much larger job, and every bug of this kind has been one of these -
    because each arrives through a flag somebody has to remember to set.
    """
    tree = ast.parse(source)

    provided: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            provided |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            provided |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            provided.add(node.name)
        elif isinstance(node, ast.arg):
            provided.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            provided.add(node.id)

    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return sorted(set(_MUST_BE_IMPORTED) & (used - provided))


def validate(spec: GeneratedFileSpec) -> None:
    """Parse Python files. Raises GeneratedCodeError with the offending line."""
    if not spec.path.endswith(".py"):
        return

    # Warnings are collected, not printed, and then treated as failures. Python
    # says a great deal about code it will nonetheless compile, and this file
    # already had every word of it:
    #
    #   pages/home_page.py:24: SyntaxWarning: invalid escape sequence '\:'
    #
    # A Tailwind class - `md:flex` in the markup, `md\:flex` once CSS escapes
    # the colon - written into a docstring, where `\:` is not an escape Python
    # knows. It compiled anyway, so `validate` passed it, and it went out in
    # every generated suite. Deprecated escapes become SyntaxError in a later
    # Python, so this was a suite that would one day stop importing entirely.
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ast.parse(spec.content, filename=spec.path)
    except SyntaxError as exc:
        line = (spec.content.splitlines() or [""])[max(0, (exc.lineno or 1) - 1)]
        raise GeneratedCodeError(
            f"{spec.path} line {exc.lineno}: {exc.msg}\n  {line.strip()}"
        ) from exc

    for warning in caught:
        if issubclass(warning.category, SyntaxWarning):
            raise GeneratedCodeError(
                f"{spec.path} line {warning.lineno}: "
                f"{warning.category.__name__}: {warning.message}"
            )

    missing = _undefined(spec.content)
    if missing:
        raise GeneratedCodeError(
            f"{spec.path} uses {', '.join(missing)} without importing "
            f"{'it' if len(missing) == 1 else 'them'}"
        )
