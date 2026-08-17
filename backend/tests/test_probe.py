"""Opening each page cold, to see what is actually on it.

Everything else AutoQA knows comes from one recording, and a recording shows one
state: the cart had something in it, the wizard was on step one, the account was
under its listing limit. Cases invented against that reach for a Checkout button
that only exists when the cart is full, and spend thirty seconds finding out.

Nothing in the recording says the button is conditional, and no amount of
reading it back will - so this looks instead. The judgement being tested here is
narrow and important: what counts as an answer, and what counts as not having
asked.
"""

import pytest

from app.codegen.converter import LocatorSpec, PageSpec
from app.codegen.probe import Reachability, _path


def page(class_name: str, *names: str) -> PageSpec:
    return PageSpec(
        class_name=class_name,
        module=class_name.lower(),
        url=f"https://shop.test/{class_name.lower()}",
        locators=[
            LocatorSpec(name=n, expression="self.page.x", strategy="role_name",
                        fragile=False)
            for n in names
        ],
    )


CART = page("ViewCartPage", "proceed_to_checkout_link", "empty_message")


# ---------------------------------------------------------------------------
# What counts as an answer
# ---------------------------------------------------------------------------
def test_an_element_that_was_on_screen_is_offered() -> None:
    found = Reachability(visible={("ViewCartPage", "empty_message")})

    assert found.offers(CART, "empty_message")


def test_an_element_that_was_not_there_is_withheld() -> None:
    """The empty cart really has no Checkout button. That is the answer, and
    the case built on it is the one worth not writing."""
    found = Reachability(visible={("ViewCartPage", "empty_message")})

    assert not found.offers(CART, "proceed_to_checkout_link")


def test_a_page_we_never_reached_changes_nothing() -> None:
    """Asked for the cart and handed a login form, "none of these exist" is a
    fact about being signed out. Acting on it would withhold every element on
    the page - a probe that failed turning into a suite with nothing left to
    write about.
    """
    found = Reachability(visible=set(), unusable={"ViewCartPage"})

    assert found.offers(CART, "proceed_to_checkout_link")
    assert found.offers(CART, "empty_message")


def test_arriving_and_finding_it_bare_is_not_the_same_as_not_arriving() -> None:
    """The distinction the whole feature rests on. Both look like "nothing was
    visible"; only one of them is evidence."""
    reached = Reachability(visible=set())
    redirected = Reachability(visible=set(), unusable={"ViewCartPage"})

    assert not reached.offers(CART, "proceed_to_checkout_link")
    assert redirected.offers(CART, "proceed_to_checkout_link")


# ---------------------------------------------------------------------------
# Telling "sent somewhere else" from "same page"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "asked, landed, same",
    [
        ("https://shop.test/view_cart", "https://shop.test/view_cart", True),
        ("https://shop.test/view_cart", "https://shop.test/view_cart/", True),
        ("https://shop.test/view_cart", "https://shop.test/view_cart?from=nav", True),
        ("https://shop.test/view_cart", "https://shop.test/login", False),
        ("https://shop.test/", "https://shop.test", True),
    ],
)
def test_a_redirect_is_recognised(asked: str, landed: str, same: bool) -> None:
    """A trailing slash or a query is the same page; a different path is a
    login wall or an error, and nothing seen there is evidence."""
    assert (_path(asked) == _path(landed)) is same


# ---------------------------------------------------------------------------
# Nothing measured, nothing changed
# ---------------------------------------------------------------------------
def test_a_suite_generated_without_a_probe_is_unaffected() -> None:
    """`reachable` defaults to True, so every existing suite and every
    environment where the application is unreachable behaves as it always did.
    """
    assert all(locator.reachable for locator in CART.locators)


def test_the_filter_keeps_what_the_probe_found(monkeypatch) -> None:
    """End to end through what the model is actually shown."""
    from app.ai.case_generator import describe_pages

    CART.locators[0].reachable = False
    try:
        described = describe_pages([CART])
    finally:
        CART.locators[0].reachable = True

    assert "empty_message" in described
    assert "proceed_to_checkout_link" not in described


# ---------------------------------------------------------------------------
# It is a source of truth, never a gate
# ---------------------------------------------------------------------------
def test_a_broken_probe_does_not_stop_generation(monkeypatch) -> None:
    """A missing import here once turned "generate some test cases" into a 500
    with a stack trace. `probe` promises never to raise and keeps that promise -
    the promise stopped at its own front door.
    """
    from app.codegen.converter import TestIR
    from app.services import codegen_service

    def explode(*_args, **_kwargs):
        raise RuntimeError("no browser on this machine")

    monkeypatch.setattr(codegen_service, "probe", explode)

    ir = TestIR(suite_name="s", function_name="test_s", module_name="test_s",
                start_url="https://shop.test/", pages=[CART])

    codegen_service.CodegenService.__new__(
        codegen_service.CodegenService
    )._mark_reachable(ir)

    # Untouched, so the model is shown exactly what it would have been shown.
    assert all(locator.reachable for locator in CART.locators)
