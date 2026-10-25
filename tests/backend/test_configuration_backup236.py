"""Complete reference snapshots and explicit, byte-exact private uploads."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from signalbar.settings import SettingsStore
from signalbar.settings.store import DEFAULTS
from signalbar.settings.export import build_configuration_export, configuration_bytes, read_configuration_import
from signalbar.settings.baseline import collect_sources, validate_complete_baseline, SOURCES
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate
from signalbar.core.profiles import Profiles
from signalbar.updates import UpdateManager, UpdateError
from test_updates import FakePrivateAuth, FakeResponse


class ConfigurationBackup236(unittest.TestCase):
    def fixture(self,root):
        store=SettingsStore(str(root/'settings.json'))
        store.update({'faceplate_player_city_row':'count','weather_snow_day_variant':0,
                      'weather_snow_night_variant':1,'ui_language':'fr'})
        store.update_display(620,'faceplate_extension')
        prefs=FaceplatePreferencesStore(root/'faceplate.json')
        prefs.update(home_scene='weather',game_scene='player-city')
        ambience=Profiles(root,store,Mock())
        ambience.save('Evening',{'light_bar_day_brightness':5})
        library=SteamGridDBFaceplate(root=root/'library')
        library.set_preference('static')
        app=library.artwork_root/'620'; prepared=app/'prepared/static';prepared.mkdir(parents=True)
        (app/'active.json').write_text(json.dumps(dict(schema=1,appid=620,mode='static')))
        (prepared/'manifest.json').write_text(json.dumps(dict(schema=2,appid=620,asset_id=42,mode='static',
            crop_x=17,crop_y=83,saturation=126,brightness=91,logo_position='top',
            dashboard_clock_size='large',dashboard_show_clock=False,source_url='SECRET-URL')))
        (prepared/'faceplate.gif').write_bytes(b'MEDIA-MUST-NOT-BE-UPLOADED')
        library.auth_path.write_text('{"api_key":"API-SECRET"}')
        engine=SimpleNamespace(settings=store,faceplate_preferences=prefs,ambience=ambience,
            faceplate=SimpleNamespace(steamgriddb=library),status=Mock(return_value={'version':'1.4.1-lab.236','game':{'appid':620}}))
        diagnostics=SimpleNamespace(status=lambda:{'automatic_upload':False})
        return engine,diagnostics

    def document(self,engine,diagnostics):
        return build_configuration_export(engine.settings,'1.4.1-lab.236',{'appid':620},
            sources=collect_sources(engine,diagnostics))

    def plugin(self,engine,diagnostics,root):
        with patch.dict(sys.modules,{'decky':ModuleType('decky')}):
            spec=importlib.util.spec_from_file_location('configuration_backup_plugin',Path(__file__).resolve().parents[2]/'main.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        plugin=module.Plugin();plugin.engine=engine;plugin.diagnostics=diagnostics
        plugin.configuration_export_path=root/'Documents/configuration.json';plugin.update_manager=Mock()
        return plugin,module

    def test_all_persisted_settings_and_independent_stores_are_present_without_preview_or_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            engine,diagnostics=self.fixture(Path(directory))
            saved=engine.settings.base_all()
            engine.settings.set_overlay({'light_bar_day_brightness':1})
            before=engine.faceplate_preferences.path.read_bytes()
            document=self.document(engine,diagnostics)
            reference=validate_complete_baseline(document)
            self.assertEqual(reference['settings'],saved)
            self.assertEqual(set(reference['settings']),set(DEFAULTS))
            self.assertEqual(reference['coverage']['sources_included'],list(SOURCES))
            self.assertEqual(reference['faceplate_preferences']['routes'],{'home':'weather','game':'player-city'})
            self.assertEqual(next(iter(reference['ambience_profiles'].values()))['name'],'Evening')
            art=reference['artwork_library']['games']['620']
            self.assertEqual(art['prepared']['game/static']['crop_y'],83)
            self.assertEqual(reference['artwork_library']['preference'],'static')
            self.assertEqual(reference['settings']['display_preset'],saved['display_preset'])
            self.assertEqual(document['configuration']['global']['display_preset'],'custom')
            text=configuration_bytes(document).decode()
            for secret in ('API-SECRET','SECRET-URL','MEDIA-MUST-NOT-BE-UPLOADED'):
                self.assertNotIn(secret,text)
            self.assertEqual(engine.faceplate_preferences.path.read_bytes(),before)

    def test_missing_keys_or_sources_cannot_claim_complete_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            engine,diagnostics=self.fixture(Path(directory));document=self.document(engine,diagnostics)
            for mutate in (lambda d:d['calibration_reference']['settings'].pop('faceplate_player_city_row'),
                           lambda d:d['calibration_reference'].pop('faceplate_preferences'),
                           lambda d:d['calibration_reference']['coverage'].update(sources_not_collected=['support'])):
                broken=deepcopy(document);mutate(broken)
                with self.assertRaises(ValueError):validate_complete_baseline(broken)

    def test_rpc_exports_complete_json_off_event_loop_and_keeps_legacy_import_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine,diagnostics=self.fixture(root);plugin,_=self.plugin(engine,diagnostics,root)
            caller=threading.get_ident();threads=[]
            original=plugin._configuration_snapshot
            def collect():threads.append(threading.get_ident());return original()
            plugin._configuration_snapshot=collect
            result=asyncio.run(plugin.export_configuration())
            payload=Path(result['path']).read_bytes()
            self.assertNotEqual(threads,[caller]);validate_complete_baseline(json.loads(payload))
            self.assertEqual(result['digest'],hashlib.sha256(payload).hexdigest())
            values,display,_,_=read_configuration_import(result['path'])
            self.assertEqual(values['faceplate_player_city_row'],'count');self.assertIn('620',display)
            plugin.update_manager.upload_configuration_backup.assert_not_called()


    def test_public_rpc_refuses_before_reading_or_writing_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine,diagnostics=self.fixture(root);plugin,module=self.plugin(engine,diagnostics,root)
            with patch.object(module,'__version__','1.4.1'),self.assertRaises(RuntimeError):
                asyncio.run(plugin.save_configuration_to_github())
            engine.status.assert_not_called();plugin.update_manager.upload_configuration_backup.assert_not_called()
            self.assertFalse((root/'Documents').exists())

    def manager(self,root,version='1.4.1-lab.236'):
        return UpdateManager(version,SettingsStore(str(root/'config.json')),str(root/'runtime'),str(root/'plugin'),Mock(),private_auth=FakePrivateAuth())



    def test_corrupt_or_linked_artwork_metadata_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);engine,_=self.fixture(root);library=engine.faceplate.steamgriddb
            file=library.artwork_root/'620/prepared/static/manifest.json';file.write_text('{')
            with self.assertRaises(ValueError):library.configuration_snapshot()
            file.unlink();file.symlink_to(root/'settings.json')
            with self.assertRaises(ValueError):library.configuration_snapshot()



if __name__=='__main__':unittest.main()
