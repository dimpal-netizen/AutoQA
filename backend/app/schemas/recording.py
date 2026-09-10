"""Recording schemas — THE CONTRACT between the Chrome extension and the backend.

The extension (Phase 9) is written to match this exactly. Changing anything here
after the extension ships means shipping a new extension too, so treat additions
as safe and removals/renames as breaking.

Per-action payload shapes:

    click, double_click, hover   {}                       optional: button, modifiers
    input                        {"value": str}
    select                       {"values": [str]}
    check, uncheck               {}
    navigate                     {"url": str}
    key_press                    {"key": str}             optional: modifiers
    upload                       {"files": [str]}
    scroll                       {"x": int, "y": int}
    drag_drop                    {"target_selectors": [Selector]}
    assert                       {"kind": str, "expected": Any}
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.models.enums import (
    ELEMENT_ACTIONS,
    SELECTOR_RANK,
    ActionType,
    RecordingStatus,
    SelectorStrategy,
)

MAX_ACTIONS_PER_BATCH = 500


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
class Selector(BaseModel):
    """One way to find an element. Actions carry several, best first."""

    strategy: SelectorStrategy
    value: str = Field(min_length=1, max_length=4096)
    # Did this match exactly one element when it was recorded? A non-unique
    # selector is a warning sign the generated test will be flaky.
    unique: bool = True
    # Extension's own confidence, 0-100. Advisory; the backend re-ranks by
    # strategy anyway so a buggy extension can't promote a bad selector.
    score: int = Field(default=0, ge=0, le=100)

    @property
    def rank(self) -> int:
        return SELECTOR_RANK[self.strategy]


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class ElementInfo(BaseModel):
    """What the element looked like when recorded.

    Used for human-readable step descriptions, and in Phase 7 to re-find an
    element whose selector has drifted.
    """

    tag: str = Field(max_length=64)
    input_type: str | None = Field(default=None, max_length=64)
    role: str | None = Field(default=None, max_length=64)
    accessible_name: str | None = Field(default=None, max_length=512)
    text: str | None = Field(default=None, max_length=2048)
    attributes: dict[str, str] = Field(default_factory=dict)
    bounding_box: BoundingBox | None = None
    # Was the element already on screen before the previous step, or did that
    # step put it there? Answerable only while the page is in front of us, and
    # it decides whether a generated test case may use the element at all: a
    # modal's close button reads exactly like an ordinary one once the recording
    # is finished. `None` on recordings made before this was captured.
    was_on_screen: bool | None = None


class FrameRef(BaseModel):
    """One `<iframe>` on the way down to a recorded element.

    An action inside a frame is meaningless without the frames above it, and
    "the second iframe" is not a durable way to say which - applications insert
    a chat widget or an advert and every index after it moves. So the frame is
    *described*, the way an element is: what it is called, what it is titled,
    what it loads. The index is kept, and kept last, for the case where an
    application gives its frames nothing else to go on.

    Every field is optional. A cross-origin frame will not say what it is called
    from inside itself, and a frame with no attributes at all still has a
    position - so a descriptor with nothing but an index is a real answer and
    has to be usable.
    """

    #: The `name` attribute. Chosen by the application, and the one thing here a
    #: developer picks specifically so it can be referred to.
    name: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=256)
    #: The `id` attribute, unless it looks generated - the recorder applies the
    #: same test it applies to element ids.
    element_id: str | None = Field(default=None, max_length=256)
    #: What the frame loads. Kept whole for the report; matched on its path, so
    #: a cache-busting query string does not make it a different frame.
    src: str | None = Field(default=None, max_length=2048)
    #: Where the frame had actually got to, which is not always its `src`: a
    #: payment frame redirects, an SPA frame pushes state.
    url: str | None = Field(default=None, max_length=2048)
    #: Position among its siblings. A fallback and never a first choice.
    index: int | None = Field(default=None, ge=0)


class ApplicationResponse(BaseModel):
    """What the application did in reply to one action.

    A recording of what somebody did is only half of what happened; this is the
    other half. Without it every recorded value looks equally permanent, because
    from a list of clicks and keystrokes an address that must be new on every run
    is indistinguishable from one that must already exist. The reply is what
    tells them apart, and it is only knowable while the page is still in front of
    the recorder.

    Every field is optional and the whole object is optional, so a recording made
    by an older extension - or one whose page navigated before the reply
    arrived - is exactly as valid as it ever was. Nothing downstream may require
    it; see `dataroles.py`, where it is treated as corroboration rather than as
    an input.
    """

    #: What kind of thing happened, in the vocabulary the generator waits on:
    #: navigated, dialog_opened, dialog_closed, messages, dom_changed, quiet.
    #: The most decisive observation wins - a click that navigates also mutates
    #: the DOM - and the rest are kept below as detail.
    #:
    #: `quiet` is a real answer, not a failure to find one. Plenty of actions
    #: change nothing a browser can see, and a test that insists on waiting for
    #: something after one waits for ever.
    kind: str | None = Field(default=None, max_length=32)

    url: str | None = Field(default=None, max_length=2048)
    navigated: bool | None = None
    title_changed: bool | None = None
    dialog_opened: bool | None = None
    dialog_closed: bool | None = None
    #: How many DOM mutations the action set off. Zero means nothing on the page
    #: moved, which is what makes "wait for nothing" a safe answer rather than a
    #: guess.
    mutations: int | None = Field(default=None, ge=0)
    #: How long after the action the observation was taken, in milliseconds.
    #: Recorded, never replayed - it says how patient the application needed
    #: somebody to be, not how long the test should sleep.
    settled_ms: int | None = Field(default=None, ge=0)
    #: Sentences that *appeared* because of this action, not everything on the
    #: page. Collected by shape - an alert role, a live region, a class with
    #: error in it - never by what they say. Reading them happens later.
    messages: list[str] = Field(default_factory=list, max_length=32)


class ViewportInfo(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class BrowserInfo(BaseModel):
    user_agent: str | None = Field(default=None, max_length=512)
    viewport: ViewportInfo | None = None
    device_pixel_ratio: float | None = Field(default=None, gt=0)
    platform: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
class RecordedActionIn(BaseModel):
    """One interaction, as the extension sends it."""

    sequence: int = Field(ge=0)
    action_type: ActionType
    timestamp_ms: int = Field(ge=0)
    url: str = Field(min_length=1, max_length=2048)

    #: The frames between the page and the element, outermost first. Empty for
    #: an element on the page itself, which is almost every element.
    #:
    #: Two shapes, and both are honoured. A list of strings is a list of literal
    #: iframe selectors, which is what every recording made before this carries -
    #: and since the only value ever sent was `[]`, that is a promise about
    #: nothing at all. A list of `FrameRef` is a description of each frame, from
    #: which a selector is chosen at generation time, preferring what an
    #: application chose over where a frame happens to sit.
    frame_path: list[FrameRef | str] = Field(default_factory=list)
    selectors: list[Selector] = Field(default_factory=list)
    element: ElementInfo | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    #: What the application said back. Absent on every recording made before it
    #: was captured, and on any action whose page navigated before the reply
    #: arrived - so it is corroboration, never a requirement.
    response: ApplicationResponse | None = None

    note: str | None = None

    @field_validator("selectors")
    @classmethod
    def rank_selectors(cls, value: list[Selector]) -> list[Selector]:
        """Sort best-first here, so nothing downstream has to remember to."""
        return sorted(value, key=lambda s: (s.rank, -s.score))

    @model_validator(mode="after")
    def check_shape(self) -> "RecordedActionIn":
        if self.action_type in ELEMENT_ACTIONS and not self.selectors:
            raise ValueError(
                f"'{self.action_type.value}' targets an element, so it needs at least "
                f"one selector — otherwise the generated test cannot find it"
            )
        _validate_payload(self.action_type, self.payload)
        return self


def _validate_payload(action_type: ActionType, payload: dict[str, Any]) -> None:
    """Reject payloads missing the keys the code generator will need.

    Catching this at ingest means Phase 3 never has to defend against a
    half-recorded action, and a buggy extension build fails loudly and early.
    """
    required: dict[ActionType, tuple[str, ...]] = {
        ActionType.INPUT: ("value",),
        ActionType.SELECT: ("values",),
        ActionType.NAVIGATE: ("url",),
        ActionType.KEY_PRESS: ("key",),
        ActionType.UPLOAD: ("files",),
        ActionType.SCROLL: ("x", "y"),
        ActionType.DRAG_DROP: ("target_selectors",),
        ActionType.ASSERT: ("kind",),
    }

    missing = [key for key in required.get(action_type, ()) if key not in payload]
    if missing:
        raise ValueError(
            f"'{action_type.value}' payload is missing {missing}; "
            f"got keys {sorted(payload)}"
        )

    # List-shaped fields must actually be lists, or the generator would emit
    # code that crashes at runtime rather than failing here.
    for key in ("values", "files", "target_selectors"):
        if key in payload and not isinstance(payload[key], list):
            raise ValueError(f"'{action_type.value}' payload field '{key}' must be a list")


class ActionBatchIn(BaseModel):
    """A chunk of actions. The extension uploads as it records, not just at stop."""

    actions: list[RecordedActionIn] = Field(min_length=1, max_length=MAX_ACTIONS_PER_BATCH)

    @field_validator("actions")
    @classmethod
    def no_duplicate_sequences(cls, value: list[RecordedActionIn]) -> list[RecordedActionIn]:
        sequences = [a.sequence for a in value]
        if len(set(sequences)) != len(sequences):
            raise ValueError("Two actions in this batch share a sequence number")
        return value


class ActionBatchResult(BaseModel):
    """Reports what actually happened, since ingest is idempotent."""

    stored: int
    skipped_duplicates: int
    action_count: int  # total on the session now


class RecordedActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    action_type: ActionType
    timestamp_ms: int
    url: str
    frame_path: list[FrameRef | str]
    selectors: list[Selector]
    element: ElementInfo | None
    payload: dict[str, Any]
    response: ApplicationResponse | None = None
    is_ignored: bool
    note: str | None


class RecordedActionUpdate(BaseModel):
    """Lets a QA engineer fix a bad selector or silence a noisy step."""

    selectors: list[Selector] | None = None
    payload: dict[str, Any] | None = None
    is_ignored: bool | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
class RecordingSessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    start_url: HttpUrl
    browser_info: BrowserInfo = Field(default_factory=BrowserInfo)
    extension_version: str | None = Field(default=None, max_length=32)


class RecordingSessionStop(BaseModel):
    duration_ms: int | None = Field(default=None, ge=0)


class RecordingLaunch(BaseModel):
    """Open a URL in a real browser and record it."""

    url: HttpUrl
    name: str | None = Field(default=None, max_length=255)
    # Headless is only useful for automated tests — a human needs to see the
    # window to interact with it.
    headless: bool = False


class RecordingSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    created_by_id: int | None
    name: str
    start_url: str
    status: RecordingStatus
    browser_info: dict[str, Any]
    extension_version: str | None
    action_count: int
    duration_ms: int | None
    # Set once code has been generated from this recording.
    suite_id: int | None = None
    created_at: datetime
    updated_at: datetime


class RecordingSessionDetail(RecordingSessionRead):
    actions: list[RecordedActionRead]


class RecordingSessionLive(RecordingSessionRead):
    """A session plus whether a browser window is currently open for it."""

    browser_open: bool = False
