"""Lab 30: per-game presentation, prepared animation and preview invariants."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signalbar.faceplate import gif
from signalbar.faceplate.artwork_layout import Logo
from signalbar.faceplate.coordinator import FaceplateCoordinator
from signalbar.faceplate.steamgriddb import compile_source
from signalbar.settings import SettingsStore

try:
    from PIL import Image
except ImportError:
    Image = None

PIXELS = 64 * 54
ROOT = Path(__file__).resolve().parents[2]


class StaticLibrary:
    def __init__(self, payload):
        self.payload = payload

    def selected(self, appid):
        if appid == 620:
            return self.payload, {"appid": 620}, Path("already-prepared.gif")
        return None


class Lab30Tests(unittest.TestCase):
    def test_retired_rotation_is_disabled_on_load_update_and_reload(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            path.write_text(json.dumps({
                "faceplate_rotate_180": True,
                "faceplate_brightness": 75,
                "faceplate_flash_protection_enabled": False,
            }), encoding="utf-8")
            config = SettingsStore(str(path))
            self.assertFalse(config.all()["faceplate_rotate_180"])
            config.update({"faceplate_rotate_180": True})
            reloaded = SettingsStore(str(path)).all()
            self.assertFalse(reloaded["faceplate_rotate_180"])
            self.assertEqual(75, reloaded["faceplate_brightness"])
            self.assertFalse(reloaded["faceplate_flash_protection_enabled"])

    def test_legacy_dashboard_artwork_assignment_migrates_to_explicit_source(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            path.write_text(json.dumps({
                "faceplate_dashboard_home_appid": 620,
            }), encoding="utf-8")
            settings = SettingsStore(str(path)).all()
        self.assertEqual(620, settings["faceplate_dashboard_home_appid"])
        self.assertEqual("artwork", settings["faceplate_dashboard_home_source"])

    def test_settings_keep_valid_game_profiles_and_reject_malformed_entries(self):
        with tempfile.TemporaryDirectory() as root:
            config = SettingsStore(str(Path(root) / "config.json"))
            config.update({
                "faceplate_rotate_180": True,
                "faceplate_artwork_style": "logo",
                "faceplate_logo_position": "top",
                "faceplate_dashboard_home_appid": 620,
                "faceplate_dashboard_home_source": "artwork",
                "faceplate_artwork_profiles": {
                    "620": {"style": "logo_only", "position": "centre"},
                    "730": {"style": "logo", "position": "bottom_rail"},
                    "nope": {"style": "art", "position": "top"},
                    "4711": {"style": "invalid", "position": "bottom"},
                },
            })
            settings = config.all()
        self.assertFalse(settings["faceplate_rotate_180"])
        self.assertEqual(settings["faceplate_artwork_style"], "logo")
        self.assertEqual(settings["faceplate_dashboard_home_appid"], 620)
        self.assertEqual(settings["faceplate_dashboard_home_source"], "artwork")
        self.assertEqual(settings["faceplate_artwork_profiles"], {
            "620": {"style": "logo_only", "position": "centre"},
            "730": {"style": "logo", "position": "bottom_rail"},
        })

    def test_shipped_rain_gifs_can_be_rotated_without_external_decoders(self):
        from signalbar.faceplate.gif_transform import rotate_gif
        from signalbar.faceplate.coordinator import validate_gif
        for name in ("rain-bluewater-64x54.gif", "rain-pearl-64x54.gif"):
            source = (ROOT / "assets/faceplate/weather" / name).read_bytes()
            with self.subTest(name=name):
                rotated = rotate_gif(source)
                validate_gif(rotated)
                self.assertTrue(rotated.startswith(b"GIF89a"))

    def test_animated_artwork_reuses_one_logo_in_all_frames(self):
        frames = [bytes((10 + i * 20, 30, 70)) * PIXELS for i in range(6)]
        logo = Logo(1, 1, ((0, 0, 1.0, (255, 255, 255)),))
        with patch("signalbar.faceplate.steamgriddb.decode_frames", return_value=frames), \
             patch("signalbar.faceplate.artwork_layout.prepare_logo", return_value=logo) as prepare:
            payload, load, count, backgrounds = compile_source(
                "local.webm", include_frames=True, appid=620,
                art_style="logo", logo_position="top",
            )
        self.assertEqual(count, 6)
        self.assertEqual(len(backgrounds), 6)
        self.assertEqual(prepare.call_count, 1)
        self.assertTrue(payload.startswith(b"GIF89a"))
        self.assertGreater(load, 0)

    def test_logo_only_produces_one_persistent_frame_instead_of_fake_motion(self):
        logo = Logo(1, 1, ((0, 0, 1.0, (255, 255, 255)),))
        with patch("signalbar.faceplate.steamgriddb.decode_frames",
                   return_value=[bytes((i * 20, 30, 70)) * PIXELS for i in range(5)]), \
             patch("signalbar.faceplate.artwork_layout.prepare_logo", return_value=logo):
            _, _, count, backgrounds = compile_source(
                "local.webm", include_frames=True, appid=620,
                art_style="logo_only", logo_position="bottom",
            )
        self.assertEqual(count, 1)
        self.assertEqual(len(backgrounds), 1)

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_preview_rotates_every_prepared_frame_without_serial_connection(self):
        palette = [(0, 0, 0), (255, 15, 55)]
        frame = bytes([1] + [0] * (PIXELS - 1))
        original = gif.encode(64, 54, palette, [frame, frame[::-1]], delay_cs=15)
        with tempfile.TemporaryDirectory() as root:
            coordinator = FaceplateCoordinator(
                ROOT / "assets/faceplate", Path(root) / "state.json",
                steamgriddb=StaticLibrary(original),
                port_finder=lambda: (_ for _ in ()).throw(
                    AssertionError("A preview must not touch USB")),
            )
            coordinator.configure_artwork("art", "bottom", {}, rotate=True)
            preview, origin = coordinator.preview_artwork(620)
        self.assertEqual(origin, "prepared")
        self.assertNotEqual(preview, original)
        with Image.open(io.BytesIO(preview)) as im:
            self.assertEqual(im.n_frames, 2)
            for index in (0, 1):
                im.seek(index)
                converted = im.convert("RGB").tobytes()
                pixel = converted[(PIXELS - 1) * 3:(PIXELS - 1) * 3 + 3]
                if index == 0:
                    self.assertEqual(pixel, bytes((255, 15, 55)))
                else:
                    self.assertEqual(converted[:3], bytes((255, 15, 55)))


if __name__ == "__main__":
    unittest.main()
