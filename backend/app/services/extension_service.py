"""Packages the Chrome extension for download.

The extension is the recorder running in the tester's own browser, which is
the only way to record on a machine that installs nothing and a server that
opens nothing. Its source lives in `extension/` at the repo root; two files in
the shipped copy are not in that folder:

- `recorder.js` is the backend's own copy, added at packaging time. One file,
  no drift: an extension downloaded from this server records exactly the way
  this server expects.
- `config.js` carries the API address, so a tester never types it.

Built on every request rather than at deploy time. It is a few dozen kilobytes
and the cost is milliseconds; a cached artifact is one more thing to go stale.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.exceptions import NotFound, ValidationError

RECORDER_JS = Path(__file__).resolve().parent.parent / "static" / "recorder.js"

#: Folder name inside the zip. Unzipping then produces one folder, which is what
#: "Load unpacked" asks for - a zip that scatters files into Downloads does not.
FOLDER = "autoqa-recorder"

#: Not shipped. Documentation and tooling for people editing the extension.
_SKIPPED_NAMES = {"README.md", "build.py", ".gitignore"}

#: The oldest extension this server still accepts recordings from. Bump it when
#: the recording contract changes in a way an older extension gets wrong, and
#: the extension tells the tester to update rather than uploading bad data.
MINIMUM_VERSION = "1.0.0"


def manifest() -> dict:
    path = settings.extension_dir / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NotFound(
            f"Extension source not found at {settings.extension_dir}"
        ) from None


def version() -> str:
    return str(manifest().get("version", "0.0.0"))


def check_api_url(api_url: str) -> str:
    """The address baked into the download, checked for shape.

    Any http(s) URL is accepted: the download is public, so the value is only
    ever what the web app that linked to it uses itself, and a wrong one costs
    the tester a sign-in error rather than anything worse - the popup lets them
    correct it.
    """
    api_url = api_url.strip().rstrip("/")
    parts = urlsplit(api_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValidationError("api_url must be an absolute http(s) URL")
    if re.search(r"[\s\"'<>]", api_url):
        raise ValidationError("api_url contains characters that are not allowed")
    return api_url


def build_zip(api_url: str) -> bytes:
    """The extension as a zip: source, this server's recorder, and its address."""
    api_url = check_api_url(api_url)
    source = settings.extension_dir
    if not (source / "manifest.json").is_file():
        raise NotFound(f"Extension source not found at {source}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if relative.name in _SKIPPED_NAMES or any(
                part.startswith(".") for part in relative.parts
            ):
                continue
            # Never ship a stale copy somebody left in the source folder; the
            # backend's own is added below.
            if relative.name in ("recorder.js", "config.js"):
                continue
            archive.write(path, f"{FOLDER}/{relative.as_posix()}")

        archive.writestr(f"{FOLDER}/recorder.js", RECORDER_JS.read_bytes())
        archive.writestr(f"{FOLDER}/config.js", config_js(api_url))

    return buffer.getvalue()


def config_js(api_url: str) -> str:
    """The one file that differs between servers.

    A plain script rather than JSON, so the popup and the service worker can
    both load it with no fetch and no async: `importScripts` in the worker, a
    `<script>` tag in the popup.
    """
    payload = json.dumps(
        {
            "apiUrl": api_url,
            "version": version(),
            "minimumVersion": MINIMUM_VERSION,
        },
        indent=2,
    )
    return (
        "// Written by the AutoQA server when this extension was downloaded.\n"
        "// The API address can be changed from the popup's Server field.\n"
        f"self.AUTOQA_CONFIG = {payload};\n"
    )
