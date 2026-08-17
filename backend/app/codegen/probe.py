"""Open each page cold and see what is actually on it.

Everything else AutoQA knows comes from one recording, and a recording shows one
state. The cart had something in it. The form was on step one. The account was
under its listing limit. So a test case invented against it reaches for a
Checkout button that is only there when the cart is full, and spends thirty
seconds finding out:

    goto   /view_cart
    click  ViewCartPage.proceed_to_checkout_link

    Locator.click: Timeout 30000ms exceeded

The application did exactly what it should. Nothing in the recording says the
button is conditional, and no amount of reading it back will.

So this looks. Once per generation, each page is opened the way a case would
open it - cold, with nothing done first - and every element the recording found
is asked whether it is on screen. What is not gets withheld from the model, the
same as an element with no name or no size. Measured rather than inferred, which
is the only reason it also covers the shapes nobody has run into yet.

Never raises. A probe that cannot run leaves generation exactly as it was.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from app.codegen.converter import PageSpec, StepSpec, TestIR
from app.models.enums import ActionType

logger = logging.getLogger(__name__)

#: Waited for before looking, bounded because plenty of pages never go quiet -
#: a map widget or a chat bubble polls forever.
IDLE_MS = 6_000

#: On top of idle. A single-page app reaches idle and then renders.
SETTLE_MS = 1_500

#: How long a sign-in has to land. Generous: it is one request, once, and the
#: cost of being impatient is probing every protected page as a stranger.
SIGN_IN_MS = 20_000

#: Per element, and deliberately not zero. The cost of being impatient here is
#: withholding something that was on its way in, which makes the suite thinner
#: for no reason - the failure this feature exists to prevent, in reverse.
CHECK_MS = 1_000


@dataclass
class Reachability:
    """What was on each page when it was opened cold.

    `unusable` is the important half: the pages we never actually reached. Asked
    for the cart and handed a login form, "none of these elements exist" is a
    fact about being signed out, and acting on it would withhold every element
    on the page - turning a probe that failed into a suite with nothing left to
    write about.

    Arriving somewhere and finding it bare is the opposite, and is exactly what
    this is for. An empty cart really has no Checkout button. That page is
    usable, it just has nothing on it, and a case built on what is missing is
    the case worth not writing.
    """

    visible: set[tuple[str, str]] = field(default_factory=set)
    unusable: set[str] = field(default_factory=set)

    def offers(self, page: PageSpec, locator_name: str) -> bool:
        """Should the model be offered this element?"""
        if page.class_name in self.unusable:
            return True  # nothing was learned here; change nothing
        return (page.class_name, locator_name) in self.visible


def probe(ir: TestIR, *, sign_in: list[StepSpec] | None = None) -> Reachability | None:
    """Open every page in `ir` and record which of its elements are on screen.

    Returns None when the probe could not run at all - no browser installed, the
    site unreachable, a page object that will not import. Generation then
    proceeds exactly as it did before, which is the right answer: a probe is an
    extra source of truth, never a gate.

    `sign_in` replays the recorded login first, because the pages worth probing
    are usually behind one. Driven through the generated page objects rather
    than by executing the generated test, so nothing here runs code a model had
    a hand in.
    """
    from app.codegen.generator import render

    workspace = Path(tempfile.mkdtemp(prefix="autoqa-probe-"))
    try:
        for spec in render(ir, browser_info={}):
            if not spec.path.startswith("pages/"):
                continue
            destination = workspace / spec.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(spec.content, encoding="utf-8")

        sys.path.insert(0, str(workspace))
        try:
            return _walk(ir, sign_in or [])
        finally:
            with suppress(ValueError):
                sys.path.remove(str(workspace))
            # The next probe writes different page objects to a different
            # folder; leaving these cached would import the last suite's.
            for name in [n for n in sys.modules if n == "pages" or n.startswith("pages.")]:
                del sys.modules[name]
    except Exception:  # noqa: BLE001 - a probe must never break generation
        logger.warning("Could not probe %s", ir.suite_name, exc_info=True)
        return None
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _walk(ir: TestIR, sign_in: list[StepSpec]) -> Reachability | None:
    from playwright.sync_api import sync_playwright

    found = Reachability()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(ignore_https_errors=True)
            # Only emitted when something in the suite can heal. Without it the
            # properties are plain locators, which is what `unhealed` would have
            # returned anyway.
            try:
                healing = importlib.import_module("pages._healing")
            except ImportError:
                healing = None

            if sign_in:
                _replay_sign_in(page, _by_variable(ir.pages), sign_in)

            for spec in ir.pages:
                _one_page(page, healing, spec, found)
        finally:
            browser.close()

    logger.info(
        "Probed %s: %d element(s) on screen cold, %d page(s) told us nothing",
        ir.suite_name, len(found.visible), len(found.unusable),
    )
    return found


def _by_variable(pages: list[PageSpec]) -> dict[str, PageSpec]:
    """`login` -> the LoginPage spec, the way a step names its page."""
    from app.codegen.synth import page_variables_for

    of_class = {class_name: var for var, class_name in page_variables_for(pages)}
    return {of_class[spec.class_name]: spec for spec in pages if spec.class_name in of_class}


def _page_object(spec: PageSpec, page):
    module = importlib.import_module(f"pages.{spec.module}")
    return getattr(module, spec.class_name)(page)


def _one_page(page, healing, spec: PageSpec, found: Reachability) -> None:
    """Open one page cold and tick off what is on it."""
    try:
        page.goto(spec.url, wait_until="domcontentloaded", timeout=30_000)
        with suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=IDLE_MS)
        page.wait_for_timeout(SETTLE_MS)
        instance = _page_object(spec, page)
    except Exception:  # noqa: BLE001 - one unreachable page is not a failed probe
        logger.debug("Could not open %s", spec.url, exc_info=True)
        found.unusable.add(spec.class_name)
        return

    # Sent somewhere else - a login wall, an error page, a redirect. Nothing
    # seen here is evidence about the page that was asked for.
    if _path(page.url) != _path(spec.url):
        logger.info("Asked for %s and got %s; leaving its elements alone",
                    spec.url, page.url)
        found.unusable.add(spec.class_name)
        return

    seen = 0
    for locator in spec.locators:
        try:
            # `unhealed`, so this answers about the element the recording chose
            # rather than about whichever spare happens to match today. A spare
            # matching is not evidence that this element is on screen.
            target = (
                healing.unhealed(instance, locator.name)
                if healing
                else getattr(instance, locator.name)
            )
            if target.first.is_visible(timeout=CHECK_MS):
                found.visible.add((spec.class_name, locator.name))
                seen += 1
        except Exception:  # noqa: BLE001 - not visible, or not there at all
            continue

    if not seen:
        # Arrived, and it is bare. An empty cart, a wizard on step one, a form
        # replaced by "Listing Limit Reached". That is an answer, not a failure.
        logger.info("Nothing on %s is there cold; its elements are withheld", spec.url)


def _path(url: str) -> str:
    """The part of an address that says which page it is."""
    from urllib.parse import urlparse

    return (urlparse(url).path or "/").rstrip("/").lower() or "/"


def _replay_sign_in(page, pages: dict[str, PageSpec], steps: list[StepSpec]) -> None:
    """Replay the recorded sign-in, so the pages behind it can be opened.

    Driven through the page objects, one action at a time, rather than by
    running the generated test: the point of the probe is to look at the
    application, not to execute a suite.

    Opening the login page first is not optional, and leaving it out is the
    whole of why this did nothing the first time: a fresh page starts on
    about:blank, so the very first step waited five seconds for `#email` on an
    empty document, gave up, and every page behind the login then answered as a
    login form. Three of them - the ones worth probing.
    """
    first = next((s for s in steps if s.page_var in pages), None)
    if first is None:
        return
    try:
        page.goto(pages[first.page_var].url, wait_until="domcontentloaded", timeout=30_000)
        with suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=IDLE_MS)
        page.wait_for_timeout(SETTLE_MS)
    except Exception:  # noqa: BLE001 - cannot sign in; pages will say so
        logger.info("Could not open the sign-in page while probing", exc_info=True)
        return

    for step in steps:
        if not (step.page_var and step.locator_name):
            continue
        spec = pages.get(step.page_var)
        if spec is None:
            continue
        try:
            target = getattr(_page_object(spec, page), step.locator_name)

            if step.action is ActionType.INPUT:
                target.fill(step.input_data or "", timeout=5_000)
            elif step.action in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
                target.click(timeout=5_000)
        except Exception:  # noqa: BLE001 - unable to sign in; pages will say so
            logger.debug("Sign-in step failed while probing", exc_info=True)
            return

    # Leaving the login page is the signal that signing in worked. Waiting for
    # the network to go quiet is not: the request is still in the air when it
    # does, so the first protected page was asked for while still anonymous and
    # came back as a login form - which then read as "that page has none of
    # these elements".
    login_path = _path(pages[first.page_var].url)
    try:
        page.wait_for_url(lambda url: _path(url) != login_path, timeout=SIGN_IN_MS)
    except Exception:  # noqa: BLE001
        logger.info("Signed in and stayed on the login page; probing anonymously")
        return

    with suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=IDLE_MS)
