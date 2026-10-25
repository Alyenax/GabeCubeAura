# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""One explicit, low-priority SteamGridDB preparation job for Decky UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from uuid import uuid4

from .artwork import clean_environment
from .steamgriddb import SteamGridDBError


def _read_json(path):
    try:
        if not path or not path.is_file() or path.stat().st_size > 64 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_json(path, value):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


class ArtworkPreparationJobs:
    """Supervise one latest explicit compiler without blocking Decky's RPC loop."""

    def __init__(self, library, current_game, logger=None):
        self.library = library
        self.current_game = current_game
        self.logger = logger
        self.root = library.root / "jobs"
        self.lock = threading.RLock()
        self.process = None
        self.job_id = ""
        # Preserve the newest terminal progress across a Decky/plugin restart.
        # This is intentionally a one-time, read-only scan; status polling never
        # walks the jobs directory.
        self.progress_path = self._latest_progress_path()

    def _latest_progress_path(self):
        latest_path = None
        latest_mtime = -1.0
        try:
            with os.scandir(self.root) as entries:
                for entry in entries:
                    if not entry.name.endswith(".progress.json"):
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.st_size > 64 * 1024 or stat.st_mtime <= latest_mtime:
                        continue
                    latest_path = Path(entry.path)
                    latest_mtime = stat.st_mtime
        except OSError:
            return None
        return latest_path

    def _log(self, level, message):
        callback = getattr(self.logger, level, None)
        if callable(callback):
            callback("[GabeCubeAura Faceplate Artwork] " + str(message))

    def status(self):
        with self.lock:
            progress = _read_json(self.progress_path)
            running = self.process is not None and self.process.poll() is None
            if not running and self.process is None and progress.get('state') in {'queued', 'running', 'cancelling'}:
                # Persisted progress is not evidence of a live owned process.
                progress.update(state='failed', stage='interrupted',
                    detail='Preparation interrupted; prepare again', updated_at=time.time())
                _write_json(self.progress_path, progress)
            if not progress:
                return {"state": "idle", "percent": 0, "stage": "idle", "detail": ""}
            if running and progress.get("state") not in {"cancelling", "cancelled"}:
                progress["state"] = "running"
            return progress

    def start(self, request):
        with self.lock:
            if request.get("mode") != "static" and int(self.current_game().get("appid", 0) or 0) > 0:
                raise SteamGridDBError("Quit the running game before preparing artwork")
            if self.process is not None and self.process.poll() is None:
                raise SteamGridDBError("Another faceplate preparation is already running")
            appid = int(request.get("appid", 0) or 0)
            asset_id = int(request.get("asset_id", 0) or 0)
            asset_kind = str(request.get("asset_kind", "grid"))
            mode = str(request.get("mode", ""))
            if appid <= 0 or mode not in {"static", "animated", "pan"}:
                raise SteamGridDBError("Invalid preparation request")
            asset = self.library._cached_asset(appid, asset_id, asset_kind)
            if asset is None:
                raise SteamGridDBError("Search again before preparing this artwork")
            if mode == "animated" and not asset.get("animated"):
                raise SteamGridDBError("Choose an animated SteamGridDB result")
            if mode in {"static", "pan"} and asset.get("animated"):
                raise SteamGridDBError("Choose a static SteamGridDB result")
            if mode == "pan" and asset.get("kind") != "hero":
                raise SteamGridDBError("The scrolling variant requires a horizontal hero")

            from .artwork_layout import validate_logo_scale
            logo_scale = validate_logo_scale(request.get("logo_scale", 100))
            job_id = uuid4().hex
            request_path = self.root / f"{job_id}.request.json"
            progress_path = self.root / f"{job_id}.progress.json"
            stderr_path = self.root / f"{job_id}.stderr.log"
            payload = {
                "schema": 1, "job_id": job_id, "appid": appid, "mode": mode,
                "asset": asset,
                "draft": bool(request.get("draft", False)),
                "crop_x": max(0, min(100, int(request.get("crop_x", 50)))),
                "crop_y": max(0, min(100, int(request.get("crop_y", 50)))),
                "saturation": max(0, min(200, int(request.get("saturation", 110)))),
                "brightness": max(50, min(150, int(request.get("brightness", 100)))),
                "art_style": str(request.get("art_style", "art")),
                "logo_position": str(request.get("logo_position", "bottom")),
                "logo_scale": logo_scale,
                "loop_cleanup": (
                    request.get("loop_cleanup")
                    if request.get("loop_cleanup") in {"no", "soft", "medium", "aggressive"}
                    else "no"
                ),
                "dashboard_treatment": str(
                    request.get("dashboard_treatment", "none")
                ),
                "dashboard_compression": (
                    request.get("dashboard_compression")
                    if request.get("dashboard_compression") in {
                        "compatible", "balanced", "fine",
                    }
                    else "compatible"
                ),
                "dashboard_show_clock": bool(
                    request.get("dashboard_show_clock", False)
                ),
                "dashboard_clock_size": (
                    request.get("dashboard_clock_size")
                    if request.get("dashboard_clock_size") in {"compact", "large"}
                    else "large"
                ),
                "dashboard_show_session": bool(
                    request.get("dashboard_show_session", True)
                ),
                "dashboard_show_battery": bool(
                    request.get("dashboard_show_battery", True)
                ),
            }
            _write_json(request_path, payload)
            _write_json(progress_path, {
                "schema": 1, "job_id": job_id, "appid": appid, "mode": mode,
                "state": "queued", "percent": 0, "stage": "queued",
                "detail": "Queued", "updated_at": time.time(),
            })
            environment = clean_environment()
            for name in ("LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
                environment.pop(name, None)
            environment["LD_LIBRARY_PATH"] = ""
            environment["PYTHONUNBUFFERED"] = "1"
            system_python = shutil.which("python3", path=environment.get("PATH"))
            if not system_python:
                raise SteamGridDBError("System python3 is unavailable")
            worker = Path(__file__).with_name("prepare_worker.py")
            command = [system_python, str(worker), str(self.library.root),
                       str(request_path), str(progress_path)]
            nice = shutil.which("nice", path=environment.get("PATH"))
            if nice:
                command = [nice, "-n", "10", *command]
            try:
                stderr_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                with stderr_path.open("wb") as stderr_stream:
                    process = subprocess.Popen(
                        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=stderr_stream, env=environment,
                        start_new_session=True, close_fds=True,
                    )
            except OSError as error:
                _write_json(progress_path, {
                    "schema": 1, "job_id": job_id, "appid": appid, "mode": mode,
                    "state": "failed", "percent": 0, "stage": "failed",
                    "detail": str(error)[:240], "updated_at": time.time(),
                })
                raise SteamGridDBError("Could not start the isolated compiler") from error
            self.process, self.job_id, self.progress_path = process, job_id, progress_path
            threading.Thread(
                target=self._monitor, args=(process, progress_path, stderr_path, mode != "static"), daemon=True,
                name="gabecubeaura-artwork-monitor",
            ).start()
            return self.status()

    @staticmethod
    def _terminate(process):
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1.5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass

    def _monitor(self, process, progress_path, stderr_path=None, cancel_on_game=True):
        cancelled_for_game = False
        while process.poll() is None:
            if cancel_on_game and int(self.current_game().get("appid", 0) or 0) > 0:
                cancelled_for_game = True
                self._terminate(process)
                break
            time.sleep(0.25)
        returncode = process.wait()
        with self.lock:
            current = _read_json(progress_path)
            if cancelled_for_game:
                current.update({
                    "state": "cancelled", "stage": "cancelled", "percent": 0,
                    "detail": "Cancelled because a game started",
                })
            elif returncode and current.get("state") not in {"failed", "cancelled"}:
                diagnostic = ""
                try:
                    diagnostic = stderr_path.read_text(
                        encoding="utf-8", errors="replace",
                    )[-500:].strip().replace("\n", " ")
                except OSError:
                    pass
                current.update({
                    "state": "failed",
                    "stage": str(current.get("stage") or "failed")[:32],
                    "percent": max(0, min(100, int(current.get("percent", 0) or 0))),
                    "detail": (
                        diagnostic[:240]
                        or f"Preparation worker exited with status {returncode}"
                    ),
                })
            current["updated_at"] = time.time()
            _write_json(progress_path, current)
            if self.process is process:
                self.process = None

    def cancel(self):
        with self.lock:
            process, progress_path = self.process, self.progress_path
            if process is None or process.poll() is not None:
                return self.status()
            current = _read_json(progress_path)
            current.update({
                "state": "cancelling", "stage": "cancelling", "detail": "Cancelling",
            })
            _write_json(progress_path, current)
        self._terminate(process)
        with self.lock:
            current = _read_json(progress_path)
            current.update({
                "state": "cancelled", "stage": "cancelled", "percent": 0,
                "detail": "Cancelled", "updated_at": time.time(),
            })
            _write_json(progress_path, current)
            if self.process is process:
                self.process = None
        return current
