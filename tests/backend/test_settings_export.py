import json
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from signalbar.settings import SettingsStore
from signalbar.settings.export import (
    build_configuration_export,
    configuration_export_path,
    read_configuration_import,
    write_configuration_export,
)


class SettingsExportTests(unittest.TestCase):
    def test_rebrand_migrates_signalbar_settings_and_caches_once(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            legacy = base / "SignalBar"
            current = base / "GabeCubeAura"
            legacy.mkdir()
            expected = {
                "config.json": b'{"mode":"weather"}',
                "artwork-cache.json": b'{"artwork":true}',
                "launch-artwork-cache.json": b'{"launch":true}',
            }
            for filename, contents in expected.items():
                (legacy / filename).write_bytes(contents)
            (legacy / "unrelated.txt").write_text("do not copy", encoding="utf-8")

            decky = types.ModuleType("decky")
            with patch.dict(sys.modules, {"decky": decky}):
                spec = importlib.util.spec_from_file_location("gabecubeaura_migration_test", root / "main.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertEqual(module.Plugin._migrate_legacy_settings(str(current)), "SignalBar")
                self.assertEqual(
                    {path.name: path.read_bytes() for path in current.iterdir()},
                    expected,
                )

                (legacy / "config.json").write_bytes(b'{"mode":"performance"}')
                self.assertEqual(module.Plugin._migrate_legacy_settings(str(current)), "")
                self.assertEqual((current / "config.json").read_bytes(), expected["config.json"])

    def test_decky_import_and_reset_routes_reach_engine(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(str(Path(directory) / "config.json"))
            settings.update({"performance_smoothing": "smooth"})
            export_path = Path(directory) / "GabeCubeAura-configuration.json"
            write_configuration_export(settings, export_path, "0.6.0")
            decky = types.ModuleType("decky")
            with patch.dict(sys.modules, {"decky": decky}):
                spec = importlib.util.spec_from_file_location("signalbar_import_test", root / "main.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                plugin = module.Plugin()
                plugin.engine = Mock()
                plugin.engine.status.return_value = {"version": "0.6.0"}
                self.assertEqual(asyncio.run(plugin.import_configuration(str(export_path))),
                                 {"version": "0.6.0"})
                args = plugin.engine.import_configuration.call_args.args
                self.assertEqual(args[0]["performance_smoothing"], "smooth")
                plugin.engine.reset_configuration.assert_not_called()
                self.assertEqual(asyncio.run(plugin.reset_configuration()), {"version": "0.6.0"})
                plugin.engine.reset_configuration.assert_called_once_with()

    def test_export_groups_global_profiles_and_current_game(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "config.json"))
            store.update_display(42, "artwork")
            store.update_artwork(42, {"source": "header", "mode": "manual", "manual_y": 0.83})

            payload = build_configuration_export(
                store,
                "0.5.1",
                {"appid": 42, "title": "Example Game"},
                "2026-09-23T10:00:00Z",
            )

            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["configuration"]["global"]["mode"], "audio_sync")
            self.assertNotIn("display_profiles", payload["configuration"]["global"])
            self.assertNotIn("launch_artwork_profiles", payload["configuration"]["global"])
            self.assertEqual(payload["configuration"]["profiles"]["display_by_appid"], {"42": "artwork"})
            self.assertEqual(payload["configuration"]["profiles"]["launch_artwork_by_appid"], {})
            self.assertEqual(payload["configuration"]["current_game"]["display"]["mode"], "artwork")
            self.assertEqual(payload["configuration"]["current_game"]["artwork"]["manual_y"], 0.83)
            self.assertNotIn("controllers", payload["configuration"])

    def test_export_flattens_active_display_preset_without_local_restore_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "config.json"))
            store.update({"display_preset": "essential"})
            exported = build_configuration_export(store, "1.3.1")
            values = exported["configuration"]["global"]
            self.assertEqual(values["display_preset"], "custom")
            self.assertNotIn("display_preset_restore", values)
            self.assertEqual(values["home_display"], "blackout")
            self.assertEqual(values["game_display"], "blackout")
            self.assertEqual(values["valve_ownership_policy"], "downloads")

    def test_write_is_readable_and_reports_exact_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Documents" / "GabeCubeAura-configuration.json"
            result = write_configuration_export(
                SettingsStore(str(Path(directory) / "config.json")),
                target,
                "0.5.1",
            )
            self.assertEqual(result["path"], str(target))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["gabecubeaura_version"], "0.5.1")
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_path_prefers_documents_and_falls_back_to_settings(self):
        self.assertEqual(
            configuration_export_path("/tmp/settings", "/home/deck"),
            Path("/home/deck/Documents/GabeCubeAura-configuration.json"),
        )
        self.assertEqual(
            configuration_export_path("/home/deck/homebrew/settings/SignalBar"),
            Path("/home/deck/Documents/GabeCubeAura-configuration.json"),
        )
        self.assertEqual(
            configuration_export_path("/tmp/settings"),
            Path("/tmp/settings/GabeCubeAura-configuration.json"),
        )

    def test_round_trip_import_reset_and_invalid_import_are_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = SettingsStore(str(folder / "source.json"))
            source.update({"performance_smoothing": "smooth", "weather_temperature_unit": "fahrenheit"})
            source.update_display(42, "artwork")
            source.update_artwork(42, {"mode": "manual", "manual_y": .83, "source": "header"})
            source.update_launch_artwork(42, {
                "palette_mode": "custom",
                "custom_palettes": {"2": [[255, 0, 0], [0, 0, 255]],
                                    "3": [[255, 0, 0], [0, 255, 0], [0, 0, 255]]},
            })
            export = folder / "GabeCubeAura-configuration.json"
            write_configuration_export(source, export, "0.6.0")
            global_values, display, artwork, launch_artwork = read_configuration_import(str(export))
            target = SettingsStore(str(folder / "target.json"))
            imported = target.replace_configuration(global_values, display, artwork, launch_artwork)
            self.assertEqual(imported["performance_smoothing"], "smooth")
            self.assertEqual(imported["weather_temperature_unit"], "fahrenheit")
            self.assertEqual(target.display_for(42)["mode"], "artwork")
            self.assertEqual(target.artwork_for(42)["manual_y"], .83)
            self.assertEqual(target.launch_artwork_for(42)["palette_mode"], "custom")
            before = (folder / "target.json").read_bytes()

            with self.assertRaisesRegex(ValueError, "Invalid configuration setting"):
                target.replace_configuration({**global_values, "mode": "not-a-mode"}, display, artwork, launch_artwork)
            self.assertEqual((folder / "target.json").read_bytes(), before)
            self.assertEqual(target.all()["performance_smoothing"], "smooth")

            reset = target.reset_configuration()
            self.assertEqual(reset["performance_smoothing"], "responsive")
            self.assertEqual(reset["weather_snow_variant"], 1)
            self.assertEqual(reset["weather_temperature_unit"], "celsius")
            self.assertEqual(reset["display_profiles"], {})
            self.assertEqual(reset["artwork_profiles"], {})
            self.assertEqual(SettingsStore(str(folder / "target.json")).all(), reset)

    def test_import_reader_rejects_bad_schema_and_oversized_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "GabeCubeAura-configuration.json"
            for payload in ({"schema_version": 2}, {"schema_version": 1, "configuration": {}},
                            {"schema_version": 1, "configuration": {"global": {}, "profiles": []}}):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_configuration_import(str(path))
            path.write_bytes(b" " * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "under 1 MB"):
                read_configuration_import(str(path))
            with self.assertRaises(ValueError):
                read_configuration_import("relative.json")


if __name__ == "__main__":
    unittest.main()
