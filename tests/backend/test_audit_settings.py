from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from signalbar.settings import SettingsStore
from signalbar.renderer import Renderer

class SettingsAuditTests(unittest.TestCase):
    def test_fresh_and_reset_defaults_match_after_reload_legacy_import_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';store=SettingsStore(str(path));fresh=store.base_all()
            expected={**fresh,'display_profiles':{},'artwork_profiles':{},'launch_artwork_profiles':{}}
            store.update_display(42,'displays_off');store.update({'home_display':'steam'})
            reset=store.reset_configuration()
            self.assertEqual(expected,reset);self.assertEqual(expected,SettingsStore(str(path)).base_all())
            self.assertEqual('audio_sync',reset['home_display']);self.assertEqual('immersive-plus',reset['display_preset'])
            migrated=store.replace_configuration({}, {}, {})
            self.assertEqual('steam',migrated['home_display']);self.assertEqual('steam',migrated['game_display'])

    def test_specialized_mutations_are_atomic_before_and_honest_after_disk_commit(self):
        for method,args in [('update_display',(42,'displays_off')),('update_artwork',(42,{'mode':'manual','manual_y':.75})),('update_launch_artwork',(42,{'palette_mode':'custom'}))]:
            for after in (False,True):
                with self.subTest(method=method,after=after),tempfile.TemporaryDirectory() as folder:
                    path=Path(folder)/'config.json';store=SettingsStore(str(path));store.save()
                    store.set_overlay({'home_display':'artwork'})
                    before=store.base_all();overlay=deepcopy(store._overlay);raw=path.read_bytes();save=store.save
                    def fail():
                        if after:save()
                        raise OSError('Simulated storage failure')
                    with patch.object(store,'save',side_effect=fail),self.assertRaises(OSError) as error:getattr(store,method)(*args)
                    self.assertEqual(after,bool(getattr(error.exception,'committed',False)))
                    if not after:
                        self.assertEqual(raw,path.read_bytes());self.assertEqual(before,store.base_all());self.assertEqual(overlay,store._overlay)
                    else:
                        self.assertNotEqual(before,store.base_all());self.assertEqual(store.base_all(),SettingsStore(str(path)).base_all())
