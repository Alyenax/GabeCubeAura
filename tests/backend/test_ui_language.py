import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from signalbar.backend import Engine
from signalbar.settings import SettingsStore


class UILanguageTests(unittest.TestCase):
    def test_changing_language_does_not_reconfigure_hardware_or_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine.__new__(Engine)
            engine._settings_apply_lock = threading.RLock()
            engine.settings = SettingsStore(str(Path(directory) / "config.json"))
            engine._apply_settings = Mock()
            engine.update_settings({"ui_language": "fr"})
            engine._apply_settings.assert_not_called()
            engine.update_settings({"faceplate_brightness": 70})
            engine._apply_settings.assert_called_once()

    def test_existing_settings_default_to_english_and_french_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"lab58_ux_enabled": False, "faceplate_brightness": 70}))
            settings = SettingsStore(str(path))
            self.assertEqual(settings.all()["ui_language"], "en")
            settings.update({"ui_language": "fr"})
            loaded = SettingsStore(str(path)).all()
            self.assertEqual(loaded["ui_language"], "fr")
            self.assertEqual(loaded["faceplate_brightness"], 70)
            self.assertFalse(loaded["lab58_ux_enabled"])
            settings.update({"ui_language": "en"})
            self.assertEqual(SettingsStore(str(path)).all()["ui_language"], "en")

    def test_invalid_languages_fall_back_without_affecting_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(str(Path(directory) / "config.json"))
            for value in (None, "de", "FR", [], {}, 1, True):
                settings.update({"ui_language": value})
                self.assertEqual(settings.all()["ui_language"], "en")

    def test_configuration_export_import_and_reset_include_the_language(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(str(Path(directory) / "config.json"))
            settings.update({"ui_language": "fr"})
            exported = settings.all()
            self.assertEqual(exported["ui_language"], "fr")
            settings.replace_configuration({"ui_language": "en"}, {}, {})
            settings.replace_configuration({"ui_language": exported["ui_language"]}, {}, {})
            self.assertEqual(settings.all()["ui_language"], "fr")
            with self.assertRaises(ValueError):
                settings.replace_configuration({"ui_language": "de"}, {}, {})
            self.assertEqual(settings.all()["ui_language"], "fr")
            settings.reset_configuration()
            self.assertEqual(settings.all()["ui_language"], "en")
