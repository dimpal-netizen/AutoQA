"""A generated suite must import only files it also produced.

This is the invariant that broke. Regenerating cases synthesised them from an
IR rebuilt from the recording, while the page objects on disk were whatever had
been stored when the suite was first created. A change to how page objects are
named desynchronised the two halves, and the failure was not subtle:

    ImportError: No module named 'pages.agent_details_page'
    on disk:     pages/agent_details_cmru9ht1z001a01l61v2hpc2u_page.py

pytest reports that as `collection failure` — a message that names neither the
module nor the reason — and one uncollectable file takes the entire run down
with it, so every other test reports as failed too.
"""

import ast
import re

import pytest

from app.ai.schemas import CaseStep, GeneratedCase
from app.codegen.converter import LocatorSpec, PageSpec, TestIR, build_ir
from app.codegen.generator import render
from app.codegen.synth import synthesise

IMPORT = re.compile(r"^from (pages\.\w+) import", re.M)


def imported_modules(code: str) -> set[str]:
    return set(IMPORT.findall(code))


def produced_modules(rendered) -> set[str]:
    """`pages/login_page.py` -> `pages.login_page`."""
    return {
        spec.path.removesuffix(".py").replace("/", ".")
        for spec in rendered
        if spec.path.startswith("pages/")
    }


RECORDING = [
    {
        "action_type": "navigate",
        "url": "https://x.test/login",
        "frame_path": [],
        "selectors": [],
        "element": None,
        "payload": {"url": "https://x.test/login"},
        "is_ignored": False,
    },
    {
        "action_type": "input",
        "url": "https://x.test/login",
        "frame_path": [],
        "selectors": [{"strategy": "label", "value": "Email", "unique": True, "score": 90}],
        "element": {"tag": "input", "input_type": "email", "role": None,
                    "accessible_name": "Email", "text": None, "attributes": {}},
        "payload": {"value": "a@b.com"},
        "is_ignored": False,
    },
    {
        "action_type": "click",
        # A record id in the path — the case that started this.
        "url": "https://x.test/agent-details/cmru9ht1z001a01l61v2hpc2u",
        "frame_path": [],
        "selectors": [
            {"strategy": "role_name", "value": "link|Agents", "unique": True, "score": 95},
            {"strategy": "xpath", "value": "//body/header[1]/div[2]/a[1]", "unique": True},
        ],
        "element": {"tag": "a", "input_type": None, "role": "link",
                    "accessible_name": "Agents", "text": "Agents", "attributes": {}},
        "payload": {},
        "is_ignored": False,
    },
]


@pytest.fixture
def recorded_ir() -> TestIR:
    return build_ir(RECORDING, suite_name="Agents", start_url="https://x.test/login")


def test_the_recorded_test_imports_only_pages_that_were_generated(recorded_ir):
    rendered = render(recorded_ir, browser_info={})
    module = next(f for f in rendered if f.path == recorded_ir.file_path)

    missing = imported_modules(module.content) - produced_modules(rendered)
    assert not missing, f"imports with no file behind them: {sorted(missing)}"


def test_a_synthesised_case_imports_only_pages_that_were_generated(recorded_ir):
    """The half that broke: cases come from one render, page objects from another."""
    page = recorded_ir.pages[0]
    generated = GeneratedCase(
        name="Agents link works",
        category="positive",
        priority="high",
        description="The Agents link goes to the agent list.",
        steps=[
            CaseStep(action="goto", value="https://x.test/login", description="Open"),
            CaseStep(
                action="click",
                target=f"{page.class_name}.{page.locators[0].name}",
                description="Click",
            ),
            CaseStep(action="expect_url", value="/agents", description="Arrived"),
        ],
    )

    case_ir = synthesise(
        generated,
        pages=recorded_ir.pages,
        start_url=recorded_ir.start_url,
        module_name="test_agents",
        function_name="test_agents",
    )

    # Rendered from the same IR the page objects come from — which is exactly
    # what the service now guarantees.
    rendered = render(case_ir, browser_info={})
    module = next(f for f in rendered if f.path == case_ir.file_path)

    ast.parse(module.content)
    missing = imported_modules(module.content) - produced_modules(rendered)
    assert not missing, f"imports with no file behind them: {sorted(missing)}"


def test_a_record_id_never_reaches_a_page_module_name(recorded_ir):
    """The specific mismatch: one half clipped the id, the other did not."""
    modules = produced_modules(render(recorded_ir, browser_info={}))

    assert "pages.agent_details_page" in modules
    assert not any("cmru9ht1z" in m for m in modules)


def test_every_page_object_is_valid_python(recorded_ir):
    for spec in render(recorded_ir, browser_info={}):
        if spec.path.endswith(".py"):
            ast.parse(spec.content)


def test_two_urls_that_differ_only_by_id_share_one_page_object():
    """Otherwise each record visited would add a page object nothing imports."""
    actions = []
    for record_id in ("cmru9ht1z001a01l61v2hpc2u", "cmryim584000q01p42kj4ts8q"):
        actions.append(
            {
                "action_type": "click",
                "url": f"https://x.test/properties/{record_id}",
                "frame_path": [],
                "selectors": [
                    {"strategy": "test_id", "value": f"buy-{record_id[:4]}", "unique": True}
                ],
                "element": {"tag": "button", "input_type": None, "role": "button",
                            "accessible_name": "Buy", "text": "Buy", "attributes": {}},
                "payload": {},
                "is_ignored": False,
            }
        )

    ir = build_ir(actions, suite_name="Properties", start_url="https://x.test/")
    page_modules = [p.module for p in ir.pages]

    assert page_modules == ["properties_page"]


def test_an_unimported_page_object_is_still_valid_output():
    """A page visited but never interacted with produces no locators, and the
    generated class must still parse rather than emitting an empty body."""
    page = PageSpec(class_name="EmptyPage", module="empty_page", url="https://x.test/e")
    ir = TestIR(
        suite_name="Empty",
        function_name="test_empty",
        module_name="test_empty",
        start_url="https://x.test/e",
        pages=[page],
    )

    for spec in render(ir, browser_info={}):
        if spec.path.endswith(".py"):
            ast.parse(spec.content)


def test_a_locator_name_collision_does_not_shadow(recorded_ir):
    """Shorter names collide more often; the second must not overwrite the first."""
    page = PageSpec(class_name="P", module="p_page", url="https://x.test/")
    first = page.add(LocatorSpec(name="submit", expression="self.page.locator('#a')",
                                 strategy="css_id", fragile=False))
    second = page.add(LocatorSpec(name="submit", expression="self.page.locator('#b')",
                                  strategy="css_id", fragile=False))

    assert first != second
    assert len({loc.name for loc in page.locators}) == 2
