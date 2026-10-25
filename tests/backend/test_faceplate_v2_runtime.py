import unittest
from datetime import datetime
from pathlib import Path

from signalbar.faceplate.scenes import PIXELS, WEATHER_VARIANTS
from signalbar.faceplate.v2_scenes import (
    V2_SCENE_REVISION,
    V2_THEMES,
    build_v2_dashboard_snapshot,
    build_v2_performance_snapshot,
    build_v2_weather_scene,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tools/pixel-studio-alternative/assets/v2-collections"


class FaceplateV2RuntimeTests(unittest.TestCase):
    def test_every_theme_builds_every_weather_variant_with_celsius_and_fahrenheit(self):
        for theme in V2_THEMES:
            for condition, variants in WEATHER_VARIANTS.items():
                for variant in range(len(variants)):
                    for unit in ("celsius", "fahrenheit"):
                        with self.subTest(theme=theme, condition=condition,
                                          variant=variant, unit=unit):
                            scene = build_v2_weather_scene(
                                theme, condition, variant, 9.4, unit, "night",
                                city="Paris",
                            )
                            self.assertIn(len(scene.frames), (6, 8))
                            self.assertTrue(all(
                                len(frame) == PIXELS * 3 for frame in scene.frames
                            ))
                            self.assertEqual(V2_SCENE_REVISION, scene.revision)
                            self.assertLess(len(scene.gif()), 512 * 1024)

    def test_dashboard_is_one_non_looping_persistent_minute(self):
        sunrise = datetime(2026, 10, 8, 7, 15)
        sunset = datetime(2026, 10, 8, 19, 0)
        for theme in V2_THEMES:
            first = build_v2_dashboard_snapshot(
                theme, datetime(2026, 10, 8, 22, 7, 54), "clear_night", 0,
                11, "celsius", sunrise, sunset,
            )
            same_minute = build_v2_dashboard_snapshot(
                theme, datetime(2026, 10, 8, 22, 7, 2), "clear_night", 0,
                11, "celsius", sunrise, sunset,
            )
            next_minute = build_v2_dashboard_snapshot(
                theme, datetime(2026, 10, 8, 22, 8), "clear_night", 0,
                11, "celsius", sunrise, sunset,
            )
            self.assertEqual(1, len(first.frames))
            self.assertEqual(first.signature, same_minute.signature)
            self.assertNotEqual(first.signature, next_minute.signature)
            self.assertNotIn(b"NETSCAPE2.0", first.gif())


    def test_invalid_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            build_v2_performance_snapshot("unknown", 1, 2, 3, 4)


if __name__ == "__main__":
    unittest.main()
