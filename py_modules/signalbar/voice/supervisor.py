"""The plugin's half of the voice assistant.

The models run in their own process (see __main__.py) because Decky's Python
can't load them. This side is small on purpose: start that process with the
venv's Python, tell it when a game starts or stops, put its moods on the
faceplate, and start it again if it dies. It imports nothing heavier than
the standard library, so the plugin's start-up doesn't notice it.

When a game starts we send {"game": true} and the voice process lets go of
the mic and unloads Qwen and Parakeet itself. What's left is a Python process
with openWakeWord loaded, which is small. If that still turns out to cost a
game anything, stopping the whole process on game start and starting it
again after is a few lines here.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time

from . import config
from .face import NoFace, for_faceplate

# Wait this long before the first restart after a crash, doubling each time
# up to the cap, so a voice process that dies on start doesn't spin.
BACKOFF_START = 5.0
BACKOFF_MAX = 300.0
# A run this long counts as healthy, and the next crash starts the wait over.
HEALTHY_SECONDS = 60.0
# The voice process's stderr goes here. Started fresh once it passes this.
LOG_LIMIT = 1024 * 1024
# py_modules, so the venv's Python can import signalbar.voice from the plugin.
PY_MODULES = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class VoiceOff:
    """Stand-in when the assistant is off or can't run. Does nothing, quietly."""

    state = "off"

    def __init__(self, reason=""):
        self.reason = reason

    def start(self):
        pass

    def stop(self):
        pass

    def set_game(self, appid=0, title=""):
        pass

    def status(self):
        return {"state": self.state, "reason": self.reason}


def user_command(command):
    """Return (command, env) for running ``command`` as the logged-in user.

    GabeCubeAura runs as root, but the mic, the speakers and the venv belong to
    the user's session, and PipeWire shows a root client a different graph.
    Audio Sync already solved that, so this borrows its lookup.
    """
    from signalbar.providers.screen_sync import ScreenCaptureService
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


class Supervisor:
    def __init__(self, settings_dir, python, face=None, logger=None,
                 popen=subprocess.Popen, command_for=user_command):
        self.settings_dir = settings_dir
        self.python = python
        self.face = face or NoFace()
        self.log = logger
        self.state = "starting"
        self.off_reason = ""
        self._popen = popen
        self._command_for = command_for
        self._game = False
        self._child = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _info(self, message):
        if self.log:
            self.log.info(f"[GabeCubeAura] voice: {message}")

    def _warn(self, message):
        if self.log:
            self.log.warning(f"[GabeCubeAura] voice: {message}")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gabecubeaura-voice", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            child = self._child
        if child is not None:
            # Closing stdin is the "stop" message. The voice process unloads
            # everything and exits on its own if it gets the chance.
            try:
                child.stdin.close()
                child.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                child.kill()
        if self._thread:
            self._thread.join(timeout=2)
        self.face.show("idle")

    def set_game(self, appid=0, title=""):
        self._game = int(appid or 0) > 0 or bool(title)
        self.send({"game": self._game})

    def send(self, message):
        with self._lock:
            child = self._child
        if child is None or child.stdin is None:
            return
        try:
            child.stdin.write(json.dumps(message) + "\n")
            child.stdin.flush()
        except (OSError, ValueError):
            pass  # it died; _run notices and restarts it

    def handle_line(self, raw):
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if message.get("state"):
            self.state = str(message["state"])
        if message.get("mood"):
            self.face.show(str(message["mood"]))
        if message.get("log"):
            level = "warning" if message.get("level") == "warning" else "info"
            (self._warn if level == "warning" else self._info)(str(message["log"]))
        if message.get("off"):
            self.off_reason = str(message["off"])
            self.state = "off"
            self._warn(f"assistant off: {self.off_reason}")

    def status(self):
        return {"state": self.state, "reason": self.off_reason}

    def _spawn(self):
        command, env = self._command_for(
            [self.python, "-m", "signalbar.voice", self.settings_dir],
        )
        env["PYTHONPATH"] = PY_MODULES
        # The plugin folder belongs to root, so don't try writing .pyc files.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        log_path = os.path.join(self.settings_dir, "voice.log")
        try:
            mode = "wb" if os.path.getsize(log_path) > LOG_LIMIT else "ab"
        except OSError:
            mode = "ab"
        with open(log_path, mode) as log:
            return self._popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                env=env, text=True, bufsize=1,
            )

    def _run(self):
        backoff = BACKOFF_START
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                child = self._spawn()
            except Exception as error:
                child = None
                self._warn(f"couldn't start the voice process: {type(error).__name__}: {error}")
            if child is not None:
                with self._lock:
                    self._child = child
                self.send({"game": self._game})
                for raw in child.stdout:
                    self.handle_line(raw)
                code = child.wait()
                with self._lock:
                    self._child = None
                if self._stop.is_set() or self.off_reason:
                    return
                if time.monotonic() - started > HEALTHY_SECONDS:
                    backoff = BACKOFF_START
                self._warn(f"voice process exited with {code}, restarting in {backoff:.0f} s")
            self._stop.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


def build(settings_dir, faceplate=None, logger=None):
    """Return a Supervisor ready to start, or VoiceOff with the reason it's off."""
    try:
        values = config.load(settings_dir)
        if not values["enabled"]:
            return VoiceOff("off in voice.json")
        python = str(values["python"])
        if not os.path.isfile(python):
            if logger:
                logger.warning(f"[GabeCubeAura] voice assistant off: no Python at {python}")
            return VoiceOff("no Python at " + python)
        face = for_faceplate(faceplate, values["faces_dir"], logger)
        return Supervisor(settings_dir, python, face, logger)
    except Exception as error:
        if logger:
            logger.warning(f"[GabeCubeAura] voice assistant off: {type(error).__name__}: {error}")
        return VoiceOff(str(error))
