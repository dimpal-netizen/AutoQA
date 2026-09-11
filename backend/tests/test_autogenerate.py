"""Stopping a recording generates its test suite automatically.

Both stop paths go through this: the API stop endpoint (extension / web app)
and the launched browser finishing. A failure to generate must never stop the
recording from stopping.
"""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.conftest import register_user

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
FIXTURE = Path(__file__).parent / "fixtures" / "sample_recording.json"


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def register(client: TestClient, role: str = "qa_engineer") -> dict:
    return register_user(client, role, email=f"auto-{uuid.uuid4().hex[:12]}@example.com")


@pytest.fixture
def project(client: TestClient):
    tokens = register(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    created = client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": f"Auto {uuid.uuid4().hex[:6]}", "base_url": "https://shop.example.com"},
    )
    return headers, created.json()["id"]


def start_and_fill(client: TestClient, headers, project_id: int, sample: dict, actions=None):
    session_id = client.post(
        f"{API}/projects/{project_id}/recordings", headers=headers, json=sample["session"]
    ).json()["id"]
    payload = sample["actions"] if actions is None else actions
    if payload:
        client.post(
            f"{API}/recordings/{session_id}/actions",
            headers=headers,
            json={"actions": payload},
        )
    return session_id


def test_stopping_generates_a_suite(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)

    stopped = client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={})

    assert stopped.status_code == 200, stopped.text
    suite_id = stopped.json()["suite_id"]
    assert suite_id is not None, "stopping did not generate a suite"

    suite = client.get(f"{API}/suites/{suite_id}", headers=headers).json()
    assert suite["recording_id"] == session_id
    assert len(suite["cases"]) == 1
    assert "page.goto(" in suite["cases"][0]["code"]
    assert any(f["path"] == "conftest.py" for f in suite["files"])
    assert any(f["path"].startswith("pages/") for f in suite["files"])


def test_a_recording_is_one_test_case_however_many_attempts_it_holds(
    client: TestClient, project, sample: dict
) -> None:
    """One recording, one recorded case — even when the person started over.

    It used to be cut into a case per attempt, which was right about the
    recording and wrong about the code. A slice begins part-way through a
    journey and all it gets to make up for that is a `goto`: segment two of a
    registration opens the form and types into field six, on a page where the
    first five are empty and the account it needed was never created. It cannot
    pass, and it fails for a reason that has nothing to do with the application.

    The sample fills the same field twice, which is `segments.split`'s own
    signal for "started over" — so this recording is exactly the shape that used
    to come back as two.
    """
    headers, project_id = project
    actions = list(sample["actions"])
    first_input = next(a for a in actions if a["action_type"] == "input")
    again = dict(first_input)
    again["sequence"] = max(a["sequence"] for a in actions) + 1
    again["timestamp_ms"] = max(a["timestamp_ms"] for a in actions) + 500

    session_id = start_and_fill(
        client, headers, project_id, {**sample, "actions": [*actions, again]}
    )
    suite_id = client.post(
        f"{API}/recordings/{session_id}/stop", headers=headers, json={}
    ).json()["suite_id"]

    cases = client.get(f"{API}/suites/{suite_id}", headers=headers).json()["cases"]

    assert len(cases) == 1, [c["name"] for c in cases]
    # And it is not named as though it were one of several.
    assert not cases[0]["name"].rstrip().endswith(("1", "2"))


def test_generated_case_has_readable_steps(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)
    suite_id = client.post(
        f"{API}/recordings/{session_id}/stop", headers=headers, json={}
    ).json()["suite_id"]

    case = client.get(f"{API}/suites/{suite_id}", headers=headers).json()["cases"][0]
    descriptions = [step["description"] for step in case["steps"]]

    assert descriptions, "no steps recorded for review"
    assert all(d.strip() for d in descriptions)
    assert any("Sign in" in d for d in descriptions)


def test_an_empty_recording_still_stops_cleanly(client: TestClient, project, sample: dict) -> None:
    """Nothing to generate must not turn into a failed stop."""
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample, actions=[])

    stopped = client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={})

    assert stopped.status_code == 200
    assert stopped.json()["status"] == "completed"
    assert stopped.json()["suite_id"] is None


def test_recording_list_exposes_the_suite(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)
    client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={})

    listed = client.get(f"{API}/recordings?project_id={project_id}", headers=headers).json()
    entry = next(s for s in listed if s["id"] == session_id)

    assert entry["suite_id"] is not None


def test_regenerating_replaces_rather_than_duplicates(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)
    first = client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={}).json()[
        "suite_id"
    ]

    regenerated = client.post(
        f"{API}/recordings/{session_id}/generate", headers=headers, json={"name": "Renamed"}
    )

    assert regenerated.status_code == 201, regenerated.text
    assert regenerated.json()["id"] == first, "regeneration created a second suite"
    assert regenerated.json()["name"] == "Renamed"
    assert len(regenerated.json()["cases"]) == 1

    suites = client.get(f"{API}/suites?project_id={project_id}", headers=headers).json()
    assert len(suites) == 1


def test_manual_qa_cannot_generate_by_hand(client: TestClient, project, sample: dict) -> None:
    """The automatic path runs as the recorder; the manual endpoint needs QA."""
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)
    client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={})

    manual_qa = register(client, role="manual_qa")
    response = client.post(
        f"{API}/recordings/{session_id}/generate",
        headers={"Authorization": f"Bearer {manual_qa['access_token']}"},
        json={},
    )

    assert response.status_code in (403, 404)


def test_cannot_generate_from_a_running_recording(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)

    response = client.post(f"{API}/recordings/{session_id}/generate", headers=headers, json={})

    assert response.status_code == 422
    assert "still running" in response.json()["detail"]


def test_bundle_returns_every_file(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_and_fill(client, headers, project_id, sample)
    suite_id = client.post(
        f"{API}/recordings/{session_id}/stop", headers=headers, json={}
    ).json()["suite_id"]

    bundle = client.get(f"{API}/suites/{suite_id}/bundle", headers=headers).json()

    assert "conftest.py" in bundle
    assert "pytest.ini" in bundle
    assert any(p.startswith("tests/") for p in bundle)
    assert any(p.startswith("pages/") for p in bundle)
