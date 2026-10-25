"""Home/game parity and temporary exact creation retrieval; simulated IO only."""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from signalbar.backend import Engine
from signalbar.faceplate.coordinator import encode_frame
from signalbar.faceplate.creation_transfer import creation_archive
from signalbar.faceplate.routing import FaceplatePreferencesStore, FaceplateSceneRouter, FaceplateRevisionConflict
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate, DASHBOARD_PACK_REVISION
from signalbar.settings import SettingsStore
from signalbar.updates import UpdateManager, UpdateError
from test_updates import FakePrivateAuth, FakeResponse
import test_configuration_backup236 as baseline_tests
import test_native_clock as native_fixture


class Display237(unittest.TestCase):
    def library(self, root):
        library = SteamGridDBFaceplate(root=root/'library')
        data = encode_frame(bytes((20,30,40))*(64*54))
        pack = bytes((20,30,40))*(64*54)
        folder = library._prepared_root(620,'animated');folder.mkdir(parents=True)
        manifest = dict(schema=2,appid=620,mode='animated',ready=True,animated=True,
            sha256=hashlib.sha256(data).hexdigest(),compiled='faceplate.gif',source_url='SECRET-URL',
            source='source.webm',dashboard_pack='artwork-dashboard.rgb',dashboard_pack_frames=1,
            dashboard_pack_sha256=hashlib.sha256(pack).hexdigest(),dashboard_pack_revision=DASHBOARD_PACK_REVISION)
        (folder/'faceplate.gif').write_bytes(data);(folder/'artwork-dashboard.rgb').write_bytes(pack)
        (folder/'manifest.json').write_text(json.dumps(manifest))
        (folder.parent.parent/'active.json').write_text(json.dumps(dict(schema=1,appid=620,mode='animated')))
        return library,folder,manifest,data,pack

    def test_archive_contains_exact_active_gif_and_pack_without_urls_or_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            library,folder,manifest,data,pack=self.library(Path(directory))
            library.auth_path.write_text('{"api_key":"SECRET-KEY"}')
            payload=creation_archive(library,620,'animated',manifest['sha256'])
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertEqual(set(archive.namelist()),{'creation.json','faceplate.gif','artwork-dashboard.rgb'})
                self.assertEqual(archive.read('faceplate.gif'),data);self.assertEqual(archive.read('artwork-dashboard.rgb'),pack)
                metadata=archive.read('creation.json');document=json.loads(metadata)
                self.assertTrue(document['active']);self.assertFalse(document['applied_as_defaults'])
                self.assertNotIn(b'SECRET',metadata);self.assertNotIn(str(folder).encode(),metadata)
                for name,digest in document['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)

    def test_stale_selection_tampered_pack_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            library,folder,manifest,_,_=self.library(Path(directory))
            with self.assertRaisesRegex(ValueError,'changed'):creation_archive(library,620,'animated','0'*64)
            (folder/'artwork-dashboard.rgb').write_bytes(bytes(64*54*3))
            with self.assertRaisesRegex(ValueError,'background changed'):creation_archive(library,620,'animated',manifest['sha256'])
            (folder/'faceplate.gif').unlink();(folder/'faceplate.gif').symlink_to(folder/'manifest.json')
            with self.assertRaisesRegex(ValueError,'linked'):creation_archive(library,620,'animated',manifest['sha256'])

    def test_home_artwork_uses_its_immutable_copy_after_game_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            library,folder,manifest,data,_=self.library(Path(directory))
            library.assign_home(620,'animated')
            replacement=encode_frame(bytes((70,80,90))*(64*54))
            (folder/'faceplate.gif').write_bytes(replacement)
            manifest['sha256']=hashlib.sha256(replacement).hexdigest();(folder/'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(library.selected(620)[0],replacement)
            self.assertEqual(library.home_selected(620)[0],data)

    def test_home_artwork_reaches_the_real_coordinator_with_home_copy_not_game_copy(self):
        fixture = native_fixture.NativeSceneTests('test_game_route_and_return_are_integrated_without_changing_preferences')
        fixture.setUp()
        try:
            library,folder,manifest,home_data,_ = self.library(fixture.root/'creation')
            library.assign_home(620,'animated')
            game_data=encode_frame(bytes((90,80,70))*(64*54))
            (folder/'faceplate.gif').write_bytes(game_data)
            manifest['sha256']=hashlib.sha256(game_data).hexdigest();(folder/'manifest.json').write_text(json.dumps(manifest))
            fixture.faceplate.steamgriddb=library
            fixture.settings.update({'faceplate_dashboard_home_appid':620})
            fixture.prefs.update(home_scene='artwork')
            with patch('signalbar.faceplate.transport.time.sleep'):
                fixture.engine._reconcile_faceplate('routing-change',force=True)
            self.assertEqual(fixture.engine.faceplate_router.status()['effective_scene'],'artwork')
            self.assertEqual(fixture.faceplate.delivery['signature'],hashlib.sha256(home_data).hexdigest())
            self.assertNotEqual(fixture.faceplate.delivery['signature'],hashlib.sha256(game_data).hexdigest())
        finally:
            fixture.doCleanups()

    def engine(self,root):
        settings=SettingsStore(str(root/'settings.json'));settings.update({'faceplate_lab_enabled':True})
        prefs=FaceplatePreferencesStore(root/'routes.json')
        engine=Engine(settings,str(root/'art.json'));self.addCleanup(engine.stop)
        engine.faceplate_preferences=prefs;engine.faceplate_router=FaceplateSceneRouter(prefs)
        engine._faceplate_power_target=None
        engine._faceplate_continuity=Mock(return_value=('',False))
        engine._configure_player_city=Mock()
        engine.faceplate_worker=Mock();engine.faceplate_worker.status.return_value={'busy':False,'queued':False,'ack_ema_ms':0}
        engine.faceplate_worker.submit.return_value=1
        engine._write_faceplate_runtime_status=Mock()
        engine._faceplate_weather_payload=Mock(return_value=(dict(condition='rain',variant=0,signature='weather-test',now='2026-10-25T10:30:00+01:00'),{},''))
        return engine,prefs

    def test_display_background_routes_generate_home_only_payload_and_keep_overlay_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine,prefs=self.engine(root)
            library,_,manifest,_,_=self.library(root);library.assign_home(620,'animated');engine.faceplate.steamgriddb=library
            engine.settings.update({'faceplate_dashboard_home_appid':620,'faceplate_dashboard_home_source':'weather',
                'faceplate_dashboard_contexts':{'home':{'show_weather':False,'show_bottom_row':False}}})
            for scene,kind in [('artwork','artwork'),('artwork-dashboard','artwork-dashboard'),('dashboard','dashboard'),('weather','weather')]:
                engine.update_faceplate_routing(scene,'player-city',prefs.read().revision)
                payload=engine.faceplate_worker.submit.call_args.args[1]
                self.assertEqual(payload['kind'],kind)
                self.assertEqual(prefs.read().game_scene,'player-city')
                if scene=='artwork':
                    self.assertTrue(payload['home_artwork']);self.assertEqual(payload['appid'],620)
                if scene=='artwork-dashboard':
                    self.assertTrue(payload['home_dashboard']);self.assertFalse(payload['show_weather_notch']);self.assertFalse(payload['dashboard_show_status_rail'])
            self.assertEqual(engine.settings.all()['faceplate_dashboard_home_appid'],620)
            self.assertEqual(engine.settings.all()['faceplate_dashboard_contexts']['home']['show_weather'],False)
            self.assertEqual(engine.settings.all()['faceplate_dashboard_home_source'],'weather')

    def test_missing_home_artwork_falls_back_and_stale_route_does_not_change_background(self):
        with tempfile.TemporaryDirectory() as directory:
            engine,prefs=self.engine(Path(directory))
            for scene,kind in [('artwork','weather'),('artwork-dashboard','dashboard')]:
                engine.update_faceplate_routing(scene,'artwork',prefs.read().revision)
                self.assertEqual(engine.faceplate_worker.submit.call_args.args[1]['kind'],kind)
            self.assertTrue(engine._faceplate_weather_required(engine.settings.all()))
            before=engine.settings.all()['faceplate_dashboard_home_source']
            with self.assertRaises(FaceplateRevisionConflict):engine.update_faceplate_routing('dashboard','artwork',0)
            self.assertEqual(engine.settings.all()['faceplate_dashboard_home_source'],before)

    def manager(self,root,version='1.4.1-lab.237'):
        return UpdateManager(version,SettingsStore(str(root/'settings.json')),str(root/'runtime'),str(root/'plugin'),Mock(),private_auth=FakePrivateAuth())


    def test_local_creation_export_is_private_and_never_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();helper=baseline_tests.ConfigurationBackup236();engine,diagnostics=helper.fixture(root)
            plugin,module=helper.plugin(engine,diagnostics,root)
            library,_,manifest,_,_=self.library(root/'creations');engine.faceplate.steamgriddb=library
            result=asyncio.run(plugin.export_creation(620,'animated',manifest['sha256']))
            data=Path(result['path']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),result['digest'])
            self.assertEqual(Path(result['path']).stat().st_mode&0o777,0o600)
            plugin.update_manager.upload_creation_archive.assert_not_called()
            with patch('signalbar.faceplate.creation_transfer.creation_archive') as capture:
                with self.assertRaises(RuntimeError):asyncio.run(plugin.save_creation_to_github(620,'animated',manifest['sha256']))
                capture.assert_not_called()
