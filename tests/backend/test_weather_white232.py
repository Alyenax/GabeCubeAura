"""Approved white LED cycles and source-fixed Snow day reflection correction."""
import hashlib
import json
from pathlib import Path
import unittest
import numpy as np
from signalbar.providers.weather_sequences import weather_sequence
from signalbar.faceplate.weather_artwork import _backgrounds, WEATHER_ARTWORK_V2_THEME as THEME

ROOT = Path(__file__).resolve().parents[2]
APPROVAL = ROOT / 'tools/weather-winter-approval'

class WinterWhiteTests(unittest.TestCase):

    def test_day_ground_has_no_warm_spill_or_substituted_bright_band(self):
        for variant in (0, 1):
            frames = np.stack([np.frombuffer(frame, dtype=np.uint8).reshape(54, 64, 3)
                              for frame in _backgrounds(THEME, f'snow:{variant}', 'day')])
            self.assertTrue(np.all(frames[:, 28:, :, 0] <= frames[:, 28:, :, 2]))
            # The formerly projected light (native source ~212 luma) must be
            # subdued locally, rather than merely recoloured to bright white.
            luminance = frames @ np.array([.2126, .7152, .0722])
            self.assertLess(float(np.median(luminance[:, 30, 26:30])), 195)
            self.assertGreater(int(np.median(frames[:, 17, 17, 0])) -
                               int(np.median(frames[:, 17, 17, 2])), 30)

