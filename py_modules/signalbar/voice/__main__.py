"""The voice process: python -m signalbar.voice <settings folder>.

Why a separate process: Decky's loader is a frozen binary with Python 3.11
baked in, and SteamOS's own Python is 3.13. numpy and onnxruntime built for
one won't import into the other, so the models can't load inside the plugin.
Instead the plugin starts this with the venv's Python and talks to it over
stdin and stdout, one JSON object per line.

Plugin to us:  {"game": true}   a game started, pause and unload
               {"game": false}  back at the Home screen
               (stdin closing)  the plugin is going away, stop
Us to plugin:  {"state": "curious", "mood": "curious"}
               {"log": "...", "level": "info"}
               {"off": "missing openwakeword"}  can't run, don't restart me

stdout belongs to the protocol. Anything else, tracebacks included, goes to
stderr, which the plugin points at voice.log.
"""

from __future__ import annotations

import json
import sys
import threading

from . import config


class Lines:
    """Writes protocol lines. The loop thread and the stdin thread both send."""

    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, **message):
        with self._lock:
            self._stream.write(json.dumps(message) + "\n")
            self._stream.flush()

    # Enough of a logger for the pieces, which only call info and warning.
    def info(self, message):
        self.send(log=message, level="info")

    def warning(self, message):
        self.send(log=message, level="warning")


def make(values, lines):
    from .assistant import Assistant
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
              values["llm_system_prompt"], lines),
        Voice(values["tts_binary"], values["tts_voice"]),
        warm=values["warm"],
        logger=lines,
        report=lambda state, mood: lines.send(state=state, mood=mood),
    )


def main(argv=None, stdin=sys.stdin, stdout=sys.stdout):
    argv = sys.argv[1:] if argv is None else argv
    lines = Lines(stdout)
    values = config.load(argv[0] if argv else "")
    gaps = config.missing(values)
    if gaps:
        lines.send(off="missing " + ", ".join(gaps))
        return 0
    assistant = make(values, lines)
    assistant.start()
    for raw in stdin:
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        if isinstance(message, dict) and "game" in message:
            assistant.set_game(1 if message["game"] else 0)
    assistant.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
