"""Make this folder loadable as an unpacked extension, for working on it.

Two files are not kept here: `recorder.js` is the backend's copy, and
`config.js` names the server. The API writes both into the zip it serves; this
does the same into the folder, so `chrome://extensions` → Load unpacked → this
folder works against a local backend.

    cd backend && poetry run python ../extension/build.py   # http://127.0.0.1:5022/api/v1
    cd backend && poetry run python ../extension/build.py https://autoqa.example.com/api/v1
"""

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"

sys.path.insert(0, str(BACKEND))
from app.services import extension_service  # noqa: E402

api_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5022/api/v1"

shutil.copyfile(extension_service.RECORDER_JS, HERE / "recorder.js")
(HERE / "config.js").write_text(extension_service.config_js(api_url), encoding="utf-8")
print(f"ready to load unpacked from {HERE} (API: {api_url})")
