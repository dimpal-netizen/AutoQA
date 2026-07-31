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

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
FIXTURE = Path(__file__).parent / "fixtures" / "sample_recording.json"


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def register(client: TestClient, role: str = "qa_engineer") -> dict:
    response = client.post(
        f"{API}/auth/register",
        json={
            "email": f"auto-{uuid.uuid4().hex[:12]}@example.com",
            "password": "supersecret123",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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
