"""Recording API against a real Postgres.

Run with: pytest -m integration   (needs `docker compose up -d`)
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
            "email": f"rec-{uuid.uuid4().hex[:12]}@example.com",
            "password": "supersecret123",
            "full_name": "Recorder",
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def headers_for(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def project(client: TestClient) -> tuple[dict[str, str], int]:
    """A fresh qa_engineer with an empty project."""
    tokens = register(client)
    headers = headers_for(tokens)
    created = client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": f"Shop {uuid.uuid4().hex[:6]}", "base_url": "https://shop.example.com"},
    )
    assert created.status_code == 201, created.text
    return headers, created.json()["id"]


def start_recording(client: TestClient, headers: dict, project_id: int, sample: dict) -> int:
    response = client.post(
        f"{API}/projects/{project_id}/recordings", headers=headers, json=sample["session"]
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# The full extension flow
# ---------------------------------------------------------------------------
def test_record_upload_stop(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)

    uploaded = client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"]},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json() == {
        "stored": 21,
        "skipped_duplicates": 0,
        "action_count": 21,
    }

    stopped = client.post(
        f"{API}/recordings/{session_id}/stop", headers=headers, json={"duration_ms": 30500}
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "completed"
    assert stopped.json()["action_count"] == 21
    assert stopped.json()["duration_ms"] == 30500


def test_actions_read_back_in_recorded_order(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"]},
    )

    actions = client.get(f"{API}/recordings/{session_id}/actions", headers=headers).json()

    assert [a["sequence"] for a in actions] == list(range(21))
    assert [a["action_type"] for a in actions] == [
        a["action_type"] for a in sample["actions"]
    ]


def test_upload_is_idempotent(client: TestClient, project, sample: dict) -> None:
    """A retried batch must not duplicate steps — the extension retries on flaky networks."""
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    body = {"actions": sample["actions"]}

    first = client.post(f"{API}/recordings/{session_id}/actions", headers=headers, json=body)
    second = client.post(f"{API}/recordings/{session_id}/actions", headers=headers, json=body)

    assert first.json()["stored"] == 21
    assert second.json() == {"stored": 0, "skipped_duplicates": 21, "action_count": 21}


def test_overlapping_batches_store_only_what_is_new(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)

    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][:10]},
    )
    overlap = client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][5:15]},
    )

    assert overlap.json() == {"stored": 5, "skipped_duplicates": 5, "action_count": 15}


def test_selectors_and_element_survive_the_round_trip(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"]},
    )

    detail = client.get(f"{API}/recordings/{session_id}", headers=headers).json()
    login_click = detail["actions"][5]

    assert login_click["action_type"] == "click"
    # Stored ranked, not in the order the extension happened to send them.
    assert login_click["selectors"][0]["strategy"] == "test_id"
    assert login_click["selectors"][0]["value"] == "login-submit"
    assert login_click["element"]["accessible_name"] == "Sign in"

    iframe_action = detail["actions"][18]
    assert iframe_action["frame_path"] == ["iframe[name='stripe-card']"]


def test_duration_falls_back_to_last_action_timestamp(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"]},
    )

    stopped = client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={})

    assert stopped.json()["duration_ms"] == 30500


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def test_cannot_upload_to_a_stopped_recording(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(f"{API}/recordings/{session_id}/stop", headers=headers, json={})

    response = client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][:1]},
    )

    assert response.status_code == 422
    assert "completed" in response.json()["detail"]


def test_malformed_action_is_rejected(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)

    response = client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={
            "actions": [
                {
                    "sequence": 0,
                    "action_type": "input",
                    "timestamp_ms": 0,
                    "url": "https://shop.example.com",
                    "selectors": [{"strategy": "test_id", "value": "x"}],
                    "payload": {},  # missing "value"
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "value" in response.text


def test_another_users_recording_is_invisible(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)

    stranger = headers_for(register(client))
    response = client.get(f"{API}/recordings/{session_id}", headers=stranger)

    # 404 not 403 — a 403 would confirm the recording exists.
    assert response.status_code == 404


def test_editing_an_action_replaces_its_selectors(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][:6]},
    )
    action_id = client.get(
        f"{API}/recordings/{session_id}/actions", headers=headers
    ).json()[1]["id"]

    response = client.patch(
        f"{API}/recordings/{session_id}/actions/{action_id}",
        headers=headers,
        json={
            "selectors": [{"strategy": "test_id", "value": "fixed-by-hand", "score": 100}],
            "note": "original selector was flaky",
        },
    )

    assert response.status_code == 200
    assert response.json()["selectors"][0]["value"] == "fixed-by-hand"
    assert response.json()["note"] == "original selector was flaky"


def test_manual_qa_cannot_edit_actions(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][:2]},
    )
    action_id = client.get(
        f"{API}/recordings/{session_id}/actions", headers=headers
    ).json()[0]["id"]

    manual_qa = headers_for(register(client, role="manual_qa"))
    response = client.patch(
        f"{API}/recordings/{session_id}/actions/{action_id}",
        headers=manual_qa,
        json={"is_ignored": True},
    )

    assert response.status_code == 403


def test_deleting_an_action_updates_the_count(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][:10]},
    )
    action_id = client.get(
        f"{API}/recordings/{session_id}/actions", headers=headers
    ).json()[3]["id"]

    assert (
        client.delete(
            f"{API}/recordings/{session_id}/actions/{action_id}", headers=headers
        ).status_code
        == 204
    )
    assert client.get(f"{API}/recordings/{session_id}", headers=headers).json()[
        "action_count"
    ] == 9


def test_deleting_a_recording_removes_its_actions(
    client: TestClient, project, sample: dict
) -> None:
    headers, project_id = project
    session_id = start_recording(client, headers, project_id, sample)
    client.post(
        f"{API}/recordings/{session_id}/actions",
        headers=headers,
        json={"actions": sample["actions"][:5]},
    )

    assert client.delete(f"{API}/recordings/{session_id}", headers=headers).status_code == 204
    assert client.get(f"{API}/recordings/{session_id}", headers=headers).status_code == 404


def test_listing_filters_by_project(client: TestClient, project, sample: dict) -> None:
    headers, project_id = project
    start_recording(client, headers, project_id, sample)

    other = client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": f"Other {uuid.uuid4().hex[:6]}", "base_url": "https://other.example.com"},
    ).json()["id"]

    mine = client.get(f"{API}/recordings?project_id={project_id}", headers=headers).json()
    theirs = client.get(f"{API}/recordings?project_id={other}", headers=headers).json()

    assert len(mine) == 1
    assert theirs == []
