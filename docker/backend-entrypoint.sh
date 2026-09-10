#!/usr/bin/env bash
#
# Start the pieces the API needs before the API itself.
#
# Order matters: the screen has to exist before anything opens a window on it,
# and the schema has to exist before the first request touches the database.
set -euo pipefail

log() { echo "[autoqa] $*"; }

# ---------------------------------------------------------------------------
# A screen for the recorder
#
# Executing a suite is headless and needs none of this. Recording is not: it
# opens a real browser window for a person to click around in, and a server has
# no screen for it to open on. Xvfb provides one, x11vnc publishes it, and
# noVNC serves it to a browser tab.
#
# Set AUTOQA_VIRTUAL_DISPLAY=0 on a deployment that only ever runs suites that
# were recorded somewhere else.
# ---------------------------------------------------------------------------
if [ "${AUTOQA_VIRTUAL_DISPLAY:-1}" = "1" ]; then
    screen="${AUTOQA_SCREEN:-1920x1080x24}"
    log "starting Xvfb on ${DISPLAY} at ${screen}"
    Xvfb "${DISPLAY}" -screen 0 "${screen}" -nolisten tcp -noreset &

    # Xvfb takes a moment to create its socket. Opening a window before it
    # exists fails with "cannot open display", which reads like a broken image
    # rather than a race. Waiting on the socket rather than asking xdpyinfo
    # keeps x11-utils out of the image for one line of shell.
    socket="/tmp/.X11-unix/X${DISPLAY#:}"
    for _ in $(seq 1 50); do
        [ -S "${socket}" ] && break
        sleep 0.2
    done
    [ -S "${socket}" ] || log "warning: ${socket} never appeared; recording will fail"

    # `-nopw` is deliberate and is why this port must never be published to the
    # internet. Anyone who can reach 29383 can drive the browser, and that
    # browser is signed in to whatever the QA engineer signed in to. Keep it
    # behind the reverse proxy's auth, or on a private network, or off.
    log "starting x11vnc on :5900"
    x11vnc -display "${DISPLAY}" -forever -shared -nopw -quiet -rfbport 5900 \
        -listen localhost &

    log "serving noVNC on :29383"
    websockify --web=/usr/share/novnc 29383 localhost:5900 &
fi

# ---------------------------------------------------------------------------
# Schema
#
# Run every deploy, not by hand. A dangling alembic pointer is invisible until
# a recording silently fails to save, and by then the cause is hours behind.
# ---------------------------------------------------------------------------
log "applying migrations"
alembic upgrade head

# ---------------------------------------------------------------------------
# The API
#
# One worker, and this is not a performance oversight. A run is dispatched as a
# thread inside this process (see services/execution_service.py) rather than to
# a queue, so the process that started a run is the only one that knows about
# it. A second worker would accept status requests for runs it has never heard
# of and report them missing.
#
# Scaling out means moving execution onto a real queue first.
# ---------------------------------------------------------------------------
log "starting API on :29381"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 29381 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips '*'
