# AutoQA backend — API, code generation, test execution, and the recorder.
#
# Built on plain Debian rather than the Playwright image on purpose: pyproject
# asks for Python 3.13 and the published Playwright images are Ubuntu noble,
# which ships 3.12. `playwright install --with-deps` pulls the same browsers
# and the same system libraries, so the only cost is build time.
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DISPLAY=:99

# Xvfb, x11vnc and noVNC are here because *recording* drives a headed browser.
#
# Running a test is headless and needs none of this. But a recording session
# opens a real window that a person clicks around in, and on a server there is
# no screen for it to open on. Xvfb gives it one, x11vnc publishes that screen,
# and noVNC turns it into something a browser tab can display — so the QA
# engineer drives the server's browser from their own machine.
#
# See docs/deployment.md. Set AUTOQA_VIRTUAL_DISPLAY=0 to run without any of
# it, on a deployment that only ever executes already-recorded suites.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Dependencies first, so a code change does not reinstall the world.
RUN pip install "poetry>=1.8"
COPY backend/pyproject.toml backend/poetry.lock* ./
# `readme = "../README.md"` in pyproject; package-mode is off so it is never
# read, but poetry still resolves the path.
COPY README.md /app/README.md
RUN poetry install --no-root --only main

# The browsers, and the system libraries they need. This is the slow layer;
# it is above the source copy so it is cached across ordinary deploys.
#
# Three browsers is what DEFAULT_BROWSERS asks for and costs roughly 1.5 GB.
# Trim the list here and in .env if a suite only ever runs on one.
RUN playwright install --with-deps chromium firefox webkit

COPY backend/ /app/backend/
# The Chrome extension source. The API zips it up on request, adding its own
# recorder.js and the server address, so a download always matches the
# backend it came from. Resolved through EXTENSION_PATH (../extension).
COPY extension/ /app/extension/
COPY docker/backend-entrypoint.sh /usr/local/bin/autoqa-entrypoint
RUN chmod +x /usr/local/bin/autoqa-entrypoint

# 29381 the API, 29383 the recording screen over noVNC. Odd on purpose — see
# the ports block in docker-compose.prod.yml.
EXPOSE 29381 29383

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:29381/health || exit 1

ENTRYPOINT ["/usr/local/bin/autoqa-entrypoint"]
