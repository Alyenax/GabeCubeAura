"""Public update cadence: fresh defaults and inherited five/fifteen-minute values."""
import json
from pathlib import Path
import tempfile
import unittest
from signalbar.settings import SettingsStore
from signalbar.updates import CHECK_INTERVAL_MINUTES

class PublicUpdateIntervalTests(unittest.TestCase):
    def test_default_and_legacy_short_intervals_resolve_to_24_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            self.assertEqual(1440,SettingsStore(str(path)).all()['updates_check_interval_minutes'])
            for minutes in [5,15]:
                path.write_text(json.dumps({'updates_check_interval_minutes':minutes,'updates_auto_install':True}))
                store=SettingsStore(str(path))
                self.assertEqual(1440,store.all()['updates_check_interval_minutes'])
                self.assertFalse(store.all()['updates_auto_install'])
                self.assertEqual(1440,store.update({'updates_check_interval_minutes':minutes,'updates_auto_install':True})['updates_check_interval_minutes'])
    def test_longer_intervals_remain_selectable(self):
        self.assertEqual({60,180,360,720,1440},CHECK_INTERVAL_MINUTES)
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(str(Path(directory)/'config.json'))
            for minutes in CHECK_INTERVAL_MINUTES:
                self.assertEqual(minutes,store.update({'updates_check_interval_minutes':minutes,'updates_auto_install':True})['updates_check_interval_minutes'])
