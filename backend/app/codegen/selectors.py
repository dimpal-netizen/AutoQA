"""Turn a recorded selector into a Playwright locator expression.

The recorder stores a ranked list of candidates per element. Here we take the
best one and render it as Python. The rest stay in the database as the
fallbacks that make Phase 7 self-healing possible.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from typing import Any

from app.models.enums import RELIABLE_SELECTOR_RANK, SELECTOR_RANK, SelectorStrategy


@dataclass(frozen=True)
class Selector:
    strategy: SelectorStrategy
    value: str
    unique: bool = True
    score: int = 0

    @property
    def rank(self) -> int:
        return SELECTOR_RANK[self.strategy]

    @property
    def is_fragile(self) -> bool:
        """True when this will probably break on the next UI change."""
        return self.rank > RELIABLE_SELECTOR_RANK or not self.unique

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Selector:
        return cls(
            strategy=SelectorStrategy(raw["strategy"]),
            value=raw["value"],
            unique=bool(raw.get("unique", True)),
            score=int(raw.get("score", 0)),
        )


def best_selector(raw_selectors: list[dict[str, Any]]) -> Selector | None:
    """Pick the most reliable candidate. Re-sorts rather than trusting order.

    Uniqueness outranks everything, including strategy. A selector that matched
    two elements when recorded is not "slightly worse" — Playwright runs in
    strict mode, so it raises rather than guessing, and the test fails every
    single time:

        strict mode violation: get_by_placeholder("Email") resolved to 2 elements

    A humble `#email` that matches exactly one element beats a beautiful
    placeholder selector that matches two. Ranking is about surviving the next
    UI change; uniqueness is about working at all, and working at all comes
    first.
    """
    if not raw_selectors:
        return None
    candidates = [Selector.from_dict(s) for s in raw_selectors]
    return min(candidates, key=lambda s: (not s.unique, s.rank, -s.score))


def py_str(value: str) -> str:
    """A Python string literal that is always safe to paste into generated code.

    Uses repr, which escapes quotes and backslashes correctly — building the
    literal by hand is how generated code ends up with syntax errors on values
    containing an apostrophe.
    """
    return repr(value)


def locator_expression(selector: Selector, root: str = "page") -> str:
    """Render one selector as a Playwright call on `root`.

    A selector that matched several elements gets `.first` appended. That only
    happens when *every* recorded candidate was ambiguous — `best_selector`
    prefers unique ones — and it is the difference between a test that picks
    the first match and one that raises a strict mode violation on every run.
    The page object flags it, so the ambiguity is visible rather than silently
    papered over.
    """
    return _render(selector, root) + ("" if selector.unique else ".first")


def _render(selector: Selector, root: str) -> str:
    match selector.strategy:
        case SelectorStrategy.TEST_ID:
            return f"{root}.get_by_test_id({py_str(selector.value)})"

        case SelectorStrategy.ROLE_NAME:
            # Stored as "role|accessible name".
            role, _, name = selector.value.partition("|")
            if name:
                return f"{root}.get_by_role({py_str(role)}, name={py_str(name)})"
            return f"{root}.get_by_role({py_str(role)})"

        case SelectorStrategy.LABEL:
            return f"{root}.get_by_label({py_str(selector.value)})"

        case SelectorStrategy.PLACEHOLDER:
            return f"{root}.get_by_placeholder({py_str(selector.value)})"

        case SelectorStrategy.TEXT:
            return f"{root}.get_by_text({py_str(selector.value)}, exact=True)"

        case SelectorStrategy.XPATH:
            return f"{root}.locator({py_str('xpath=' + selector.value)})"

        case _:  # CSS_ID, CSS, NTH_CHILD are all CSS selectors
            return f"{root}.locator({py_str(selector.value)})"


def frame_root(frame_path: list[str], base: str = "page") -> str:
    """Chain frame_locator calls for an element inside iframes."""
    root = base
    for frame in frame_path:
        root = f"{root}.frame_locator({py_str(frame)})"
    return root


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------
_NON_IDENT = re.compile(r"[^0-9a-zA-Z]+")

# Reserved because a page object already defines them.
_RESERVED = {"page", "url", "self"}


def snake_case(text: str, fallback: str = "element") -> str:
    """A safe Python identifier derived from arbitrary text."""
    # Split camelCase before stripping punctuation, so "loginSubmit" survives.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    cleaned = _NON_IDENT.sub("_", spaced).strip("_").lower()
    cleaned = re.sub(r"_+", "_", cleaned)

    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}"
    if keyword.iskeyword(cleaned) or cleaned in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned[:60]


def element_name(selector: Selector, element: dict[str, Any] | None) -> str:
    """A readable name for a locator property, e.g. `email_input`.

    Prefers the test id, then the accessible name, then the visible text —
    whatever a person would call the thing.
    """
    if selector.strategy is SelectorStrategy.TEST_ID:
        base = selector.value
    elif selector.strategy is SelectorStrategy.ROLE_NAME:
        role, _, name = selector.value.partition("|")
        base = name or role
    elif selector.strategy in (SelectorStrategy.LABEL, SelectorStrategy.PLACEHOLDER):
        base = selector.value
    elif element and element.get("accessible_name"):
        base = str(element["accessible_name"])
    elif element and element.get("text"):
        base = str(element["text"])
    else:
        base = selector.value

    name = snake_case(base, fallback="element")

    # Give the name a type hint when it doesn't already read like one.
    suffix: str | None = None
    if element:
        tag = (element.get("tag") or "").lower()
        input_type = (element.get("input_type") or "").lower()
        suffix = {
            "button": "button",
            "a": "link",
            "select": "select",
            "textarea": "input",
        }.get(tag)
        if tag == "input":
            suffix = {"checkbox": "checkbox", "radio": "radio", "file": "upload"}.get(
                input_type, "input"
            )

    # No hint from the tag: fall back to the ARIA role, so a nav item becomes
    # `main_navigation` rather than a bare `main`.
    if suffix is None and selector.strategy is SelectorStrategy.ROLE_NAME:
        role, _, _ = selector.value.partition("|")
        suffix = snake_case(role) or None

    if suffix and not name.endswith(suffix):
        name = f"{name}_{suffix}"

    return name
