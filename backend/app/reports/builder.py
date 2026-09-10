"""Render a run as one self-contained HTML file.

Self-contained is the whole requirement. The point of a report is to send it to
someone who does not have AutoQA — a developer, a manager, a client — so it has
to survive being emailed, opened from a download folder, and read in two years.
That rules out a CSS link, a script tag, or an <img src> pointing at our API:
each of those turns the report into a blank page the moment it leaves this
machine. Styles are inlined and screenshots are embedded as data URIs.

The cost is size, which is why screenshots are capped rather than unlimited.
A report nobody can email is no more useful than one that will not render.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.core.config import settings
from app.models.enums import ArtifactType, ResultStatus

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Roughly what still attaches to an email without complaint. Reports over this
# stop being shareable, which defeats the point of making one.
MAX_EMBEDDED_BYTES = 6 * 1024 * 1024
MAX_SINGLE_IMAGE = 1_500_000

_BADGE = {
    ResultStatus.PASSED: "b-pass",
    ResultStatus.FAILED: "b-fail",
    ResultStatus.ERROR: "b-fail",
    ResultStatus.SKIPPED: "b-skip",
    ResultStatus.FLAKY: "b-warn",
}


@dataclass
class ReportContext:
    """Everything the template needs, already resolved.

    Built here rather than in the template so the report can be produced from
    a detached run without triggering a lazy load halfway through rendering.
    """

    rows: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    #: Tests that passed by doing something other than what was recorded. Kept
    #: apart from `rows` so the report can say so in its own section: a pass
    #: reached by substituting data the application would accept is a different
    #: thing from a pass, and burying it in a green table hides the one fact
    #: somebody reading the report most needs to check.
    adapted: list[dict] = field(default_factory=list)
    omitted_screenshots: int = 0


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        # Unconditional, NOT select_autoescape(["html"]). That helper matches on
        # the filename, and this template is `run_report.html.j2` — the
        # extension is .j2, so it would quietly leave escaping off. Everything
        # this environment renders is HTML, and the values are the least
        # trustworthy in the system: error text, tracebacks, AI prose and test
        # names, one of which is literally an XSS payload in any suite with
        # security cases.
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_report(
    run,
    results: list,
    *,
    analyses: dict[int, object] | None = None,
    suite_name: str = "Test run",
    project_name: str = "",
    base_url: str | None = None,
) -> str:
    """Render one run as standalone HTML."""
    analyses = analyses or {}
    context = ReportContext()
    budget = MAX_EMBEDDED_BYTES

    for result in results:
        context.rows.append(
            {
                "name": result.case_name,
                "browser": result.browser.value,
                "status": result.status.value,
                "badge": _BADGE.get(result.status, "b-skip"),
                "duration": _duration(result.duration_ms),
                "adapted": bool(getattr(result, "adaptations", None)),
            }
        )

        for note in getattr(result, "adaptations", None) or []:
            context.adapted.append(
                {
                    "name": result.case_name,
                    "browser": result.browser.value,
                    "note": note,
                }
            )

        if result.status not in (ResultStatus.FAILED, ResultStatus.ERROR):
            continue

        screenshot, used = _embed_screenshot(result, budget)
        budget -= used
        if not screenshot and _has_screenshot(result):
            context.omitted_screenshots += 1

        context.failures.append(
            {
                "name": result.case_name,
                "browser": result.browser.value,
                "failed_step": result.failed_step,
                "error": result.error_message,
                "analysis": _analysis(analyses.get(result.id)),
                "screenshot": screenshot,
            }
        )

    total = run.total or len(results) or 1

    return _environment().get_template("run_report.html.j2").render(
        run=run,
        suite_name=suite_name,
        project_name=project_name or "",
        base_url=base_url,
        browsers=", ".join(run.browsers) if run.browsers else "—",
        started=_when(run.started_at) or _when(run.created_at) or "unknown",
        generated=_when(datetime.now(UTC)),
        duration=_duration(run.duration_ms),
        pass_rate=round(run.passed / total * 100),
        rows=context.rows,
        failures=context.failures,
        adapted=context.adapted,
        omitted_screenshots=context.omitted_screenshots,
    )


# ---------------------------------------------------------------------------
def _analysis(analysis) -> dict | None:
    if analysis is None:
        return None
    return {
        "is_product_bug": analysis.is_product_bug,
        "severity": analysis.severity.value,
        "confidence": round(analysis.confidence * 100),
        "root_cause": analysis.root_cause,
        "suggested_fix": analysis.suggested_fix,
    }


def _has_screenshot(result) -> bool:
    return any(a.type is ArtifactType.SCREENSHOT for a in result.artifacts)


def _embed_screenshot(result, budget: int) -> tuple[str | None, int]:
    """The failure screenshot as a data URI, and what it cost.

    Returns (None, 0) when there is none, when it is too big on its own, or
    when the budget for this report is spent.
    """
    for artifact in result.artifacts:
        if artifact.type is not ArtifactType.SCREENSHOT:
            continue

        path = (settings.storage_dir / artifact.file_path).resolve()
        root = settings.storage_dir.resolve()
        # The stored path is data; treating it as a filesystem instruction
        # without this check turns a database read into an arbitrary file read.
        if not path.is_relative_to(root) or not path.is_file():
            continue

        size = path.stat().st_size
        if size > MAX_SINGLE_IMAGE or size * 1.37 > budget:
            return None, 0  # base64 inflates by about a third

        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            logger.exception("Could not read screenshot %s", path)
            return None, 0

        media = mimetypes.guess_type(path.name)[0] or "image/png"
        return f"data:{media};base64,{encoded}", len(encoded)

    return None, 0


def _duration(ms: int | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {round(seconds % 60):02d}s"


def _when(value) -> str | None:
    if value is None:
        return None
    return value.strftime("%d %b %Y, %H:%M")
