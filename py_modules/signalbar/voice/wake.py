"""Wake word, using openWakeWord.

openWakeWord scores every 80 ms frame from 0 to 1 for each model it has
loaded. Over the threshold means someone said it. The model is tiny and runs
on the CPU without anyone noticing, which is the whole reason it gets to run
all the time while the bigger models wait.

The stock "hey_jarvis" model is there for testing. For "hey Gabe" you train
your own with the notebook in the openWakeWord repo and point wake_word at
the .onnx it gives you. I'd expect a homemade model to need its threshold
tuned against a real living room with the TV on.

Written against the openWakeWord docs and not run on a Steam Machine yet.
"""

from __future__ import annotations

import time

# One "hey Gabe" usually scores high on several frames in a row. Ignore the
# rest of them, or one phrase wakes it up three times.
COOLDOWN_SECONDS = 2.0


class WakeWord:
    def __init__(self, name, threshold=0.5, clock=time.monotonic):
        self.name = name
        self.threshold = float(threshold)
        self._clock = clock
        self._model = None
        self._last_fired = -COOLDOWN_SECONDS

    def load(self):
        """Load the model. Deferred until the loop starts so plugin start stays quick."""
        if self._model is not None:
            return
        from openwakeword.model import Model
        # The ONNX runtime is already here for Parakeet, so use it instead of
        # pulling in tflite as well. Stock model names need a one-off
        # openwakeword.utils.download_models() during setup, see docs/VOICE.md.
        self._model = Model(wakeword_models=[self.name], inference_framework="onnx")

    def heard(self, frame):
        """Feed one 80 ms frame of int16 bytes. True when the wake word fires."""
        import numpy as np
        self.load()
        scores = self._model.predict(np.frombuffer(frame, dtype=np.int16))
        now = self._clock()
        if max(scores.values(), default=0.0) < self.threshold:
            return False
        if now - self._last_fired < COOLDOWN_SECONDS:
            return False
        self._last_fired = now
        # Clear the model's rolling buffer so the tail of this phrase doesn't
        # trigger it again straight after the answer.
        self._model.reset()
        return True
