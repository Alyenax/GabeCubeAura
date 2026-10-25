"""Reset is not a completed setup, across USB detection and process restarts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate

class ResetFaceplate246Tests(unittest.TestCase):
    def test_fresh_and_reset_defaults_follow_without_claiming_completed_setup(self):
        for calibrated in (False,True):
            with self.subTest(calibrated=calibrated),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'config.json';store=SettingsStore(str(path),first_install_defaults=calibrated)
                self.assertTrue(store.all()['faceplate_lab_enabled'])
                self.assertFalse(store.all()['faceplate_setup_completed'])
                store.update({'faceplate_lab_enabled':False,'faceplate_setup_completed':True})
                self.assertFalse(SettingsStore(str(path),first_install_defaults=calibrated).all()['faceplate_lab_enabled'])
                store.reset_configuration()
                loaded=SettingsStore(str(path),first_install_defaults=calibrated)
                self.assertTrue(loaded.all()['faceplate_lab_enabled'])
                self.assertFalse(loaded.all()['faceplate_setup_completed'])
                self.assertFalse(loaded.all()['onboarding_completed'])

    def test_reset_forgets_usage_preferences_and_usb_reconnect_requests_setup_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'config.json';prefs=FaceplatePreferencesStore(root/'routes.json')
            store=SettingsStore(str(path),first_install_defaults=True)
            store.update({'onboarding_completed':True,'faceplate_setup_completed':True,
                'faceplate_lab_enabled':False,'faceplate_rotate_180':True,
                'faceplate_artwork_profiles':{'620':{'style':'logo','position':'top'}}})
            prefs.update(home_scene='native-clock',game_scene='weather')
            raw=json.loads(prefs.path.read_text());raw.update(previous_setup=True,usb_device_id='old-fixture-device',retired_performance_routes={'home':'performance'})
            prefs.path.write_text(json.dumps(raw));previous_revision=prefs.read().revision
            engine=Engine(store,str(root/'cache.json'),faceplate_preferences=prefs,faceplate_runtime_path=root/'runtime.json')
            engine.faceplate.steamgriddb = SteamGridDBFaceplate(root/'library')
            try:
                engine.reset_settings_only()
                self.assertFalse(engine.faceplate_worker.status()['enabled'])
                self.assertFalse(engine.faceplate_worker.status()['queued'])
                self.assertGreater(prefs.read().revision,previous_revision)
                for key in ('previous_setup','usb_device_id','retired_performance_routes'):
                    self.assertNotIn(key,json.loads(prefs.path.read_text()))
                self.assertFalse(store.all()['faceplate_rotate_180'])
                self.assertEqual(store.all()['faceplate_artwork_profiles'],{})
                self.assertTrue(store.all()['faceplate_lab_enabled'])
                # General setup remains mandatory. Completing it without a
                # connected panel must not suppress its later separate setup.
                store.update({'onboarding_completed':True})
                for available in (True,False,True):
                    with patch.object(engine.faceplate,'status',return_value={'available':available}):
                        status=engine.status()
                        self.assertFalse(status['faceplate_setup_completed'])
                        self.assertTrue(status['faceplate_lab_enabled'])
                engine.stop()
                loaded=SettingsStore(str(path),first_install_defaults=True)
                resumed=Engine(loaded,str(root/'cache.json'),faceplate_preferences=FaceplatePreferencesStore(prefs.path),faceplate_runtime_path=root/'runtime.json')
                resumed.faceplate.steamgriddb = SteamGridDBFaceplate(root/'library')
                try:
                    with patch.object(resumed.faceplate,'status',return_value={'available':True}):
                        self.assertFalse(resumed.status()['faceplate_setup_completed'])
                    resumed.update_faceplate_routing(home_scene='native-clock')
                    self.assertTrue(loaded.all()['faceplate_setup_completed'])
                    resumed.reset_settings_only()
                    self.assertFalse(loaded.all()['faceplate_setup_completed'])
                finally:resumed.stop()
            finally:engine.stop()
