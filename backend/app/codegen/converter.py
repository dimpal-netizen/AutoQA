"""Recorded actions → Playwright test code.

Plain deterministic Python, no AI. The mapping from an action to a Playwright
call is a fixed set of thirteen cases, so a function does it perfectly, for
free, and identically every time. Phase 4 layers AI on top of *already valid*
code to improve naming and structure — that way a failed model call degrades
the output instead of destroying it.

The pipeline is:

    normalise()  drop noise, collapse repeats, resolve waits
    build_ir()   actions → TestIR (pages + steps)
    then the templates render TestIR into files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.codegen.selectors import (
    Selector,
    best_selector,
    conflicting,
    distinguisher,
    element_name,
    frame_root,
    identity,
    locator_expression,
    py_str,
    scoped_root,
    snake_case,
    usable_selectors,
)
from app.models.enums import ActionType, SelectorStrategy

#: Locators that find an element by what it is called. These are the ones that
#: collide across a header and a footer, so these are the ones worth scoping to
#: a landmark.
_NAME_BASED = {
    SelectorStrategy.ROLE_NAME,
    SelectorStrategy.TEXT,
    SelectorStrategy.LABEL,
    SelectorStrategy.PLACEHOLDER,
}

MAX_IDENT = 60


# ---------------------------------------------------------------------------
# Intermediate representation
# ---------------------------------------------------------------------------
@dataclass
class LocatorSpec:
    """One element, as a property on a page object."""

    name: str
    expression: str          # e.g. self.page.get_by_test_id("email-input")
    strategy: str
    fragile: bool
    fallbacks: list[str] = field(default_factory=list)
    # Every recorded way of finding this element, best first, as runnable
    # expressions. `fallbacks` above is the same information written for a
    # human to read in the docstring; this is the version the test can execute
    # when the first one stops matching.
    candidates: list[tuple[str, str]] = field(default_factory=list)
    # Every recorded candidate matched more than one element, so the expression
    # ends in `.first`. Worth saying out loud: the test will run, but it may be
    # driving the wrong element.
    ambiguous: bool = False
    # The element occupied space on the page when it was recorded. False means
    # Playwright will not act on it: the click waits thirty seconds and fails.
    # Recorded steps keep it anyway - the recording is what it is - but nothing
    # new should be built on it. See `_is_visible`.
    visible: bool = True
    # What made this element itself, beyond what it is called. Two locators may
    # only be merged when these agree - see `PageSpec.add` and `identity`.
    identity: tuple[str, ...] = ()
    # The expression before any narrowing was added. Collisions are judged on
    # this: once two locators have been told apart their expressions differ, so
    # comparing the final ones would say there was never a clash.
    base_expression: str = ""


@dataclass
class PageSpec:
    class_name: str          # LoginPage
    module: str              # login_page
    url: str
    locators: list[LocatorSpec] = field(default_factory=list)

    def add(self, locator: LocatorSpec) -> str:
        """Register a locator, reusing an identical one. Returns its final name.

        Identical means the same expression *and* the same element. The second
        half is not pedantry: two nav items sharing a role and a name are two
        links, and merging them makes every step aimed at either drive whichever
        comes first. See `identity`.
        """
        for existing in self.locators:
            if existing.expression == locator.expression and not conflicting(
                existing.identity, locator.identity
            ):
                return existing.name

        # Same readable name, different element — disambiguate rather than
        # silently shadowing.
        taken = {loc.name for loc in self.locators}
        name = locator.name
        suffix = 2
        while name in taken:
            name = f"{locator.name}_{suffix}"
            suffix += 1

        self.locators.append(
            LocatorSpec(
                name=name,
                expression=locator.expression,
                strategy=locator.strategy,
                fragile=locator.fragile,
                fallbacks=locator.fallbacks,
                candidates=locator.candidates,
                ambiguous=locator.ambiguous,
                visible=locator.visible,
                identity=locator.identity,
                base_expression=locator.base_expression,
            )
        )
        return name

    def collides(self, base: str, identity: tuple[str, ...]) -> bool:
        """Would this expression find an element already registered as another?"""
        return any(
            existing.base_expression == base
            and conflicting(existing.identity, identity)
            for existing in self.locators
        )


@dataclass
class StepSpec:
    """One line (or few) of the test body, plus its human-readable description."""

    sequence: int
    action: ActionType
    code: list[str]
    description: str
    page_var: str | None = None
    locator_name: str | None = None
    input_data: str | None = None
    expected_result: str | None = None
    strategy: str | None = None
    fragile: bool = False
    # Which word from the synthesiser's vocabulary produced this step, when one
    # did. `action` alone cannot be edited back: seven different assertions all
    # arrive as ActionType.ASSERT, so a step loaded into the editor would come
    # back as whichever of them happened to be listed first. Empty for recorded
    # steps, which come from the recording rather than from a vocabulary.
    verb: str | None = None


@dataclass
class TestIR:
    suite_name: str
    function_name: str
    module_name: str
    start_url: str
    pages: list[PageSpec] = field(default_factory=list)
    steps: list[StepSpec] = field(default_factory=list)
    fragile_count: int = 0
    # Set when a step asserts on the URL: those use re.compile, so the module
    # needs `import re`. A flag rather than scanning the rendered code, which
    # would couple the template to string matching.
    needs_regex: bool = False
    # Set when a step uses a value that must differ per run, so the module
    # imports uuid4. Same reasoning as needs_regex: a flag rather than scanning
    # the rendered code, which would couple the template to string matching.
    needs_uuid: bool = False
    # Set when a step observes an element, so the module imports `unhealed`.
    # Assertions are looked up without healing - see `uses_unhealed` below.
    needs_unhealed: bool = False
    # Set when a step ticks a checkbox or radio, so the module imports
    # `set_checked` instead of calling `.check()` on a control that is very
    # probably invisible.
    needs_set_checked: bool = False
    # Set when a step hovers, so the module imports `reveal`. A hover only opens
    # a menu for the step after it, and must never be able to fail the test.
    needs_reveal: bool = False
    # (variable, expression, the value that was recorded) for each input the
    # application would refuse a second time. Assigned once at the top of the
    # test so two fields that were given the same address still get the same
    # one. See `_fresh_value`.
    unique_values: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def file_path(self) -> str:
        return f"tests/{self.module_name}.py"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalise(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop noise and collapse repeats before any code is generated.

    A raw recording contains things nobody wants in a test: a scroll for every
    gesture, the same field typed into twice, a navigation the click already
    implies. Cleaning here means every downstream stage sees tidy input.
    """
    live = [a for a in actions if not a.get("is_ignored")]
    result: list[dict[str, Any]] = []

    for action in live:
        kind = ActionType(action["action_type"])

        # The browser AutoQA launches starts on a blank page, and that first
        # navigation gets recorded like any other. Left in, the generated test
        # navigates away from the application it just opened and every step
        # after it fails on an empty document.
        if kind is ActionType.NAVIGATE and _is_blank(action):
            continue

        # A wheel event with no distance. Harmless but meaningless, and it is
        # a step that can appear in a failure report as though it mattered.
        if kind is ActionType.SCROLL and not _scroll_distance(action):
            continue

        # The mouse crossing the page on its way somewhere, rather than opening
        # anything:
        #
        #     hover "Find Agent" -> scroll
        #
        # Playwright hovers before every click anyway, so a hover is only worth a
        # step when something else depends on it. Nothing depends on this one: it
        # is followed by a scroll, a navigation, or the end of the recording.
        #
        # A hover followed by an action on a *different* element is kept, because
        # that is the shape of a menu being opened:
        #
        #     hover "New Projects+"  ->  click "House"
        #
        # An earlier version kept a hover only when the element advertised
        # itself with aria-haspopup, aria-expanded or a menu role. Almost no
        # site does. This one opens its navigation submenus on CSS hover from a
        # plain <a href>, so the hover was dropped, the submenu never opened,
        # and clicking the item inside it waited thirty seconds on a link that
        # was in the page all along:
        #
        #     Locator.click: Timeout 30000ms exceeded.
        #       - locator resolved to <a href="...property-type=HOUSE">House</a>
        #       - element is not visible
        #
        # The hazard that rule was guarding against is real, and it is handled
        # where it belongs instead: see `reveal` in the healing template. A hover
        # that only opens a menu is best-effort, so hovering something transient
        # -- "Creating Account..." -- costs a moment and never a verdict.
        if kind is ActionType.HOVER and not _reveals_something(live, action):
            continue

        # A gesture aimed at something with no size on the page. Nobody clicked
        # it, because there was nothing there to click: it is an overlay the
        # recorder caught instead of the thing underneath. One click on a map
        # pin arrived as three actions -
        #
        #     click <div>   "Zenith Towers, Upper Hill"   1198.4 x   0.0
        #     click <img>                                   26.0 x  37.0
        #     click <area>  #gmimap4 area                     0.0 x   0.0
        #
        # of which only the middle one is a thing a person can press. Keeping
        # the other two does not make the test more faithful to the recording;
        # it adds two steps that wait thirty seconds each and then report the
        # property listing as broken.
        #
        # Only gestures are dropped. A `fill` or a `select` on a control with no
        # size is the custom-widget pattern, which `set_checked` handles, and
        # dropping one would silently change what the test submits.
        if kind in _GESTURES and not _is_visible(action.get("element")):
            continue

        previous = result[-1] if result else None

        if previous is not None:
            prev_kind = ActionType(previous["action_type"])

            # Only the final position of a scroll gesture matters.
            if kind is prev_kind is ActionType.SCROLL:
                result[-1] = action
                continue

            # Hovering something and then acting on it is one intention, and
            # Playwright hovers before it clicks anyway. Recording both doubles
            # the number of ways the step can fail while testing nothing extra.
            # A hover over a *different* element is kept: that is a menu being
            # opened, which the next step depends on.
            if prev_kind is ActionType.HOVER and _same_element(previous, action):
                result[-1] = action
                continue

            # Typing into a field twice in a row: keep the final value.
            if (
                kind is prev_kind is ActionType.INPUT
                and _same_element(previous, action)
            ):
                result[-1] = action
                continue

            # Enter, and then the submit button, on the same page. Both were
            # recorded because a person pressed Enter and clicked before the
            # browser had finished leaving — but only one of them can happen
            # twice. Replayed, Enter submits, the page navigates, and the click
            # waits thirty seconds for a button that is no longer there:
            #
            #   Locator.click: Timeout 30000ms exceeded.
            #     waiting for locator("#login-button")
            #
            # which is the recorded test failing on every run despite recording
            # a flow that worked. The click is the one to keep: clicking a
            # submit button always submits, while Enter only does on some forms,
            # so keeping the click is right whichever of the two did the work.
            #
            # Same URL is what makes this safe. If Enter had been the thing that
            # navigated, the following click would have been recorded on the
            # next page, and dropping the Enter would strand the test on this
            # one.
            if (
                prev_kind is ActionType.KEY_PRESS
                and kind in (ActionType.CLICK, ActionType.DOUBLE_CLICK)
                and _is_submit_key(previous)
                and previous.get("url") == action.get("url")
            ):
                result[-1] = action
                continue

            # One click on a custom checkbox arrives as two actions. The person
            # clicks the styled box - a <span>, which is what they can see - and
            # the browser forwards that to the hidden <input>, which fires
            # `change`. So the recording holds:
            #
            #   click   <span>  'House'   box: 18.0 x 18.0
            #   uncheck <input> 'House'   box:  0.0 x  0.0
            #
            # Two steps, one gesture. The click is the one to drop: the span has
            # nothing to identify it but its position in the markup, so the test
            # ends up clicking whichever span comes first and ticking the wrong
            # filter. The toggle knows what it is - `get_by_role("checkbox",
            # name="House")` - and `set_checked` clicks its label, which is the
            # thing the person actually pressed.
            if (
                prev_kind in (ActionType.CLICK, ActionType.DOUBLE_CLICK)
                and kind in (ActionType.CHECK, ActionType.UNCHECK)
                and _is_proxy_for(previous, action)
            ):
                result[-1] = action
                continue

            # A click that navigates records both; the navigation becomes a
            # wait attached to the click rather than a separate step.
            if kind is ActionType.NAVIGATE and prev_kind in (
                ActionType.CLICK,
                ActionType.DOUBLE_CLICK,
            ):
                previous["_navigates_to"] = action["payload"].get("url")
                continue

        result.append(action)

    # A trailing scroll is just where the user left the page.
    while result and ActionType(result[-1]["action_type"]) is ActionType.SCROLL:
        result.pop()

    return result


#: Pages a browser shows when it has nothing to show. None of them are the
#: application under test, so none of them belong in a generated test.
_BLANK_URLS = ("about:blank", "about://blank", "chrome://newtab", "edge://newtab")


def _is_blank(action: dict[str, Any]) -> bool:
    """Only `payload["url"]` is consulted: for a navigation that is where it
    goes, while `action["url"]` is the page it left, and judging a destination
    by its origin would drop the wrong steps."""
    url = ((action.get("payload") or {}).get("url") or "").strip()
    return not url or url.lower().rstrip("/") in _BLANK_URLS


def _scroll_distance(action: dict[str, Any]) -> int:
    """How far a scroll actually moved, in pixels."""
    payload = action.get("payload") or {}
    return abs(int(payload.get("x") or 0)) + abs(int(payload.get("y") or 0))


#: What a control that opens something declares about itself. Presence is what
#: counts, not the value: `aria-expanded="false"` is a disclosure control that
#: happens to be closed, which is exactly the one worth hovering.
_MENU_ATTRIBUTES = ("aria-haspopup", "aria-expanded", "aria-controls")

#: Roles that only exist on things that open, or live inside something that did.
_MENU_ROLES = {"menu", "menubar", "menuitem", "combobox", "listbox"}


def _opens_a_menu(action: dict[str, Any]) -> bool:
    """Does this element say out loud that it opens something?

    aria-haspopup, aria-expanded and the menu roles are the accessible way of
    announcing a menu, and an element carrying one is keeping its hover whatever
    follows it.

    Almost nothing carries one, which is why this cannot be the whole test — see
    `_reveals_something`.
    """
    element = action.get("element") or {}
    attributes = {
        str(name).lower() for name in (element.get("attributes") or {})
    }
    if any(name in attributes for name in _MENU_ATTRIBUTES):
        return True
    return str(element.get("role") or "").strip().lower() in _MENU_ROLES


#: What a hover has to be followed by to have revealed anything. A scroll or a
#: navigation happens wherever the pointer is; neither is evidence of a menu.
_DEPENDS_ON_A_HOVER = {
    ActionType.CLICK,
    ActionType.DOUBLE_CLICK,
    ActionType.HOVER,
    ActionType.INPUT,
    ActionType.SELECT,
    ActionType.CHECK,
    ActionType.UNCHECK,
}


def _reveals_something(live: list[dict[str, Any]], action: dict[str, Any]) -> bool:
    """Is this hover load-bearing, or the mouse on its way past?

    The evidence is what comes next. A hover followed by an action on a
    *different* element is the shape of a menu being opened and then used:

        hover "New Projects+"  ->  click "House"

    A hover followed by a scroll, a navigation, or nothing at all revealed
    nothing that anything went on to need - scrolling away is close to proof
    that the pointer was only passing through. And a hover followed by an action
    on the same element is the pointer arriving where it was already going,
    which the collapse rule below removes anyway.

    Only the very next action counts. Anything further on has had a scroll or a
    page load in between, and a menu does not survive either.

    This is a guess, and it is allowed to be, because being wrong is cheap in
    one direction and not the other: a hover kept needlessly is best-effort and
    costs a moment (see `reveal`), while a hover dropped wrongly costs a
    thirty-second timeout on a menu item that never appeared.
    """
    if _opens_a_menu(action):
        return True

    index = live.index(action)
    following = live[index + 1] if index + 1 < len(live) else None
    if following is None:
        return False

    return (
        ActionType(following["action_type"]) in _DEPENDS_ON_A_HOVER
        and not _same_element(action, following)
    )


#: Keys that submit a form. Only these can make a following click redundant —
#: Tab or Escape change focus and leave the button exactly where it was.
_SUBMIT_KEYS = {"enter", "numpadenter", "return"}


def _is_submit_key(action: dict[str, Any]) -> bool:
    key = ((action.get("payload") or {}).get("key") or "").strip().lower()
    return key.replace(" ", "") in _SUBMIT_KEYS


def _is_proxy_for(click: dict[str, Any], toggle: dict[str, Any]) -> bool:
    """Was that click the visible stand-in for this checkbox?

    Three things have to hold, and each one rules out a real pair of steps:

    * the toggle's own control is invisible - a visible checkbox needs no
      stand-in, and `check()` on one works fine;
    * the click was not on a form control - otherwise it is a different field;
    * both name the same thing, which is what a shared `<label>` gives them.

    Same page, immediately adjacent, is already guaranteed by the caller.
    """
    if _is_visible(toggle.get("element")):
        return False

    clicked = click.get("element") or {}
    if (clicked.get("tag") or "").lower() in _FORM_CONTROLS:
        return False

    return _accessible_name(clicked) == _accessible_name(toggle.get("element")) != ""


_FORM_CONTROLS = {"input", "select", "textarea"}

#: Actions that are a person aiming the pointer at something they can see. These
#: are the ones a zero-size target disproves; typing into a hidden control is a
#: real pattern, aiming at one is not.
_GESTURES = {
    ActionType.CLICK,
    ActionType.DOUBLE_CLICK,
    ActionType.HOVER,
}


def _accessible_name(element: dict[str, Any] | None) -> str:
    if not element:
        return ""
    return str(element.get("accessible_name") or element.get("text") or "").strip()


def _is_visible(element: dict[str, Any] | None) -> bool:
    """Did this element occupy any space on the page when it was recorded?

    A control with no width or no height cannot be clicked by a person, so it is
    never what they clicked - it is the machinery behind what they clicked.
    Unknown counts as visible: an old recording with no box should keep behaving
    exactly as it did.
    """
    box = (element or {}).get("bounding_box")
    if not box:
        return True
    return bool(box.get("width")) and bool(box.get("height"))


def _same_element(a: dict[str, Any], b: dict[str, Any]) -> bool:
    first = best_selector(a.get("selectors") or [])
    second = best_selector(b.get("selectors") or [])
    if first is None or second is None:
        return False
    return (first.strategy, first.value) == (second.strategy, second.value)


# ---------------------------------------------------------------------------
# Page objects
# ---------------------------------------------------------------------------
def _is_identifier_segment(segment: str) -> bool:
    """True when a URL path segment is a record id rather than a page name.

    An id in the path becomes part of the page object's name if it is not
    caught, and the result is a class called
    `PropertiesCmryim584000q01p42kj4ts8qPage` that no longer matches anything
    the next time the record changes.

    Three shapes, all of which appear in real URLs:

    - all digits — `/orders/1042/edit`
    - a UUID — `/users/3f2504e0-4f89-11d3-9a0c-0305e82c3301`
    - an opaque token: long, alphanumeric, and containing a digit. That last
      condition is what separates `cmryim584000q01p42kj4ts8q` from a genuine
      slug like `property-management`, and it is why the length floor is
      generous — real page names rarely carry digits at all.
    """
    if not segment:
        return False
    if segment.isdigit():
        return True
    if re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", segment, re.I):
        return True
    return len(segment) >= 12 and segment.isalnum() and any(c.isdigit() for c in segment)


def page_identity(url: str) -> tuple[str, str]:
    """(ClassName, module_name) for the page at `url`."""
    path = urlparse(url).path.strip("/")
    if not path:
        base = "home"
    else:
        # Skip path segments that are ids — /orders/1042/edit -> orders_edit
        parts = [p for p in path.split("/") if not _is_identifier_segment(p)]
        base = "_".join(parts[-2:]) if parts else "home"

    module = snake_case(base, fallback="page")
    if not module.endswith("_page"):
        module = f"{module}_page"

    class_name = "".join(word.capitalize() for word in module.split("_"))
    return class_name, module


def _page_for(ir: TestIR, url: str) -> PageSpec:
    class_name, module = page_identity(url)
    for page in ir.pages:
        if page.class_name == class_name:
            return page

    page = PageSpec(class_name=class_name, module=module, url=_clean_url(url))
    ir.pages.append(page)
    return page


def _clean_url(url: str) -> str:
    """Drop the query string — recorded ids and tokens should not be baked in."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else url


def _arrives_at(destination: str) -> str:
    """A pattern matching that address, with or without whatever follows it.

    `_clean_url` throws the query string away on purpose - a recorded
    `?token=...` or `?id=cmryim584000q01p42` is one row on one server on one
    day. But the browser still goes to the full address, so waiting for the
    cleaned one as an exact string waits for something that never arrives:

        waiting for navigation to ".../properties" until 'load'
          navigated to ".../properties?listing-type=NEW_PROJECT&property-type=HOUSE"

    Thirty seconds, then red, on a navigation that happened correctly and is
    printed in the failure saying so.

    Anchored at both ends, and only a query or a fragment may follow, so this
    stays a real check: `/properties` does not match `/properties/cmryim584...`,
    which is a different page.
    """
    return rf"^{re.escape(destination.rstrip('/'))}/?(?:[?#].*)?$"


# ---------------------------------------------------------------------------
# Actions → code
# ---------------------------------------------------------------------------
def build_ir(
    actions: list[dict[str, Any]],
    *,
    suite_name: str,
    start_url: str,
) -> TestIR:
    """Turn normalised actions into everything the templates need."""
    function_name = snake_case(suite_name, fallback="recorded_flow")
    if not function_name.startswith("test_"):
        function_name = f"test_{function_name}"

    ir = TestIR(
        suite_name=suite_name,
        function_name=function_name,
        module_name=function_name,
        start_url=_clean_url(start_url),
    )

    ir.steps.append(
        StepSpec(
            sequence=0,
            action=ActionType.NAVIGATE,
            code=[f"page.goto({py_str(ir.start_url)})"],
            description=f"Open {ir.start_url}",
            expected_result="The page loads",
        )
    )

    # The recorder logs the opening navigation too, and again after every
    # click that navigates. Emitting those would produce a goto to the page we
    # are already on.
    current_url = ir.start_url

    for action in normalise(actions):
        if ActionType(action["action_type"]) is ActionType.NAVIGATE:
            if _clean_url(str(action["payload"].get("url", ""))) == current_url:
                continue

        step = _build_step(ir, action, sequence=len(ir.steps))
        if step is None:
            continue

        if step.action is ActionType.NAVIGATE:
            current_url = _clean_url(str(action["payload"].get("url", "")))
        elif action.get("_navigates_to"):
            current_url = _clean_url(str(action["_navigates_to"]))

        ir.steps.append(step)

    # Renumber: skipped actions would otherwise leave gaps in the comments.
    for index, step in enumerate(ir.steps):
        step.sequence = index

    ir.fragile_count = sum(1 for step in ir.steps if step.fragile)
    ir.needs_unhealed = uses_unhealed(ir.steps)
    ir.needs_set_checked = any(
        step.action in (ActionType.CHECK, ActionType.UNCHECK) for step in ir.steps
    )
    ir.needs_reveal = any(step.action is ActionType.HOVER for step in ir.steps)
    return ir


def uses_unhealed(steps: list[StepSpec]) -> bool:
    """True when a step observes an element, so the module imports `unhealed`.

    Every assertion that names an element is looked up without healing, because
    a spare would answer the question about a different element. The assertions
    about the URL name no element and need nothing.
    """
    return any(
        step.action is ActionType.ASSERT and step.locator_name for step in steps
    )


def _build_step(ir: TestIR, action: dict[str, Any], *, sequence: int) -> StepSpec | None:
    kind = ActionType(action["action_type"])
    payload = action.get("payload") or {}
    element = action.get("element")
    # Everything below reads `usable`, not the raw list. A candidate that would
    # find a different element is no safer as a fallback than as the primary -
    # healing would reach for it the moment the page shifted.
    usable = usable_selectors(action.get("selectors") or [], element)
    selector = best_selector(usable, element)

    # Page-level actions need no locator.
    if kind is ActionType.NAVIGATE:
        url = _clean_url(str(payload.get("url", "")))
        return StepSpec(
            sequence=sequence,
            action=kind,
            code=[f"page.goto({py_str(url)})"],
            description=f"Go to {url}",
            expected_result="The page loads",
        )

    if kind is ActionType.SCROLL:
        y = int(payload.get("y", 0))
        return StepSpec(
            sequence=sequence,
            action=kind,
            code=[f"page.mouse.wheel(0, {y})"],
            description=f"Scroll down {y}px",
        )

    if kind is ActionType.KEY_PRESS and selector is None:
        key = str(payload.get("key", "Enter"))
        return StepSpec(
            sequence=sequence,
            action=kind,
            code=[f"page.keyboard.press({py_str(key)})"],
            description=f"Press {key}",
        )

    if selector is None:
        return None  # nothing to target; the schema should have caught this

    page_spec = _page_for(ir, action["url"])
    page_var = snake_case(page_spec.module.removesuffix("_page"), fallback="page_object")

    frame_path = action.get("frame_path") or []
    root = frame_root(frame_path, "self.page")

    # Scope name-based locators to the landmark they were recorded in. A site's
    # nav links usually appear in both the header and the footer, so
    # `get_by_role("link", name="Home")` finds two elements and Playwright
    # refuses to guess. Test ids and element ids are already unique by
    # definition and are left alone.
    scoped = False
    if selector.strategy in _NAME_BASED:
        narrowed = scoped_root(usable, root)
        scoped = narrowed != root
        root = narrowed

    # A name-based locator describes what an element is called, and a site can
    # call two different things the same:
    #
    #   <a href="...listing-type=FOR_RENT&property-type=HOUSE">House</a>
    #   <a href="...listing-type=NEW_PROJECT&property-type=HOUSE">House</a>
    #
    # `get_by_role("link", name="House")` is both of them, so `.first` decides
    # which one the test drives - and `.first` is DOM order, not intent. The
    # recorded journey opened the New Projects menu and clicked the item inside
    # it. The test opened the same menu and clicked the Rent one, which was
    # hidden, and waited thirty seconds. Nothing in the failure hinted that two
    # elements had been folded into one.
    #
    # So when the recorder counted more than one match, or when this expression
    # is already registered for a different element, narrow it by whatever tells
    # them apart. `and_` keeps the readable half - still "the link called House"
    # - and adds only the part that decides which.
    who = identity(element)
    apart = distinguisher(element)
    base = locator_expression(selector, root, scoped=scoped)

    narrow = None
    if apart and (not selector.unique or page_spec.collides(base, who)):
        narrow = f"[{apart[0]}={apart[1]!r}]"

    expression = locator_expression(selector, root, scoped=scoped, narrow=narrow)

    # Rank the candidates ourselves rather than trusting input order, and drop
    # the one we actually used — listing the primary as its own fallback is
    # noise.
    ranked = sorted(
        (Selector.from_dict(s) for s in usable),
        key=lambda s: (s.rank, -s.score),
    )
    spares = [
        s for s in ranked
        if (s.strategy, s.value) != (selector.strategy, selector.value)
    ][:3]
    fallbacks = [f"{s.strategy.value}: {s.value}" for s in spares]

    # The chosen selector first, then the spares in rank order. A positional
    # spare is deliberately kept: when the descriptive one has stopped matching,
    # a path through the DOM is worth trying before giving up.
    candidates = [(selector.strategy.value, expression)] + [
        (s.strategy.value, locator_expression(s, root)) for s in spares
    ]
    name = page_spec.add(
        LocatorSpec(
            name=element_name(selector, element),
            expression=expression,
            strategy=selector.strategy.value,
            fragile=selector.is_fragile,
            fallbacks=fallbacks,
            candidates=candidates,
            ambiguous=not selector.unique,
            visible=_is_visible(element),
            identity=who,
            base_expression=base,
        )
    )

    target = f"{page_var}.{name}"
    label = _readable_target(selector, element, usable)
    code: list[str] = []
    description = ""
    input_data: str | None = None
    expected: str | None = None

    match kind:
        case ActionType.CLICK:
            code = [f"{target}.click()"]
            description = f"Click {label}"
        case ActionType.DOUBLE_CLICK:
            code = [f"{target}.dblclick()"]
            description = f"Double-click {label}"
        case ActionType.HOVER:
            # Best-effort. A hover opens a menu for the step after it and
            # asserts nothing itself, so it must not be able to fail the test -
            # see `reveal` in pages/_healing.py.
            code = [f"reveal({target})"]
            description = f"Hover over {label}"
        case ActionType.INPUT:
            value = str(payload.get("value", ""))
            # A sign-up form creates a record, and the recorded address is in it
            # from the first run onwards. Replaying the same one asks the
            # application to create the same account twice, which it is right to
            # refuse — so the test passes once and is red for ever after.
            fresh = _fresh_value(ir, value, element, str(action.get("url") or ""))
            code = [f"{target}.fill({fresh or py_str(value)})"]
            description = f"Type into {label}"
            input_data = value
        case ActionType.SELECT:
            values = payload.get("values") or []
            arg = py_str(str(values[0])) if len(values) == 1 else repr([str(v) for v in values])
            code = [f"{target}.select_option({arg})"]
            description = f"Select {', '.join(map(str, values))} in {label}"
            input_data = ", ".join(map(str, values))
        case ActionType.CHECK:
            # Not `.check()`. See `set_checked` in pages/_healing.py: the real
            # input is usually 0x0 and hidden under a styled box, and Playwright
            # waits thirty seconds before failing on it.
            code = [f"set_checked({target}, True)"]
            description = f"Tick {label}"
            expected = f"{label} is checked"
        case ActionType.UNCHECK:
            code = [f"set_checked({target}, False)"]
            description = f"Untick {label}"
            expected = f"{label} is not checked"
        case ActionType.UPLOAD:
            files = [str(f) for f in (payload.get("files") or [])]
            arg = py_str(files[0]) if len(files) == 1 else repr(files)
            code = [
                "# Place the file next to this test, or point at a fixture.",
                f"{target}.set_input_files({arg})",
            ]
            description = f"Upload {', '.join(files)} to {label}"
            input_data = ", ".join(files)
        case ActionType.KEY_PRESS:
            key = str(payload.get("key", "Enter"))
            code = [f"{target}.press({py_str(key)})"]
            description = f"Press {key} in {label}"
        case ActionType.DRAG_DROP:
            drop_selector = best_selector(payload.get("target_selectors") or [])
            if drop_selector is None:
                return None
            drop_name = page_spec.add(
                LocatorSpec(
                    name=element_name(drop_selector, None) + "_target",
                    expression=locator_expression(drop_selector, root),
                    strategy=drop_selector.strategy.value,
                    fragile=drop_selector.is_fragile,
                    ambiguous=not drop_selector.unique,
                )
            )
            code = [f"{target}.drag_to({page_var}.{drop_name})"]
            description = f"Drag {label} onto {drop_name.replace('_', ' ')}"
        case ActionType.ASSERT:
            kind_name = str(payload.get("kind", "to_be_visible"))
            # An assertion asks about *this* element, so it is looked up with
            # healing switched off: a spare would answer about a different one.
            # See `unhealed` in pages/_healing.py.
            observed = f"unhealed({page_var}, {py_str(name)})"
            if kind_name == "to_have_text":
                text = str(payload.get("expected", ""))
                code = [f"expect({observed}).to_have_text({py_str(text)})"]
                description = f"Check {label} shows {text!r}"
                expected = text
            else:
                code = [f"expect({observed}).to_be_visible()"]
                description = f"Check {label} is visible"
                expected = f"{label} is visible"
        case _:
            return None

    # A click that caused a navigation waits for it, rather than asserting the
    # URL immediately — an instant assert is a classic source of flakiness.
    if action.get("_navigates_to"):
        destination = _clean_url(action["_navigates_to"])
        ir.needs_regex = True
        code.append(f"page.wait_for_url(re.compile({py_str(_arrives_at(destination))}))")
        expected = f"Navigates to {destination}"

    return StepSpec(
        sequence=sequence,
        action=kind,
        code=code,
        description=description,
        page_var=page_var,
        locator_name=name,
        input_data=input_data,
        expected_result=expected,
        strategy=selector.strategy.value,
        fragile=selector.is_fragile,
    )


# ---------------------------------------------------------------------------
# Values that cannot be replayed
#
# The recorded suite's own regression test read:
#
#     register_buyer.email_input.fill('lucy@yopmail.com')
#     register_buyer.mobile_number_input.fill('9632587412')
#
# It passed the day it was recorded and failed every day after, because by then
# that account existed and the application was right to refuse a second one. The
# steps were correct, the application was correct, and the test was red — which
# is the most expensive way for a test to be wrong, because the tester spends an
# afternoon on it and then learns to ignore the next red test.
#
# `synth.py` has had placeholders for this since the model started inventing
# sign-up cases. The recording never went through them: it replays exactly what
# was typed, which is right for a login and fatal for a registration.
# ---------------------------------------------------------------------------

#: Where filling in a form creates a record rather than reading one.
_SIGNUP_PATH = re.compile(r"regist|sign[-_]?up|signup|create[-_]?account|join", re.I)

#: What the replacement looks like. The recorded value's own shape is kept
#: wherever it carries a constraint: a domain the application accepted, a
#: number of the length and leading digit its country expects. Inventing those
#: from nothing is how a "fix" for one form breaks another.
_EMAIL = "f'autoqa-{uuid4().hex[:10]}@%s'"
_PHONE = "f'%s{uuid4().int %% %d:0%dd}'"
_TEXT = "f'autoqa{uuid4().hex[:8]}'"

_DOMAIN_OK = re.compile(r"^[a-zA-Z0-9.-]+$")

#: An address, not merely something with an @ in it. `Test@1234` has an @ and is
#: a password — substituting it locked the test out of the account it had just
#: created, with the failure landing on the login step two tests later.
_LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Never replaced, whatever else they look like. A password is typed into a
#: sign-up form and is not an identity: the account is created with it and the
#: test needs it again to sign in.
_SECRET = ("password", "passcode", "pin", "secret", "cvv", "otp")


def _field_words(element: dict[str, Any] | None) -> str:
    """Everything the recorder knows about what a field is called, lowercased."""
    if not element:
        return ""
    attributes = element.get("attributes") or {}
    parts = [
        element.get("input_type"),
        element.get("accessible_name"),
        attributes.get("name"),
        attributes.get("id"),
        attributes.get("placeholder"),
        attributes.get("data-testid"),
        attributes.get("autocomplete"),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _fresh_expression(value: str, element: dict[str, Any] | None) -> str | None:
    """A per-run replacement for one recorded value, or None to keep it.

    Only the fields that have to be unique for a record to exist at all. A
    password is typed into a sign-up form too and must stay exactly as recorded:
    it is not an identity, and changing it would lock the test out of the
    account it just made.
    """
    words = _field_words(element)

    if any(secret in words for secret in _SECRET):
        return None

    if "email" in words or _LOOKS_LIKE_EMAIL.match(value.strip()):
        domain = value.rpartition("@")[2].strip()
        if not domain or not _DOMAIN_OK.match(domain):
            # example.test is reserved and cannot receive mail, so it is only
            # right when the recording gives us nothing better to copy.
            domain = "example.test"
        return _EMAIL % domain

    digits = value.strip()
    if digits.isdigit() and (
        "tel" in words or "phone" in words or "mobile" in words or "contact" in words
    ):
        # Same length and same leading digit as the number that was accepted.
        # A hard-coded shape is how a generated Indian number ends up in a form
        # defaulting to Kenya, where it is not a valid number at all.
        rest = len(digits) - 1
        if rest < 1:
            return None
        return _PHONE % (digits[0], 10**rest, rest)

    if "username" in words or "user_name" in words:
        return _TEXT

    return None


def _fresh_value(
    ir: TestIR, value: str, element: dict[str, Any] | None, url: str
) -> str | None:
    """The variable holding a per-run value for `value`, or None to keep it.

    Hoisted to a variable rather than inlined, because the same address is often
    typed twice — an email and its confirmation — and two separate calls to
    `uuid4()` would put two different addresses in fields the form requires to
    match. One name, assigned once, read wherever it was recorded.
    """
    if not value.strip() or not _SIGNUP_PATH.search(urlparse(url).path or ""):
        return None

    expression = _fresh_expression(value, element)
    if expression is None:
        return None

    for name, existing, recorded in ir.unique_values:
        if recorded == value:
            return name

    kind = "email" if "@" in expression else "mobile" if "uuid4().int" in expression else "id"
    name = f"fresh_{kind}"
    taken = {existing_name for existing_name, _, _ in ir.unique_values}
    suffix = 2
    while name in taken:
        name = f"fresh_{kind}_{suffix}"
        suffix += 1

    ir.unique_values.append((name, expression, value))
    ir.needs_uuid = True
    return name


# Selectors whose value is text a human would recognise, most natural first.
_HUMAN_STRATEGIES = ("label", "placeholder", "role_name", "text", "test_id")


def _readable_target(
    selector: Selector,
    element: dict[str, Any] | None,
    candidates: list[dict[str, Any]] | None = None,
) -> str:
    """How a person would refer to the element in a sentence.

    Deliberately independent of which selector the code uses. Those answer
    different questions: the code wants the most *reliable* way to find the
    element, the description wants the most *recognisable* name for it. Tying
    them together means fixing an unreliable selector turns a step that read
    `Type into "Email"` into `Type into "#email"`, which is a worse description
    of the very same click.
    """
    if element:
        for key in ("accessible_name", "text"):
            value = element.get(key)
            if value:
                return f'"{str(value)[:60]}"'

    for strategy in _HUMAN_STRATEGIES:
        for raw in candidates or []:
            if raw.get("strategy") != strategy:
                continue
            value = str(raw.get("value", ""))
            if strategy == "role_name":
                _, _, value = value.partition("|")
            if value:
                return f'"{value[:60]}"'

    if selector.strategy.value == "role_name":
        _, _, name = selector.value.partition("|")
        if name:
            return f'"{name}"'
    return f'"{selector.value[:60]}"'


def page_variables(ir: TestIR) -> list[tuple[str, str]]:
    """(variable, ClassName) pairs the test body needs to construct."""
    seen: dict[str, str] = {}
    for page in ir.pages:
        variable = snake_case(page.module.removesuffix("_page"), fallback="page_object")
        seen[variable] = page.class_name
    return sorted(seen.items())
