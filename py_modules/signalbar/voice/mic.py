"""The USB microphone, read through pw-record.

pw-record ships with SteamOS, so this needs nothing installed to get audio in.
It writes raw 16-bit mono samples to stdout and we read them in 80 ms frames.

Why 16 kHz mono: openWakeWord and Parakeet were both trained on 16 kHz speech,
so recording at anything else just means resampling later. PipeWire does the
conversion for us if the mic runs at 48 kHz natively.

Why 1280 samples: that's 80 ms at 16 kHz, the frame size openWakeWord expects.
Parakeet doesn't care. It gets the frames glued back together.

The Steam Machine doesn't have a mic as far as I know, so this assumes a USB
one is plugged in and is PipeWire's default source. If you have more than one,
set the default in Desktop Mode or add --target to the command below.
arecord would work as a fallback too. I just haven't needed it.
"""

from __future__ import annotations

import subprocess

RATE = 16000
FRAME_SAMPLES = 1280
FRAME_BYTES = FRAME_SAMPLES * 2


class Microphone:
    def __init__(self, popen=subprocess.Popen):
        self._popen = popen
        self._process = None

    def open(self):
        if self._process and self._process.poll() is None:
            return
        self._process = self._popen(
            ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, bufsize=0,
        )

    def read_frame(self):
        """Return one 80 ms frame as bytes, or None if the mic isn't running."""
        process = self._process
        if process is None or process.stdout is None:
            return None
        data = b""
        while len(data) < FRAME_BYTES:
            chunk = process.stdout.read(FRAME_BYTES - len(data))
            if not chunk:
                return None  # pw-record went away, the loop reopens it
            data += chunk
        return data

    def close(self):
        """Stop recording. Called when a game starts so we're not holding the
        mic while someone's on voice chat."""
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
