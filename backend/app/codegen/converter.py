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

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.codegen.selectors import (
    _DECORATION,
    Selector,
    actionable_ancestor,
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
from app.codegen.dataroles import (
    SUBSTITUTE_ABOVE,
    DataRole,
    Decision,
    classify_targets,
    classify_values,
    identity_kind,
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

logger = logging.getLogger(__name__)

MAX_IDENT = 60

#: The helpers a generated test may call from pages/_state.py. Named here
#: because both the import line and the decision to ship the file are worked out
#: from the code that was emitted - see `TestIR.state_helpers`.
STATE_HELPERS = ("one_of", "submit")


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
    # The step before this one put it on screen: a menu opened, a modal, a video
    # overlay. Recorded steps reach it the same way the person did, but a test
    # case that opens the page and goes straight for it cannot - see
    # `_was_revealed`.
    revealed: bool = False
    # The tag the recording captured - "button", "a", "input". A spare that
    # finds a different kind of element is not this element, whatever its
    # selector says. See `heal`.
    tag: str = ""
    # Was it on screen when the page was opened cold? False means a case that
    # goes straight there finds nothing - a Checkout button on an empty cart, a
    # field on the second step of a wizard. True when nothing was measured, so a
    # suite generated without a probe behaves exactly as it did. See probe.py.
    reachable: bool = True
    # The role this element plays in the test's data - see `dataroles.py`. Only
    # STATE_DEPENDENT means anything here, and it means "if the application
    # refuses this, a comparable element may be tried instead". Never "start
    # somewhere else": the recorded element is what runs first, every time.
    role: str = DataRole.STATIC.value
    # The locator matching everything of the same shape as this one, when the
    # recording holds a way of finding them. Read only after a refusal.
    among: str | None = None
    # Set on that second locator, naming the one it serves. It is not an element
    # the recording ever touched - no step targets it, and nothing but a refused
    # step ever reads it - so anything counting the elements a recording used
    # should skip it.
    alternatives_for: str | None = None


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
            if (
                existing.expression == locator.expression
                and existing.role == locator.role
                and not conflicting(existing.identity, locator.identity)
            ):
                # Reached without opening anything even once, anywhere in the
                # recording, and it is reachable. The question is only ever
                # whether a test case can get to it at all.
                existing.revealed = existing.revealed and locator.revealed
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
                revealed=locator.revealed,
                tag=locator.tag,
                reachable=locator.reachable,
                role=locator.role,
                among=locator.among,
                alternatives_for=locator.alternatives_for,
            )
        )
        return name

    def remember_alternatives(self, name: str, among: str | None) -> None:
        """Note which locator holds the comparable elements for another.

        Carried on the IR for anything that reads it - a report, the editor -
        rather than for the generated code, which is handed the name directly.
        """
        if among is None:
            return
        for locator in self.locators:
            if locator.name == name:
                locator.among = among
                return

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
    # This step typed into a password field. The one unambiguous marker of
    # where a recording signed in, and so of which pages after it need an
    # account - see `sign_in_sequence` in synth.py.
    is_password: bool = False
    # Which of the tests the person performed this step belongs to. A recording
    # is rarely one test - see `codegen/segments.py` - and the cut is worked out
    # from the actions, before any of them became steps. Carried here so the
    # split survives normalisation, which drops and merges actions and would
    # otherwise leave nothing to line the two up by.
    segment: int = 0


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
    # Set when a step uploads, so the module imports `sample_file`. The file the
    # recording names is on somebody else's machine; this one is built at run
    # time. See pages/_files.py.
    needs_sample_file: bool = False
    # UNIQUE fields filled in but not yet submitted, as (page variable, locator
    # name, the expression that makes a fresh value). Accumulated by the fills
    # and claimed by the click that sends them - see `_renewals_for`.
    pending_renew: list[tuple[str, str, str]] = field(default_factory=list)
    # (variable, expression, the value that was recorded) for each input the
    # application would refuse a second time. Assigned once at the top of the
    # test so two fields that were given the same address still get the same
    # one. See `_fresh_value`.
    unique_values: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def state_helpers(self) -> list[str]:
        """Which pages/_state.py helpers this module's steps actually call.

        Read off the steps rather than carried as a flag, and that is the whole
        point of it. Every other `needs_*` on this class is a flag somebody has
        to remember to copy, and a TestIR is derived in three other places - a
        recording is sliced into one test per journey, invented cases are built
        from a vocabulary, cases are rebuilt from recorded steps. Two of those
        copied the steps and forgot the flag, so a generated module called
        `one_of` without importing it and the whole batch of cases was rejected:

            tests/test_product_add_to_cart_alternative_button.py
            uses one_of without importing it

        A step that calls the helper is the only thing that can possibly decide
        this, so it is the thing asked.
        """
        return sorted(
            {
                helper
                for step in self.steps
                for line in step.code
                for helper in STATE_HELPERS
                if line.lstrip().startswith(f"{helper}(")
            }
        )

    @property
    def needs_state(self) -> bool:
        """True when anything in this module needs pages/_state.py."""
        return bool(self.state_helpers)

    @property
    def needs_sync(self) -> bool:
        """True when any step waits for what its action was observed to do.

        Read off the steps for the same reason `state_helpers` is: a TestIR is
        derived in three other places and a flag is a thing somebody has to
        remember to copy.
        """
        return any(
            line.lstrip().startswith("after(")
            for step in self.steps
            for line in step.code
        )

    @needs_sync.setter
    def needs_sync(self, _value: bool) -> None:
        """Accepted and ignored: the steps are the only thing that decides."""

    def renewal_for(self, name: str) -> str:
        """The expression that made a hoisted value, so it can make another.

        The variable at the top of the test holds one value for the whole run,
        which is what two fields that must match need. Retrying a refused
        submission needs a *new* one, and that means the expression rather than
        the variable.
        """
        for existing, expression, _recorded in self.unique_values:
            if existing == name:
                return expression
        return "''"

    @property
    def file_path(self) -> str:
        return f"tests/{self.module_name}.py"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalise(
    actions: list[dict[str, Any]], *, host: str | None = None
) -> list[dict[str, Any]]:
    """Drop noise and collapse repeats before any code is generated.

    A raw recording contains things nobody wants in a test: a scroll for every
    gesture, the same field typed into twice, a navigation the click already
    implies. Cleaning here means every downstream stage sees tidy input.

    `host` is the application under test. Without it nothing is dropped for
    being somewhere else, which is what every existing caller and test expects.
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

        # An advertising pixel, an analytics beacon, a payment iframe: the
        # browser navigates to these on its own and the recorder writes them
        # down like any other navigation. Replayed, the test leaves the
        # application entirely, and one recorded journey died on
        #
        #     Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE
        #       at https://googleads.g.doubleclick.net/xbbe/pixel
        #
        # which is a recorded test failing on an ad network. `synth.py` has
        # refused these on the generated-case path since a made-up subdomain
        # errored a test the same way; the recorded path never had the rule.
        if kind is ActionType.NAVIGATE and not _same_site(
            host, urlparse(str((action.get("payload") or {}).get("url") or "")).hostname
        ):
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


def _aim_at_the_control(
    selector: Selector | None, element: dict[str, Any] | None
) -> Selector | None:
    """Point a click at the button rather than at the icon drawn on it.

    Only when the element has nothing else going for it. A `<path>` inside an
    `<svg>` inside a `<button>` has no role, no name, no label and no test id,
    so the best way of finding it is a path through the DOM - and that is
    precisely the case where what somebody meant is the control it sits in. An
    element with a name of its own is left alone, because then the recording
    knows what was clicked.

    See `actionable_ancestor` for the failure this comes from.
    """
    if selector is None or selector.strategy is not SelectorStrategy.XPATH:
        return selector

    tag = str((element or {}).get("tag") or "").lower()
    if tag not in _DECORATION:
        return selector

    ancestor = actionable_ancestor(selector.value)
    if ancestor is None:
        return selector

    return Selector(
        strategy=SelectorStrategy.XPATH,
        value=ancestor,
        # A control is a bigger, better-defined target than the glyph inside it,
        # but nothing here has counted how many match - keep what was measured.
        unique=selector.unique,
        score=selector.score,
    )


def _same_site(host: str | None, target: str | None) -> bool:
    """Is `target` the same site as the application under test?

    Compared on the last two labels rather than the whole hostname, so an
    application that spans subdomains keeps working: `app.example.com` to
    `account.example.com` is one journey, and dropping the navigation between
    them would strand the test on the page before it. `doubleclick.net` against
    `betaeserver.com` is not.

    Unknown counts as the same. This decides what to *throw away*, so every
    uncertain case - no host configured, a relative URL, a hostname this cannot
    parse - has to keep the step. A navigation wrongly dropped breaks a
    recording that worked; one wrongly kept is the behaviour we already had.
    """
    if not host or not target:
        return True

    def site(name: str) -> str:
        labels = name.lower().strip(".").split(".")
        return ".".join(labels[-2:]) if len(labels) > 1 else name.lower()

    return site(host) == site(target)


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


def _was_revealed(element: dict[str, Any] | None) -> bool:
    """Did the step before this one put the element on screen?

    The recorder answers this at the moment of the click, because it is the one
    thing that cannot be worked out afterwards. In a finished recording
    `home.close_video_button` and `home.house_link` look exactly like the site's
    other links - same tag, same good accessible name, each clicked once - but
    one is on the page when it loads and the other only exists while a video is
    playing.

    A recorded test reaches them the way the person did, so it keeps them. An
    invented case opens the page and goes straight there, and there is nothing
    to go to: thirty seconds of waiting, then a defect raised against a page
    that is behaving perfectly. Those are the cases that must not be written -
    see `describe_pages`.

    Absent on recordings made before this was captured, and absent means no.
    Withholding an element on a guess would shrink the suite for nothing.
    """
    return (element or {}).get("was_on_screen") is False


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

    A record id in the path becomes a wildcard, because it is a different record
    every run. The recording added a property and landed on

        /property-owner/my-listings/cmsoao69n001501pd

    so the test waited for that exact listing - the one made during the
    recording, which the test does not create and can never reach. Thirty
    seconds, then red, on a property that had been added perfectly well. What
    is being checked is that adding a listing lands on a listing page, and the
    id is the one part of that which cannot be part of the claim.
    """
    scheme, _, rest = destination.partition("://")
    host, _, path = rest.partition("/")
    parts = [
        r"[^/]+" if _is_identifier_segment(segment) else re.escape(segment)
        for segment in path.rstrip("/").split("/")
        if segment
    ]
    prefix = re.escape(f"{scheme}://{host}") if scheme else re.escape(destination)
    body = "/" + "/".join(parts) if parts else ""
    return rf"^{prefix}{body}/?(?:[?#].*)?$"


# ---------------------------------------------------------------------------
# Actions → code
# ---------------------------------------------------------------------------
def build_ir(
    actions: list[dict[str, Any]],
    *,
    suite_name: str,
    start_url: str,
    refine_roles: Callable[..., dict[int, Decision]] | None = None,
) -> TestIR:
    """Turn normalised actions into everything the templates need.

    `refine_roles` is the one door through which a model may influence this
    file, and it opens onto a corridor rather than a room: it is handed the
    decisions the rules already reached and may only revise the ones they were
    unsure about. Left out - which is the default, and what every test here
    does - the generation is deterministic from end to end, exactly as it has
    always been. See `app/ai/dataroles_ai.py`.
    """
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

    # Held in a list rather than streamed, because a role is decided by looking
    # at the whole recording - what else was on the page, what the application
    # said back - and not at one action in isolation. See `dataroles.py`.
    recorded = list(normalise(actions, host=urlparse(start_url).hostname))
    roles = {**classify_values(recorded), **classify_targets(recorded)}
    if refine_roles is not None:
        try:
            roles = refine_roles(recorded, roles, start_url=start_url)
        except Exception:  # noqa: BLE001 - the deterministic answer still ships
            logger.warning("Data-role refinement failed; using the rules alone")

    for index, action in enumerate(recorded):
        if ActionType(action["action_type"]) is ActionType.NAVIGATE:
            if _clean_url(str(action["payload"].get("url", ""))) == current_url:
                continue

        step = _build_step(
            ir, action, sequence=len(ir.steps), decision=roles.get(index)
        )
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
    ir.needs_sample_file = any(step.action is ActionType.UPLOAD for step in ir.steps)
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


def _build_step(
    ir: TestIR,
    action: dict[str, Any],
    *,
    sequence: int,
    decision: Decision | None = None,
) -> StepSpec | None:
    kind = ActionType(action["action_type"])
    segment = int(action.get("segment") or 0)
    payload = action.get("payload") or {}
    element = action.get("element")
    # Everything below reads `usable`, not the raw list. A candidate that would
    # find a different element is no safer as a fallback than as the primary -
    # healing would reach for it the moment the page shifted.
    usable = usable_selectors(action.get("selectors") or [], element)
    selector = best_selector(usable, element)
    selector = _aim_at_the_control(selector, element)


    # Page-level actions need no locator.
    if kind is ActionType.NAVIGATE:
        url = _clean_url(str(payload.get("url", "")))
        return StepSpec(
            sequence=sequence,
            segment=segment,
            action=kind,
            code=[f"page.goto({py_str(url)})"],
            description=f"Go to {url}",
            expected_result="The page loads",
        )

    if kind is ActionType.SCROLL:
        y = int(payload.get("y", 0))
        return StepSpec(
            sequence=sequence,
            segment=segment,
            action=kind,
            code=[f"page.mouse.wheel(0, {y})"],
            description=f"Scroll down {y}px",
        )

    if kind is ActionType.KEY_PRESS and selector is None:
        key = str(payload.get("key", "Enter"))
        return StepSpec(
            sequence=sequence,
            segment=segment,
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
            revealed=_was_revealed(element),
            tag=str((element or {}).get("tag") or "").lower(),
            # Only a *target* role. A value's role describes the step, and
            # putting it here split one field into two locators: the click that
            # focused it and the fill that followed disagreed about the role,
            # so `add` refused to merge them and every step after the first
            # drove `email_input_2`.
            role=(
                DataRole.STATE_DEPENDENT.value
                if decision is not None and decision.role is DataRole.STATE_DEPENDENT
                else DataRole.STATIC.value
            ),
        )
    )

    # A STATE_DEPENDENT element gets a second locator alongside its own: the
    # recorded selector that everything of the same shape answers to. Registered
    # after it, so it can be named for it. The step never touches it unless the
    # application refuses the recorded element, and a recording that offers no
    # such selector simply has none - see `dataroles.classify_targets`.
    among = _register_shape(page_spec, decision, root, element, name)
    page_spec.remember_alternatives(name, among)

    target = f"{page_var}.{name}"
    label = _readable_target(selector, element, usable)
    code: list[str] = []
    description = ""
    input_data: str | None = None
    expected: str | None = None
    # A state-aware step does its own waiting, because the address the recording
    # arrived at belongs to the recorded data. Waiting for it outside the helper
    # would fail on exactly the runs this exists to save.
    waits_for_itself = False

    match kind:
        case ActionType.CLICK:
            renew = _renewals_for(ir, page_var, element)
            state_dependent = (
                decision is not None
                and decision.role is DataRole.STATE_DEPENDENT
            )
            if state_dependent or renew:
                code = [
                    _state_call(
                        ir,
                        action,
                        page_var=page_var,
                        name=name,
                        label=label,
                        sequence=sequence,
                        among=among,
                        renew=renew,
                    )
                ]
                description = f"Click {label}"
                waits_for_itself = True
            else:
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
            # A form that creates a record puts the recorded value into it from
            # the first run onwards. Replaying the same one asks the application
            # to create the same record twice, which it is right to refuse — so
            # the test passes once and is red for ever after. Which values those
            # are is `dataroles.classify_values`' answer, not this file's.
            fresh = None
            if decision is not None and decision.role is DataRole.UNIQUE:
                shape = _fresh_expression(value, element)
                if shape is not None:
                    # Above the line the recording itself shows the value being
                    # consumed, so replaying it would fail every run for a
                    # reason already known here. Below it, the recorded value
                    # still runs and a new one is generated only if the
                    # application refuses it - see `SUBSTITUTE_ABOVE`.
                    if decision.confidence >= SUBSTITUTE_ABOVE:
                        fresh = _fresh_value(ir, value, shape)
                    # Whether or not the value is replaced now, the retry can
                    # replace it later - and that expression calls uuid4 too.
                    ir.needs_uuid = True
                    ir.pending_renew.append((page_var, name, shape[1]))
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
            # A browser never tells a page where a chosen file really lives, so
            # the recording holds a name and nothing else. Replayed as a path it
            # looks beside the test, finds nothing, and takes every step after
            # it down with a form that was working. `sample_file` builds one in
            # memory instead - see pages/_files.py.
            files = [str(f) for f in (payload.get("files") or [])]
            arg = (
                f"sample_file({py_str(files[0])})"
                if len(files) == 1
                else "[" + ", ".join(f"sample_file({py_str(f)})" for f in files) + "]"
            )
            code = [f"{target}.set_input_files({arg})"]
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
    #
    # `domcontentloaded` rather than the default `load`, and that one word is
    # the difference between a recorded journey passing and failing. From a real
    # run, thirty seconds then red on a navigation that had already happened:
    #
    #     TimeoutError: Timeout 30000ms exceeded.
    #     waiting for navigation to ".../property-owner/add-property" until 'load'
    #
    # `load` waits for every subresource on the new page - images, fonts, and
    # the advertising and analytics scripts that a real site is full of. The
    # same suite had a doubleclick pixel in it. None of that has anything to do
    # with the claim being made, which is that the click went to the right
    # address; the DOM being parsed is the point at which that is knowable, and
    # every action after this waits for its own element anyway.
    #
    # Never after a state-aware step: that one waits for the recorded address
    # itself and knows what to make of not arriving, so a second wait out here
    # would only fail on the runs it exists to save.
    if not waits_for_itself:
        waiting = _sync_call(ir, action, kind)
        if waiting:
            code.append(waiting)
            expected = expected or _describes(waiting, action)

    return StepSpec(
        sequence=sequence,
        segment=segment,
        action=kind,
        code=code,
        description=description,
        page_var=page_var,
        locator_name=name,
        input_data=input_data,
        expected_result=expected,
        strategy=selector.strategy.value,
        fragile=selector.is_fragile,
        is_password=(
            kind is ActionType.INPUT
            and str((element or {}).get("input_type") or "").lower() == "password"
        ),
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


#: Fields holding a document or account number that identifies one person: a
#: national id, a passport, a tax pin, a licence. A sign-up form checks these
#: for duplicates exactly as it checks an email address, and the recorded one is
#: in the database from the first run onwards.
#:
#: Every token is long enough to mean something on its own. "id" is not here and
#: cannot be: `_field_words` includes the element's own `id` attribute, so a bare
#: substring test matches almost every field on the page.
_DOCUMENT = (
    "national",
    "passport",
    "nid",
    "identity",
    "id number",
    "id_number",
    "idnumber",
    "licence",
    "license",
    "kra",
    "aadhaar",
    "aadhar",
)

#: Runs of digits inside a document number, replaced one at a time so the shape
#: the application accepted survives.
_DIGIT_RUN = re.compile(r"\d+")


def _fresh_document(value: str) -> str | None:
    """`KRA/980/61` -> the same shape with different digits, or None.

    Every run of digits is replaced with a fresh run of the same length and
    everything else is kept, because the punctuation and the letters are the
    format the application validates against. Inventing a number from nothing
    is how a fix for one form breaks the next one along.

    None when there is nothing to vary. A document number with no digits in it
    at all is not something this can make unique, and returning the recorded
    value unchanged is better than returning something the form will reject.
    """
    if not _DIGIT_RUN.search(value):
        return None

    parts: list[str] = []
    position = 0
    for match in _DIGIT_RUN.finditer(value):
        if match.start() > position:
            parts.append(py_str(value[position : match.start()]))
        width = len(match.group())
        parts.append(f"f'{{uuid4().int % {10 ** width}:0{width}d}}'")
        position = match.end()

    if position < len(value):
        parts.append(py_str(value[position:]))

    return parts[0] if len(parts) == 1 else " + ".join(parts)


def _fresh_expression(
    value: str, element: dict[str, Any] | None
) -> tuple[str, str] | None:
    """A per-run replacement for one recorded value as (kind, expression).

    *Which* values need replacing is `dataroles.identity_kind`'s answer, and it
    is asked here rather than answered again. The two used to keep separate
    vocabularies and they drifted apart exactly as you would expect: a field
    called "Account Number" was classified as an identity that must be unique,
    and then handed to a generator that had never heard of it, so the role was
    right and the test replayed the recorded value anyway.

    What is left here is the *shape*. The recorded value's own form is kept
    wherever it carries a constraint - a domain the application accepted, a
    number of the length and leading digit its country expects - because
    inventing those from nothing is how a fix for one form breaks the next.

    `kind` names the variable the value is hoisted into, and is returned rather
    than guessed from the expression: a mobile number and a document number are
    both built out of `uuid4().int`, and guessing called one of them the other.
    """
    kind = identity_kind(value, element)
    if kind is None:
        return None

    if kind == "email":
        domain = value.rpartition("@")[2].strip()
        if not domain or not _DOMAIN_OK.match(domain):
            # example.test is reserved and cannot receive mail, so it is only
            # right when the recording gives us nothing better to copy.
            domain = "example.test"
        return "email", _EMAIL % domain

    if kind == "mobile":
        # Same length and same leading digit as the number that was accepted.
        # A hard-coded shape is how a generated Indian number ends up in a form
        # defaulting to Kenya, where it is not a valid number at all.
        digits = value.strip()
        rest = len(digits) - 1
        if not digits.isdigit() or rest < 1:
            return None
        return "mobile", _PHONE % (digits[0], 10**rest, rest)

    if kind == "username":
        return "username", _TEXT

    # A national id, a passport, a tax pin, a customer reference. From a real
    # recorded registration that passed once and was red on every run after it:
    #
    #     national_id_number_passport_number_input.fill('KRA/980/61')
    #
    # The email and the mobile beside it were already being replaced per run,
    # so the account got as far as being refused on the one field nobody had
    # thought of. The form was right and the test was red, which is the most
    # expensive way for a test to be wrong.
    document = _fresh_document(value.strip())
    return ("id", document) if document is not None else None


def _fresh_value(
    ir: TestIR, value: str, fresh: tuple[str, str]
) -> str | None:
    """The variable holding a per-run value for `value`, or None to keep it.

    Hoisted to a variable rather than inlined, because the same address is often
    typed twice — an email and its confirmation — and two separate calls to
    `uuid4()` would put two different addresses in fields the form requires to
    match. One name, assigned once, read wherever it was recorded.
    """
    kind, expression = fresh

    for name, _existing, recorded in ir.unique_values:
        if recorded == value:
            return name

    name = f"fresh_{kind}"
    taken = {existing_name for existing_name, _, _ in ir.unique_values}
    suffix = 2
    while name in taken:
        name = f"fresh_{kind}_{suffix}"
        suffix += 1

    ir.unique_values.append((name, expression, value))
    ir.needs_uuid = True
    return name


# ---------------------------------------------------------------------------
# Waiting for what the action actually does
# ---------------------------------------------------------------------------
#: Actions that make the application do something, and so are worth waiting on.
#: A hover asserts nothing and a scroll moves the viewport; neither has an
#: outcome, and emitting a wait after one only slows the test down.
_HAS_AN_OUTCOME = {
    ActionType.CLICK,
    ActionType.DOUBLE_CLICK,
    ActionType.CHECK,
    ActionType.UNCHECK,
    ActionType.SELECT,
    ActionType.KEY_PRESS,
    ActionType.UPLOAD,
    ActionType.DRAG_DROP,
}

#: Outcomes `pages/_sync.py` knows how to wait for. Anything else the recorder
#: learns to report later falls through to watching the DOM settle, which is
#: never wrong - only sometimes slower than a better answer would have been.
_OUTCOMES = {
    "navigated", "dialog_opened", "dialog_closed", "messages", "dom_changed", "quiet",
}


def _describes(waiting: str, action: dict[str, Any]) -> str:
    """What the wait is waiting for, in the words a test-case sheet prints."""
    if "'navigated'" in waiting:
        destination = action.get("_navigates_to") or (action.get("response") or {}).get("url")
        return f"Navigates to {_clean_url(str(destination))}" if destination else "Navigates"
    if "'messages'" in waiting:
        return "The application answers on screen"
    if "dialog_opened" in waiting:
        return "A dialog opens"
    if "dialog_closed" in waiting:
        return "The dialog closes"
    return "The page finishes updating"


def _sync_call(ir: TestIR, action: dict[str, Any], kind: ActionType) -> str | None:
    """The line that waits for what this action was observed to do, if any.

    This replaces the single assumption the generator used to make - that a
    click either navigates or needs no wait at all - and it replaces it with an
    observation. The recorder watched what happened: the page went somewhere, a
    dialog opened, a sentence appeared, the DOM changed, or nothing did. That
    answer is turned into one call here.

    None means no wait is emitted, and there are two quite different reasons for
    it. The action was seen to change nothing observable, so there is nothing to
    wait for and inventing something to wait for would hang. Or the recording
    predates outcome capture and says nothing either way, in which case the old
    adjacency rule still applies and the generated test behaves exactly as it
    always did - a recording made last year must not start waiting on things
    nobody watched.
    """
    if kind not in _HAS_AN_OUTCOME:
        return None

    observed = str((action.get("response") or {}).get("kind") or "")
    if observed not in _OUTCOMES:
        # No observation. Fall back to what the recording *arrangement* implies,
        # which is all the generator ever had before.
        observed = "navigated" if action.get("_navigates_to") else ""
    if not observed or observed == "quiet":
        return None

    ir.needs_sync = True

    if observed == "navigated":
        destination = action.get("_navigates_to") or (action.get("response") or {}).get("url")
        if destination:
            ir.needs_regex = True
            arrives = _arrives_at(_clean_url(str(destination)))
            return f"after(page, 'navigated', url=re.compile({py_str(arrives)}))"
        # Seen to navigate, nowhere recorded to. An SPA route that leaves no
        # address behind. "Somewhere other than here" is weaker but still an
        # observation rather than a guess.
        return "after(page, 'navigated')"

    if observed == "messages":
        said = [str(m) for m in (action.get("response") or {}).get("messages") or []]
        first = next((m.strip() for m in said if m.strip()), "")
        if first:
            return f"after(page, 'messages', text={py_str(first[:120])})"
        return "after(page, 'dom_changed')"

    return f"after(page, {py_str(observed)})"


# ---------------------------------------------------------------------------
# Steps that depend on data or state
# ---------------------------------------------------------------------------
def _register_shape(
    page_spec: PageSpec,
    decision: Decision | None,
    root: str,
    element: dict[str, Any] | None,
    name: str,
) -> str | None:
    """A second locator matching everything of the same shape as this element.

    Only for STATE_DEPENDENT, and only when the recording holds a selector that
    other elements answered to as well. It is never what the step runs first -
    the recorded element is - and exists purely so that a refusal has somewhere
    to go next.

    Returns the property name to read after a refusal, or None when there is
    nothing comparable and the step therefore has no alternative to offer.
    """
    if decision is None or decision.shape is None:
        return None

    strategy, value = decision.shape
    try:
        shape = Selector(strategy=SelectorStrategy(strategy), value=value, unique=False)
    except ValueError:
        return None

    tag = str((element or {}).get("tag") or "").lower()
    expression = locator_expression(shape, root)
    # `.first` would defeat the whole purpose: this locator exists to be counted
    # and indexed into, and one element is not a set.
    expression = expression.removesuffix(".first")

    return page_spec.add(
        LocatorSpec(
            name=f"{name}_alternatives"[:MAX_IDENT],
            expression=expression,
            strategy=strategy,
            fragile=True,
            candidates=[(strategy, expression)],
            ambiguous=True,
            tag=tag,
            role=DataRole.STATE_DEPENDENT.value,
            alternatives_for=name,
        )
    )


#: Clicks that could be submitting a form. A click on a text field is somebody
#: putting the cursor in it, and consuming the renewals there would leave the
#: actual submission with nothing to retry.
_SUBMITTING = {"button", "a"}
_SUBMIT_INPUTS = {"submit", "button", "image"}


def _renewals_for(
    ir: TestIR, page_var: str, element: dict[str, Any] | None
) -> list[tuple[str, list[tuple[str, str]]]]:
    """The UNIQUE fields this click is about to submit, grouped by their value.

    Grouped because an address and its confirmation have to keep matching, and
    two calls to a generator would put two different addresses in fields the
    form requires to be the same.

    Consumed rather than copied: once a submission has claimed them the next one
    starts empty, so a two-page wizard does not retry the first page's fields
    from the second.
    """
    element = element or {}
    tag = str(element.get("tag") or "").lower()
    input_type = str(element.get("input_type") or "").lower()
    if tag not in _SUBMITTING and not (tag == "input" and input_type in _SUBMIT_INPUTS):
        return []

    mine = [entry for entry in ir.pending_renew if entry[0] == page_var]
    if not mine:
        return []
    ir.pending_renew = [entry for entry in ir.pending_renew if entry[0] != page_var]

    grouped: dict[str, list[tuple[str, str]]] = {}
    for _page, locator_name, expression in mine:
        grouped.setdefault(expression, []).append((_page, locator_name))
    return list(grouped.items())


def _state_call(
    ir: TestIR,
    action: dict[str, Any],
    *,
    page_var: str,
    name: str,
    label: str,
    sequence: int,
    among: str | None,
    renew: list[tuple[str, list[tuple[str, str]]]],
) -> str:
    """The generated line for a step whose data or state may have moved on.

    Two shapes, and which one is used says what the step is allowed to vary.
    `submit` may enter new values into fields the application keeps unique;
    `one_of` may act on a comparable element instead. Neither may do anything at
    all unless the application refuses the recorded step first - see
    pages/_state.py, where every one of those words is enforced.
    """
    described = py_str(f"Click {label}"[:80])
    arrives = ""
    if action.get("_navigates_to"):
        ir.needs_regex = True
        destination = _arrives_at(_clean_url(action["_navigates_to"]))
        arrives = f", navigates=re.compile({py_str(destination)})"

    if renew:
        groups = ", ".join(
            "(lambda: {}, [{}])".format(
                expression,
                ", ".join(f"({page}, {py_str(field)})" for page, field in fields),
            )
            for expression, fields in renew
        )
        return (
            f"submit({page_var}, {py_str(name)}, step={sequence}, "
            f"described={described}, renew=[{groups}]{arrives})"
        )

    among_arg = f", among={py_str(among)}" if among else ""
    return (
        f"one_of({page_var}, {py_str(name)}, step={sequence}, "
        f"described={described}{among_arg}{arrives})"
    )


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
