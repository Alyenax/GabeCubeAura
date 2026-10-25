# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
#!/usr/bin/env python3
"""Isolated low-priority compiler used only by an explicit Pixel Studio job."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time


PY_MODULES = Path(__file__).resolve().parents[2]
if str(PY_MODULES) not in sys.path:
    sys.path.insert(0, str(PY_MODULES))

from signalbar.faceplate.steamgriddb import SteamGridDBError, SteamGridDBFaceplate  # noqa: E402
from signalbar.faceplate.render_lock import (  # noqa: E402
    FaceplateRenderBusy, exclusive_render_lock,
)


def _write(path, value):
    value = {**value, "updated_at": time.time()}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def _game_state_path():
    home = Path(os.environ.get("DECKY_USER_HOME") or Path.home())
    return home / ".local/state/gabecubeaura/pixel-studio-game.json"


def _game_running():
    try:
        path = _game_state_path()
        if not path.is_file() or path.stat().st_size > 4096:
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
        return int(value.get("appid", 0) or 0) > 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _watch_for_game(stop):
    """Abort this worker and its decoder if a Steam game starts mid-job."""
    while not stop.wait(0.25):
        if not _game_running():
            continue
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpgrp(), signal.SIGTERM)
        else:  # defensive fallback for direct developer invocation
            os.kill(os.getpid(), signal.SIGTERM)
        return


def main(argv):
    if len(argv) != 4:
        return 64
    root, request_path, progress_path = Path(argv[1]), Path(argv[2]), Path(argv[3])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        appid = int(request["appid"])
        mode = str(request["mode"])
        asset = request["asset"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 64
    base = {"schema": 1, "job_id": request.get("job_id", ""), "appid": appid,
            "mode": mode, "state": "running", "percent": 2}
    _write(progress_path, {**base, "stage": "starting", "detail": "Starting isolated worker"})
    animation = mode != "static"
    if animation and _game_running():
        _write(progress_path, {**base, "state": "cancelled", "percent": 0,
                               "stage": "cancelled", "detail": "A game is running"})
        return 3
    watchdog_stop = threading.Event()
    watchdog = threading.Thread(
        target=_watch_for_game, args=(watchdog_stop,), daemon=True,
        name="faceplate-preparation-game-watchdog",
    )
    if animation:
        watchdog.start()
    latest = {**base, "percent": 1, "stage": "waiting"}

    def progress(percent, stage, detail):
        latest.update({"percent": int(percent), "stage": stage, "detail": detail})
        _write(progress_path, latest)

    try:
        library = SteamGridDBFaceplate(root)
        progress(1, "waiting", "Waiting for the shared Faceplate renderer")
        with exclusive_render_lock(timeout=30.0):
            selected = library.prepare_choice(
                appid, asset, mode,
                crop_x=request.get("crop_x", 50),
                crop_y=request.get("crop_y", 50),
                saturation=request.get("saturation", 110),
                brightness=request.get("brightness", 100),
                loop_cleanup=request.get("loop_cleanup", "no"),
                art_style=request.get("art_style", "art"),
                logo_position=request.get("logo_position", "bottom"),
                logo_scale=request.get("logo_scale", 100),
                dashboard_treatment=request.get("dashboard_treatment", "none"),
                dashboard_compression=request.get(
                    "dashboard_compression", "compatible",
                ),
                dashboard_show_clock=request.get("dashboard_show_clock"),
                dashboard_clock_size=request.get("dashboard_clock_size", "large"),
                dashboard_show_session=request.get("dashboard_show_session", True),
                dashboard_show_battery=request.get("dashboard_show_battery", True),
                progress=progress,
                draft=bool(request.get("draft", False)),
            )
        _write(progress_path, {**base, "state": "ready", "percent": 100,
                               "stage": "ready", "detail": "Ready to activate",
                               "prepared": selected})
        return 0
    except (FaceplateRenderBusy, SteamGridDBError, OSError, ValueError, TypeError) as error:
        _write(progress_path, {**latest, "state": "failed",
                               "detail": str(error)[:240]})
        return 1
    finally:
        watchdog_stop.set()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
