"""The two complaints that matter about generated tests.

They are not "does it compile" — the golden-file tests already cover that.
They are:

  1. The tests are not proper. Names cut off mid-word, page objects carrying a
     database id, locator properties named after an entire property listing.
  2. They fail for very small reasons. A blank-page navigation the recorder
     picked up, a scroll of zero pixels, a hover duplicating the click after
     it, and an absolute XPath that any redesign invalidates.

Every case below is taken from output the generator actually produced.
"""

import re

import pytest

from app.codegen.converter import normalise, page_identity
from app.codegen.selectors import (
    Selector,
    best_selector,
    clip_words,
    locator_expression,
    snake_case,
)
from app.codegen.synth import module_for
from app.models.enums import ActionType, SelectorStrategy


def action(kind: ActionType, *, payload=None, selectors=None, url="https://app.test/"):
    return {
        "action_type": kind.value,
        "payload": payload or {},
        "selectors": selectors or [],
        "url": url,
        "is_ignored": False,
    }


def sel(strategy: str, value: str, unique: bool = True, score: int = 50) -> dict:
    return {"strategy": strategy, "value": value, "unique": unique, "score": score}


# ---------------------------------------------------------------------------
# 1. Names a person can read
# ---------------------------------------------------------------------------
def test_names_a_cuid_in_the_path_is_not_part_of_the_page_name():
    """`PropertiesCmryim584000q01p42kj4ts8qPage` was a real generated class."""
    cls, module = page_identity(
        "https://homeske-dev.betaeserver.com/properties/cmryim584000q01p42kj4ts8q"
    )
    assert cls == "PropertiesPage"
    assert module == "properties_page"

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://a.test/orders/1042/edit", "OrdersEditPage"),
        ("https://a.test/users/3f2504e0-4f89-11d3-9a0c-0305e82c3301", "UsersPage"),
        ("https://a.test/agent-details/cmru9ht1z001a01l61v2hpc2u", "AgentDetailsPage"),
        ("https://a.test/", "HomePage"),
    ],
)
def test_names_identifier_segments_are_dropped(url, expected):
    assert page_identity(url)[0] == expected

@pytest.mark.parametrize(
    "url,expected",
    [
        # A real slug carries no digits — keeping it is the whole point.
        ("https://a.test/property-management", "PropertyManagementPage"),
        ("https://a.test/reports/q4", "ReportsQ4Page"),
        ("https://a.test/api/v2/settings", "V2SettingsPage"),
    ],
)
def test_names_real_page_names_survive(url, expected):
    assert page_identity(url)[0] == expected

def test_names_a_long_name_is_clipped_on_a_word_boundary():
    name, _ = module_for(
        "Verify 'Back to search' link is not visible on the Home Page", set()
    )
    # The old output was `..._is_not_visible_on_the` — a truncated sentence.
    assert not name.endswith("_the")
    assert not name.endswith("_")
    assert len(name) <= 53
    # Still says what it is about.
    assert name.startswith("test_verify_back_to_search")

def test_names_clipping_never_cuts_a_word_in_half():
    clipped = clip_words("verify_behavior_with_repeated_clicks_on_a_navigation", 40)
    for word in clipped.split("_"):
        assert word in "verify_behavior_with_repeated_clicks_on_a_navigation".split("_")

def test_names_a_single_enormous_word_is_still_cut():
    """Nothing else can be done with it, and the name must stay bounded."""
    assert clip_words("x" * 100, 20) == "x" * 20

def test_names_a_property_listing_does_not_become_a_locator_name():
    """`for_sale_zenith_towers33225_sq_mupper_hill_nairobi_kenya_ksh_link`."""
    name = snake_case("For SaleZenith Towers33225 Sq MUpper Hill, Nairobi, KenyaKsh")
    assert len(name) <= 42
    assert not name.endswith("_")

def test_names_short_names_are_left_alone():
    assert snake_case("Email") == "email"
    assert clip_words("sign_in_button", 42) == "sign_in_button"


# ---------------------------------------------------------------------------
# 2. Selectors that survive a redesign
# ---------------------------------------------------------------------------
def test_selector_a_semantic_selector_beats_a_unique_absolute_xpath():
    """Taken from a real page object.

    The XPath was unique so it won, and `//body/section[2]/div[1]/div[1]/a[1]`
    is invalidated by one extra wrapper div.
    """
    chosen = best_selector(
        [
            sel("xpath", "//body/section[2]/div[1]/div[1]/a[1]", unique=True),
            sel("role_name", "link|See All Properties", unique=False),
            sel("text", "See All Properties", unique=False),
            sel("css", "body section div div a", unique=True),
        ]
    )
    assert chosen is not None
    assert chosen.strategy is SelectorStrategy.ROLE_NAME

def test_selector_an_ambiguous_semantic_selector_gets_first():
    """`.first` picks a real element by a name a human recognises."""
    chosen = best_selector(
        [
            sel("xpath", "//body/div[3]/a[1]", unique=True),
            sel("role_name", "link|Home", unique=False),
        ]
    )
    assert chosen is not None
    assert locator_expression(chosen).endswith(".first")

def test_selector_uniqueness_still_decides_between_semantic_selectors():
    """The original rule, unchanged where it applies."""
    chosen = best_selector(
        [
            sel("placeholder", "Email", unique=False),
            sel("css_id", "#email", unique=True),
        ]
    )
    assert chosen is not None
    assert chosen.strategy is SelectorStrategy.CSS_ID

def test_selector_a_test_id_still_wins_outright():
    chosen = best_selector(
        [
            sel("css", "form > button", unique=True),
            sel("test_id", "login-btn", unique=True),
            sel("role_name", "button|Login", unique=True),
        ]
    )
    assert chosen is not None
    assert chosen.strategy is SelectorStrategy.TEST_ID

def test_selector_positional_selectors_are_used_when_nothing_else_exists():
    """Last resort is still a resort — better than generating nothing."""
    chosen = best_selector([sel("xpath", "//div[1]/span[2]", unique=True)])
    assert chosen is not None
    assert chosen.strategy is SelectorStrategy.XPATH

def test_selector_text_matching_is_exact():
    """A substring match resolves to five elements on a real site."""
    expr = locator_expression(
        Selector(SelectorStrategy.ROLE_NAME, "link|Home", unique=True)
    )
    assert "exact=True" in expr


# ---------------------------------------------------------------------------
# 3. Steps that cannot fail, because they should never have been recorded
# ---------------------------------------------------------------------------
def test_noise_the_blank_page_navigation_is_dropped():
    """The launched browser starts blank, and that got recorded.

    Left in, the test navigates away from the application it just opened
    and every step after it fails on an empty document.
    """
    cleaned = normalise(
        [
            action(ActionType.NAVIGATE, payload={"url": "https://app.test/"}),
            action(ActionType.NAVIGATE, payload={"url": "about://blank"}),
            action(ActionType.HOVER, selectors=[sel("role_name", "link|Find Agent")]),
        ]
    )
    urls = [
        a["payload"].get("url")
        for a in cleaned
        if ActionType(a["action_type"]) is ActionType.NAVIGATE
    ]
    assert urls == ["https://app.test/"]

@pytest.mark.parametrize("blank", ["about:blank", "about://blank", "chrome://newtab", ""])
def test_noise_every_blank_url_form_is_recognised(blank):
    cleaned = normalise([action(ActionType.NAVIGATE, payload={"url": blank})])
    assert cleaned == []

def test_noise_a_zero_pixel_scroll_is_dropped():
    """`page.mouse.wheel(0, 0)` was in real generated output."""
    cleaned = normalise(
        [
            action(ActionType.SCROLL, payload={"x": 0, "y": 0}),
            action(ActionType.CLICK, selectors=[sel("test_id", "go")]),
        ]
    )
    assert [ActionType(a["action_type"]) for a in cleaned] == [ActionType.CLICK]

def test_noise_a_real_scroll_is_kept():
    """Some pages load content on scroll; only the useless ones go.

    Followed by a click, because a scroll in last position is dropped
    separately — that is just where the user left the page.
    """
    cleaned = normalise(
        [
            action(ActionType.SCROLL, payload={"x": 0, "y": 600}),
            action(ActionType.CLICK, selectors=[sel("test_id", "go")]),
        ]
    )
    assert [ActionType(a["action_type"]) for a in cleaned] == [
        ActionType.SCROLL,
        ActionType.CLICK,
    ]

def test_noise_a_hover_immediately_before_clicking_the_same_thing_is_dropped():
    """Playwright hovers before it clicks. Recording both only adds a way to fail."""
    target = [sel("role_name", "link|See All Properties")]
    cleaned = normalise(
        [
            action(ActionType.HOVER, selectors=target),
            action(ActionType.CLICK, selectors=target),
        ]
    )
    assert [ActionType(a["action_type"]) for a in cleaned] == [ActionType.CLICK]

def test_noise_a_hover_over_a_different_element_is_kept():
    """That is a menu being opened, and the next step depends on it."""
    cleaned = normalise(
        [
            action(ActionType.HOVER, selectors=[sel("role_name", "button|Products")]),
            action(ActionType.CLICK, selectors=[sel("role_name", "link|Pricing")]),
        ]
    )
    assert [ActionType(a["action_type"]) for a in cleaned] == [
        ActionType.HOVER,
        ActionType.CLICK,
    ]

def test_noise_the_whole_opening_sequence_from_the_real_recording():
    """goto, blank, hover, scroll, hover-then-click on one element."""
    link = [sel("role_name", "link|See All Properties", unique=False)]
    cleaned = normalise(
        [
            action(ActionType.NAVIGATE, payload={"url": "https://app.test/"}),
            action(ActionType.NAVIGATE, payload={"url": "about://blank"}),
            action(ActionType.HOVER, selectors=[sel("role_name", "link|Find Agent")]),
            action(ActionType.SCROLL, payload={"x": 0, "y": 600}),
            action(ActionType.HOVER, selectors=link),
            action(ActionType.CLICK, selectors=link),
            action(ActionType.SCROLL, payload={"x": 0, "y": 0}),
        ]
    )
    assert [ActionType(a["action_type"]) for a in cleaned] == [
        ActionType.NAVIGATE,
        ActionType.HOVER,   # over Find Agent — a different element, kept
        ActionType.SCROLL,  # 600px — real
        ActionType.CLICK,   # the hover before it folded in
    ]

def test_noise_nothing_useful_is_lost_from_an_ordinary_recording():
    cleaned = normalise(
        [
            action(ActionType.NAVIGATE, payload={"url": "https://app.test/login"}),
            action(ActionType.INPUT, payload={"value": "a@b.c"},
                   selectors=[sel("label", "Email")]),
            action(ActionType.INPUT, payload={"value": "hunter2"},
                   selectors=[sel("label", "Password")]),
            action(ActionType.CLICK, selectors=[sel("role_name", "button|Login")]),
        ]
    )
    assert len(cleaned) == 4


def test_generated_function_names_are_valid_python_identifiers():
    """Clipping must not produce something that will not parse."""
    taken: set[str] = set()
    for name in [
        "Verify 'Back to search' link is not visible on the Home Page",
        "Verify behavior with repeated clicks on a navigation link",
        "SQL payload ' OR 1=1-- in the email field is rejected",
        "###",
    ]:
        function_name, _ = module_for(name, taken)
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name), function_name
