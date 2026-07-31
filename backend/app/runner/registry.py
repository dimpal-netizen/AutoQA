"""Which processes belong to which run, so a run can genuinely be stopped.

Cancelling used to mean "mark the row cancelled and look away": pytest carried
on, the browsers stayed open, and the machine kept working on a run nobody
wanted. Stopping something has to actually stop it.

The registry is process-local, which is correct for today — runs execute in a
background thread of the API process. When Celery takes over, this is the piece
that gets replaced by a signal through Redis, and nothing above it changes.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_processes: dict[int, set[subprocess.Popen]] = {}
# Runs cancelled before their process existed. Without this a Stop pressed in
# the second between "queued" and "launched" is silently ignored.
_cancelled: set[int] = set()


def register(run_id: int, process: subprocess.Popen) -> None:
    with _lock:
        if run_id in _cancelled:
            # Cancelled while we were starting up. Do not let it run at all.
            terminate(process)
            return
        _processes.setdefault(run_id, set()).add(process)


def unregister(run_id: int, process: subprocess.Popen) -> None:
    with _lock:
        processes = _processes.get(run_id)
        if processes is None:
            return
        processes.discard(process)
        if not processes:
            _processes.pop(run_id, None)


def cancel(run_id: int) -> int:
    """Kill everything this run is doing. Returns how many processes were stopped."""
    with _lock:
        _cancelled.add(run_id)
        processes = list(_processes.get(run_id, ()))

    for process in processes:
        terminate(process)

    logger.info("Run %s: cancelled, stopped %d process(es)", run_id, len(processes))
    return len(processes)


def is_cancelled(run_id: int) -> bool:
    with _lock:
        return run_id in _cancelled


def clear(run_id: int) -> None:
    """Forget a finished run, so its id can never cancel a future one."""
    with _lock:
        _cancelled.discard(run_id)
        _processes.pop(run_id, None)


def terminate(process: subprocess.Popen) -> None:
    """Kill a pytest process and every browser it started.

    Killing only the parent leaves Chromium, Firefox and WebKit running with no
    one to close them — they are children of pytest, not of us, so on Windows
    the whole tree has to be named explicitly.
    """
    if process.poll() is not None:
        return

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=20,
                check=False,
            )
        else:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    except Exception:
        logger.exception("Could not stop process %s", process.pid)
        try:
            process.kill()
        except Exception:
            pass
