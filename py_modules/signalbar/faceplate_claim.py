"""Explicit handoff to Eli Hodapp's Pixel Faceplate Decky plugin.

Pixel Faceplate recognizes a live claim in any Decky plugin settings folder.
Only an active GabeCubeAura Faceplate should hold this claim. A stale process
claim is ignored by Pixel Faceplate; a clean disable/unload releases it.

Adapted from hodapp's GabeCubeAura PR #5 (BSD-3-Clause).
"""
from __future__ import annotations

import json
import os

CLAIM_FILENAME = "faceplate-claim.json"


def claim(settings_dir: str) -> bool:
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
    path = os.path.join(settings_dir, CLAIM_FILENAME)
    try:
        with open(path, encoding="utf-8") as handle:
            if json.load(handle).get("pid") != os.getpid():
                return
        os.remove(path)
    except (OSError, ValueError, AttributeError):
        pass
