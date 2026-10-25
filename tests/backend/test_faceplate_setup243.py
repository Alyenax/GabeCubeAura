"""Migration evidence, independent of native bar setup and USB writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from signalbar.settings import SettingsStore
from signalbar.backend import Engine

class FaceplateSetupMigrationTests(unittest.TestCase):
    def test_public_140_upgrade_unlocks_bar_but_keeps_faceplate_unreviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            path.write_text(json.dumps({'light_bar_day_brightness':31,'home_display':'customization'}))
            store=SettingsStore(str(path))
            self.assertTrue(store.all()['onboarding_completed'])
            self.assertFalse(store.all()['faceplate_setup_completed'])
            self.assertEqual(31,store.all()['light_bar_day_brightness'])
            store.update({'light_bar_day_brightness':32})
            self.assertFalse(SettingsStore(str(path)).all()['faceplate_setup_completed'])

    def test_older_configured_lab_panel_is_recognised_without_new_wizard(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            path.write_text(json.dumps({'faceplate_lab_enabled':True}))
            self.assertTrue(SettingsStore(str(path)).all()['faceplate_setup_completed'])

    def test_saved_routes_are_not_evidence_of_completed_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            store=SettingsStore(str(root/'config.json'))
            store.update({'faceplate_lab_enabled':False})
            engine=Engine(store,str(root/'artwork.json'))
            with patch.object(engine.faceplate,'status',return_value={'available':True}):
                self.assertFalse(engine.status()['faceplate_setup_completed'])
                engine.faceplate_preferences.update(home_scene='native-clock')
                self.assertFalse(engine.status()['faceplate_setup_completed'])
                engine.update_faceplate_routing(home_scene='native-clock')
                self.assertTrue(engine.status()['faceplate_setup_completed'])
                self.assertFalse(store.all()['faceplate_lab_enabled'])

    def test_automatic_first_install_enable_is_not_evidence_of_user_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            store=SettingsStore(str(root/'config.json'),first_install_defaults=True)
            engine=Engine(store,str(root/'artwork.json'))
            self.assertTrue(store.all()['faceplate_lab_enabled'])
            self.assertFalse(engine.status()['faceplate_setup_completed'])
