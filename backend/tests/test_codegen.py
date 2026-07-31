"""Code generation. No database, no network.

The important property is that generated code is always *valid Python* — it
gets executed later, so a syntax error here becomes a baffling runtime failure
three phases away.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.codegen.converter import build_ir, normalise, page_identity
from app.codegen.generator import GeneratedCodeError, GeneratedFileSpec, render, validate
from app.codegen.selectors import Selector, best_selector, element_name, locator_expression, snake_case
from app.models.enums import ActionType, FileType, SelectorStrategy

FIXTURE = Path(__file__).parent / "fixtures" / "sample_recording.json"


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated(sample: dict) -> list[GeneratedFileSpec]:
    ir = build_ir(
        sample["actions"],
        suite_name="Checkout flow",
        start_url=sample["session"]["start_url"],
    )
    return render(ir, browser_info=sample["session"]["browser_info"])


# ---------------------------------------------------------------------------
# Selector to Playwright
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("strategy", "value", "expected"),
    [
        ("test_id", "login-submit", "page.get_by_test_id('login-submit')"),
        ("role_name", "button|Sign in", "page.get_by_role('button', name='Sign in')"),
        ("role_name", "navigation", "page.get_by_role('navigation')"),
        ("label", "Email address", "page.get_by_label('Email address')"),
        ("placeholder", "you@x.com", "page.get_by_placeholder('you@x.com')"),
        ("text", "Sign in", "page.get_by_text('Sign in', exact=True)"),
        ("css_id", "#email", "page.locator('#email')"),
        ("css", "form input", "page.locator('form input')"),
        ("xpath", "//div[1]", "page.locator('xpath=//div[1]')"),
    ],
)
def test_locator_expressions(strategy: str, value: str, expected: str) -> None:
    selector = Selector(strategy=SelectorStrategy(strategy), value=value)
    assert locator_expression(selector) == expected


def test_values_with_quotes_do_not_break_the_code() -> None:
    """A selector containing an apostrophe must not produce a syntax error."""
    selector = Selector(strategy=SelectorStrategy.TEXT, value="Bob's account")
    expression = locator_expression(selector)

    ast.parse(expression)  # would raise if the literal were built by hand
    assert "Bob's account" in expression


def test_best_selector_ignores_input_order() -> None:
    """A buggy recorder must not be able to promote a bad selector."""
    raw = [
        {"strategy": "nth_child", "value": "li:nth-child(3)", "score": 100},
        {"strategy": "test_id", "value": "submit", "score": 1},
    ]
    assert best_selector(raw).strategy is SelectorStrategy.TEST_ID


def test_a_unique_selector_beats_a_better_ranked_ambiguous_one() -> None:
    """Regression: this exact data made a real recording fail every run.

    Playwright is strict — a locator matching two elements raises rather than
    guessing. So a plain #email that matches one element is worth more than a
    placeholder that matches two, however much nicer the placeholder reads.
    """
    raw = [
        {"strategy": "placeholder", "value": "Email", "score": 84, "unique": False},
        {"strategy": "css_id", "value": "#email", "score": 70, "unique": True},
    ]
    chosen = best_selector(raw)

    assert chosen.strategy is SelectorStrategy.CSS_ID
    assert ".first" not in locator_expression(chosen)


def test_ranking_still_decides_between_equally_unique_selectors() -> None:
    """Uniqueness is a tie-breaker on top of ranking, not a replacement."""
    raw = [
        {"strategy": "xpath", "value": "//div[1]/input", "score": 10, "unique": True},
        {"strategy": "test_id", "value": "email", "score": 90, "unique": True},
    ]
    assert best_selector(raw).strategy is SelectorStrategy.TEST_ID


def test_step_wording_stays_human_when_the_code_uses_an_id() -> None:
    """Choosing #email for reliability must not make the step say `Click "#email"`.

    The description and the locator answer different questions, so they read
    different candidates: most recognisable name vs. most reliable selector.
    """
    ir = build_ir(
        [
            {
                "action_type": "input",
                "url": "https://example.com/login",
                "selectors": [
                    {"strategy": "placeholder", "value": "Email", "score": 84,
                     "unique": False},
                    {"strategy": "css_id", "value": "#email", "score": 70, "unique": True},
                ],
                "element": {"tag": "input"},
                "payload": {"value": "a@b.com"},
            }
        ],
        suite_name="Login",
        start_url="https://example.com/login",
    )

    step = ir.steps[-1]
    assert 'Type into "Email"' == step.description
    assert "#email" in ir.pages[0].locators[0].expression


def test_an_unavoidably_ambiguous_selector_falls_back_to_first() -> None:
    """When nothing is unique, running on the first match beats always failing."""
    raw = [
        {"strategy": "text", "value": "Delete", "score": 50, "unique": False},
        {"strategy": "css", "value": "button.delete", "score": 40, "unique": False},
    ]
    chosen = best_selector(raw)

    assert chosen.strategy is SelectorStrategy.TEXT  # ranking still applies
    assert locator_expression(chosen).endswith(".first")
    assert chosen.is_fragile  # and the UI flags it


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Email address", "email_address"),
        ("loginSubmit", "login_submit"),
        ("class", "class_"),          # Python keyword
        ("page", "page_"),            # would shadow the page object attribute
        ("2fa-code", "element_2fa_code"),
        ("", "element"),
    ],
)
def test_identifier_naming(text: str, expected: str) -> None:
    assert snake_case(text) == expected


def test_element_names_read_like_english() -> None:
    selector = Selector(strategy=SelectorStrategy.TEST_ID, value="email-input")
    element = {"tag": "input", "input_type": "email", "accessible_name": "Email address"}

    assert element_name(selector, element) == "email_input"


def test_checkbox_gets_a_checkbox_suffix() -> None:
    selector = Selector(strategy=SelectorStrategy.TEST_ID, value="remember-me")
    element = {"tag": "input", "input_type": "checkbox"}

    assert element_name(selector, element) == "remember_me_checkbox"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def _action(seq: int, kind: str, **kwargs) -> dict:
    base = {
        "sequence": seq,
        "action_type": kind,
        "url": "https://x.test/",
        "frame_path": [],
        "selectors": [{"strategy": "test_id", "value": "a", "unique": True, "score": 90}],
        "element": None,
        "payload": {},
        "is_ignored": False,
    }
    base.update(kwargs)
    return base


def test_consecutive_scrolls_collapse() -> None:
    actions = [
        _action(0, "scroll", payload={"x": 0, "y": 100}, selectors=[]),
        _action(1, "scroll", payload={"x": 0, "y": 400}, selectors=[]),
        _action(2, "click"),
    ]
    result = normalise(actions)

    assert [a["action_type"] for a in result] == ["scroll", "click"]
    assert result[0]["payload"]["y"] == 400


def test_retyping_a_field_keeps_the_last_value() -> None:
    actions = [
        _action(0, "input", payload={"value": "buy"}),
        _action(1, "input", payload={"value": "buyer@example.com"}),
    ]
    result = normalise(actions)

    assert len(result) == 1
    assert result[0]["payload"]["value"] == "buyer@example.com"


def test_navigation_after_a_click_becomes_a_wait() -> None:
    actions = [
        _action(0, "click"),
        _action(1, "navigate", payload={"url": "https://x.test/next"}, selectors=[]),
    ]
    result = normalise(actions)

    assert len(result) == 1
    assert result[0]["_navigates_to"] == "https://x.test/next"


def test_ignored_actions_are_dropped() -> None:
    actions = [_action(0, "click", is_ignored=True), _action(1, "click")]

    assert len(normalise(actions)) == 1


def test_trailing_scroll_is_dropped() -> None:
    actions = [_action(0, "click"), _action(1, "scroll", payload={"x": 0, "y": 9}, selectors=[])]

    assert [a["action_type"] for a in normalise(actions)] == ["click"]


@pytest.mark.parametrize(
    ("url", "class_name"),
    [
        ("https://x.test/login", "LoginPage"),
        ("https://x.test/", "HomePage"),
        ("https://x.test/checkout/shipping", "CheckoutShippingPage"),
    ],
)
def test_page_naming(url: str, class_name: str) -> None:
    assert page_identity(url)[0] == class_name


# ---------------------------------------------------------------------------
# The generated bundle
# ---------------------------------------------------------------------------
def test_every_generated_python_file_parses(generated) -> None:
    for spec in generated:
        if spec.path.endswith(".py"):
            ast.parse(spec.content, filename=spec.path)


def test_expected_files_are_produced(generated) -> None:
    paths = {spec.path for spec in generated}

    assert "tests/test_checkout_flow.py" in paths
    assert "conftest.py" in paths
    assert "pytest.ini" in paths
    assert any(p.startswith("pages/") for p in paths)

    kinds = {spec.file_type for spec in generated}
    assert kinds == {FileType.TEST, FileType.PAGE_OBJECT, FileType.CONFTEST, FileType.CONFIG}


def test_generated_files_are_ascii(generated) -> None:
    """Generated code lands on unknown machines; don't depend on their encoding."""
    for spec in generated:
        non_ascii = {c for c in spec.content if ord(c) > 127}
        assert not non_ascii, f"{spec.path} contains {non_ascii}"


def test_the_test_body_covers_every_action(generated, sample) -> None:
    code = next(s for s in generated if s.path.startswith("tests/")).content

    for fragment in [
        "page.goto(",
        ".click()",
        ".fill(",
        ".check()",
        ".uncheck()",
        ".select_option(",
        ".hover()",
        ".dblclick()",
        ".press(",
        ".set_input_files(",
        ".drag_to(",
        "page.mouse.wheel(",
        "expect(",
        "page.wait_for_url(",
    ]:
        assert fragment in code, f"generated test never uses {fragment}"


def test_no_duplicate_goto_for_the_opening_page(generated) -> None:
    """The recorder logs the opening navigation, which the goto already covers."""
    code = next(s for s in generated if s.path.startswith("tests/")).content

    assert code.count("page.goto('https://shop.example.com/login')") == 1


def test_query_strings_are_stripped_from_urls() -> None:
    """Recorded session ids and tokens must not be baked into a test."""
    actions = [_action(0, "click", url="https://x.test/orders?token=secret123")]
    ir = build_ir(actions, suite_name="Flow", start_url="https://x.test/?session=abc")

    rendered = "\n".join(spec.content for spec in render(ir))
    assert "secret123" not in rendered
    assert "session=abc" not in rendered


def test_page_object_lists_the_fallback_selectors(generated) -> None:
    """The fallbacks are what make Phase 7 self-healing possible."""
    login = next(s for s in generated if s.path == "pages/login_page.py").content

    assert "Recorded alternatives" in login
    assert "label: Email address" in login

    # The chosen selector must not also be listed as its own alternative.
    email_block = login.split("def email_input")[1].split("@property")[0]
    alternatives = [
        line.strip().removeprefix("- ")
        for line in email_block.splitlines()
        if line.strip().startswith("- ")
    ]
    assert alternatives, "no fallbacks recorded"
    assert not any(alt.startswith("test_id:") for alt in alternatives), alternatives


def test_iframe_actions_use_frame_locator(generated) -> None:
    payment = next(s for s in generated if s.path == "pages/checkout_payment_page.py").content

    assert "frame_locator('iframe[name=\\'stripe-card\\']')" in payment or (
        "frame_locator" in payment and "stripe-card" in payment
    )


def test_fragile_selectors_are_flagged() -> None:
    actions = [
        _action(
            0,
            "click",
            selectors=[{"strategy": "nth_child", "value": "li:nth-child(2)", "unique": True}],
        )
    ]
    ir = build_ir(actions, suite_name="Fragile", start_url="https://x.test/")

    assert ir.fragile_count == 1
    code = next(s for s in render(ir) if s.path.startswith("tests/")).content
    assert "brittle" in code.lower()


def test_steps_are_human_readable(generated, sample) -> None:
    ir = build_ir(
        sample["actions"], suite_name="Checkout flow", start_url=sample["session"]["start_url"]
    )
    descriptions = [step.description for step in ir.steps]

    assert 'Click "Sign in"' in descriptions
    assert 'Tick "Remember me"' in descriptions
    assert any(d.startswith("Open https://") for d in descriptions)
    # Every step must say something; a blank description is useless in review.
    assert all(d.strip() for d in descriptions)


def test_generation_is_deterministic(sample) -> None:
    """Same recording in, byte-identical code out — no AI, no randomness."""
    def once() -> str:
        ir = build_ir(
            sample["actions"],
            suite_name="Checkout flow",
            start_url=sample["session"]["start_url"],
        )
        return "\n".join(s.content for s in render(ir))

    assert once() == once()


def test_validate_rejects_broken_python() -> None:
    spec = GeneratedFileSpec(path="tests/bad.py", content="def (:", file_type=FileType.TEST)

    with pytest.raises(GeneratedCodeError, match="tests/bad.py"):
        validate(spec)


def test_empty_recording_still_produces_a_valid_test() -> None:
    ir = build_ir([], suite_name="Nothing happened", start_url="https://x.test/")
    files = render(ir)

    code = next(s for s in files if s.path.startswith("tests/")).content
    ast.parse(code)
    assert "page.goto('https://x.test/')" in code


def test_conftest_uses_the_recorded_viewport(sample) -> None:
    ir = build_ir(sample["actions"], suite_name="Flow", start_url="https://x.test/")
    conftest = next(
        s for s in render(ir, browser_info=sample["session"]["browser_info"])
        if s.path == "conftest.py"
    ).content

    assert '"width": 1440' in conftest
    assert '"height": 900' in conftest


def test_absurd_viewport_falls_back_to_a_sane_default() -> None:
    ir = build_ir([], suite_name="Flow", start_url="https://x.test/")
    conftest = next(
        s for s in render(ir, browser_info={"viewport": {"width": 0, "height": -5}})
        if s.path == "conftest.py"
    ).content

    assert '"width": 1280' in conftest


def test_the_bundle_is_collectable_by_pytest(generated, tmp_path) -> None:
    """The real bar: not "it parses" but "pytest can load and collect it".

    Catches broken imports between the test and its page objects, a conftest
    that raises, and an invalid pytest.ini — none of which ast.parse would see.
    """
    for spec in generated:
        target = tmp_path / spec.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(spec.content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "test_checkout_flow" in result.stdout
    assert "1 test collected" in result.stdout


def test_first_step_is_always_a_goto(sample) -> None:
    ir = build_ir(
        sample["actions"], suite_name="Flow", start_url=sample["session"]["start_url"]
    )

    assert ir.steps[0].action is ActionType.NAVIGATE
    assert ir.steps[0].code == ["page.goto('https://shop.example.com/login')"]
