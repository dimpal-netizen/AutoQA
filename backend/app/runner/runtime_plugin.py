"""A pytest plugin the runner loads into every run, whatever the suite says.

A suite carries its own conftest.py, and that file is the suite's to edit: once
generated it is never overwritten. So anything that has to hold for *every*
run - including suites generated last month - cannot live there. It lives
here. The executor copies this file into the run's workspace and loads it with
`-p`, the same way it loads pytest-playwright; the suite's conftest is still
free to add to or override what is here.

Keep it small and dependency-free: it runs inside the generated suite's
process, not the API's.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_native_file_dialogs(context) -> None:
    """Keep the operating system's file picker from ever opening.

    A recording of an upload holds the click on "Choose file" and then the
    file. Replayed headless, the click goes nowhere and `set_input_files` does
    the upload. Replayed headed - a run somebody is watching - that click opens
    the real picker, which no test can fill in, and the run sits behind it
    until the timeout. With a listener attached, Playwright intercepts the
    chooser instead of showing it; the listener has nothing to do, because the
    upload step that follows sets the files directly.

    On the context so that a popup or a second tab is covered too.
    """

    def ignore(chooser) -> None:  # noqa: ARG001 - the point is that it does nothing
        return None

    for open_page in context.pages:
        open_page.on("filechooser", ignore)
    context.on("page", lambda new_page: new_page.on("filechooser", ignore))
