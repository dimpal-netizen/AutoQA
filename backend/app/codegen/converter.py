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
    element_name,
    frame_root,
    locator_expression,
    py_str,
    scoped_root,
    snake_case,
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


@dataclass
class PageSpec:
    class_name: str          # LoginPage
    module: str              # login_page
    url: str
    locators: list[LocatorSpec] = field(default_factory=list)

    def add(self, locator: LocatorSpec) -> str:
        """Register a locator, reusing an identical one. Returns its final name."""
        for existing in self.locators:
            if existing.expression == locator.expression:
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
            )
        )
        return name


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
    return ir


def _build_step(ir: TestIR, action: dict[str, Any], *, sequence: int) -> StepSpec | None:
    kind = ActionType(action["action_type"])
    payload = action.get("payload") or {}
    element = action.get("element")
    selector = best_selector(action.get("selectors") or [])

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
        narrowed = scoped_root(action.get("selectors") or [], root)
        scoped = narrowed != root
        root = narrowed

    expression = locator_expression(selector, root, scoped=scoped)

    # Rank the candidates ourselves rather than trusting input order, and drop
    # the one we actually used — listing the primary as its own fallback is
    # noise.
    ranked = sorted(
        (Selector.from_dict(s) for s in (action.get("selectors") or [])),
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
        )
    )

    target = f"{page_var}.{name}"
    label = _readable_target(selector, element, action.get("selectors") or [])
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
            code = [f"{target}.hover()"]
            description = f"Hover over {label}"
        case ActionType.INPUT:
            value = str(payload.get("value", ""))
            code = [f"{target}.fill({py_str(value)})"]
            description = f"Type into {label}"
            input_data = value
        case ActionType.SELECT:
            values = payload.get("values") or []
            arg = py_str(str(values[0])) if len(values) == 1 else repr([str(v) for v in values])
            code = [f"{target}.select_option({arg})"]
            description = f"Select {', '.join(map(str, values))} in {label}"
            input_data = ", ".join(map(str, values))
        case ActionType.CHECK:
            code = [f"{target}.check()"]
            description = f"Tick {label}"
            expected = f"{label} is checked"
        case ActionType.UNCHECK:
            code = [f"{target}.uncheck()"]
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
            if kind_name == "to_have_text":
                text = str(payload.get("expected", ""))
                code = [f"expect({target}).to_have_text({py_str(text)})"]
                description = f"Check {label} shows {text!r}"
                expected = text
            else:
                code = [f"expect({target}).to_be_visible()"]
                description = f"Check {label} is visible"
                expected = f"{label} is visible"
        case _:
            return None

    # A click that caused a navigation waits for it, rather than asserting the
    # URL immediately — an instant assert is a classic source of flakiness.
    if action.get("_navigates_to"):
        code.append(f"page.wait_for_url({py_str(_clean_url(action['_navigates_to']))})")
        expected = f"Navigates to {_clean_url(action['_navigates_to'])}"

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
