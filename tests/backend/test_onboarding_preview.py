from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.models import LED_COUNT
from signalbar.providers.onboarding import (
    immersive_preview_output,
    synthetic_screen_sync_frame,
    synthetic_slow_prism_frame,
)
from signalbar.settings import SettingsStore


class OnboardingPreviewTests(unittest.TestCase):
    def test_slow_prism_demo_is_mirrored_bounded_and_breathes(self):
        first = synthetic_slow_prism_frame(0.0)
        expanded = synthetic_slow_prism_frame(0.65)
        self.assertEqual(len(first), LED_COUNT)
        self.assertEqual(first, tuple(reversed(first)))
        self.assertEqual(expanded, tuple(reversed(expanded)))
        self.assertNotEqual(first, expanded)
        self.assertGreater(sum(pixel != (0, 0, 0) for pixel in first), 0)
        self.assertGreater(
            sum(pixel != (0, 0, 0) for pixel in expanded),
            sum(pixel != (0, 0, 0) for pixel in first),
        )

    def test_screen_sync_demo_is_spatial_bounded_and_moves(self):
        first = synthetic_screen_sync_frame(0.0)
        moved = synthetic_screen_sync_frame(1.2)
        self.assertEqual(len(first), LED_COUNT)
        self.assertNotEqual(first, moved)
        self.assertGreater(len(set(first)), 8)
        for frame in (first, moved):
            for pixel in frame:
                self.assertTrue(all(0 <= channel <= 255 for channel in pixel))

    def test_immersive_demo_switches_from_audio_to_screen(self):
        audio = immersive_preview_output(1.0, 10.0)
        screen = immersive_preview_output(7.0, 10.0)
        self.assertEqual(audio.provider, "audio-sync:slow-prism-demo")
        self.assertEqual(screen.provider, "screen-sync:panorama-demo")
        self.assertIsNotNone(audio.frame)
        self.assertIsNotNone(screen.frame)

    def test_engine_status_exposes_the_synthetic_preview_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            engine = Engine(store, str(Path(directory) / "artwork.json"))
            with patch("signalbar.backend.engine.time.monotonic", return_value=100.0):
                self.assertTrue(engine.preview_display_preset("immersive"))
            with patch("signalbar.backend.engine.time.monotonic", return_value=101.0):
                preview = engine.status()["display_preset_preview"]
            self.assertTrue(preview["active"])
            self.assertEqual(preview["phase"], "Audio Sync")
            self.assertEqual(len(preview["colors"]), LED_COUNT)


if __name__ == "__main__":
    unittest.main()
