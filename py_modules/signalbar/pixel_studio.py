"""Compatibility cleanup for the retired standalone Pixel Studio companion.

Pixel Studio now lives entirely inside Decky. Historical component sources
remain in the repository for research, but Lab runtime bundles no longer ship
them and the active plugin removes any prior managed installation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import threading
import time
from urllib.request import Request, urlopen
from uuid import uuid4


COMPONENTS = ("faceplate-service", "pixel-studio")
HOST = "127.0.0.1"
PORT = 39054
URL = f"http://{HOST}:{PORT}/"
MAX_LOG_BYTES = 256 * 1024


class PixelStudioError(RuntimeError):
    pass


def _read_component(path: Path):
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _component_version(root: Path, component: str):
    value = _read_component(root / component / "component.json")
    if value.get("id") != component or value.get("product") != "GabeCubeAura":
        return ""
    return str(value.get("version", ""))


class PixelStudioManager:
    """Own bootstrap, status and local-service startup for Pixel Studio."""

    def __init__(self, plugin_dir: str, user_home: str, version: str, logger,
                 *, popen=subprocess.Popen, sleep=time.sleep, health_probe=None,
                 proc_root=Path("/proc")):
        self.plugin_dir = Path(plugin_dir).resolve()
        self.user_home = Path(user_home or "/home/deck").resolve()
        self.version = str(version)
        self.logger = logger
        self.component_root = (
            self.user_home / ".local/share/gabecubeaura/components"
        ).resolve()
        self.applications_dir = (self.user_home / ".local/share/applications").resolve()
        self.desktop_path = self.applications_dir / "gabecubeaura-pixel-studio.desktop"
        self.state_dir = (self.user_home / ".local/state/gabecubeaura").resolve()
        self.game_state_path = self.state_dir / "pixel-studio-game.json"
        self._popen = popen
        self._sleep = sleep
        self._health_probe = health_probe or self._probe_health
        self._proc_root = Path(proc_root)
        self._lock = threading.RLock()
        self._process = None
        self.last_brightness = 100
        self.last_error = ""

    def _log(self, level: str, message: str):
        callback = getattr(self.logger, level, None)
        if callable(callback):
            callback(f"[GabeCubeAura] Pixel Studio: {message}")

    def _service_environment(self):
        """Detach the companion from Decky's injected Python/runtime paths."""
        environment = dict(os.environ)
        for name in ("LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
            environment.pop(name, None)
        # An empty value is safer than inheriting Decky's private shared-object
        # directory into the system Python process.
        environment["LD_LIBRARY_PATH"] = ""
        environment["HOME"] = str(self.user_home)
        environment["DECKY_USER_HOME"] = str(self.user_home)
        environment["PYTHONUNBUFFERED"] = "1"
        return environment

    def _prepare_log_path(self):
        """Keep the crash log useful without allowing it to grow forever."""
        log_path = self.state_dir / "pixel-studio.log"
        previous = self.state_dir / "pixel-studio.previous.log"
        try:
            if log_path.stat().st_size >= MAX_LOG_BYTES:
                previous.unlink(missing_ok=True)
                os.replace(log_path, previous)
                os.chmod(previous, 0o600)
        except OSError:
            pass
        return log_path

    def _source_root(self):
        return self.plugin_dir / "components"

    def _validate_source(self):
        source_root = self._source_root()
        for component in COMPONENTS:
            source = source_root / component
            if source.is_symlink() or not source.is_dir():
                raise PixelStudioError(f"embedded {component} component is missing")
            if _component_version(source_root, component) != self.version:
                raise PixelStudioError(f"embedded {component} version does not match")
        service = source_root / "faceplate-service"
        studio = source_root / "pixel-studio"
        for required in (
            service / "server.py",
            service / "launch-pixel-studio.sh",
            studio / "index.html",
            studio / "app.js",
        ):
            if not required.is_file() or required.is_symlink():
                raise PixelStudioError(f"embedded file is missing: {required.name}")
        return source_root

    def _set_permissions(self):
        executables = {"server.py", "launch-pixel-studio.sh"}
        for component in COMPONENTS:
            root = self.component_root / component
            for directory, subdirectories, files in os.walk(root):
                os.chmod(directory, 0o755)
                for name in subdirectories:
                    os.chmod(Path(directory) / name, 0o755)
                for name in files:
                    os.chmod(Path(directory) / name, 0o755 if name in executables else 0o644)

    def installed(self):
        return all(
            _component_version(self.component_root, item) == self.version
            for item in COMPONENTS
        )

    def ensure_installed(self, force=False):
        """Install embedded companions atomically enough to recover both together."""
        with self._lock:
            try:
                source_root = self._validate_source()
                if not force and self.installed():
                    self.desktop_path.unlink(missing_ok=True)
                    self.last_error = ""
                    return self.status()
                self.component_root.mkdir(parents=True, mode=0o755, exist_ok=True)
                token = uuid4().hex
                staging = self.component_root / f".bootstrap-{token}"
                rollback = self.component_root / f".rollback-{token}"
                staging.mkdir(mode=0o700)
                installed = []
                try:
                    for component in COMPONENTS:
                        shutil.copytree(source_root / component, staging / component, symlinks=False)
                    rollback.mkdir(mode=0o700)
                    for component in COMPONENTS:
                        active = self.component_root / component
                        previous = rollback / component
                        if active.exists():
                            if active.is_symlink() or not active.is_dir():
                                raise PixelStudioError(f"installed {component} path is unsafe")
                            os.replace(active, previous)
                        os.replace(staging / component, active)
                        installed.append(component)
                    self._set_permissions()
                    self.desktop_path.unlink(missing_ok=True)
                except Exception:
                    for component in reversed(installed):
                        active = self.component_root / component
                        previous = rollback / component
                        if active.exists():
                            shutil.rmtree(active)
                        if previous.exists():
                            os.replace(previous, active)
                    raise
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
                    shutil.rmtree(rollback, ignore_errors=True)
                self.last_error = ""
                self._log("info", f"retained dormant rollback components {self.version}")
            except Exception as error:
                self.last_error = str(error)[:180] or type(error).__name__
                self._log("warning", f"bootstrap failed: {self.last_error}")
            return self.status()

    def _probe_health(self):
        try:
            request = Request(URL + "api/v1/health", headers={"Cache-Control": "no-store"})
            with urlopen(request, timeout=0.4) as response:
                if response.status != 200 or int(response.headers.get("Content-Length", "0")) > 4096:
                    return {"running": False, "version": ""}
                value = json.loads(response.read(4096).decode("utf-8"))
                return {
                    "running": bool(value.get("ok")),
                    "version": str(value.get("version", "")),
                }
        except Exception:
            return {"running": False, "version": ""}

    @staticmethod
    def _port_busy():
        try:
            with socket.create_connection((HOST, PORT), timeout=0.2):
                return True
        except OSError:
            return False

    def status(self, probe=True):
        versions = {item: _component_version(self.component_root, item) for item in COMPONENTS}
        installed = all(value == self.version for value in versions.values())
        return {
            "schema": 1,
            "version": self.version,
            "standalone_enabled": False,
            "installed": installed,
            "desktop_launcher": False,
            "service_running": False,
            "service_version": "",
            "url": URL,
            "components": versions,
            "brightness": self.last_brightness,
            "error": self.last_error,
        }

    def _managed_service_pids(self):
        """Find only our exact retired server command, never a generic Python job."""
        expected = str((self.component_root / "faceplate-service/server.py").resolve())
        try:
            entries = tuple(self._proc_root.iterdir())
        except OSError:
            return []
        result = []
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == os.getpid():
                continue
            try:
                argv = [
                    value.decode("utf-8", errors="replace")
                    for value in (entry / "cmdline").read_bytes().split(b"\0")
                    if value
                ]
            except OSError:
                continue
            if expected in argv and "--studio" in argv:
                result.append(pid)
        return result

    def disable_standalone(self):
        """Remove the launcher and stop only a matching legacy local service."""
        with self._lock:
            self.desktop_path.unlink(missing_ok=True)
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                except (AttributeError, OSError):
                    pass
            self._process = None
            stopped = []
            for pid in self._managed_service_pids():
                try:
                    os.kill(pid, signal.SIGTERM)
                    stopped.append(pid)
                except OSError:
                    continue
            for component in COMPONENTS:
                target = self.component_root / component
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target, ignore_errors=True)
            self.last_error = ""
            if stopped:
                self._log("info", "stopped retired standalone Pixel Studio service")
            return self.status(probe=False)

    def set_current_game(self, game):
        """Expose only the active app identity to the loopback Studio service."""
        try:
            appid = max(0, int((game or {}).get("appid", 0) or 0))
        except (TypeError, ValueError, OverflowError, AttributeError):
            appid = 0
        title = str((game or {}).get("title", "") if isinstance(game, dict) else "")[:160]
        self.state_dir.mkdir(parents=True, mode=0o755, exist_ok=True)
        temporary = self.game_state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "schema": 1, "appid": appid, "title": title,
        }, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, self.game_state_path)
        return {"appid": appid, "title": title}

    def start(self):
        self.disable_standalone()
        self.last_error = "Standalone Pixel Studio is retired; use the Decky Pixel Studio pages"
        result = self.status(probe=False)
        result["started"] = False
        return result

    def set_brightness(self, value):
        self.last_brightness = max(5, min(100, int(value)))
        self.last_error = ""
        return self.status(probe=False)

    def uninstall(self):
        """Remove only managed companion paths during an explicit plugin uninstall."""
        with self._lock:
            self.desktop_path.unlink(missing_ok=True)
            for component in COMPONENTS:
                target = self.component_root / component
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
