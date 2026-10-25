# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Host-side launcher for the isolated Faceplate scene renderer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


class FaceplateRenderError(RuntimeError):
    pass


def _renderer_environment():
    """Return an environment detached from Decky's bundled Python runtime."""
    environment = dict(os.environ)
    for name in ("LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    # Decky's loader libraries are not compatible with the system Python used
    # by the isolated renderer.  An explicit empty value also neutralizes a
    # value inherited through a wrapper process.
    environment["LD_LIBRARY_PATH"] = ""
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def render_isolated(request, *, temporary_root=None, timeout=30.0):
    """Return ``(gif, manifest)`` from a bounded low-priority child process."""
    root = Path(temporary_root) if temporary_root else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gabecubeaura-scene-", dir=root) as folder:
        folder = Path(folder)
        request_path = folder / "request.json"
        gif_path = folder / "scene.gif"
        result_path = folder / "result.json"
        request_path.write_text(
            json.dumps(dict(request), separators=(",", ":")), encoding="utf-8",
        )
        worker = Path(__file__).with_name("scene_process.py")
        environment = _renderer_environment()
        system_python = shutil.which("python3", path=environment.get("PATH"))
        if not system_python:
            raise FaceplateRenderError("system python3 is unavailable")
        command = [
            system_python, str(worker), str(request_path), str(gif_path),
            str(result_path),
        ]
        nice = shutil.which("nice", path=environment.get("PATH"))
        if nice:
            command = [nice, "-n", "10", *command]
        try:
            completed = subprocess.run(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=max(2.0, float(timeout)),
                check=False, env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FaceplateRenderError(f"isolated renderer failed: {error}") from error
        try:
            manifest = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            detail = completed.stderr.decode("utf-8", "replace")[:180]
            raise FaceplateRenderError(
                f"isolated renderer returned no result{': ' + detail if detail else ''}"
            ) from error
        if completed.returncode or not manifest.get("ok"):
            raise FaceplateRenderError(str(manifest.get("error") or "scene rendering failed")[:240])
        try:
            payload = gif_path.read_bytes()
        except OSError as error:
            raise FaceplateRenderError("isolated renderer produced no GIF") from error
        return payload, manifest
