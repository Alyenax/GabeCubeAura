"""Exercise Artwork settings through the same RPC entry point as Decky."""

import asyncio
import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class ArtworkDeckyEntryTests(unittest.TestCase):
    def test_changed_draft_is_rejected_until_its_new_preview_is_reviewed(self):
        root = Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules, {"decky": types.ModuleType("decky")}):
            spec = importlib.util.spec_from_file_location("lab58_draft_guard_main", root / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.faceplate_artwork_jobs = Mock()
            plugin.faceplate_artwork_jobs.status.return_value = {"state": "ready"}
            library = plugin.engine.faceplate.steamgriddb
            library.prepared.return_value = (b"GIF", {"sha256": "b" * 64}, Path("draft.gif"))
            with self.assertRaisesRegex(ValueError, "changed"):
                plugin._verify_faceplate_draft(620, "static", "a" * 64)
            plugin._verify_faceplate_draft(620, "static", "b" * 64)
            library.activate_prepared.assert_not_called()
            library.assign_home.assert_not_called()

    def test_running_preparation_cannot_be_applied_from_a_stale_ui(self):
        root = Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules, {"decky": types.ModuleType("decky")}):
            spec = importlib.util.spec_from_file_location("lab58_busy_draft_main", root / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.faceplate_artwork_jobs = Mock()
            plugin.faceplate_artwork_jobs.status.return_value = {"state": "running"}
            with self.assertRaisesRegex(ValueError, "Wait"):
                plugin._verify_faceplate_draft(620, "static", "a" * 64)
            plugin.engine.faceplate.steamgriddb.prepared.assert_not_called()

    def test_colour_intensity_reaches_the_engine(self):
        root = Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules, {"decky": types.ModuleType("decky")}):
            spec = importlib.util.spec_from_file_location(
                "gabecubeaura_artwork_main_test", root / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.engine.status.return_value = {"artwork_vibrance": 145}

            result = asyncio.run(plugin.set_artwork_setting(42, "vibrance", 145))

            plugin.engine.update_artwork_settings.assert_called_once_with(
                42, {"vibrance": 145},
            )
            self.assertEqual(result["artwork_vibrance"], 145)

    def test_dashboard_assignment_validates_pack_and_reconciles_once(self):
        root = Path(__file__).resolve().parents[2]
        decky = types.ModuleType("decky")
        decky.logger = types.SimpleNamespace(warning=lambda _message: None)
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location(
                "gabecubeaura_dashboard_assignment_main_test", root / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.engine._faceplate_configuration_lock = threading.RLock()
            plugin.diagnostics = Mock()
            plugin.faceplate_artwork_jobs = Mock()
            plugin.faceplate_artwork_jobs.status.return_value = {"state": "idle"}
            plugin.engine.faceplate_game_snapshot.return_value = {"appid": 0}
            library = plugin.engine.faceplate.steamgriddb
            library.prepared_dashboard_manifest.return_value = {
                "appid": 620, "mode": "animated", "dashboard_pack_frames": 12,
            }
            library.activate_prepared.return_value = {
                "appid": 620, "mode": "animated", "dashboard_pack_frames": 12,
            }
            library.assign_home.return_value = library.activate_prepared.return_value
            preferences = types.SimpleNamespace(
                home_scene="weather", game_scene="artwork", revision=7,
            )
            plugin.engine.faceplate_preferences.read.return_value = preferences
            plugin.engine.status.return_value = {
                "faceplate_dashboard_home_appid": 620,
                "faceplate_dashboard_home_source": "artwork",
            }

            result = asyncio.run(plugin.assign_faceplate_dashboard_artwork(
                620, "animated",
            ))

        library.activate_prepared.assert_called_once_with(620, "animated")
        plugin.engine.settings.update.assert_called_once_with({
            "faceplate_dashboard_home_appid": 620,
            "faceplate_dashboard_home_source": "artwork",
        })
        plugin.engine.update_faceplate_routing.assert_called_once_with(
            "artwork-dashboard", "artwork-dashboard", 7,
        )
        plugin.engine.update_settings.assert_not_called()
        self.assertEqual(result["faceplate_dashboard_home_appid"], 620)

    def test_delete_returns_fresh_inventory_without_rescanning_steam_games(self):
        root = Path(__file__).resolve().parents[2]
        decky = types.ModuleType("decky")
        decky.logger = types.SimpleNamespace(warning=lambda _message: None)
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location(
                "gabecubeaura_library_delete_main_test", root / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.engine._faceplate_configuration_lock = threading.RLock()
            plugin.diagnostics = Mock()
            plugin.faceplate_artwork_jobs = Mock()
            plugin.faceplate_artwork_jobs.status.return_value = {"state": "idle"}
            plugin.engine.faceplate_game_snapshot.return_value = {"appid": 0}
            plugin.engine.settings.all.return_value = {
                "faceplate_dashboard_home_appid": 0,
                "faceplate_dashboard_home_source": "weather",
            }
            library = plugin.engine.faceplate.steamgriddb
            library.delete_prepared.return_value = True
            library.library_entries.return_value = [{
                "appid": 730, "mode": "animated", "dashboard_ready": True,
            }]
            with patch.object(module, "installed_games") as game_scan:
                result = asyncio.run(plugin.delete_faceplate_artwork(620, "static"))

        library.delete_prepared.assert_called_once_with(620, "static")
        library.library_entries.assert_called_once_with()
        game_scan.assert_not_called()
        plugin.engine.refresh_faceplate.assert_called_once_with("artwork-library-delete")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entries"][0]["appid"], 730)


if __name__ == "__main__":
    unittest.main()
