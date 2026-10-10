"""Text to speech, using Piper, played with pw-play.

Piper runs on the CPU, takes about 60-100 MB with a medium voice and is quick
enough that a sentence is ready before you'd notice a pause. It writes a WAV and
pw-play plays it through whatever PipeWire's default output is, which on a
Steam Machine is usually the TV over HDMI.

Speaking one whole answer at a time is the simple version. Streaming
sentence by sentence while Qwen is still writing would feel snappier and is
the obvious next step.

Written against Piper's README and not run on a Steam Machine yet.
"""

from __future__ import annotations

import os
import subprocess
import tempfile


class Voice:
    def __init__(self, binary, voice, run=subprocess.run):
        self.binary = binary
        self.voice = voice
        self._run = run

    def say(self, text, cancel):
        if not text or cancel.is_set():
            return
        handle, wav = tempfile.mkstemp(prefix="gabecubeaura-voice-", suffix=".wav")
        os.close(handle)
        try:
            self._run([self.binary, "--model", self.voice, "--output_file", wav],
                      input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, timeout=30, check=True)
            if cancel.is_set():
                return
            # A game starting mid-sentence doesn't cut this off yet. Using
            # Popen and killing it on cancel would.
            self._run(["pw-play", wav], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, timeout=60, check=False)
        finally:
            try:
                os.unlink(wav)
            except OSError:
                pass
