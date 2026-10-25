"""Real defaults, empty artwork library and mandatory setup remain one coherent path."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from signalbar.calibration import SETTINGS
from signalbar.settings import SettingsStore
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate
from signalbar.backend import Engine
from signalbar.onboarding import clean_draft

ROOT=Path(__file__).resolve().parents[2]
ASSETS=ROOT/'assets/faceplate'

class CalibrationTests(unittest.TestCase):
    def test_calibrated_settings_require_setup_on_fresh_boot_and_after_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'config.json'),first_install_defaults=True)
            values=store.all()
            self.assertEqual(values['light_bar_day_brightness'],15)
            self.assertEqual(values['faceplate_brightness'],70)
            self.assertEqual(values['faceplate_dashboard_home_appid'],0)
            self.assertEqual(values['faceplate_dashboard_contexts']['game']['game_row'],'e')
            self.assertFalse(values['onboarding_completed']);self.assertFalse(values['faceplate_setup_completed'])
            self.assertIsNone(values['weather_location'])
            self.assertTrue(values['updates_auto_check']);self.assertFalse(values['updates_auto_install'])
            self.assertEqual(values['updates_channel'],'stable')
            store.update({'light_bar_day_brightness':31,'faceplate_brightness':42,'onboarding_completed':True})
            self.assertEqual(SettingsStore(store.path,first_install_defaults=True).all()['light_bar_day_brightness'],31)
            self.assertEqual(SettingsStore(store.path,first_install_defaults=True).all()['faceplate_brightness'],42)
            store.reset_configuration()
            self.assertFalse(store.all()['onboarding_completed'])
            self.assertEqual(store.all()['light_bar_day_brightness'],15)
            self.assertEqual(store.all()['faceplate_brightness'],70)
            prefs=FaceplatePreferencesStore(Path(folder)/'routes.json',calibrated=True)
            self.assertEqual(prefs.read().home_scene,'dashboard')
            self.assertEqual(prefs.read().game_scene,'artwork-dashboard')
            self.assertEqual(clean_draft({'preset':'custom'}),{'preset':'custom'})

    def test_real_engine_boot_has_no_starter_and_preserves_personal_artwork(self):
        for personal in (False, True):
            with self.subTest(personal=personal),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                opener=Mock(side_effect=AssertionError('Boot must not fetch artwork'))
                library=SteamGridDBFaceplate(root/'library',opener=opener)
                if personal:
                    existing=library.artwork_root/'620/personal.gif'
                    existing.parent.mkdir(parents=True);existing.write_bytes(b'keep-my-save')
                before={str(p.relative_to(library.root)):p.read_bytes() for p in library.root.rglob('*') if p.is_file()}
                store=SettingsStore(str(root/'settings.json'),first_install_defaults=True)
                with patch('signalbar.faceplate.coordinator.SteamGridDBFaceplate',return_value=library):
                    engine=Engine(store,str(root/'cache.json'))
                try:
                    after={str(p.relative_to(library.root)):p.read_bytes() for p in library.root.rglob('*') if p.is_file()}
                    self.assertEqual(before,after)
                    self.assertIsNone(library.home_selected(1332010))
                    self.assertFalse(library.auth_path.exists());opener.assert_not_called()
                    self.assertFalse(engine.status()['onboarding_completed'])
                    self.assertFalse(engine.status()['faceplate_setup_completed'])
                    self.assertEqual(engine.faceplate_preferences.read().home_scene,'dashboard')
                finally:engine.stop()
