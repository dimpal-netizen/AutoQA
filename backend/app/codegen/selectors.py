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


#: Selectors that describe *where an element sits* rather than *what it is*.
#: A structural path is invalidated by any change to the markup around it —
#: a wrapper div, a reordered section, a new sibling — none of which change
#: the element itself.
_POSITIONAL = {
    SelectorStrategy.CSS,
    SelectorStrategy.XPATH,
    SelectorStrategy.NTH_CHILD,
}


#: Tags `get_by_label` is allowed to describe. See `usable_selectors`.
_FORM_CONTROLS = {"input", "select", "textarea"}


def usable_selectors(
    raw_selectors: list[dict[str, Any]], element: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Drop candidates that would not find the element they were recorded for.

    Only one does that, and it does it silently. `get_by_label` returns the
    *form control* a label is attached to - never the label, and never anything
    else inside it. The recorder does not know that, so a click on the styled box
    of a custom checkbox is recorded as:

        <span> 'House'   ->   label: "House"

    and rendered as `get_by_label("House")`, which resolves to the `<input>`
    hidden behind that span:

        - locator resolved to <input type="checkbox"/>
        - element is not visible

    Thirty seconds later the test is red, pointing at an element the recording
    never touched. Nothing in the failure says the selector changed target, which
    is what makes this worth ruling out here rather than debugging later.

    An unknown tag keeps every candidate: guessing is what caused the problem.
    """
    tag = str((element or {}).get("tag") or "").lower()
    if not tag or tag in _FORM_CONTROLS:
        return raw_selectors

    kept = [s for s in raw_selectors if s.get("strategy") != SelectorStrategy.LABEL.value]
    # Never strip the last one. A label is a poor description of a <span>, but a
    # test with no locator at all is worse than one aimed slightly wide.
    return kept or raw_selectors


def best_selector(
    raw_selectors: list[dict[str, Any]], element: dict[str, Any] | None = None
) -> Selector | None:
    """Pick the most durable candidate. Re-sorts rather than trusting order.

    Two properties compete, and the order between them is the whole decision.

    *Uniqueness* is about working at all. Playwright runs in strict mode, so a
    selector matching two elements raises rather than guessing:

        strict mode violation: get_by_placeholder("Email") resolved to 2 elements

    *Being descriptive* is about surviving the next UI change. `//body/section[2]
    /div[1]/div[1]/a[1]` describes a position in a tree; wrap that section in one
    more div and it points at nothing. `get_by_role("link", name="See All
    Properties")` describes the element, and survives any redesign that keeps the
    link saying what it says.

    Descriptive wins. An earlier version put uniqueness first outright, which
    meant a unique absolute XPath beat a role-and-name that happened to match two
    links — trading a test that fails on the next deploy for one that fails now.
    Neither is good, but `.first` on a semantic locator at least picks a real
    element by a name a human recognises, and keeps working when the page moves.

    Among equally descriptive candidates, uniqueness decides; then strategy rank;
    then the recorder's own score.
    """
    if not raw_selectors:
        return None

    candidates = [Selector.from_dict(s) for s in usable_selectors(raw_selectors, element)]
    return min(
        candidates,
        key=lambda s: (s.strategy in _POSITIONAL, not s.unique, s.rank, -s.score),
    )


#: HTML elements that are landmarks, and the ARIA role Playwright knows them by.
#:
#: Only the "page chrome" landmarks are listed. A site's navigation is routinely
#: repeated in the header and the footer — that duplication is the single most
#: common cause of a strict mode violation on a recorded test. `main` is
#: deliberately absent: its contents are rarely duplicated, so scoping to it
#: would add a way to break without removing one.
_LANDMARKS = {
    "header": "banner",
    "footer": "contentinfo",
    "nav": "navigation",
    "aside": "complementary",
}

#: `//body/header[1]/div[2]/...` or `header.Navbar div.navRight ul li a`
_XPATH_LANDMARK = re.compile(r"^(?://)?(?:html/)?(?:body/)?(header|footer|nav|aside)\b")
_CSS_LANDMARK = re.compile(r"^\s*(header|footer|nav|aside)\b")


def landmark_role(raw_selectors: list[dict[str, Any]]) -> str | None:
    """Which landmark the recorded element sits in, if we can tell.

    The recorder never captured this directly, but it did capture a CSS path and
    an XPath for every element, and both start at the landmark:

        //body/header[1]/div[2]/ul[1]/li[1]/a[1]

    Reading it back out means existing recordings get the benefit without being
    re-recorded, which matters — asking someone to walk through their app again
    to fix a bug in our generator is a poor trade.
    """
    for raw in raw_selectors:
        try:
            strategy = SelectorStrategy(raw["strategy"])
        except ValueError:
            continue

        value = str(raw.get("value", ""))
        if strategy is SelectorStrategy.XPATH:
            match = _XPATH_LANDMARK.match(value.removeprefix("xpath=").lstrip("/"))
        elif strategy is SelectorStrategy.CSS:
            match = _CSS_LANDMARK.match(value)
        else:
            continue

        if match:
            return _LANDMARKS[match.group(1)]

    return None


def scoped_root(raw_selectors: list[dict[str, Any]], root: str = "page") -> str:
    """`page` -> `page.get_by_role('banner')` when the element is in the header.

    This is what turns

        get_by_role("link", name="Home")            -> 2 elements, test dies

    into

        get_by_role("banner").get_by_role("link", name="Home")

    which is exactly what Playwright suggests in the strict mode error, and what
    a person would say out loud: the Home link *in the header*.
    """
    role = landmark_role(raw_selectors)
    return f"{root}.get_by_role({py_str(role)})" if role else root


#: Attributes that say *which* element this is when the name does not, strongest
#: first. Deliberately excludes anything that changes as the page is used - an
#: input's `value` would make one field look like a different one per keystroke.
#:
#: `href` is last because it is the only one that can carry a record id, and a
#: locator built on `/properties/cmryim584000q01p42kj4ts8q` describes one row on
#: one server on one day. It is still worth having: an ambiguous name with no
#: other way to tell it apart leaves `.first`, which is a guess either way.
_DISTINGUISHING = ("data-testid", "id", "name", "href")

#: A record id sitting in a URL - all digits, a UUID, or a long opaque token.
#: The digit is what separates `cmryim584000q01p42kj4ts8q` from a real slug
#: like `property-management`.
_RECORD_ID = re.compile(
    r"^\d+$|^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$|^(?=[a-z0-9]*\d)[a-z0-9]{16,}$",
    re.I,
)


def _is_stable(attribute: str, value: str) -> bool:
    """Would this still identify the same element tomorrow?

    Only hrefs are questioned, and only for the segments in their path. A query
    string like `?listing-type=NEW_PROJECT&property-type=HOUSE` is what the link
    is *for* and belongs in the locator; `/properties/cmryim584000q01p42kj4ts8q`
    is a row that will be gone by next week.
    """
    if attribute != "href":
        return True
    path = value.split("?", 1)[0].split("#", 1)[0]
    return not any(_RECORD_ID.match(segment) for segment in path.split("/") if segment)


def distinguisher(element: dict[str, Any] | None) -> tuple[str, str] | None:
    """The strongest (attribute, value) pair singling this element out, if any."""
    attributes = (element or {}).get("attributes") or {}
    for name in _DISTINGUISHING:
        value = str(attributes.get(name) or "").strip()
        if value and _is_stable(name, value):
            return name, value
    return None


def identity(element: dict[str, Any] | None) -> tuple[str, ...]:
    """What makes this element itself, beyond what it is called.

    Two nav items can share a role and an accessible name and still be different
    links. A property site had "House" under its Rent menu and "House" under its
    New Projects menu:

        <a href="/properties?listing-type=FOR_RENT&property-type=HOUSE">House</a>
        <a href="/properties?listing-type=NEW_PROJECT&property-type=HOUSE">House</a>

    Both render as `get_by_role("link", name="House", exact=True)`, so the page
    object kept one property for the two of them and every step aimed at either
    drove whichever came first. The recorded journey opened the New Projects
    menu and clicked the item in it; the test opened the same menu and clicked
    the Rent one, which was hidden, and waited thirty seconds. Nothing in the
    failure suggested two elements had been merged.

    Everything present is recorded here, and `conflicting` then compares only
    what the two have in common. That split matters, because the recorder
    captures whatever the element carried at the moment of the event and it is
    not the same set twice. The identical email field arrived as

        click  {id: "email", name: "email", data-testid: "email-input"}
        input  {data-testid: "email-input"}

    Requiring the sets to match would have made those two different elements and
    split one field into `email_input` and `email_input_2`. Comparing what they
    share - `data-testid`, which agrees - keeps them one.
    """
    attributes = (element or {}).get("attributes") or {}
    return tuple(
        f"{name}={value}"
        for name in _DISTINGUISHING
        if (value := str(attributes.get(name) or "").strip())
        and _is_stable(name, value)
    )


def conflicting(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """Do these two identities prove they are different elements?

    Only a disagreement on an attribute they both carry counts. An element with
    nothing to identify it is not evidence of anything, and treating "unknown"
    or "not captured this time" as "different" splits one element into several
    page-object properties - which is the failure this exists to avoid, in the
    other direction.
    """
    theirs = {pair.split("=", 1)[0]: pair for pair in right}
    return any(
        (mine := pair.split("=", 1)[0]) in theirs and theirs[mine] != pair
        for pair in left
    )


def py_str(value: str) -> str:
    """A Python string literal that is always safe to paste into generated code.

    Uses repr, which escapes quotes and backslashes correctly — building the
    literal by hand is how generated code ends up with syntax errors on values
    containing an apostrophe.
    """
    return repr(value)


#: Locators naming something a visitor can see. Sites duplicate these freely —
#: a desktop and a mobile copy of the same link, a call-to-action repeated in
#: two sections — and the duplicate is often absent when the recording is made.
_VISIBLE_NAME = {SelectorStrategy.ROLE_NAME, SelectorStrategy.TEXT}


def locator_expression(
    selector: Selector,
    root: str = "page",
    *,
    scoped: bool = False,
    narrow: str | None = None,
) -> str:
    """Render one selector as a Playwright call on `root`.

    `.first` is appended when the locator names a visible element and nothing
    has already disambiguated it. This is a deliberate reversal of an earlier,
    stricter position, and the reason is that record-time uniqueness turned out
    not to survive to run time:

        get_by_role("link", name="See All Properties") resolved to 2 elements
          1) <a href="/properties" class="...seeAllDesktop">
          2) <a href="/properties?listing-type=NEW_PROJECT">

    The recorder counted one match on the page in front of it. By the time the
    test ran, a second section had loaded carrying the same link. No amount of
    counting at record time can prevent that.

    `.first` on a locator that really does match one element is a no-op, so the
    cost is nothing in the common case, and in the uncommon case it is the
    difference between a test that runs and a test that raises every time. It
    is not applied when `scoped=True` — a landmark has already narrowed the
    search, and that is a sharper answer than "whichever comes first".

    Labels and placeholders are left strict on purpose. Two form fields sharing
    a label is a real accessibility defect, and a test that fails on it is
    doing its job.

    `narrow` is an attribute selector that tells this element from the others
    answering to the same name, and it goes on *before* `.first` - the whole
    point is to choose which one, and `.first.and_(...)` would pick one and then
    check it, which is the same guess with an extra step.
    """
    ambiguous = not selector.unique or (
        selector.strategy in _VISIBLE_NAME and not scoped
    )
    expression = _render(selector, root)
    if narrow:
        expression = f"{expression}.and_({root}.locator({py_str(narrow)}))"
    return expression + (".first" if ambiguous else "")


def _render(selector: Selector, root: str) -> str:
    """
    Note `exact=True` on every text-matching locator. Playwright matches these
    names as case-insensitive SUBSTRINGS by default, which is a trap for a
    recorder: at capture time `get_by_role("link", name="Home")` matched the
    one link the user clicked, so it was recorded as unique — but on a site
    with "Homes", "Home Loans" and "Find a Home" it resolves to five elements
    at run time and the test dies on a strict mode violation.

    We recorded one specific element with one specific accessible name. Exact
    is what we actually meant.
    """
    match selector.strategy:
        case SelectorStrategy.TEST_ID:
            return f"{root}.get_by_test_id({py_str(selector.value)})"

        case SelectorStrategy.ROLE_NAME:
            # Stored as "role|accessible name".
            role, _, name = selector.value.partition("|")
            if name:
                return (
                    f"{root}.get_by_role({py_str(role)}, name={py_str(name)}, exact=True)"
                )
            return f"{root}.get_by_role({py_str(role)})"

        case SelectorStrategy.LABEL:
            return f"{root}.get_by_label({py_str(selector.value)}, exact=True)"

        case SelectorStrategy.PLACEHOLDER:
            return f"{root}.get_by_placeholder({py_str(selector.value)}, exact=True)"

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
    return clip_words(cleaned, 42)


def clip_words(name: str, limit: int) -> str:
    """Shorten a snake_case name without cutting a word in half.

    Slicing to a character count produces `..._is_not_visible_on_the` and
    `..._on_a_naviga` — names that read like a truncated sentence, because they
    are one. Dropping whole words instead leaves something that still parses as
    English, and a name that stops early is far easier to read than one that
    stops mid-syllable.

    A single word longer than the limit is cut anyway; there is nothing else to
    do with it, and a link label can be arbitrarily long.
    """
    if len(name) <= limit:
        return name

    kept: list[str] = []
    used = 0
    for word in name.split("_"):
        # +1 for the underscore that will join it.
        cost = len(word) + (1 if kept else 0)
        if used + cost > limit:
            break
        kept.append(word)
        used += cost

    return "_".join(kept) if kept else name[:limit]


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
