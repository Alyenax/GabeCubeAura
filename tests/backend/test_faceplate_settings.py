from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from signalbar.faceplate import options
from signalbar.settings import SettingsStore
from signalbar.steam import find_library_artwork, find_library_logo


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


class FaceplateStoreTests(unittest.TestCase):
    def test_defaults_and_bad_values_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "GabeCubeAura", "config.json")
            write_json(path, {"faceplate_mode": "disco", "faceplate_brightness": 300,
                              "faceplate_logo_position": "top"})
            values = SettingsStore(path).all()
        self.assertEqual(values["faceplate_mode"], "off")
        self.assertEqual(values["faceplate_brightness"], 60)
        self.assertEqual(values["faceplate_logo_position"], "top")

    def test_pixel_faceplate_settings_come_across_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "GabeCubeAura", "config.json")
            write_json(path, {"mode": "artwork"})
            standalone = os.path.join(tmp, "Pixel-Faceplate", "settings.json")
            write_json(standalone, {
                "mode": "artwork", "brightness": 80, "art_style": "logo_only",
                "logo_position": "center", "clock_color": "#1a9fff", "rotate": True,
                "game_profiles": {"1931770": {"art_style": "art", "logo_position": "center"}},
                "not_a_setting": 1,
            })
            values = SettingsStore(path).all()
            self.assertEqual(values["faceplate_mode"], "artwork")
            self.assertEqual(values["faceplate_brightness"], 80)
            self.assertEqual(values["faceplate_logo_position"], "centre")
            self.assertEqual(values["faceplate_clock_colour"], "#1a9fff")
            self.assertTrue(values["faceplate_rotate"])
            self.assertEqual(values["faceplate_game_profiles"]["1931770"],
                             {"art_style": "art", "logo_position": "centre"})
            # Saved straight away, and later changes over there are not copied again.
            write_json(standalone, {"mode": "clock"})
            self.assertEqual(SettingsStore(path).all()["faceplate_mode"], "artwork")

    def test_no_standalone_plugin_means_nothing_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "GabeCubeAura", "config.json")
            values = SettingsStore(path).all()
            self.assertEqual(values["faceplate_mode"], "off")
            self.assertFalse(os.path.exists(path))

    def test_unreadable_configuration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "GabeCubeAura", "config.json")
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"mode": "artwork", "light_bar_day_brightness": 2')  # cut off mid-write
            write_json(os.path.join(tmp, "Pixel-Faceplate", "settings.json"), {"mode": "clock"})
            SettingsStore(path)
            with open(path, encoding="utf-8") as handle:
                self.assertTrue(handle.read().endswith(": 2"))

    def test_one_bad_game_profile_does_not_cost_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "GabeCubeAura", "config.json")
            write_json(path, {"faceplate_mode": "artwork", "faceplate_game_profiles": {
                "10": {"art_style": "art"}, "0": {"art_style": "art"}, "11": {"brightness": 5},
            }})
            self.assertEqual(SettingsStore(path).all()["faceplate_game_profiles"], {"10": {"art_style": "art"}})

    def test_import_from_another_machine_drops_a_missing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SettingsStore(os.path.join(tmp, "GabeCubeAura", "config.json"))
            values = store.replace_configuration(
                {"faceplate_mode": "image", "faceplate_image_path": "/home/deck/Pictures/gone.png",
                 "faceplate_clock_colour": "FF0000"}, {}, {}, {},
            )
        self.assertEqual(values["faceplate_mode"], "image")
        self.assertEqual(values["faceplate_image_path"], "")
        self.assertEqual(values["faceplate_clock_colour"], "#ff0000")

    def test_service_view_carries_the_light_bar_orientation(self):
        self.assertTrue(options.unprefixed({})["light_bar_reversed"])
        self.assertFalse(options.unprefixed({"reverse_led_order": False})["light_bar_reversed"])

    def test_options_reject_what_cannot_be_per_game(self):
        with self.assertRaises(ValueError):
            options.game_profile({"brightness": 10})
        self.assertEqual(options.for_game(
            {"art_style": "logo", "logo_position": "bottom",
             "game_profiles": {"7": {"logo_position": "top"}}}, 7,
        )["logo_position"], "top")


class LogoLookupTests(unittest.TestCase):
    def test_custom_grid_logo_then_library_cache_without_falling_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "appcache/librarycache"
            (cache / "10" / "abc123").mkdir(parents=True)
            (cache / "10" / "library_hero.jpg").write_bytes(b"hero")
            with patch.dict(os.environ, {"SIGNALBAR_STEAM_ROOT": str(root)}):
                # A hero alone is not a logo.
                self.assertIsNone(find_library_logo(10))
                (cache / "10" / "abc123" / "logo.png").write_bytes(b"logo")
                self.assertEqual(find_library_logo(10), cache / "10" / "abc123" / "logo.png")
                grid = root / "userdata/42/config/grid"
                grid.mkdir(parents=True)
                (grid / "10_logo.png").write_bytes(b"custom")
                self.assertEqual(find_library_logo(10), grid / "10_logo.png")
                # The light bar's own lookup is unchanged.
                self.assertEqual(find_library_artwork(10, "hero"), cache / "10" / "library_hero.jpg")


class FaceplateEntryTests(unittest.TestCase):
    def load_plugin(self):
        root = Path(__file__).resolve().parents[2]
        decky = types.ModuleType("decky")
        decky.logger = Mock()
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location("signalbar_faceplate_main_test", root / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        plugin = module.Plugin()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        plugin.engine = Mock()
        store = SettingsStore(os.path.join(tmp.name, "GabeCubeAura", "config.json"))
        plugin.engine.settings = store
        plugin.engine.update_settings.side_effect = store.update
        plugin.faceplate = Mock()
        plugin.faceplate_power = None
        return module, plugin

    def test_power_hook_runs_only_while_the_faceplate_is_on(self):
        module, plugin = self.load_plugin()
        with patch.object(module, "PowerEvents") as power:
            asyncio.run(plugin.set_faceplate_setting("mode", "artwork"))
            power.return_value.start.assert_called_once_with()
            asyncio.run(plugin.set_faceplate_setting("brightness", 40))
            self.assertEqual(power.call_count, 1)
            asyncio.run(plugin.set_faceplate_setting("mode", "off"))
            power.return_value.stop.assert_called_once_with()
            self.assertIsNone(plugin.faceplate_power)
        configured = plugin.faceplate.configure.call_args[0][0]
        self.assertEqual(configured["brightness"], 40)

    def test_claim_for_pixel_faceplate_follows_the_mode(self):
        module, plugin = self.load_plugin()
        claim_dir = tempfile.TemporaryDirectory()
        self.addCleanup(claim_dir.cleanup)
        plugin.faceplate_settings_dir = claim_dir.name
        claim = os.path.join(claim_dir.name, "faceplate-claim.json")
        with patch.object(module, "PowerEvents"):
            asyncio.run(plugin.set_faceplate_setting("mode", "clock"))
            self.assertTrue(os.path.exists(claim))
            asyncio.run(plugin.set_faceplate_setting("mode", "off"))
            self.assertFalse(os.path.exists(claim))
            asyncio.run(plugin.set_faceplate_setting("mode", "artwork"))
            plugin._stop_faceplate()  # what _unload and _uninstall call
            self.assertFalse(os.path.exists(claim))

    def test_bad_value_is_refused(self):
        _, plugin = self.load_plugin()
        with self.assertRaises(ValueError):
            asyncio.run(plugin.set_faceplate_setting("mode", "disco"))

    def test_game_settings_start_from_the_global_choice(self):
        _, plugin = self.load_plugin()
        asyncio.run(plugin.set_faceplate_setting("art_style", "logo"))
        asyncio.run(plugin.set_faceplate_game_settings(1931770, {}))
        profiles = plugin.engine.settings.all()["faceplate_game_profiles"]
        self.assertEqual(profiles["1931770"], {"art_style": "logo", "logo_position": "bottom"})
        asyncio.run(plugin.set_faceplate_game_settings(1931770, {"logo_position": "top"}))
        self.assertEqual(plugin.engine.settings.all()["faceplate_game_profiles"]["1931770"]["logo_position"], "top")
        asyncio.run(plugin.set_faceplate_game_settings(1931770, None))
        self.assertEqual(plugin.engine.settings.all()["faceplate_game_profiles"], {})
        with self.assertRaises(ValueError):
            asyncio.run(plugin.set_faceplate_game_settings(0, {}))

    def test_without_faceplate_support_the_calls_say_so(self):
        _, plugin = self.load_plugin()
        plugin.faceplate = None
        with self.assertRaises(RuntimeError):
            asyncio.run(plugin.get_faceplate_status())
        asyncio.run(plugin.game_changed(10))  # still fine for the light bar

    def test_game_changes_reach_the_faceplate(self):
        _, plugin = self.load_plugin()
        asyncio.run(plugin.game_changed(4358690, "Graveyard Keeper 2", True, "lifetime"))
        plugin.faceplate.game_event.assert_called_with(4358690, True)
        asyncio.run(plugin.game_changed(0))
        plugin.faceplate.game_event.assert_called_with(0, False)


if __name__ == "__main__":
    unittest.main()
