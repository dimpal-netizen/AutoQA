"""Reading a site's own pages, instead of being shown them.

A project has always carried the address of the application under test, and
until now nothing used it to look — elements came from recordings, so "you need
a recording first" got written into the shape of the product. What a test case
actually needs is elements, and a person driving a browser is only one way to
find them.

None of these need a browser. The parts that decide *what gets explored* are
plain functions, and they are where the mistakes that matter live: following a
link off-site, exploring the same page forty times because its query string
changed, or spending the whole budget on a listings page and never reaching the
login form a test plan is mostly about.
"""

from app.codegen.converter import PageSpec, TestIR
from app.codegen.explorer import _key, _page_for, _pages_to_visit, explore


class FakePage:
    """Enough of a Playwright page to choose what to visit."""

    def __init__(self, links: list[str], *, url: str = "") -> None:
        self._links = links
        self.url = url
        self.visited: list[str] = []

    def goto(self, url, **_kwargs):
        self.visited.append(url)
        self.url = url

    def wait_for_load_state(self, *_args, **_kwargs):
        pass

    def wait_for_timeout(self, *_args, **_kwargs):
        pass

    def eval_on_selector_all(self, *_args, **_kwargs):
        return self._links


# ---------------------------------------------------------------------------
# Which addresses are the same page
# ---------------------------------------------------------------------------
def test_a_query_string_does_not_make_a_new_page() -> None:
    """A listings page with forty filter combinations is one page, and
    exploring it forty times would spend the whole budget on it."""
    assert _key("https://a.test/properties?type=house") == _key(
        "https://a.test/properties?type=flat"
    )


def test_a_trailing_slash_and_case_do_not_either() -> None:
    assert _key("https://a.test/Login/") == _key("https://a.test/login")


def test_different_paths_stay_different() -> None:
    assert _key("https://a.test/login") != _key("https://a.test/register")


# ---------------------------------------------------------------------------
# What is worth opening
# ---------------------------------------------------------------------------
def test_the_landing_page_is_always_first() -> None:
    page = FakePage([])

    assert _pages_to_visit(page, "https://a.test/", 6)[0] == "https://a.test/"


def test_sign_in_beats_whatever_came_first_in_the_markup() -> None:
    """A site's footer links to its privacy policy long before its login form.

    Taken in document order the budget goes on terms and cookie pages, and the
    one page a manual test plan is mostly about never gets opened.
    """
    page = FakePage(["/privacy", "/terms", "/login", "/blog/hello"])

    chosen = _pages_to_visit(page, "https://a.test/", 3)

    assert chosen[1] == "https://a.test/login"


def test_another_site_is_not_explored() -> None:
    """Following an outbound link would read somebody else's application."""
    page = FakePage(["https://elsewhere.test/login", "/register"])

    chosen = _pages_to_visit(page, "https://a.test/", 6)

    assert all("elsewhere.test" not in url for url in chosen)
    assert "https://a.test/register" in chosen


def test_links_that_go_nowhere_are_skipped() -> None:
    page = FakePage(["#top", "mailto:hi@a.test", "tel:+254700000000", "javascript:void(0)"])

    assert _pages_to_visit(page, "https://a.test/", 6) == ["https://a.test/"]


def test_the_same_page_twice_is_opened_once() -> None:
    page = FakePage(["/login", "/login/", "/login?next=/account"])

    chosen = _pages_to_visit(page, "https://a.test/", 6)

    assert len(chosen) == 2  # the landing page and one login


def test_the_budget_is_respected() -> None:
    page = FakePage([f"/page-{n}" for n in range(40)])

    assert len(_pages_to_visit(page, "https://a.test/", 4)) == 4


def test_a_landing_page_that_will_not_open_is_still_explored() -> None:
    """Its own elements are worth reading even when its links are not."""

    class Broken(FakePage):
        def eval_on_selector_all(self, *_args, **_kwargs):
            raise RuntimeError("detached")

    assert _pages_to_visit(Broken([]), "https://a.test/", 6) == ["https://a.test/"]


# ---------------------------------------------------------------------------
# Where elements get put
# ---------------------------------------------------------------------------
def test_two_sightings_of_a_page_share_one_page_object() -> None:
    """Otherwise the header links found on every page would each start a new
    class, and the suite would carry five copies of HomePage."""
    ir = TestIR(
        suite_name="x", function_name="test_x", module_name="test_x",
        start_url="https://a.test/",
    )

    first = _page_for(ir, "https://a.test/login")
    second = _page_for(ir, "https://a.test/login?next=/account")

    assert first is second
    assert len(ir.pages) == 1


def test_different_pages_get_their_own() -> None:
    ir = TestIR(
        suite_name="x", function_name="test_x", module_name="test_x",
        start_url="https://a.test/",
    )

    _page_for(ir, "https://a.test/login")
    _page_for(ir, "https://a.test/register")

    assert [p.class_name for p in ir.pages] == ["LoginPage", "RegisterPage"]
    assert all(isinstance(p, PageSpec) for p in ir.pages)


# ---------------------------------------------------------------------------
# Failing quietly
# ---------------------------------------------------------------------------
def test_a_site_that_cannot_be_reached_returns_nothing(monkeypatch) -> None:
    """Never raises. Exploring is one way of answering "what is on these
    pages" — when it cannot, the caller says so rather than 500ing."""
    monkeypatch.setattr(
        "app.codegen.explorer._walk",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no browser")),
    )

    assert explore("https://nowhere.invalid/", suite_name="Nowhere") is None
