"""The Chrome extension the API packages, and the route it needs.

The zip is what a tester installs, so what matters is that it is complete -
manifest, scripts, this server's recorder, the server address - and that it
is one folder, which is what "Load unpacked" wants.
"""

import io
import json
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import extension_service
from tests.conftest import register_user

API = settings.API_V1_PREFIX


def unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


# ---------------------------------------------------------------------------
# The download
# ---------------------------------------------------------------------------
def test_info_reports_the_version_from_the_manifest(client: TestClient) -> None:
    response = client.get(f"{API}/extension")

    assert response.status_code == 200
    body = response.json()
    manifest = json.loads((settings.extension_dir / "manifest.json").read_text())
    assert body["version"] == manifest["version"]
    assert body["minimum_version"] == extension_service.MINIMUM_VERSION
    assert body["download_path"].endswith("/extension/download")


def test_download_is_one_folder_with_everything_in_it(client: TestClient) -> None:
    response = client.get(
        f"{API}/extension/download", params={"api_url": "https://qa.example.com/api/v1"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "autoqa-recorder-" in response.headers["content-disposition"]

    files = unzip(response.content)
    folder = extension_service.FOLDER
    assert all(name.startswith(f"{folder}/") for name in files), sorted(files)

    for required in (
        "manifest.json",
        "background.js",
        "content-main.js",
        "content-relay.js",
        "popup.html",
        "popup.js",
        "recorder.js",
        "config.js",
        "icons/icon-128.png",
    ):
        assert f"{folder}/{required}" in files, required

    # Not for testers.
    assert f"{folder}/README.md" not in files
    assert f"{folder}/build.py" not in files


def test_download_carries_this_servers_recorder_and_address(client: TestClient) -> None:
    files = unzip(
        client.get(
            f"{API}/extension/download", params={"api_url": "https://qa.example.com/api/v1/"}
        ).content
    )
    folder = extension_service.FOLDER

    assert files[f"{folder}/recorder.js"] == extension_service.RECORDER_JS.read_bytes()

    config = files[f"{folder}/config.js"].decode()
    assert '"apiUrl": "https://qa.example.com/api/v1"' in config   # trailing slash gone
    assert "self.AUTOQA_CONFIG" in config


def test_download_defaults_to_the_address_it_was_asked_at(client: TestClient) -> None:
    files = unzip(client.get(f"{API}/extension/download").content)
    config = files[f"{extension_service.FOLDER}/config.js"].decode()

    assert f"http://testserver{API}" in config


@pytest.mark.parametrize("bad", ["ftp://x", "not a url", "javascript:alert(1)", 'https://x/"'])
def test_download_refuses_an_address_that_is_not_http(client: TestClient, bad: str) -> None:
    response = client.get(f"{API}/extension/download", params={"api_url": bad})

    assert response.status_code == 422, response.text


def test_manifest_loads_the_recorder_in_the_page_world() -> None:
    """The recorder must run in the page's own world so that the page-side
    bridge is the `window.__autoqaBridge` it reads at load - and after
    content-main.js, which defines it."""
    manifest = json.loads((settings.extension_dir / "manifest.json").read_text())

    main_world = [s for s in manifest["content_scripts"] if s.get("world") == "MAIN"]
    assert len(main_world) == 1
    assert main_world[0]["js"] == ["content-main.js", "recorder.js"]
    assert main_world[0]["all_frames"] is True
    assert main_world[0]["run_at"] == "document_start"


# ---------------------------------------------------------------------------
# The progress route the extension rejoins with
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_progress_reports_what_a_rejoining_page_needs(client: TestClient) -> None:
    tokens = register_user(client, email=f"ext-{uuid.uuid4().hex[:10]}@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    project = client.post(
        f"{API}/projects",
        headers=headers,
        json={"name": f"Ext {uuid.uuid4().hex[:6]}", "base_url": "https://shop.example.com"},
    ).json()
    session = client.post(
        f"{API}/projects/{project['id']}/recordings",
        headers=headers,
        json={"name": "ext", "start_url": "https://shop.example.com/", "extension_version": "chrome-1.0.0"},
    ).json()

    empty = client.get(f"{API}/recordings/{session['id']}/progress", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == {"action_count": 0, "max_sequence": None, "max_timestamp_ms": None}

    client.post(
        f"{API}/recordings/{session['id']}/actions",
        headers=headers,
        json={"actions": [
            {"sequence": 100000, "action_type": "navigate", "timestamp_ms": 5,
             "url": "https://shop.example.com/", "payload": {"url": "https://shop.example.com/"}},
            {"sequence": 100001, "action_type": "click", "timestamp_ms": 900,
             "url": "https://shop.example.com/",
             "selectors": [{"strategy": "text", "value": "Buy"}],
             "element": {"tag": "button"}},
        ]},
    ).raise_for_status()

    after = client.get(f"{API}/recordings/{session['id']}/progress", headers=headers).json()
    assert after == {"action_count": 2, "max_sequence": 100001, "max_timestamp_ms": 900}


@pytest.mark.integration
def test_progress_is_not_visible_across_projects(client: TestClient) -> None:
    owner = register_user(client, email=f"own-{uuid.uuid4().hex[:10]}@example.com")
    other = register_user(client, role="manual_qa", email=f"oth-{uuid.uuid4().hex[:10]}@example.com")
    own_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = client.post(
        f"{API}/projects", headers=own_headers,
        json={"name": f"P {uuid.uuid4().hex[:6]}", "base_url": "https://a.example.com"},
    ).json()
    session = client.post(
        f"{API}/projects/{project['id']}/recordings", headers=own_headers,
        json={"name": "s", "start_url": "https://a.example.com/"},
    ).json()

    response = client.get(
        f"{API}/recordings/{session['id']}/progress",
        headers={"Authorization": f"Bearer {other['access_token']}"},
    )

    assert response.status_code == 404
