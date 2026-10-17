"""Tell the standalone Pixel Faceplate plugin that GabeCubeAura drives the faceplate.

Pixel Faceplate (https://github.com/hodapp/pixel-faceplate) 0.2.1 and later
looks in every Decky plugin settings folder for ``faceplate-claim.json``. While
the file names a live GabeCubeAura process it closes the serial port, stops
sending pictures and asks the user to uninstall it. Claim when GabeCubeAura
starts driving the panel and release when it stops; a claim left behind by a
crash is ignored because its process is gone.
"""

from __future__ import annotations

import json
import os

CLAIM_FILENAME = "faceplate-claim.json"


def claim(settings_dir: str) -> bool:
    """Write the claim atomically; False if the settings folder is not writable."""
    path = os.path.join(settings_dir, CLAIM_FILENAME)
    temporary = path + ".tmp"
    try:
        os.makedirs(settings_dir, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"plugin": "GabeCubeAura", "pid": os.getpid()}, handle)
        os.replace(temporary, path)
        return True
    except OSError:
        return False


def release(settings_dir: str) -> None:
    """Remove the claim, but only if this process wrote it."""
    path = os.path.join(settings_dir, CLAIM_FILENAME)
    try:
        with open(path, encoding="utf-8") as handle:
            if json.load(handle).get("pid") != os.getpid():
                return
        os.remove(path)
    except (OSError, ValueError, AttributeError):
        pass
