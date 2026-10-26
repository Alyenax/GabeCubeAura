"""Explicit handoff to Eli Hodapp's Pixel Faceplate Decky plugin.

Pixel Faceplate recognizes a live claim in any Decky plugin settings folder.
Only an active GabeCubeAura Faceplate should hold this claim. A stale process
claim is ignored by Pixel Faceplate; a clean disable/unload releases it.

Adapted from hodapp's GabeCubeAura PR #5 (BSD-3-Clause).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading

CLAIM_FILENAME = "faceplate-claim.json"
_lock = threading.RLock()


def claim(settings_dir: str) -> bool:
    """Atomically publish the nonsecret claim for an unprivileged reader."""
    path = os.path.join(settings_dir, CLAIM_FILENAME)
    with _lock:
        temporary = None
        try:
            os.makedirs(settings_dir, exist_ok=True)
            # Never follow a pre-existing predictable .tmp path as root.
            fd, temporary = tempfile.mkstemp(prefix="." + CLAIM_FILENAME + ".",
                                             suffix=".tmp", dir=settings_dir)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"plugin": "GabeCubeAura", "pid": os.getpid()}, handle)
                handle.flush()
                # GCA runs as root; Pixel Faceplate runs as the Decky user.
                # Only plugin/PID are shared. Do not loosen settings folders
                # or private configuration/credential file permissions.
                os.fchmod(handle.fileno(), 0o644)
            os.replace(temporary, path)
            temporary = None
            return True
        except OSError:
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def release(settings_dir: str) -> None:
    """Remove this process's claim; leave a replacement process's alone."""
    path = os.path.join(settings_dir, CLAIM_FILENAME)
    with _lock:
        try:
            with open(path, encoding="utf-8") as handle:
                if json.load(handle).get("pid") != os.getpid():
                    return
            os.remove(path)
        except (OSError, ValueError, AttributeError):
            pass
