"""Turning described test cases into real ones. No network.

The value of these tests is the rejections. A model will confidently reference
an element that does not exist, or write a "test" that checks nothing, and the
whole design rests on those never reaching a file.
"""

import ast

import pytest

from app.ai.case_generator import generate_cases
from app.ai.schemas import CaseStep, GeneratedCase, GeneratedCases
from app.codegen.converter import LocatorSpec, PageSpec, TestIR
from app.codegen.generator import render
from app.codegen.synth import SynthesisError, module_for, synthesise
from app.models.enums import CaseCategory, CasePriority

from tests.test_ai import FakeLLM


@pytest.fixture
def pages() -> list[PageSpec]:
    page = PageSpec(class_name="LoginPage", module="login_page", url="https://x.test/login")
    for name, expression in [
        ("email_input", "self.page.locator('#email')"),
        ("password_input", "self.page.get_by_placeholder('Password')"),
        ("login_button", "self.page.get_by_role('button', name='Login')"),
    ]:
        page.locators.append(
            LocatorSpec(name=name, expression=expression, strategy="css_id", fragile=False)
        )
    return [page]


@pytest.fixture
def recorded(pages) -> TestIR:
    return TestIR(
        suite_name="Login",
        function_name="test_login",
        module_name="test_login",
        start_url="https://x.test/login",
        pages=pages,
    )


def case(**overrides) -> GeneratedCase:
    base = dict(
        name="Login is rejected with a wrong password",
        category="negative",
        priority="high",
        description="A wrong password must not sign anyone in.",
        steps=[
            CaseStep(action="goto", value="https://x.test/login", description="Open login"),
            CaseStep(
                action="fill",
                target="LoginPage.email_input",
                value="a@b.com",
                description="Type the email",
            ),
            CaseStep(
                action="click", target="LoginPage.login_button", description="Submit"
            ),
            CaseStep(
                action="expect_not_url", value="/dashboard", description="Still on login"
            ),
        ],
    )
    base.update(overrides)
    return GeneratedCase(**base)


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------
def test_a_described_case_becomes_runnable_python(pages, recorded):
    ir = synthesise(
        case(), pages=pages, start_url=recorded.start_url,
        module_name="test_x", function_name="test_x",
    )

    module = next(f for f in render(ir, browser_info={}) if f.path == ir.file_path)
    ast.parse(module.content)  # raises if the synthesised code is not valid

    assert "login.email_input.fill('a@b.com')" in module.content
    assert "login.login_button.click()" in module.content
    assert "import re" in module.content  # the URL assertion needs it


def test_only_the_pages_a_case_touches_are_imported(pages, recorded):
    other = PageSpec(class_name="CartPage", module="cart_page", url="https://x.test/cart")
    other.locators.append(
        LocatorSpec(name="checkout", expression="self.page.locator('#c')",
                    strategy="css_id", fragile=False)
    )

    ir = synthesise(
        case(), pages=[*pages, other], start_url=recorded.start_url,
        module_name="test_x", function_name="test_x",
    )

    assert [p.class_name for p in ir.pages] == ["LoginPage"]


def test_an_invented_element_is_refused(pages, recorded):
    """The most common bad suggestion: a plausible element that is not there."""
    bad = case(
        steps=[
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(
                action="click",
                target="LoginPage.forgot_password_link",
                description="Click forgot password",
            ),
            CaseStep(action="expect_url", value="/reset", description="On reset page"),
        ]
    )

    with pytest.raises(SynthesisError, match="unknown element"):
        synthesise(bad, pages=pages, start_url="https://x.test/login",
                   module_name="test_x", function_name="test_x")


def test_an_unknown_action_is_refused(pages):
    bad = case(
        steps=[
            CaseStep(action="scroll_to_bottom", description="Scroll"),
            CaseStep(action="expect_url", value="/x", description="Check"),
        ]
    )

    with pytest.raises(SynthesisError, match="unknown action"):
        synthesise(bad, pages=pages, start_url="https://x.test/login",
                   module_name="test_x", function_name="test_x")


def test_a_case_that_asserts_nothing_is_refused(pages):
    """It would report green whether or not the feature works — worse than no test."""
    bad = case(
        steps=[
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="click", target="LoginPage.login_button", description="Click"),
        ]
    )

    with pytest.raises(SynthesisError, match="no assertion"):
        synthesise(bad, pages=pages, start_url="https://x.test/login",
                   module_name="test_x", function_name="test_x")


def test_clearing_a_field_is_a_valid_step(pages):
    """Empty required field then submit is a core negative test.

    Regression: `fill` with an empty value was rejected as "needs a value",
    which silently made the most obvious QA check impossible to express.
    """
    empty = case(
        steps=[
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(action="fill", target="LoginPage.email_input", value="",
                     description="Leave the email empty"),
            CaseStep(action="click", target="LoginPage.login_button", description="Submit"),
            CaseStep(action="expect_not_url", value="/dashboard", description="Rejected"),
        ]
    )

    ir = synthesise(empty, pages=pages, start_url="https://x.test/login",
                    module_name="test_x", function_name="test_x")

    assert "login.email_input.fill('')" in "\n".join(
        line for step in ir.steps for line in step.code
    )


def test_a_value_is_still_required_where_it_is_meaningless(pages):
    bad = case(
        steps=[
            CaseStep(action="goto", value="", description="Open nothing"),
            CaseStep(action="expect_url", value="/x", description="Check"),
        ]
    )

    with pytest.raises(SynthesisError, match="needs a value"):
        synthesise(bad, pages=pages, start_url="https://x.test/login",
                   module_name="test_x", function_name="test_x")


def test_module_names_are_unique_and_safe():
    taken: set[str] = set()
    first = module_for("Login fails!", taken)
    second = module_for("Login fails?", taken)  # same slug after cleaning

    assert first[0].startswith("test_") and first[0].isidentifier()
    assert first != second


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def test_good_cases_are_kept_and_bad_ones_reported(recorded):
    client = FakeLLM(
        GeneratedCases(
            cases=[
                case(),
                case(name="Broken", steps=[
                    CaseStep(action="click", target="LoginPage.nope", description="x"),
                    CaseStep(action="expect_url", value="/y", description="y"),
                ]),
            ]
        )
    )

    outcome = generate_cases(recorded, client=client)

    # One bad suggestion must not cost the good one.
    assert len(outcome.cases) == 1
    assert len(outcome.rejected) == 1
    assert "Broken" in outcome.rejected[0]
    assert outcome.cases[0].category is CaseCategory.NEGATIVE
    assert outcome.cases[0].priority is CasePriority.HIGH


def test_a_generated_case_can_never_claim_to_be_the_recorded_one(recorded):
    outcome = generate_cases(recorded, client=FakeLLM(
        GeneratedCases(cases=[case(category="recorded")])
    ))

    assert outcome.cases[0].category is not CaseCategory.RECORDED


@pytest.mark.parametrize("bad", ["nonsense", "", "POSITIVE!"])
def test_an_unparseable_category_falls_back(recorded, bad):
    outcome = generate_cases(recorded, client=FakeLLM(
        GeneratedCases(cases=[case(category=bad)])
    ))

    assert outcome.cases[0].category is CaseCategory.POSITIVE


def test_no_provider_is_reported_not_swallowed(recorded, monkeypatch):
    """Generation genuinely needs a model, so it must say so rather than no-op."""
    monkeypatch.setattr("app.ai.case_generator.ai_available", lambda: False)

    outcome = generate_cases(recorded)

    assert not outcome.ok
    assert "needs an AI provider" in outcome.skipped


def test_a_navigation_only_recording_is_explained(recorded):
    recorded.pages = []

    outcome = generate_cases(recorded, client=FakeLLM(GeneratedCases(cases=[case()])))

    assert not outcome.ok
    assert "no elements" in outcome.skipped


def test_a_provider_failure_does_not_raise(recorded):
    from app.ai.client import LLMError

    outcome = generate_cases(recorded, client=FakeLLM(error=LLMError("API is down")))

    assert not outcome.ok and "API is down" in outcome.skipped


def test_generated_modules_do_not_collide_with_the_recorded_one(recorded):
    outcome = generate_cases(
        recorded,
        client=FakeLLM(GeneratedCases(cases=[case(name="Login"), case(name="Login")])),
    )

    modules = {c.ir.module_name for c in outcome.cases}
    assert len(modules) == len(outcome.cases)
    assert recorded.module_name not in modules


# ---------------------------------------------------------------------------
# Regenerating an unchanged suite rebuilds the same cases
#
# Regeneration replaces every generated case, which is what it is for. What it
# must not do is replace them with *different* tests: the model was sampling, so
# a case that passed on Monday came back on Tuesday as a different test wearing
# the same name and went red against an application nobody had touched. The
# mirror of that was quieter and worse — a case failing because it had found a
# real bug came back weaker and went green.
# ---------------------------------------------------------------------------
def test_the_prompt_does_not_ask_for_cases_longer_than_it_accepts():
    """It did, and the whole batch was thrown away.

        The model returned no usable test cases.
        Rejected: Successful registration with unique valid data:
                  37 steps is beyond the 30 limit

    Telling the model to reproduce the recorded sequence made every case as long
    as the recording — 28 steps here — and `MAX_STEPS` rejected all of them. The
    setup that instruction was protecting is restored by `_restore_setup` after
    the fact, so the prompt does not need to ask for it and must not.
    """
    from app.ai.client import load_prompt
    from app.codegen.synth import MAX_STEPS

    prompt = load_prompt(
        "generate_cases", suite_name="S", start_url="u", pages="p",
        steps="\n".join(f"{i}. step" for i in range(28)), target_count=12,
        guidance="", guidance_reminder="",
    )

    assert "Do not replay it" in prompt
    assert "put back for you" in prompt
    # The length it asks for has to fit the length it enforces.
    assert "Four to eight steps is normal" in prompt
    assert MAX_STEPS >= 30


# ---------------------------------------------------------------------------
# The brief the person typed
# ---------------------------------------------------------------------------
def _prompt_for(guidance: str | None, count: int = 12) -> str:
    from app.ai.case_generator import _asked_for, _last_word
    from app.ai.client import load_prompt

    return load_prompt(
        "generate_cases", suite_name="S", start_url="u", pages="p", steps="s",
        target_count=count,
        guidance=_asked_for(guidance, count),
        guidance_reminder=_last_word(guidance, count),
    )


def test_a_brief_is_the_last_thing_the_model_reads():
    """It was the twenty-seventh line of two hundred and thirty-two.

    Everything after it is generic rules, so the last instruction before
    answering was a note about step counts — and batches came back covering the
    four categories evenly with the brief touched once. Whatever is said last is
    what a model is holding when it starts writing, and the brief is the one
    instruction that came from a person.
    """
    prompt = _prompt_for("the phone number validation rules")
    tail = "\n".join(prompt.splitlines()[-12:])

    assert "the phone number validation rules" in tail
    # And still stated up front, where the categories are introduced.
    assert prompt.count("the phone number validation rules") >= 2


def test_a_brief_outranks_the_category_quota():
    """"Write 12 cases covering these categories" sat one line under the brief
    and read as four quotas to satisfy alongside it."""
    prompt = _prompt_for("the phone number rules")

    assert "not four quotas to satisfy alongside it" in prompt
    assert "write fewer rather than filling the gap" in prompt


def test_no_brief_adds_nothing_at_all():
    """An empty heading reads as a requirement to be satisfied somehow."""
    plain = _prompt_for(None)

    assert "BEFORE YOU ANSWER" not in plain
    assert "WHAT THESE TEST CASES ARE FOR" not in plain


def test_a_brief_is_collapsed_and_capped():
    """It is somebody's free text arriving in a prompt."""
    from app.ai.case_generator import _brief

    assert _brief("  the   phone \n rules  ") == "the phone rules"
    assert len(_brief("x" * 5000)) == 1000
    assert _brief(None) == ""


def test_a_whole_batch_rejected_says_so_rather_than_naming_one(recorded):
    """"Rejected: <one case>" read as though one case had been the problem."""
    from app.services.codegen_service import _why_nothing_was_usable

    outcome = generate_cases(recorded, client=FakeLLM(GeneratedCases(cases=[
        case(name=f"Case {i}", steps=[
            CaseStep(action="click", target="LoginPage.nope", description="x"),
            CaseStep(action="expect_url", value="/y", description="y"),
        ])
        for i in range(5)
    ])))

    assert not outcome.cases
    message = _why_nothing_was_usable(outcome)
    assert "All 5" in message


def test_nothing_samples():
    """Temperature zero and a fixed seed, or the same input has no same answer."""
    from app.ai.client import SEED, TEMPERATURE

    assert TEMPERATURE == 0.0
    assert isinstance(SEED, int)


def test_every_provider_that_can_be_pinned_is_pinned():
    """A provider left sampling reintroduces the whole problem silently."""
    from app.ai.client import SEED, TEMPERATURE
    from app.ai.langchain_client import _provider

    for name in ("gemini", "openai"):
        kwargs = _provider(name).kwargs
        assert kwargs["temperature"] == TEMPERATURE, name
        assert kwargs["seed"] == SEED, name

    # Claude Opus 5 removed temperature outright — sending it is a 400 — so it
    # is steered by the prompt instead. Asserted so nobody "fixes" the gap.
    assert "temperature" not in _provider("claude").kwargs


def test_an_existing_module_name_is_never_reused(recorded):
    """Two cases writing one file means the older test silently becomes the newer."""
    outcome = generate_cases(
        recorded,
        client=FakeLLM(GeneratedCases(cases=[case(name="Login is rejected")])),
        taken_modules={"test_login_is_rejected"},
    )

    assert outcome.cases[0].ir.module_name != "test_login_is_rejected"
