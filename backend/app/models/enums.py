"""Enums shared by models and schemas.

All of these become native PostgreSQL enum types. Note the `values_callable`
in the models: without it SQLAlchemy stores the member *name* ("MANUAL_QA")
instead of the value ("manual_qa").
"""

from enum import Enum


class UserRole(str, Enum):
    """The three product roles, plus admin.

    Ordered by privilege — see ROLE_LEVEL below.
    """

    MANUAL_QA = "manual_qa"
    QA_ENGINEER = "qa_engineer"
    TEST_MANAGER = "test_manager"
    ADMIN = "admin"


# Permissions are hierarchical: a test_manager can do anything a qa_engineer can.
# `require_role(UserRole.QA_ENGINEER)` therefore means "qa_engineer or above".
ROLE_LEVEL: dict[UserRole, int] = {
    UserRole.MANUAL_QA: 1,
    UserRole.QA_ENGINEER: 2,
    UserRole.TEST_MANAGER: 3,
    UserRole.ADMIN: 4,
}


class Browser(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class RecordingStatus(str, Enum):
    RECORDING = "recording"
    COMPLETED = "completed"
    DISCARDED = "discarded"


class ActionType(str, Enum):
    """Every interaction the Chrome extension can capture.

    This list is the contract: the extension may only emit these, and the
    Phase 3 code generator must handle every one of them.
    """

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    INPUT = "input"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    HOVER = "hover"
    DRAG_DROP = "drag_drop"
    NAVIGATE = "navigate"
    KEY_PRESS = "key_press"
    UPLOAD = "upload"
    SCROLL = "scroll"
    ASSERT = "assert"


# Actions that operate on a specific element, and therefore must carry at least
# one selector. `navigate` and `scroll` are page-level; `key_press` may be either
# (typing into a focused field vs. a global shortcut like Escape).
ELEMENT_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.CLICK,
        ActionType.DOUBLE_CLICK,
        ActionType.INPUT,
        ActionType.SELECT,
        ActionType.CHECK,
        ActionType.UNCHECK,
        ActionType.HOVER,
        ActionType.DRAG_DROP,
        ActionType.UPLOAD,
        ActionType.ASSERT,
    }
)


class SelectorStrategy(str, Enum):
    """Ways to locate an element, best first.

    The extension records several candidates per element rather than one string.
    The generator emits the highest-ranked one and keeps the rest as fallbacks,
    which is what stops a recorded test from breaking the first time the UI
    changes. See SELECTOR_RANK for the ordering.
    """

    TEST_ID = "test_id"          # data-testid — survives redesigns
    ROLE_NAME = "role_name"      # ARIA role + accessible name
    LABEL = "label"              # associated <label> text
    PLACEHOLDER = "placeholder"
    TEXT = "text"                # exact visible text
    CSS_ID = "css_id"            # #id, only when it looks hand-written
    CSS = "css"                  # scoped CSS path
    XPATH = "xpath"
    NTH_CHILD = "nth_child"      # positional — last resort, very brittle


# Lower number = more reliable. The generator sorts candidates by this.
SELECTOR_RANK: dict[SelectorStrategy, int] = {
    SelectorStrategy.TEST_ID: 1,
    SelectorStrategy.ROLE_NAME: 2,
    SelectorStrategy.LABEL: 3,
    SelectorStrategy.PLACEHOLDER: 4,
    SelectorStrategy.TEXT: 5,
    SelectorStrategy.CSS_ID: 6,
    SelectorStrategy.CSS: 7,
    SelectorStrategy.XPATH: 8,
    SelectorStrategy.NTH_CHILD: 9,
}

# Anything at or below this rank is reliable enough to use without warning the
# user. Beyond it the UI should flag the step as fragile.
RELIABLE_SELECTOR_RANK = SELECTOR_RANK[SelectorStrategy.CSS_ID]


class CaseSource(str, Enum):
    """Where a test case came from."""

    RECORDING = "recording"
    AGENT = "agent"
    MANUAL = "manual"


class CaseStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class FileType(str, Enum):
    """Kind of generated file. Drives where it lands in the suite directory."""

    TEST = "test"
    PAGE_OBJECT = "page_object"
    CONFTEST = "conftest"
    CONFIG = "config"
    FIXTURE = "fixture"
    UTIL = "util"
    HELPER = "helper"


class RunStatus(str, Enum):
    """A whole execution.

    PASSED and FAILED are both finished states; ERROR means the run itself
    broke (pytest would not start, the browser is missing) rather than a test
    failing, which is a different problem with a different fix.
    """

    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ERROR = "error"


FINISHED_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.PASSED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.ERROR}
)


class ResultStatus(str, Enum):
    """One test, in one browser.

    FLAKY is deliberately distinct from PASSED: a test that only passed on
    retry is not trustworthy, and hiding that behind a green tick is how a
    suite quietly stops meaning anything.
    """

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    FLAKY = "flaky"


class ArtifactType(str, Enum):
    """Evidence saved from a run. Files live on disk; only paths go in the database."""

    SCREENSHOT = "screenshot"
    VIDEO = "video"
    LOG = "log"
    TRACE = "trace"
    HTML_REPORT = "html_report"
    ALLURE_REPORT = "allure_report"
