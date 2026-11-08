"""Per-game reset keeps prepared media, Home choices and unrelated games."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from signalbar.faceplate.steamgriddb import SteamGridDBError
from signalbar.settings import SettingsStore
from test_cinema_integration import plugin_class
import test_faceplate_display237 as display_fixture


class GameArtworkLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.library,self.folder,self.manifest,self.data,self.pack=display_fixture.Display237().library(self.root)

    def test_overview_reads_active_metadata_without_loading_media_or_decoding(self):
        with patch.object(Path,'read_bytes',side_effect=AssertionError('No media reads')):
            entries=self.library.game_override_entries()
        self.assertEqual(len(entries),1);self.assertEqual(entries[0]['appid'],620)
        self.assertEqual(entries[0]['source'],'artwork')
        (self.folder.parents[1]/'active.json').unlink()
        self.assertEqual(self.library.game_override_entries(),[],'Prepared drafts are not game overrides')

    def test_default_pointer_blocks_legacy_fallback_but_keeps_all_reusable_files(self):
        root=self.folder.parents[1]
        legacy=dict(schema=1,appid=620,mode='static',sha256=hashlib.sha256(self.data).hexdigest())
        (root/'manifest.json').write_text(json.dumps(legacy));(root/'faceplate.gif').write_bytes(self.data)
        before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file() and p.name!='active.json'}
        self.library.reset_game_override(620)
        self.assertIsNone(self.library.selected(620));self.assertEqual(self.library.selected_dashboard_manifest(620),{})
        self.assertEqual(self.library.game_override_entries(),[])
        for path,data in before.items():self.assertEqual((root/path).read_bytes(),data)
        self.library.activate_prepared(620,'animated')
        self.assertEqual(self.library.selected(620)[0],self.data)

    def test_invalid_app_ids_and_symlinked_game_roots_cannot_write_elsewhere(self):
        outside=self.root/'outside';outside.mkdir();(self.library.artwork_root/'730').symlink_to(outside,target_is_directory=True)
        for appid in (0,-1,0x100000000,730):
            with self.assertRaises(SteamGridDBError):self.library.reset_game_override(appid)
        self.assertEqual(list(outside.iterdir()),[])


class GameArtworkRPCTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.library,self.folder,self.manifest,self.data,self.pack=display_fixture.Display237().library(self.root)
        self.settings=SettingsStore(str(self.root/'settings.json'))
        self.settings.update({'faceplate_artwork_profiles':{'620':{'style':'art','position':'top'},'730':{'style':'logo','position':'bottom'}}})
        self.plugin=plugin_class()();self.plugin.diagnostics=Mock()
        self.plugin.faceplate_artwork_jobs=SimpleNamespace(status=lambda:{'state':'idle'})
        self.current=0
        self.plugin.engine=SimpleNamespace(settings=self.settings,_faceplate_configuration_lock=threading.RLock(),
            faceplate=SimpleNamespace(steamgriddb=self.library),faceplate_game_snapshot=lambda:{'appid':self.current},
            refresh_settings=Mock(),status=lambda:{'profiles':self.settings.all()['faceplate_artwork_profiles']})

    async def test_inactive_game_reset_never_changes_routes_home_other_profiles_or_usb(self):
        result=await self.plugin.reset_faceplate_game_artwork(620)
        self.assertEqual(set(result['profiles']),{'730'})
        self.plugin.engine.refresh_settings.assert_not_called()
        self.assertEqual((self.folder/'faceplate.gif').read_bytes(),self.data)
        self.assertIsNone(self.library.selected(620))

    async def test_running_game_reconciles_once_and_home_borrowed_copy_is_preserved(self):
        self.current=620
        self.settings.update({'faceplate_dashboard_home_source':'artwork','faceplate_dashboard_home_appid':620})
        await self.plugin.reset_faceplate_game_artwork(620)
        self.assertEqual(self.library.home_selected(620)[0],self.data)
        self.assertIsNone(self.library.selected(620));self.plugin.engine.refresh_settings.assert_called_once()
        self.assertEqual(self.settings.all()['faceplate_dashboard_home_appid'],620)

    async def test_overview_contains_only_custom_games_and_names_without_full_status_reads(self):
        self.plugin.engine.status=Mock(side_effect=AssertionError('No full status read'))
        with patch.dict(self.plugin.get_faceplate_game_artwork_overrides.__func__.__globals__,
                        {'installed_games':lambda:[{'appid':620,'name':'Portal 2'},{'appid':100,'name':'Not customized'}]}):
            result=await self.plugin.get_faceplate_game_artwork_overrides()
        self.assertEqual({x['appid'] for x in result['entries']},{620,730})
        self.assertEqual(next(x for x in result['entries'] if x['appid']==620)['name'],'Portal 2')

    async def test_failed_reset_does_not_hide_its_original_error_or_delete_media(self):
        with patch.object(self.library,'reset_game_override',side_effect=SteamGridDBError('cannot save')):
            with self.assertRaisesRegex(SteamGridDBError,'cannot save'):await self.plugin.reset_faceplate_game_artwork(620)
        self.assertEqual((self.folder/'faceplate.gif').read_bytes(),self.data)
        self.assertIn('620',self.settings.all()['faceplate_artwork_profiles'])

    async def test_layout_is_an_exception_for_one_game_and_never_changes_global_defaults(self):
        before=self.settings.all()
        await self.plugin.set_faceplate_game_artwork_layout(620,'style','logo_only')
        after=self.settings.all()
        self.assertEqual(after['faceplate_artwork_style'],before['faceplate_artwork_style'])
        self.assertEqual(after['faceplate_logo_position'],before['faceplate_logo_position'])
        self.assertEqual(after['faceplate_artwork_profiles']['620']['style'],'logo_only')
        self.assertEqual(after['faceplate_artwork_profiles']['730'],before['faceplate_artwork_profiles']['730'])
        self.plugin.engine.refresh_settings.assert_not_called()

    async def test_new_layout_exception_inherits_the_unchanged_other_global_field(self):
        self.current=570
        await self.plugin.set_faceplate_game_artwork_layout(570,'position','top')
        row=self.settings.all()['faceplate_artwork_profiles']['570']
        self.assertEqual(row,{'style':self.settings.all()['faceplate_artwork_style'],'position':'top'})
        self.plugin.engine.refresh_settings.assert_called_once()

    async def test_invalid_layout_is_rejected_before_any_settings_change(self):
        before=self.settings.all()
        for key,value in [('brightness','50'),('style','unknown'),('position','side')]:
            with self.assertRaises(ValueError):await self.plugin.set_faceplate_game_artwork_layout(620,key,value)
        self.assertEqual(before,self.settings.all())
