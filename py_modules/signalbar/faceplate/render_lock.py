# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Cross-process serialization for all CPU-heavy Faceplate rendering.

Aura Core and Pixel Studio are intentionally separate processes, but the
Faceplate architecture permits only one GIF renderer at a time.  This small
advisory lock is shared by generated Weather/Dashboard/Performance scenes and
explicit SteamGridDB conversions.  It never owns the serial port.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import threading
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - SteamOS is POSIX
    fcntl = None


class FaceplateRenderBusy(RuntimeError):
    pass


_FALLBACK_LOCK = threading.Lock()


def default_render_lock_path() -> Path:
    override = os.environ.get("GABECUBEAURA_FACEPLATE_RENDER_LOCK")
    if override:
        return Path(override)
    decky_home = os.environ.get("DECKY_USER_HOME")
    if decky_home:
        return Path(decky_home) / ".local/state/gabecubeaura/faceplate-render.lock"
    # Developer/test processes may have a read-only home.  A per-user path in
    # the system temporary directory still coordinates every child process.
    uid = os.getuid() if hasattr(os, "getuid") else os.getpid()
    return Path(tempfile.gettempdir()) / f"gabecubeaura-{uid}-faceplate-render.lock"


@contextmanager
def exclusive_render_lock(path=None, *, timeout=20.0, poll_interval=0.05):
    """Acquire the shared renderer lock or fail after a bounded wait."""
    timeout = max(0.0, float(timeout))
    deadline = time.monotonic() + timeout
    lock_path = Path(path) if path is not None else default_render_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # defensive local-development fallback
        acquired = _FALLBACK_LOCK.acquire(timeout=timeout)
        if not acquired:
            raise FaceplateRenderBusy("another Faceplate render is still running")
        try:
            yield lock_path
        finally:
            _FALLBACK_LOCK.release()
        return

    with lock_path.open("a+b") as stream:
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise FaceplateRenderBusy("another Faceplate render is still running")
                time.sleep(max(0.01, min(0.25, float(poll_interval))))
        try:
            yield lock_path
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
