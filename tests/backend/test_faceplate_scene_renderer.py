"""Regression tests for the isolated Faceplate scene renderer launcher."""

import json
import hashlib
from io import BytesIO
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

from signalbar.faceplate.scene_renderer import FaceplateRenderError, render_isolated


class FaceplateSceneRendererTests(unittest.TestCase):
    def test_real_isolated_renderer_builds_weather_and_dashboard_gifs(self):
        weather = {
            "kind": "weather", "condition": "rain", "variant": 0,
            "temperature_c": 12, "unit": "celsius", "phase": "day",
            "city": "Paris",
        }
        dashboard = {
            "kind": "dashboard", "hour": "2026-10-07T11:12:00+02:00",
            "condition": "rain", "variant": 0, "temperature_c": 12,
            "unit": "celsius", "sunrise": "2026-10-07T07:51:00+02:00",
            "sunset": "2026-10-07T19:13:00+02:00", "city": "Paris",
            "clock_24h": True,
        }
        v3_weather = {**weather, "visual_theme": "night-paper-v3"}
        v3_dashboard = {**dashboard, "visual_theme": "night-paper-v3"}
        animated_dashboard = {
            **dashboard,
            "visual_theme": "weather-artwork-v2",
            "bottom_mode": "next_hour",
            "forecast": {
                "next_hour_condition": "rain",
                "next_hour_temperature_c": 12,
                "next_hour_precipitation_probability": 80,
            },
        }
        for request in (weather, dashboard, v3_weather, v3_dashboard, animated_dashboard):
            with self.subTest(kind=request["kind"]):
                payload, manifest = render_isolated(request, timeout=30)
                self.assertTrue(payload.startswith((b"GIF87a", b"GIF89a")))
                self.assertEqual(manifest["kind"], request["kind"])
                self.assertEqual(manifest["size_bytes"], len(payload))
                if request is animated_dashboard:
                    with Image.open(BytesIO(payload)) as image:
                        durations = [
                            frame.info.get("duration", 0)
                            for frame in ImageSequence.Iterator(image)
                        ]
                    self.assertGreaterEqual(len(durations), 20)
                    self.assertEqual(sum(durations), 2400)
                    self.assertEqual(manifest["visual_theme"], "weather-artwork-v2")

    def test_real_isolated_renderer_builds_full_artwork_dashboard_pack(self):
        frame_count = 80
        pack = b"".join(
            bytes((index, 40, 100)) * (64 * 54)
            for index in range(frame_count)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artwork-dashboard.rgb"
            path.write_bytes(pack)
            payload, manifest = render_isolated({
                "kind": "artwork-dashboard",
                "dashboard_pack_path": str(path),
                "dashboard_pack_frames": frame_count,
                "dashboard_pack_sha256": hashlib.sha256(pack).hexdigest(),
                "display_at": "2026-10-10T12:30:00+02:00",
                "weather": {"condition": "rain", "temperature_c": 12},
                "bottom_mode": "next_hour",
                "forecast": {
                    "next_hour_condition": "rain",
                    "next_hour_temperature_c": 13,
                    "next_hour_precipitation_probability": 80,
                },
            }, timeout=30)
        self.assertTrue(payload.startswith((b"GIF87a", b"GIF89a")))
        self.assertEqual("artwork-dashboard", manifest["kind"])
        self.assertEqual(frame_count, manifest["frames"])
        self.assertEqual(10, manifest["delay_cs"])
        with Image.open(BytesIO(payload)) as image:
            self.assertEqual(frame_count, sum(1 for _ in ImageSequence.Iterator(image)))

    def test_renderer_uses_system_python_and_strips_decky_runtime_paths(self):
        observed = {}

        def which(name, path=None):
            return {"python3": "/usr/bin/python3", "nice": "/usr/bin/nice"}.get(name)

        def run(command, **options):
            observed["command"] = list(command)
            observed["environment"] = dict(options["env"])
            gif_path = Path(command[-2])
            result_path = Path(command[-1])
            gif_path.write_bytes(b"GIF89a")
            result_path.write_text(
                json.dumps({"ok": True, "signature": "test"}), encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stderr=b"")

        injected = {
            "LD_PRELOAD": "/tmp/decky-preload.so",
            "LD_LIBRARY_PATH": "/tmp/decky-libs",
            "PYTHONHOME": "/tmp/decky-python",
            "PYTHONPATH": "/tmp/decky-modules",
        }
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, injected, clear=False), \
                patch("signalbar.faceplate.scene_renderer.shutil.which", side_effect=which), \
                patch("signalbar.faceplate.scene_renderer.subprocess.run", side_effect=run):
            payload, manifest = render_isolated(
                {"kind": "weather"}, temporary_root=directory,
            )

        self.assertEqual(payload, b"GIF89a")
        self.assertTrue(manifest["ok"])
        self.assertIn("/usr/bin/python3", observed["command"])
        self.assertNotIn("LD_PRELOAD", observed["environment"])
        self.assertNotIn("PYTHONHOME", observed["environment"])
        self.assertNotIn("PYTHONPATH", observed["environment"])
        self.assertEqual(observed["environment"]["LD_LIBRARY_PATH"], "")

    def test_renderer_fails_cleanly_when_system_python_is_missing(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "signalbar.faceplate.scene_renderer.shutil.which", return_value=None,
        ):
            with self.assertRaisesRegex(FaceplateRenderError, "system python3"):
                render_isolated({"kind": "weather"}, temporary_root=directory)


if __name__ == "__main__":
    unittest.main()
