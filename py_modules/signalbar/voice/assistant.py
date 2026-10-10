"""The loop that ties the voice pieces together.

One thread does all of it, in this order:

    idle       mic on, openWakeWord scoring every 80 ms frame
    curious    wake word heard: curious face, start warming Qwen
    listening  record until the person stops talking
    thinking   Parakeet turns that into text, Qwen writes a reply
    talking    Piper reads the reply out, talking face
    idle       back to the top

    paused     a game is running: mic closed, models unloaded

A game starting cancels whatever turn is in progress, closes the mic so we're
not fighting voice chat for it, and unloads Qwen and Parakeet so the game gets
the memory back. When the game ends we go back to idle and the models reload
the next time they're needed.

Any step that blows up gets logged and we drop back to idle. The plugin's
lights matter more than this does, so nothing in here is allowed to take the
plugin down with it.
"""

from __future__ import annotations

import sys
import threading

from . import config
from .face import NoFace, for_faceplate


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


class Assistant:
    def __init__(self, mic, wake, ears, brain, voice, face=None, warm="on_wake", logger=None):
        self.mic = mic
        self.wake = wake
        self.ears = ears
        self.brain = brain
        self.voice = voice
        self.face = face or NoFace()
        self.warm = warm
        self.log = logger
        self.state = "idle"
        self.last_heard = ""
        self.last_reply = ""
        self._game_running = False
        self._cancel = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def _info(self, message):
        if self.log:
            self.log.info(f"[GabeCubeAura] voice: {message}")

    def _warn(self, message):
        if self.log:
            self.log.warning(f"[GabeCubeAura] voice: {message}")

    def _enter(self, state, mood=None):
        self.state = state
        if mood:
            self.face.show(mood)

    # ---- lifecycle -----------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gabecubeaura-voice", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._cancel.set()
        self.mic.close()
        if self._thread:
            self._thread.join(timeout=3)
        self._unload()
        self.face.show("idle")

    def set_game(self, appid=0, title=""):
        """Called from game_changed. A running game pauses everything."""
        running = int(appid or 0) > 0 or bool(title)
        if running == self._game_running:
            return
        self._game_running = running
        if running:
            self._cancel.set()
            self.mic.close()
            self._unload()
            self._enter("paused", "idle")
            self._info("game started, paused and unloaded")
        else:
            # A fresh event, so a turn still winding down from before the
            # game keeps seeing its own cancel.
            self._cancel = threading.Event()
            self._enter("idle", "idle")
            if self.warm == "resident":
                self.brain.warm_up()

    def _unload(self):
        for part in (self.brain, self.ears):
            try:
                part.unload()
            except Exception as error:
                self._warn(f"unload failed: {type(error).__name__}: {error}")

    def status(self):
        return {"state": self.state, "heard": self.last_heard, "reply": self.last_reply}

    # ---- the loop ------------------------------------------------------
    def _run(self):
        if self.warm == "resident" and not self._game_running:
            self.brain.warm_up()
        while not self._stop.is_set():
            if self._game_running:
                self._stop.wait(0.5)
                continue
            try:
                self.mic.open()
                frame = self.mic.read_frame()
                if frame is None:
                    self._stop.wait(1.0)  # mic unplugged or pw-record died; retry
                    continue
                if self.wake.heard(frame):
                    self.turn()
            except Exception as error:
                self._warn(f"{type(error).__name__}: {error}")
                self._enter("idle", "idle")
                self._stop.wait(2.0)

    def turn(self):
        """One wake word to one answer. Each step checks whether a game started."""
        cancel = self._cancel
        self._enter("curious", "curious")
        # Warm on wake: the model loads while the person is still talking.
        if self.warm == "on_wake":
            self.brain.warm_up()
        self._enter("listening")
        text = self.ears.listen(self.mic, cancel)
        if cancel.is_set() or not text:
            return self._finish(cancel)
        self.last_heard = text
        self._enter("thinking", "thinking")
        reply = self.brain.ask(text, cancel)
        if cancel.is_set() or not reply:
            return self._finish(cancel)
        self.last_reply = reply
        self._enter("talking", "talking")
        self.voice.say(reply, cancel)
        return self._finish(cancel)

    def _finish(self, cancel):
        if not cancel.is_set():
            self._enter("idle", "idle")
        return self.state


def build(settings_dir, faceplate=None, logger=None, find_missing=config.missing):
    """Return an Assistant ready to start, or VoiceOff with the reason it's off."""
    try:
        values = config.load(settings_dir)
        if not values["enabled"]:
            return VoiceOff("off in voice.json")
        for path in values["python_path"] or []:
            if isinstance(path, str) and path not in sys.path:
                sys.path.append(path)
        gaps = find_missing(values)
        if gaps:
            reason = "missing " + ", ".join(gaps)
            if logger:
                logger.warning(f"[GabeCubeAura] voice assistant off: {reason}")
            return VoiceOff(reason)
        # Imported here so a disabled assistant never even loads these files.
        from .brain import Brain
        from .listen import Listener
        from .mic import Microphone
        from .speak import Voice
        from .wake import WakeWord
        return Assistant(
            Microphone(),
            WakeWord(values["wake_word"], values["wake_threshold"]),
            Listener(values["stt_model"], values["stt_path"],
                     values["listen_seconds"], values["silence_seconds"]),
            Brain(values["llm_server"], values["llm_model"], values["llm_port"],
                  values["llm_gpu_layers"], values["llm_context"],
                  values["llm_system_prompt"], logger),
            Voice(values["tts_binary"], values["tts_voice"]),
            for_faceplate(faceplate, values["faces_dir"], logger),
            values["warm"],
            logger,
        )
    except Exception as error:
        if logger:
            logger.warning(f"[GabeCubeAura] voice assistant off: {type(error).__name__}: {error}")
        return VoiceOff(str(error))
