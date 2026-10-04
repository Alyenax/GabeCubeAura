"""Exercise Artwork settings through the same RPC entry point as Decky."""

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class ArtworkDeckyEntryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
