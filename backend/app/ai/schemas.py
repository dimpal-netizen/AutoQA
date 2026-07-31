"""What we ask the model to return.

These are the shapes handed to `complete_model()`, which makes the provider
validate its own output against them. Everything here is advisory data — names
and prose — never code. The model is never allowed to write a line that ends up
executing; see `enhancer.py` for why.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CodeEnhancement(BaseModel):
    """Naming and documentation improvements for a generated suite."""

    function_name: str | None = Field(
        default=None,
        description="pytest function name, snake_case, starts with test_, under 60 chars",
    )
    title: str | None = Field(
        default=None, description="Short human-readable suite name, under 60 chars"
    )
    description: str | None = Field(
        default=None, description="One or two sentences on what this test verifies"
    )
    step_descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Clearer sentence per step, keyed by the step's sequence number as a string",
    )
    locator_names: dict[str, str] = Field(
        default_factory=dict,
        description='Better page-object property names, keyed by "PageClassName.current_name"',
    )


class CaseStep(BaseModel):
    """One step of an invented test case.

    Note what is *not* here: code. The model chooses an action from a fixed
    vocabulary and points at a locator that already exists on a page object.
    Anything else is rejected, so a hallucinated element becomes a dropped
    step rather than a test that crashes.
    """

    action: str = Field(
        description=(
            "One of: goto, fill, click, check, uncheck, select, press, "
            "expect_visible, expect_hidden, expect_text, expect_url, "
            "expect_not_url"
        )
    )
    target: str | None = Field(
        default=None,
        description='Locator as "PageClassName.property_name". Omit for goto and expect_url.',
    )
    value: str | None = Field(
        default=None, description="Text to type, option to select, key to press, or URL"
    )
    description: str = Field(description="What this step does, in plain English")


class GeneratedCase(BaseModel):
    name: str = Field(description="Short sentence describing what this verifies")
    category: str = Field(description="One of: positive, negative, edge, security")
    priority: str = Field(description="One of: critical, high, medium, low")
    description: str = Field(description="Why this test matters, one or two sentences")
    steps: list[CaseStep] = Field(description="The steps, in order")


class GeneratedCases(BaseModel):
    cases: list[GeneratedCase] = Field(default_factory=list)


class FailureAnalysis(BaseModel):
    """Workflow 3 output: why a test failed and what to do about it."""

    root_cause: str = Field(description="What actually went wrong, in plain language")
    suggested_fix: str = Field(description="The concrete next action to take")
    category: str = Field(
        description=(
            "One of: application_bug, test_bug, selector_broken, timing, "
            "environment, test_data, flaky"
        )
    )
    severity: str = Field(description="One of: critical, high, medium, low")
    priority: str = Field(description="One of: critical, high, medium, low")
    confidence: float = Field(
        ge=0.0, le=1.0, description="How sure you are, 0.0 to 1.0"
    )
    is_product_bug: bool = Field(
        description="True if the application is broken, false if the test is"
    )
