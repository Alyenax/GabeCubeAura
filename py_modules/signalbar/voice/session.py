"""Run a command as the logged-in user instead of root.

GabeCubeAura runs as root, but the mic, the speakers and llama-server all
belong to the user's session. PipeWire in particular hands a root client a
different view of the graph, which Audio Sync already found out the hard way,
so this borrows the same runtime-dir lookup and runuser wrapping it uses.
"""

from __future__ import annotations

import os

from signalbar.providers.screen_sync import ScreenCaptureService


def user_command(command):
    """Return (command, env) for running ``command`` in the user's session."""
    runtime_dirs = ScreenCaptureService._runtime_dirs()
    if not runtime_dirs:
        raise RuntimeError("no PipeWire session found")
    # Same order Audio Sync uses: a real user's session before root's.
    runtime_dir = sorted(
        runtime_dirs,
        key=lambda path: (
            (ScreenCaptureService._runtime_owner(path) or (0, ""))[0] == 0, path,
        ),
    )[0]
    wrapped, _identity = ScreenCaptureService._command_for_runtime(command, runtime_dir)
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = runtime_dir
    return wrapped, env
