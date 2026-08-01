"""Rendering a run as HTML. No database, no network.

The property that matters is self-containment: a report is emailed to someone
who has never heard of AutoQA, so anything it has to fetch is a blank space on
their screen.
"""

import base64
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.models.enums import ArtifactType, Browser, ResultStatus
from app.reports.builder import MAX_SINGLE_IMAGE, build_report


@dataclass
class FakeArtifact:
    type: ArtifactType
    file_path: str
    file_size: int = 1000


@dataclass
class FakeResult:
    id: int
    case_name: str
    browser: Browser = Browser.CHROMIUM
    status: ResultStatus = ResultStatus.PASSED
    duration_ms: int | None = 1200
    error_message: str | None = None
    failed_step: int | None = None
    artifacts: list = field(default_factory=list)


@dataclass
class FakeRun:
    id: int = 7
    total: int = 3
    passed: int = 2
    failed: int = 1
    skipped: int = 0
    duration_ms: int | None = 45_000
    browsers: list = field(default_factory=lambda: ["chromium", "firefox"])
    started_at: datetime | None = datetime(2026, 7, 31, 14, 30, tzinfo=UTC)
    created_at: datetime = datetime(2026, 7, 31, 14, 29, tzinfo=UTC)


@dataclass
class FakeAnalysis:
    result_id: int = 2
    is_product_bug: bool = True
    severity: object = type("S", (), {"value": "critical"})()
    confidence: float = 0.85
    root_cause: str = "The login button never became interactable."
    suggested_fix: str = "Raise a bug about the login page hanging."


@pytest.fixture
def results():
    return [
        FakeResult(1, "Signs in with valid credentials"),
        FakeResult(
            2,
            "Rejects a wrong password",
            status=ResultStatus.FAILED,
            failed_step=3,
            error_message="AssertionError: Locator expected to be visible",
        ),
        FakeResult(3, "Not applicable here", status=ResultStatus.SKIPPED,
                   duration_ms=None),
    ]


def render(results, **kwargs) -> str:
    return build_report(FakeRun(), results, suite_name="Login flow", **kwargs)


# ---------------------------------------------------------------------------
# Self-containment — the whole point
# ---------------------------------------------------------------------------
def test_nothing_is_fetched_from_anywhere(results):
    """A report that needs the network is a blank page once it is emailed."""
    html = render(results)

    assert "<link" not in html, "no external stylesheet"
    assert "<script" not in html, "no scripts at all"
    assert not re.search(r'src="https?://', html), "no remote images"
    assert "localhost" not in html and "/api/" not in html


def test_it_is_a_whole_document(results):
    html = render(results)

    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "</html>" in html.strip()


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
def test_every_result_is_listed(results):
    html = render(results)

    for result in results:
        assert result.case_name in html


def test_failures_get_their_own_section_with_the_error(results):
    html = render(results)

    assert "Failures (1)" in html
    assert "Locator expected to be visible" in html
    assert "failed at step 3" in html


def test_the_headline_numbers_are_right(results):
    html = render(results)

    assert ">67%<" in html, "2 of 3 passed"
    assert ">45.0s<" in html


def test_an_analysis_is_included_when_there_is_one(results):
    html = render(results, analyses={2: FakeAnalysis()})

    assert "Application bug" in html
    assert "never became interactable" in html
    assert "85% confident" in html


def test_a_run_with_no_failures_has_no_failures_section():
    passing = [FakeResult(1, "All good")]
    html = build_report(FakeRun(total=1, passed=1, failed=0), passing,
                        suite_name="Smoke")

    assert "Failures (" not in html


# ---------------------------------------------------------------------------
# Escaping — error text and AI prose go straight into HTML
# ---------------------------------------------------------------------------
def test_angle_brackets_in_an_error_cannot_break_the_page():
    """A traceback containing <div> would otherwise eat the rest of the report."""
    hostile = [
        FakeResult(
            1,
            "Rejects <script>alert(1)</script> in the email field",
            status=ResultStatus.FAILED,
            error_message="expected <b>bold</b> but got <script>alert('xss')</script>",
        )
    ]

    html = build_report(FakeRun(total=1, passed=0, failed=1), hostile,
                        suite_name="Security")

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------
def test_a_screenshot_is_embedded_as_a_data_uri(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels" * 50)

    failed = FakeResult(
        1, "Broken", status=ResultStatus.FAILED,
        artifacts=[FakeArtifact(ArtifactType.SCREENSHOT, "shot.png")],
    )
    html = build_report(FakeRun(total=1, passed=0, failed=1), [failed],
                        suite_name="X")

    assert "data:image/png;base64," in html
    assert base64.b64encode(shot.read_bytes()).decode()[:40] in html


def test_an_oversized_screenshot_is_left_out_and_the_report_says_so(
    tmp_path, monkeypatch
):
    """A report too big to email is as useless as one that will not render."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    huge = tmp_path / "huge.png"
    huge.write_bytes(b"x" * (MAX_SINGLE_IMAGE + 1))

    failed = FakeResult(
        1, "Broken", status=ResultStatus.FAILED,
        artifacts=[FakeArtifact(ArtifactType.SCREENSHOT, "huge.png")],
    )
    html = build_report(FakeRun(total=1, passed=0, failed=1), [failed],
                        suite_name="X")

    assert "data:image" not in html
    assert "left out to keep this file a" in html


def test_a_screenshot_outside_storage_is_refused(tmp_path, monkeypatch):
    """The stored path is data, not a filesystem instruction."""
    from app.core.config import settings

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(settings, "STORAGE_PATH", str(storage))

    secret = tmp_path / "secret.png"
    secret.write_bytes(b"private")

    failed = FakeResult(
        1, "Broken", status=ResultStatus.FAILED,
        artifacts=[FakeArtifact(ArtifactType.SCREENSHOT, "../secret.png")],
    )
    html = build_report(FakeRun(total=1, passed=0, failed=1), [failed],
                        suite_name="X")

    assert "data:image" not in html
    assert base64.b64encode(b"private").decode() not in html


def test_a_missing_screenshot_file_does_not_break_the_report(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path))
    failed = FakeResult(
        1, "Broken", status=ResultStatus.FAILED,
        artifacts=[FakeArtifact(ArtifactType.SCREENSHOT, "gone.png")],
    )

    html = build_report(FakeRun(total=1, passed=0, failed=1), [failed],
                        suite_name="X")

    assert "Broken" in html  # the report still renders
