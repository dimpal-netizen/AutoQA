"""The recording JSON contract. No database needed.

These tests pin the format the Chrome extension must produce. If one fails
after a change here, the extension needs updating too.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.models.enums import ActionType, SelectorStrategy
from app.schemas.recording import ActionBatchIn, RecordedActionIn, RecordingSessionCreate

FIXTURE = Path(__file__).parent / "fixtures" / "sample_recording.json"


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The reference fixture
# ---------------------------------------------------------------------------
def test_fixture_parses(sample: dict) -> None:
    RecordingSessionCreate.model_validate(sample["session"])
    batch = ActionBatchIn.model_validate({"actions": sample["actions"]})

    assert len(batch.actions) == 21


def test_fixture_covers_every_action_type(sample: dict) -> None:
    """Phase 3's generator must handle all 13, so all 13 must be exercised."""
    used = {a["action_type"] for a in sample["actions"]}
    missing = {t.value for t in ActionType} - used

    assert not missing, f"sample_recording.json never uses: {sorted(missing)}"


def test_fixture_has_sequential_ordering(sample: dict) -> None:
    sequences = [a["sequence"] for a in sample["actions"]]
    assert sequences == list(range(len(sequences)))


def test_fixture_exercises_iframes(sample: dict) -> None:
    assert any(a["frame_path"] for a in sample["actions"]), (
        "no action inside an iframe — Phase 3 would never exercise frame_locator()"
    )


# ---------------------------------------------------------------------------
# Selector ranking
# ---------------------------------------------------------------------------
def test_selectors_are_sorted_best_first() -> None:
    # Deliberately worst-first on input.
    action = RecordedActionIn.model_validate(
        {
            "sequence": 0,
            "action_type": "click",
            "timestamp_ms": 0,
            "url": "https://example.com",
            "selectors": [
                {"strategy": "nth_child", "value": "li:nth-child(3)"},
                {"strategy": "css", "value": ".btn"},
                {"strategy": "test_id", "value": "submit"},
                {"strategy": "label", "value": "Submit"},
            ],
        }
    )

    assert [s.strategy for s in action.selectors] == [
        SelectorStrategy.TEST_ID,
        SelectorStrategy.LABEL,
        SelectorStrategy.CSS,
        SelectorStrategy.NTH_CHILD,
    ]


def test_equal_strategies_break_ties_on_score() -> None:
    action = RecordedActionIn.model_validate(
        {
            "sequence": 0,
            "action_type": "click",
            "timestamp_ms": 0,
            "url": "https://example.com",
            "selectors": [
                {"strategy": "css", "value": ".weak", "score": 10},
                {"strategy": "css", "value": ".strong", "score": 90},
            ],
        }
    )

    assert [s.value for s in action.selectors] == [".strong", ".weak"]


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------
def test_element_action_without_a_selector_is_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="needs at least one selector"):
        RecordedActionIn.model_validate(
            {
                "sequence": 0,
                "action_type": "click",
                "timestamp_ms": 0,
                "url": "https://example.com",
                "selectors": [],
            }
        )


def test_page_level_actions_need_no_selector() -> None:
    for action_type, payload in [
        ("navigate", {"url": "https://example.com"}),
        ("scroll", {"x": 0, "y": 100}),
    ]:
        RecordedActionIn.model_validate(
            {
                "sequence": 0,
                "action_type": action_type,
                "timestamp_ms": 0,
                "url": "https://example.com",
                "selectors": [],
                "payload": payload,
            }
        )


@pytest.mark.parametrize(
    ("action_type", "payload", "missing"),
    [
        ("input", {}, "value"),
        ("select", {}, "values"),
        ("navigate", {}, "url"),
        ("key_press", {}, "key"),
        ("upload", {}, "files"),
        ("scroll", {"x": 0}, "y"),
        ("drag_drop", {}, "target_selectors"),
        ("assert", {}, "kind"),
    ],
)
def test_incomplete_payload_is_rejected(
    action_type: str, payload: dict, missing: str
) -> None:
    """A half-recorded action must fail here, not produce broken code later."""
    with pytest.raises(PydanticValidationError, match=missing):
        RecordedActionIn.model_validate(
            {
                "sequence": 0,
                "action_type": action_type,
                "timestamp_ms": 0,
                "url": "https://example.com",
                "selectors": [{"strategy": "test_id", "value": "x"}],
                "payload": payload,
            }
        )


def test_list_payload_fields_must_be_lists() -> None:
    with pytest.raises(PydanticValidationError, match="must be a list"):
        RecordedActionIn.model_validate(
            {
                "sequence": 0,
                "action_type": "upload",
                "timestamp_ms": 0,
                "url": "https://example.com",
                "selectors": [{"strategy": "test_id", "value": "x"}],
                "payload": {"files": "single.pdf"},
            }
        )


def test_unknown_action_type_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        RecordedActionIn.model_validate(
            {
                "sequence": 0,
                "action_type": "telepathy",
                "timestamp_ms": 0,
                "url": "https://example.com",
            }
        )


def test_duplicate_sequences_within_a_batch_are_rejected() -> None:
    action = {
        "sequence": 4,
        "action_type": "navigate",
        "timestamp_ms": 0,
        "url": "https://example.com",
        "payload": {"url": "https://example.com"},
    }

    with pytest.raises(PydanticValidationError, match="share a sequence number"):
        ActionBatchIn.model_validate({"actions": [action, dict(action)]})


def test_empty_batch_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        ActionBatchIn.model_validate({"actions": []})
