"""Automatic offline game Dashboard, cache and isolated-renderer regressions."""

import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from signalbar.faceplate.automatic_dashboard import AutomaticDashboardBackgrounds
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard
from signalbar.faceplate.scene_renderer import FaceplateRenderError, render_isolated
from signalbar.backend.engine import faceplate_scene_cache_namespace
from signalbar.backend import Engine
from signalbar.settings import SettingsStore


RGB = bytes((24, 52, 96)) * (64 * 54)


class AutomaticDashboardTests(unittest.TestCase):
    def test_saved_background_takes_priority_and_unprepared_game_preview_is_automatic(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            self.addCleanup(engine.stop)
            library = engine.faceplate.steamgriddb
            pack = Path(folder) / "artwork-dashboard.rgb"
            pack.write_bytes(RGB)
            saved = {"dashboard_pack_frames": 1, "dashboard_pack_sha256": hashlib.sha256(RGB).hexdigest()}
            with patch.object(library, "selected_dashboard_pack_reference", return_value=(saved, pack)) as selected, \
                    patch.object(engine._automatic_dashboard_backgrounds, "get", return_value=(RGB, "local.png", "hero")) as local:
                manifest, fields, _ = engine._dashboard_background(620)
                self.assertEqual(str(pack), fields["dashboard_pack_path"])
                self.assertNotIn("automatic_background", manifest)
                local.assert_not_called()
                selected.return_value = None
                preview = engine.faceplate_artwork_dashboard_preview(620)
                self.assertEqual((1, 100), (preview["frames"], preview["delay_cs"]))
                self.assertTrue(preview["gif"].startswith(b"GIF89a"))
                self.assertEqual(1, local.call_count)

    def test_source_and_layout_cache_invalidates_for_artwork_and_logo_changes(self):
        cache = AutomaticDashboardBackgrounds()
        with tempfile.TemporaryDirectory() as folder:
            source, logo = Path(folder) / "hero.png", Path(folder) / "logo.png"
            source.write_bytes(b"source")
            logo.write_bytes(b"logo")
            with patch("signalbar.faceplate.artwork._find_artwork_details", return_value=(source, "hero", False)), \
                    patch("signalbar.faceplate.artwork.find_logo", return_value=logo), \
                    patch("signalbar.faceplate.artwork.artwork", return_value=(RGB, str(source), "hero")) as decode:
                self.assertEqual(RGB, cache.get(620)[0])
                cache.get(620)
                self.assertEqual(1, decode.call_count)
                source.write_bytes(b"new-source")
                cache.get(620)
                self.assertEqual(2, decode.call_count)
                logo.write_bytes(b"new-logo")
                cache.get(620)
                self.assertEqual(3, decode.call_count)
                cache.get(620, position="top")
                self.assertEqual(4, decode.call_count)
                cache.get(620, style="art")
                self.assertEqual(5, decode.call_count)

    def test_cache_is_bounded_and_missing_artwork_can_appear_later(self):
        cache = AutomaticDashboardBackgrounds()
        with patch("signalbar.faceplate.artwork._find_artwork_details", return_value=(None, "hero", False)), \
                patch("signalbar.faceplate.artwork.find_logo", return_value=None), \
                patch("signalbar.faceplate.artwork.artwork", return_value=(None, "", "")) as decode:
            self.assertIsNone(cache.get(620))
            decode.return_value = (RGB, "local.png", "hero")
            self.assertIsNotNone(cache.get(620))
            for appid in range(1, 20):
                cache.get(appid)
            self.assertEqual(8, len(cache.frames))
            decode.return_value = (b"short", "local.png", "hero")
            with self.assertRaises(ValueError):
                cache.get(100)

    def test_real_child_composes_inline_frame_with_live_information_and_no_wall_clock(self):
        request = {
            "kind": "artwork-dashboard", "dashboard_background_rgb": RGB.hex(),
            "dashboard_pack_frames": 1, "dashboard_pack_sha256": hashlib.sha256(RGB).hexdigest(),
            "display_at": "2026-10-18T12:30:00+02:00", "game_running": True,
            "dashboard_show_clock": True, "session_minutes": 27,
            "show_game_session": True, "bottom_mode": "controllers",
            "controllers": [{"percent": 87}], "connected_controller_count": 1,
            "show_weather_notch": False,
        }
        data, manifest = render_isolated(request)
        expected = build_artwork_dashboard(
            (RGB,), request["display_at"], 27, game_running=True, show_clock=True,
            background_signature=request["dashboard_pack_sha256"], source_frame_count=1,
            show_game_session=True, bottom_mode="controllers", controllers=({"percent": 87},),
            connected_controller_count=1, show_weather_notch=False,
        )
        self.assertEqual(expected.gif(), data)
        self.assertEqual((1, 100), (manifest["frames"], manifest["delay_cs"]))
        with Image.open(BytesIO(data)) as image:
            self.assertEqual((64, 54), image.size)
        with self.assertRaises(FaceplateRenderError):
            render_isolated({**request, "dashboard_pack_sha256": "invalid"})
        with self.assertRaises(FaceplateRenderError):
            render_isolated({**request, "dashboard_background_rgb": "00"})

    def test_persistent_render_cache_includes_background_checksum(self):
        self.assertNotEqual(
            faceplate_scene_cache_namespace({"kind": "artwork-dashboard", "dashboard_pack_sha256": "old"}),
            faceplate_scene_cache_namespace({"kind": "artwork-dashboard", "dashboard_pack_sha256": "new"}),
        )
