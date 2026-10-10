"""Speech to text, using NVIDIA's Parakeet through ONNX.

Parakeet normally runs on NeMo with CUDA, and the Steam Machine is all AMD, so
that's out. The onnx-asr package runs the same model on the CPU through
onnxruntime and is fast enough for a sentence or two. sherpa-onnx is the other
option if onnx-asr gives trouble.

Memory: Parakeet TDT 0.6B is about 1-2 GB once loaded. It loads on the first
wake after the plugin starts (or after a game ends) and gets dropped when a
game starts. The first question after that is slower while it loads. If that
turns out to be annoying, loading it right when the game closes is a one-line
change in assistant.py.

Ending the recording is the crude part. It stops after a stretch of quiet or
at listen_seconds, whichever comes first. Silero VAD would be the proper fix:
swap is_quiet() for a Silero call and keep the rest.

Written against the onnx-asr docs and not run on a Steam Machine yet.
"""

from __future__ import annotations

import math
import struct

from .mic import FRAME_SAMPLES, RATE

# RMS level, out of 32768, that counts as quiet. A guess. The first thing I'd
# do on real hardware is print the levels with the TV on and pick from there.
QUIET_RMS = 500


def is_quiet(frame):
    count = len(frame) // 2
    if not count:
        return True
    samples = struct.unpack(f"<{count}h", frame[:count * 2])
    return math.sqrt(sum(s * s for s in samples) / count) < QUIET_RMS


class Listener:
    def __init__(self, model_name, model_path="", listen_seconds=8.0, silence_seconds=0.8):
        self.model_name = model_name
        self.model_path = model_path or None
        self.listen_frames = int(listen_seconds * RATE / FRAME_SAMPLES)
        self.silence_frames = max(1, int(silence_seconds * RATE / FRAME_SAMPLES))
        self._model = None

    def load(self):
        if self._model is None:
            import onnx_asr
            self._model = onnx_asr.load_model(self.model_name, self.model_path)

    def unload(self):
        # Dropping the reference is enough for onnxruntime to free the session.
        self._model = None

    def record(self, mic, cancel):
        """Collect frames until the speaker goes quiet. Returns raw int16 bytes."""
        frames = []
        quiet = 0
        heard_something = False
        while len(frames) < self.listen_frames and not cancel.is_set():
            frame = mic.read_frame()
            if frame is None:
                break
            frames.append(frame)
            if is_quiet(frame):
                quiet += 1
            else:
                quiet = 0
                heard_something = True
            # Wait for actual speech before the quiet timer counts, so a slow
            # start after "hey Gabe" doesn't end the turn early.
            if heard_something and quiet >= self.silence_frames:
                break
        return b"".join(frames) if heard_something else b""

    def transcribe(self, audio):
        if not audio:
            return ""
        import numpy as np
        self.load()
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        return str(self._model.recognize(samples, sample_rate=RATE) or "").strip()

    def listen(self, mic, cancel):
        return self.transcribe(self.record(mic, cancel))
