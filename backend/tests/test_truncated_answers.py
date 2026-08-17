"""Keeping the work a truncated answer already contains.

Generation asks for twelve test cases in one call. The answer came back at
27,990 tokens against a 32,000 ceiling, cut off partway through the twelfth
case, and a response cut mid-JSON does not parse - so all twelve were lost:

    Gemini hit the 32000 token limit before finishing its GeneratedCases
    response - 3996 spent thinking, 27990 on the answer

The key is allowed twenty requests a day. Losing eleven finished test cases
because the twelfth was half-written spends a twentieth of the day on nothing.
"""

import json

import pytest

from app.ai.gemini import _salvage
from app.ai.schemas import GeneratedCases


def case(name: str) -> dict:
    return {
        "name": name,
        "category": "negative",
        "priority": "medium",
        "description": "Why this matters.",
        "steps": [
            {"action": "goto", "target": None, "value": "https://x.test/login"},
            {"action": "click", "target": "LoginPage.sign_in_button", "value": None},
            {"action": "expect_visible", "target": "LoginPage.email_input", "value": None},
        ],
    }


def cut(count: int, *, after: str) -> str:
    """A full answer of `count` cases, truncated partway through `after`."""
    whole = json.dumps({"cases": [case(f"Case {n}") for n in range(count)]})
    return whole[: whole.index(after)]


def test_the_finished_cases_survive_a_cut_mid_answer() -> None:
    salvaged = _salvage(cut(12, after='"Case 11"'), GeneratedCases)

    assert salvaged is not None
    # Ten, not eleven: the item the cut may have landed inside is dropped too.
    assert [c.name for c in salvaged.cases] == [f"Case {n}" for n in range(10)]


def test_the_last_item_is_dropped_even_when_it_looks_whole() -> None:
    """"Looks whole" is exactly what a cut-off object does when the cut lands
    just after a nested field closes - here, after a complete `steps` list but
    before the case's own closing brace."""
    whole = json.dumps({"cases": [case("A"), case("B")]})
    salvaged = _salvage(whole[: whole.rindex("]}")], GeneratedCases)

    assert salvaged is not None
    assert [c.name for c in salvaged.cases] == ["A"]


def test_one_item_alone_is_not_salvageable() -> None:
    """It is the one the cut may have landed inside, so there is nothing whole
    to keep and the caller should raise as before."""
    assert _salvage(cut(2, after='"Case 1"'), GeneratedCases) is None


def test_a_brace_inside_a_string_does_not_end_an_item() -> None:
    """Placeholders are written `{{unique_email}}`, and a test case about JSON
    injection contains worse. Counting braces without tracking quotes would cut
    the answer in the wrong place and lose good cases."""
    tricky = case("Injection")
    tricky["steps"][1]["value"] = '{"nested": "}}{{"} and {{unique_email}}'
    whole = json.dumps({"cases": [tricky, case("Second"), case("Third")]})

    salvaged = _salvage(whole[: whole.index('"Third"')], GeneratedCases)

    assert salvaged is not None
    assert [c.name for c in salvaged.cases] == ["Injection"]


@pytest.mark.parametrize("text", ["", "not json at all", '{"cases": ', "[]"])
def test_nothing_whole_means_nothing_returned(text: str) -> None:
    assert _salvage(text, GeneratedCases) is None


def test_a_schema_that_is_not_a_single_list_is_left_alone() -> None:
    """Salvage only makes sense for many self-contained items. A truncated
    single object has no complete half to keep, and guessing at one would put
    an invented answer into the suite."""
    from app.ai.schemas import CodeEnhancement

    assert _salvage('{"title": "Half a titl', CodeEnhancement) is None
