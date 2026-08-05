"""The AI layer. No network, ever.

Every test here runs against `FakeLLM`. That is not just for speed: it is the
only way to assert what happens when the model misbehaves. A real key would
give us one well-behaved answer and no coverage of the cases that actually
matter — refusals, outages, and confidently wrong suggestions.
"""

import ast
import json
from pathlib import Path

import pytest

from app.ai.client import LLMClient, LLMError, LLMRefusal, LLMResponse, load_prompt
from app.ai.enhancer import enhance
from app.ai.schemas import CodeEnhancement, FailureAnalysis
from app.codegen.converter import build_ir
from app.codegen.generator import render

FIXTURE = Path(__file__).parent / "fixtures" / "sample_recording.json"


class FakeLLM(LLMClient):
    """A scripted model. Returns what the test tells it to, or raises."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, parsed=None, *, error: Exception | None = None) -> None:
        self.parsed = parsed
        self.error = error
        self.calls: list[str] = []

    def complete(self, prompt, *, system="", max_tokens=8000) -> LLMResponse:
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return LLMResponse(text="ok", provider=self.provider, model=self.model)

    def complete_model(
        self, prompt, schema, *, system="", max_tokens=8000, image=None
    ) -> LLMResponse:
        # Recorded so a test can assert the screenshot reached the model.
        self.image = image
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return LLMResponse(
            text="",
            parsed=self.parsed,
            provider=self.provider,
            model=self.model,
            input_tokens=1200,
            output_tokens=300,
            cost_usd=0.0135,
        )


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def ir(sample: dict):
    return build_ir(
        sample["actions"],
        suite_name="Checkout flow",
        start_url=sample["session"]["start_url"],
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def test_prompt_template_fills_in():
    text = load_prompt(
        "enhance_code", suite_name="Login", start_url="http://x", pages="P", steps="S"
    )
    assert "Login" in text and "http://x" in text
    assert "{" not in text.replace("{}", "")  # every placeholder was filled


def test_missing_prompt_is_an_llm_error():
    with pytest.raises(LLMError, match="not found"):
        load_prompt("no_such_prompt")


def test_prompt_missing_value_is_an_llm_error():
    with pytest.raises(LLMError, match="expects a value"):
        load_prompt("enhance_code", suite_name="Login")


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
def test_enhancement_renames_and_describes(ir):
    page = ir.pages[0]
    old = page.locators[0].name
    step = next(s for s in ir.steps if s.locator_name == old)

    client = FakeLLM(
        CodeEnhancement(
            function_name="test_customer_completes_checkout",
            title="Customer Checkout",
            description="Verifies a returning customer can complete a purchase.",
            step_descriptions={str(step.sequence): "Sign in as a returning customer"},
            locator_names={f"{page.class_name}.{old}": "email_field"},
        )
    )

    outcome = enhance(ir, client=client)

    assert outcome.applied
    assert ir.function_name == "test_customer_completes_checkout"
    assert ir.suite_name == "Customer Checkout"
    assert outcome.description.startswith("Verifies")
    assert step.description == "Sign in as a returning customer"
    assert page.locators[0].name == "email_field"
    assert step.locator_name == "email_field"
    assert outcome.cost_usd == 0.0135 and outcome.tokens == 1500


def test_rename_rewrites_the_code_that_uses_it(ir):
    page = ir.pages[0]
    old = page.locators[0].name
    step = next(s for s in ir.steps if s.locator_name == old)
    page_var = step.page_var

    enhance(
        ir,
        client=FakeLLM(
            CodeEnhancement(locator_names={f"{page.class_name}.{old}": "email_field"})
        ),
    )

    body = "\n".join(line for s in ir.steps for line in s.code)
    assert f"{page_var}.email_field" in body
    # The old name must be gone, or the test calls a property that no longer
    # exists — the exact failure this rename has to avoid.
    assert f"{page_var}.{old}" not in body


def test_enhanced_code_still_compiles(ir, sample):
    page = ir.pages[0]
    renames = {
        f"{page.class_name}.{loc.name}": f"element_{i}"
        for i, loc in enumerate(page.locators)
    }
    enhance(
        ir,
        client=FakeLLM(
            CodeEnhancement(
                function_name="test_renamed_everything",
                step_descriptions={str(s.sequence): "Do the thing" for s in ir.steps},
                locator_names=renames,
            )
        ),
    )

    for spec in render(ir, browser_info=sample["session"]["browser_info"]):
        if spec.path.endswith(".py"):
            ast.parse(spec.content)  # raises if the rename broke anything


# ---------------------------------------------------------------------------
# Degrading gracefully — the point of the whole design
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "error",
    [
        LLMError("Could not reach the Anthropic API"),
        LLMRefusal("Claude declined this request"),
        RuntimeError("the SDK exploded"),
    ],
)
def test_a_failed_call_leaves_the_test_untouched(ir, error):
    before = (ir.function_name, ir.suite_name, [s.description for s in ir.steps])

    outcome = enhance(ir, client=FakeLLM(error=error))

    assert not outcome.applied and outcome.skipped
    assert (ir.function_name, ir.suite_name, [s.description for s in ir.steps]) == before


def test_no_provider_configured_skips_without_calling_anything(ir, monkeypatch):
    monkeypatch.setattr("app.ai.enhancer.ai_available", lambda: False)
    outcome = enhance(ir)
    assert not outcome.applied
    assert "no LLM provider" in outcome.skipped


def test_empty_response_is_not_applied(ir):
    outcome = enhance(ir, client=FakeLLM(None))
    assert not outcome.applied


# ---------------------------------------------------------------------------
# Confidently wrong suggestions are dropped, not trusted
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "proposed",
    [
        "checkout_flow",            # missing the test_ prefix, pytest ignores it
        "test-checkout",            # not an identifier
        "test_" + "x" * 80,         # too long
        "",
        "class",
    ],
)
def test_bad_function_names_are_rejected(ir, proposed):
    original = ir.function_name
    enhance(ir, client=FakeLLM(CodeEnhancement(function_name=proposed)))
    assert ir.function_name == original


@pytest.mark.parametrize("proposed", ["page", "open", "url", "class", "2nd_field", "Email", "_x"])
def test_unsafe_locator_names_are_rejected(ir, proposed):
    page = ir.pages[0]
    old = page.locators[0].name

    enhance(
        ir, client=FakeLLM(CodeEnhancement(locator_names={f"{page.class_name}.{old}": proposed}))
    )

    assert page.locators[0].name == old


def test_a_colliding_rename_is_dropped(ir):
    page = next(p for p in ir.pages if len(p.locators) > 1)
    first, second = page.locators[0].name, page.locators[1].name

    # Renaming one onto the other would silently shadow a property.
    enhance(
        ir, client=FakeLLM(CodeEnhancement(locator_names={f"{page.class_name}.{first}": second}))
    )

    assert [locator.name for locator in page.locators][:2] == [first, second]


def test_unknown_targets_are_ignored(ir):
    descriptions = [s.description for s in ir.steps]
    names = [loc.name for p in ir.pages for loc in p.locators]

    enhance(
        ir,
        client=FakeLLM(
            CodeEnhancement(
                step_descriptions={"9999": "a step that does not exist", "abc": "nonsense"},
                locator_names={"NoSuchPage.field": "whatever", "malformed": "x"},
            )
        ),
    )

    assert [s.description for s in ir.steps] == descriptions
    assert [loc.name for p in ir.pages for loc in p.locators] == names


def test_prose_cannot_escape_a_comment_or_a_docstring(ir, sample):
    """Model prose is rendered unquoted, so it has to be neutralised.

    A step description becomes a `# comment` and the title becomes the module
    docstring. A newline escapes the first and a `\"\"\"` ends the second, so
    both would let the model smuggle in a line of real code.
    """
    attack = 'x"""\nimport os\nos.system("rm -rf /")\n#'
    enhance(
        ir,
        client=FakeLLM(
            CodeEnhancement(
                title=attack,
                description=attack,
                step_descriptions={str(ir.steps[0].sequence): attack},
            )
        ),
    )

    assert "\n" not in ir.suite_name and '"""' not in ir.suite_name
    assert "\n" not in ir.steps[0].description

    module = next(
        spec for spec in render(ir, browser_info=sample["session"]["browser_info"])
        if spec.path == ir.file_path
    )
    tree = ast.parse(module.content)  # would raise if the docstring was broken
    # The payload survives only as prose inside the docstring — never as code.
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Import)]
    assert "os.system" in ast.get_docstring(tree)
    assert "os.system" not in "\n".join(line for s in ir.steps for line in s.code)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
def test_failure_analysis_confidence_is_bounded():
    with pytest.raises(ValueError):
        FailureAnalysis(
            root_cause="x",
            suggested_fix="y",
            category="test_bug",
            severity="high",
            priority="high",
            confidence=1.5,
            is_product_bug=False,
        )


def test_enhancement_defaults_are_empty():
    empty = CodeEnhancement()
    assert empty.function_name is None
    assert empty.step_descriptions == {} and empty.locator_names == {}


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("provider", "setting"),
    [
        ("claude", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
    ],
)
def test_ai_is_available_only_with_the_matching_key(monkeypatch, provider, setting):
    """Each provider must read its own key, not another one's."""
    from app.ai.client import ai_available
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", provider)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(settings, name, "")

    assert not ai_available()

    monkeypatch.setattr(settings, setting, "a-key")
    assert ai_available()


def test_an_unknown_provider_names_the_valid_ones(monkeypatch):
    from app.ai.client import get_llm_client
    from app.core.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "llama")
    with pytest.raises(LLMError, match="claude, gemini, openai"):
        get_llm_client()


def test_a_provider_without_a_key_refuses_to_build(monkeypatch):
    """Better to fail loudly here than to send an unauthenticated request."""
    from app.ai.gemini import GeminiClient
    from app.core.config import settings

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiClient()


# ---------------------------------------------------------------------------
# Gemini specifics — the parts a fake client cannot cover
# ---------------------------------------------------------------------------
def _gemini_response(**kwargs):
    """A GenerateContentResponse built from the real SDK types."""
    from google.genai import types

    return types.GenerateContentResponse(**kwargs)


def test_a_blocked_prompt_is_a_refusal_not_a_crash():
    """Gemini returns HTTP 200 for a safety block, with no text to read."""
    from google.genai import types

    from app.ai.gemini import _guard_refusal

    response = _gemini_response(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(
            block_reason=types.BlockedReason.SAFETY
        )
    )

    with pytest.raises(LLMRefusal, match="declined"):
        _guard_refusal(response)


def test_a_safety_stop_mid_answer_is_a_refusal():
    from google.genai import types

    from app.ai.gemini import _guard_refusal

    response = _gemini_response(
        candidates=[types.Candidate(finish_reason=types.FinishReason.SAFETY)]
    )

    with pytest.raises(LLMRefusal):
        _guard_refusal(response)


def test_a_normal_stop_is_not_a_refusal():
    from google.genai import types

    from app.ai.gemini import _guard_refusal

    response = _gemini_response(
        candidates=[types.Candidate(finish_reason=types.FinishReason.STOP)]
    )

    _guard_refusal(response)  # must not raise


def test_thinking_tokens_are_counted_as_output():
    """Gemini reports them separately, but they are billed as output."""
    from google.genai import types

    from app.ai.gemini import GeminiClient

    client = GeminiClient(api_key="test-key")
    response = _gemini_response(
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=800
        )
    )

    result = client._to_response(response, text="hi", started=0.0)

    assert result.input_tokens == 1000
    assert result.output_tokens == 1000  # 200 answer + 800 thinking
    assert result.cost_usd > 0
    assert result.provider == "gemini"


@pytest.mark.parametrize(
    ("model", "expected_input_rate"),
    [
        ("gemini-3.5-flash-lite", 0.10),
        ("gemini-flash-latest", 0.30),
        ("gemini-2.5-pro", 1.25),
        ("some-unreleased-model", 1.25),  # unknown falls back to the dearest tier
    ],
)
def test_cost_is_priced_for_the_model_actually_used(model, expected_input_rate):
    """The model is configurable, so quoting pro rates for a flash run lies."""
    from app.ai.gemini import _rates

    assert _rates(model)[0] == expected_input_rate


def test_a_wrong_model_id_says_how_to_fix_it():
    """A 404 here almost always means a stale model name, not a broken key."""
    from google.genai import errors

    from app.ai.gemini import _translate

    translated = _translate(
        errors.ClientError(404, {"error": {"message": "not found"}}), "gemini-9-ultra"
    )

    assert isinstance(translated, LLMError)
    assert "GEMINI_MODEL" in str(translated)
