"""The plugin the runner loads into every run - see app/runner/runtime_plugin.py.

A suite's conftest.py is the suite's own and is never regenerated, so what has
to hold for every run, old suites included, is loaded from here instead.
"""

import subprocess
import textwrap
from pathlib import Path

from app.models.enums import Browser
from app.runner.executor import RUNTIME_PLUGIN_NAME, _command, _environment, _materialise


def test_the_plugin_is_in_every_workspace_and_loaded(tmp_path: Path) -> None:
    _materialise({"tests/test_a.py": "x = 1\n"}, tmp_path)

    assert (tmp_path / f"{RUNTIME_PLUGIN_NAME}.py").is_file()
    command = _command(Browser.CHROMIUM, headless=False)
    assert command[command.index(RUNTIME_PLUGIN_NAME) - 1] == "-p"


def test_a_click_that_opens_a_file_picker_does_not_stall_a_headed_run(tmp_path: Path) -> None:
    """Seen on a watched run: the recorded click on "Choose file" opened the
    server's real file picker and the test sat behind it until the timeout.
    With the plugin loaded, Playwright intercepts the picker instead - the
    click is harmless, the upload step still sets the file, and the page is
    not blocked afterwards."""
    test = textwrap.dedent(
        '''
        def test_upload(page):
            page.goto(
                "data:text/html,<input id=f type=file>"
                "<button id=b onclick=\\"document.getElementById('f').click()\\">"
                "Choose file</button>"
            )
            page.click("#b")                       # would open the OS picker
            page.set_input_files(
                "#f", {"name": "x.png", "mimeType": "image/png", "buffer": b"png"}
            )
            assert page.evaluate("document.getElementById('f').files[0].name") == "x.png"
            page.click("#b")                       # and again, still no picker
            assert page.evaluate("1 + 1") == 2     # the page is not blocked
        '''
    )
    _materialise(
        {"pytest.ini": "[pytest]\ntestpaths = tests\n", "tests/test_upload.py": test},
        tmp_path,
    )

    result = subprocess.run(
        [*_command(Browser.CHROMIUM, headless=False), "--no-header"],
        cwd=tmp_path,
        env=_environment(None, headless=False),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "1 passed" in result.stdout
