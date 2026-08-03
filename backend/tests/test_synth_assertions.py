"""What a generated case is allowed to assert, and how it compiles.

Both cases here came out of a real generated suite.

The first could never run: `re.compile('?password=')` raises before the
assertion is reached, so the test reports as an error rather than telling you
anything about the application.

The second could never pass: `expect(agents_link).to_be_hidden()` on an error
page, where "Agents" is site navigation present on every page. The model had no
verb for "the password is masked" and reached for the nearest thing, which is a
different claim entirely.
"""

import ast
import re

import pytest

from app.ai.schemas import CaseStep, GeneratedCase
from app.codegen.converter import LocatorSpec, PageSpec
from app.codegen.generator import render
from app.codegen.synth import VERBS, SynthesisError, synthesise


@pytest.fixture
def pages() -> list[PageSpec]:
    page = PageSpec(class_name="LoginPage", module="login_page", url="https://x.test/login")
    for name, expression in [
        ("email_input", "self.page.get_by_label('Email')"),
        ("password_input", "self.page.get_by_label('Password')"),
        ("reveal_button", "self.page.get_by_role('button', name='Show password')"),
        ("login_button", "self.page.get_by_role('button', name='Login')"),
    ]:
        page.locators.append(
            LocatorSpec(name=name, expression=expression, strategy="label", fragile=False)
        )
    return [page]


def build(steps: list[CaseStep], pages) -> str:
    """Synthesise and render, returning the test module source."""
    ir = synthesise(
        GeneratedCase(
            name="Case", category="negative", priority="high",
            description="A case.", steps=steps,
        ),
        pages=pages,
        start_url="https://x.test/login",
        module_name="test_case",
        function_name="test_case",
    )
    return next(f for f in render(ir, browser_info={}) if f.path == ir.file_path).content


OPEN = CaseStep(action="goto", value="https://x.test/login", description="Open")


# ---------------------------------------------------------------------------
# URL assertions must survive being turned into a regex
# ---------------------------------------------------------------------------
def test_a_url_fragment_with_a_regex_character_still_compiles(pages):
    """`?password=` is not a pattern, it is a query string."""
    code = build(
        [OPEN, CaseStep(action="expect_not_url", value="?password=",
                        description="No password in the URL")],
        pages,
    )
    ast.parse(code)

    pattern = re.search(r"re\.compile\('([^']*)'\)", code).group(1)
    # The generated literal must itself be a valid regex — this is the check
    # that would have caught the real failure.
    re.compile(pattern.encode().decode("unicode_escape"))
    assert re.search(
        pattern.encode().decode("unicode_escape"), "https://x.test/a?password=hunter2"
    )


def test_dots_in_a_host_no_longer_match_any_character(pages):
    code = build(
        [OPEN, CaseStep(action="expect_url", value="app.example.com/home",
                        description="Arrived")],
        pages,
    )
    pattern = re.search(r"re\.compile\('([^']*)'\)", code).group(1)
    compiled = re.compile(pattern.encode().decode("unicode_escape"))

    assert compiled.search("https://app.example.com/home")
    assert not compiled.search("https://appXexampleYcom/home")


@pytest.mark.parametrize(
    "fragment",
    ["?password=", "/a+b", "(checkout)", "price=$5", "a|b", "[id]", "*"],
)
def test_no_url_fragment_can_produce_an_invalid_pattern(fragment, pages):
    code = build(
        [OPEN, CaseStep(action="expect_url", value=fragment, description="x")], pages
    )
    pattern = re.search(r"re\.compile\('([^']*)'\)", code).group(1)
    re.compile(pattern.encode().decode("unicode_escape"))  # raises if not escaped


def test_the_readable_step_keeps_the_unescaped_value(pages):
    r"""`\?password\=` in a test-case sheet is noise to whoever reads it."""
    ir = synthesise(
        GeneratedCase(
            name="Case", category="security", priority="high", description="d",
            steps=[OPEN, CaseStep(action="expect_not_url", value="?password=",
                                  description="No password in the URL")],
        ),
        pages=pages, start_url="https://x.test/login",
        module_name="test_case", function_name="test_case",
    )
    assertion = ir.steps[-1]
    assert assertion.expected_result == "?password="


# ---------------------------------------------------------------------------
# Masking is an attribute, not visibility
# ---------------------------------------------------------------------------
def test_a_masked_password_is_expressible(pages):
    """The verb that did not exist, which is why expect_hidden got misused."""
    code = build(
        [OPEN, CaseStep(action="expect_masked", target="LoginPage.password_input",
                        description="The password is masked")],
        pages,
    )
    ast.parse(code)
    assert "to_have_attribute('type', 'password')" in code
    assert "to_be_hidden" not in code


def test_revealing_the_password_is_a_separate_assertion(pages):
    code = build(
        [
            OPEN,
            CaseStep(action="fill", target="LoginPage.password_input",
                     value="hunter2", description="Type a password"),
            CaseStep(action="click", target="LoginPage.reveal_button",
                     description="Click the eye icon"),
            CaseStep(action="expect_not_masked", target="LoginPage.password_input",
                     description="The password is now readable"),
        ],
        pages,
    )
    ast.parse(code)
    assert "not_to_have_attribute('type', 'password')" in code


def test_both_masking_verbs_count_as_assertions():
    """A case ending in one of these must not be rejected as asserting nothing."""
    from app.codegen.synth import _ASSERTIONS

    assert {"expect_masked", "expect_not_masked"} <= _ASSERTIONS


def test_a_case_of_only_masking_assertions_is_still_rejected(pages):
    """Nothing was done to the app, so nothing was tested."""
    with pytest.raises(SynthesisError):
        build(
            [CaseStep(action="expect_masked", target="LoginPage.password_input",
                      description="Masked")],
            pages,
        )


def test_the_vocabulary_stays_closed():
    """Every verb is renderable and nothing was added by accident."""
    assert set(VERBS) == {
        "goto", "fill", "click", "check", "uncheck", "select", "press",
        "expect_visible", "expect_hidden", "expect_text",
        "expect_url", "expect_not_url", "expect_masked", "expect_not_masked",
    }


def test_an_invented_verb_is_still_refused(pages):
    with pytest.raises(SynthesisError, match="unknown action"):
        build([OPEN, CaseStep(action="expect_greyed_out",
                              target="LoginPage.password_input", description="x")], pages)
