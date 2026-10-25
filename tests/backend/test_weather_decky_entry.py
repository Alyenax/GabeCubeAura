"""Exercise the same async search entry point that Decky invokes."""

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock


class WeatherDeckyEntryTests(unittest.TestCase):
    def test_faceplate_scene_theme_reaches_backend_as_one_independent_choice(self):
        root = Path(__file__).resolve().parents[2]
        decky = types.ModuleType("decky")
        decky.logger = types.SimpleNamespace(warning=lambda _message: None)
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location(
                "signalbar_weather_scene_theme_main_test", root / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.diagnostics = Mock()
            plugin.engine.status.return_value = {
                "faceplate": {"routing": {"scene_themes": {
                    "weather": "weather-artwork-v1",
                    "dashboard": "integrated",
                    "performance": "integrated",
                }}},
            }

            result = asyncio.run(plugin.set_faceplate_scene_theme(
                "weather", "weather-artwork-v1", 3,
            ))

        plugin.engine.update_faceplate_scene_theme.assert_called_once_with(
            "weather", "weather-artwork-v1", 3,
        )
        self.assertEqual(
            "weather-artwork-v1",
            result["faceplate"]["routing"]["scene_themes"]["weather"],
        )

    def test_weather_preview_and_stop_reach_backend_through_decky(self):
        root = Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules, {"decky": types.ModuleType("decky")}):
            spec = importlib.util.spec_from_file_location("signalbar_weather_colour_main_test", root / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.engine.preview_weather.return_value = True
            plugin.engine.stop_weather_preview.return_value = True
            self.assertTrue(asyncio.run(plugin.preview_weather(
                "rain", 1, "weather-artwork-v2",
            )))
            plugin.engine.preview_weather.assert_called_once_with(
                "rain", 1, "weather-artwork-v2",
            )
            self.assertTrue(asyncio.run(plugin.stop_weather_preview()))
            plugin.engine.stop_weather_preview.assert_called_once_with()

    def test_search_returns_results_or_diagnostic_without_raising(self):
        root = Path(__file__).resolve().parents[2]
        warnings = []
        decky = types.ModuleType("decky")
        decky.logger = types.SimpleNamespace(warning=warnings.append)
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location("signalbar_weather_main_test", root / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            city = {"name": "Paris", "country": "France", "latitude": 48.85, "longitude": 2.35}
            with patch.object(module, "search_cities", return_value=[city]) as search:
                result = asyncio.run(plugin.search_weather_cities("Paris, France"))
                self.assertEqual(result, {"results": [city], "error": ""})
                search.assert_called_once_with("Paris, France")
            with patch.object(module, "search_cities", side_effect=OSError("network unavailable")):
                result = asyncio.run(plugin.search_weather_cities("Paris"))
                self.assertEqual(result["results"], [])
                self.assertIn("network unavailable", result["error"])
                self.assertIn("city search failed", warnings[-1])

    def test_faceplate_weather_preview_is_base64_and_rendered_off_rpc_loop(self):
        root = Path(__file__).resolve().parents[2]
        decky = types.ModuleType("decky")
        decky.logger = types.SimpleNamespace(warning=lambda _message: None)
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location(
                "signalbar_weather_faceplate_preview_main_test", root / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.engine.faceplate_weather_preview.return_value = {
                "gif": b"GIF89a-test", "condition": "rain", "variant": 1,
                "phase": "day", "live_weather": True,
            }
            result = asyncio.run(plugin.get_faceplate_weather_preview(
                "rain", 1, "weather-artwork-v2",
            ))
        self.assertTrue(result["data_uri"].startswith("data:image/gif;base64,"))
        self.assertEqual(result["error"], "")
        plugin.engine.faceplate_weather_preview.assert_called_once_with(
            "rain", 1, "weather-artwork-v2",
        )

    def test_faceplate_dashboard_preview_is_base64_and_rendered_off_rpc_loop(self):
        root = Path(__file__).resolve().parents[2]
        decky = types.ModuleType("decky")
        decky.logger = types.SimpleNamespace(warning=lambda _message: None)
        with patch.dict(sys.modules, {"decky": decky}):
            spec = importlib.util.spec_from_file_location(
                "signalbar_dashboard_faceplate_preview_main_test", root / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.engine = Mock()
            plugin.engine.faceplate_dashboard_preview.return_value = {
                "gif": b"GIF89a-dashboard", "condition": "cloud", "variant": 2,
                "selection_status": "exact", "preset_id": "cloud:2",
            }
            result = asyncio.run(plugin.get_faceplate_dashboard_preview(
                "cloud", 2, "weather-artwork-v2",
            ))
        self.assertTrue(result["data_uri"].startswith("data:image/gif;base64,"))
        self.assertEqual(result["error"], "")
        plugin.engine.faceplate_dashboard_preview.assert_called_once_with(
            "cloud", 2, "weather-artwork-v2",
        )


if __name__ == "__main__":
    unittest.main()
