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
