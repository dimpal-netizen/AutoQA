"""Open a site's own URL and find out what is on it.

A project has always carried the address of the application under test, and
until now nothing used it to *look*. Elements came from recordings, because the
recorder was the only thing that ever opened the site — so "a test case needs a
recording" got written into the shape of the code, when what a test case
actually needs is elements. A person driving a browser is one way to find those.
Opening the URL is another.

That distinction matters most for the half of AutoQA that has no recording at
all. A team's manual test-case sheet says *what is worth checking*; it cannot
say which box is the email field. With this, the sheet no longer has to wait for
somebody to record the same journey before it can become tests.

The elements are read by the recorder's own code, injected into the page and
called directly:

    window.AutoQARecorder.selectorsFor(el)   ->  the same selector candidates
    window.AutoQARecorder.describeFor(el)    ->  the same element description

so an element found here and the same element found by recording produce the
same locator. Reimplementing either would mean two definitions of "how AutoQA
names things", which drift.

Two things it genuinely cannot do, and both are properties of arriving as a
stranger rather than gaps to be closed later:

  * **Anything behind a sign-in is invisible.** A recording reaches the
    dashboard because a person signed in on the way. Explored, the site answers
    with its login form, and that is all there is to see.

  * **It finds pages, not journeys.** A recording knows checkout is five steps
    in a particular order. This knows there is a checkout page with fields on
    it. For sheet-driven generation that is usually enough, because the sheet
    supplies the order - but it is less than a recording knows.

Never raises. An exploration that fails returns nothing, and the caller says so.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from app.codegen.converter import PageSpec, TestIR, page_identity, register_element
from app.codegen.selectors import best_selector, snake_case, usable_selectors

logger = logging.getLogger(__name__)

RECORDER_JS = Path(__file__).resolve().parent.parent / "static" / "recorder.js"

#: How many pages to open. Small on purpose: this runs while somebody waits,
#: and the pages worth finding - the landing page and whatever it links to
#: prominently - are the first few. A crawler that walks a whole site spends
#: minutes to return a vocabulary too large for the model to use anyway.
MAX_PAGES = 6

#: Per page. Long enough for a single-page app to render, short enough that one
#: dead link does not hold up the rest.
LOAD_MS = 20_000
IDLE_MS = 5_000
SETTLE_MS = 1_200

#: Elements per page. A listings page has hundreds of links, and past the first
#: few dozen they are all the same shape - one per property - so the tail adds
#: length without adding vocabulary.
MAX_ELEMENTS = 60

#: What a test can act on. Everything else on a page is layout.
_INTERACTIVE = (
    "input:not([type=hidden])", "textarea", "select", "button",
    "a[href]", "[role=button]", "[role=link]", "[role=checkbox]",
    "[role=radio]", "[role=tab]", "[role=combobox]", "[contenteditable=true]",
)

#: Collect the elements and describe each one with the recorder's own helpers.
#: Visibility is checked here rather than after the fact: an element with no box
#: cannot be acted on, and carrying it back only to drop it later wastes the
#: round trip and pollutes the count.
_COLLECT = """
([selectors, limit]) => {
  const seen = new Set();
  const out = [];
  for (const element of document.querySelectorAll(selectors.join(","))) {
    if (out.length >= limit) break;
    if (seen.has(element)) continue;
    seen.add(element);

    const box = element.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) continue;
    const style = getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none") continue;
    if (element.disabled) continue;

    try {
      out.push({
        selectors: window.AutoQARecorder.selectorsFor(element),
        element: window.AutoQARecorder.describeFor(element),
      });
    } catch (error) {
      // One awkward element must not end the sweep.
    }
  }
  return out;
}
"""

#: Links worth following from the landing page, in preference order. A site's
#: sign-in and sign-up pages are where most of a manual test plan points, and
#: they are reachable from the front page of essentially every application.
_WORTH_FOLLOWING = (
    "login", "signin", "sign-in", "register", "signup", "sign-up",
    "account", "search", "products", "cart", "checkout", "contact",
)


def explore(base_url: str, *, suite_name: str, max_pages: int = MAX_PAGES) -> TestIR | None:
    """Open `base_url`, read what is on it, and return an IR of pages.

    Returns None when nothing could be explored at all - no browser, the site
    unreachable, not one usable element found. The caller then says so rather
    than producing an empty suite that looks like it worked.

    The IR has pages and locators but only a single `goto` step, because
    nothing was performed. That is exactly what case generation needs: it reads
    `pages` for the vocabulary and writes its own steps.
    """
    try:
        return _walk(base_url, suite_name=suite_name, max_pages=max_pages)
    except Exception:  # noqa: BLE001 - exploring must never 500 a request
        logger.warning("Could not explore %s", base_url, exc_info=True)
        return None


def _walk(base_url: str, *, suite_name: str, max_pages: int) -> TestIR | None:
    from playwright.sync_api import sync_playwright

    recorder_js = RECORDER_JS.read_text(encoding="utf-8")
    ir = TestIR(
        suite_name=suite_name,
        function_name=snake_case(f"test_{suite_name}", fallback="test_explored"),
        module_name=snake_case(f"test_{suite_name}", fallback="test_explored"),
        start_url=base_url,
    )

    found = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(ignore_https_errors=True)
            # No bridge config, so the recorder defines its helpers and stays
            # asleep - it only starts itself when both the bridge and a config
            # are present. Injected per document so it survives navigation.
            context.add_init_script(recorder_js)
            page = context.new_page()

            for url in _pages_to_visit(page, base_url, max_pages):
                found += _read_page(page, ir, url)
        finally:
            browser.close()

    if not found:
        logger.info("Explored %s and found nothing a test could act on", base_url)
        return None

    logger.info(
        "Explored %s: %d element(s) across %d page(s)",
        base_url, found, len(ir.pages),
    )
    return ir


def _pages_to_visit(page, base_url: str, max_pages: int) -> list[str]:
    """The landing page, then the most promising links on it.

    Promising rather than exhaustive. A site's own navigation points at the
    pages a manual test plan talks about - sign in, register, search, cart -
    and following those few finds more of what a sheet needs than crawling
    breadth-first through a listings page ever would.
    """
    urls = [base_url]
    try:
        _open(page, base_url)
        links = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => e.getAttribute('href'))"
        )
    except Exception:  # noqa: BLE001 - the landing page alone is still worth it
        logger.info("Could not read links from %s", base_url, exc_info=True)
        return urls

    origin = urlparse(base_url).netloc
    ranked: list[tuple[int, str]] = []
    seen = {_key(base_url)}

    for href in links or []:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).netloc != origin or _key(absolute) in seen:
            continue

        lowered = absolute.lower()
        rank = next(
            (i for i, word in enumerate(_WORTH_FOLLOWING) if word in lowered),
            len(_WORTH_FOLLOWING),
        )
        seen.add(_key(absolute))
        ranked.append((rank, absolute))

    ranked.sort(key=lambda pair: pair[0])
    urls.extend(url for _, url in ranked[: max_pages - 1])
    return urls


def _key(url: str) -> str:
    """Two addresses that are the same page. Query and fragment are dropped:
    a listings page with forty filter combinations is one page."""
    parsed = urlparse(url)
    return f"{parsed.netloc}{(parsed.path or '/').rstrip('/').lower()}"


def _open(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=LOAD_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=IDLE_MS)
    except Exception:  # noqa: BLE001 - plenty of pages never go quiet
        pass
    page.wait_for_timeout(SETTLE_MS)


def _read_page(page, ir: TestIR, url: str) -> int:
    """Open one page and register everything on it. Returns how many stuck."""
    try:
        _open(page, url)
        collected: list[dict[str, Any]] = page.evaluate(
            _COLLECT, [list(_INTERACTIVE), MAX_ELEMENTS]
        )
    except Exception:  # noqa: BLE001 - one bad page is not a failed exploration
        logger.info("Could not read %s", url, exc_info=True)
        return 0

    if not collected:
        return 0

    # Where the browser actually ended up. A redirect to a login page means the
    # elements belong to that page, not to the one that was asked for.
    landed = page.url or url
    spec = _page_for(ir, landed)

    kept = 0
    for item in collected:
        element = item.get("element")
        usable = usable_selectors(item.get("selectors") or [], element)
        selector = best_selector(usable, element)
        if selector is None:
            continue  # nothing to find it by that a test could rely on
        try:
            register_element(spec, selector, usable, element)
            kept += 1
        except Exception:  # noqa: BLE001 - one element, not the page
            logger.debug("Could not register an element on %s", landed, exc_info=True)

    logger.debug("Explored %s: kept %d of %d", landed, kept, len(collected))
    return kept


def _page_for(ir: TestIR, url: str) -> PageSpec:
    """The PageSpec for this address, created if this is the first sighting.

    Deliberately not `converter._page_for`: that one is built around a recorded
    action and its own URL cleaning. This keeps explored pages in the same
    identity scheme - `page_identity` decides both - without borrowing the rest.
    """
    class_name, module = page_identity(url)
    for existing in ir.pages:
        if existing.class_name == class_name:
            return existing

    spec = PageSpec(class_name=class_name, module=module, url=url)
    ir.pages.append(spec)
    return spec
