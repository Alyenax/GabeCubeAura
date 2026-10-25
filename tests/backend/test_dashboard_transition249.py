"""Regression: Weather -> Artwork Dashboard with provider-local timestamps."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import shutil
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from signalbar.backend import Engine
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate, DASHBOARD_PACK_REVISION
from signalbar.models import GameState
from signalbar.settings import SettingsStore


class DashboardTransition249Tests(unittest.TestCase):
    def exercise(self, *, zoned=False, via_artwork=False, apply=False, remove=False):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            root=Path(__file__).resolve().parents[2]
            library=SteamGridDBFaceplate(state/'library')
            faceplate=FaceplateCoordinator(root/'assets/faceplate',state/'panel.json',
                steamgriddb=library,port_finder=lambda:'/test/faceplate')
            store=SettingsStore(str(state/'settings.json'),first_install_defaults=True)
            store.update({'onboarding_completed':True,'faceplate_setup_completed':True,
                'faceplate_dashboard_home_appid':1332010,'faceplate_dashboard_home_source':'artwork'})
            prefs=FaceplatePreferencesStore(state/'routes.json')
            engine=Engine(store,str(state/'cache.json'),faceplate=faceplate,
                faceplate_preferences=prefs,faceplate_runtime_path=state/'runtime.json')
            # Use a synthetic personal creation, with no bundled starter.
            if not library.home_dashboard_manifest(1332010):
                prepared=library._prepared_root(1332010,'animated');prepared.mkdir(parents=True)
                rgb=bytes((20,170,70))*3456;gif=encode_frame(rgb)
                (prepared/'faceplate.gif').write_bytes(gif)
                (prepared/'artwork-dashboard.rgb').write_bytes(rgb)
                (prepared/'manifest.json').write_text(json.dumps({'schema':2,'appid':1332010,
                    'mode':'animated','ready':True,'frames':1,'sha256':hashlib.sha256(gif).hexdigest(),
                    'dashboard_pack':'artwork-dashboard.rgb','dashboard_pack_frames':1,
                    'dashboard_pack_sha256':hashlib.sha256(rgb).hexdigest(),
                    'dashboard_pack_revision':DASHBOARD_PACK_REVISION}))
                library.assign_home(1332010,'animated')
            engine.faceplate_worker.stop()
            worker=Mock();worker.status.return_value={'busy':False,'queued':False,
                'handler_ema_ms':0,'ack_ema_ms':0};worker.submit.return_value=1
            engine.faceplate_worker=worker;engine._game=GameState()
            suffix='+01:00' if zoned else ''
            engine.weather.status=Mock(return_value={'condition':'rain','temperature_c':14,
                'faceplate_weather_state':'fresh','sunrise_at':'2026-10-25T07:30:00'+suffix,
                'sunset_at':'2026-10-25T18:00:00'+suffix,'utc_offset_seconds':3600,
                'is_day':True})
            with patch.dict(sys.modules,{'decky':types.ModuleType('decky')}):
                spec=importlib.util.spec_from_file_location('transition249_main',root/'main.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            plugin=module.Plugin();plugin.engine=engine;plugin.diagnostics=Mock()
            plugin.faceplate_artwork_jobs=Mock()
            plugin.faceplate_artwork_jobs.status.return_value={'state':'idle'}
            try:
                self.assertIsNotNone(engine._faceplate_weather_payload(store.all(),False)[0])
                self.assertTrue(library.home_dashboard_manifest(1332010))
                asyncio.run(plugin.set_faceplate_routing('dashboard','artwork',prefs.read().revision))
                self.assertEqual(worker.submit.call_args.args[1]['kind'],'dashboard')
                weather_target=engine._faceplate_dashboard_target_minute
                self.assertEqual(weather_target.utcoffset() is not None,zoned)
                if via_artwork:
                    asyncio.run(plugin.set_faceplate_routing('artwork','artwork',prefs.read().revision))
                    self.assertIsNone(engine._faceplate_dashboard_target_minute)
                if apply:
                    selected=library.home_selected(1332010)[1]
                    mode=selected['mode']
                    shutil.copytree(library._prepared_root(1332010,mode,home=True),
                        library._prepared_root(1332010,mode),dirs_exist_ok=True)
                    asyncio.run(plugin.assign_faceplate_dashboard_artwork(
                        1332010,mode,False,True,selected['sha256'],False))
                else:
                    asyncio.run(plugin.set_faceplate_routing('artwork-dashboard','artwork',prefs.read().revision))
                payload=worker.submit.call_args.args[1]
                self.assertEqual(payload['kind'],'artwork-dashboard')
                self.assertTrue(payload['home_dashboard'])
                self.assertEqual(prefs.read().home_scene,'artwork-dashboard')
                self.assertEqual(engine._faceplate_configuration_error,'')
                self.assertTrue(engine.status()['faceplate']['home_artwork_prepared'])
                if remove:
                    for item in library.artwork_root.iterdir():
                        if item.is_dir():shutil.rmtree(item)
                        else:item.unlink()
                    engine.refresh_faceplate('artwork-library-delete')
                    self.assertFalse(engine.status()['faceplate']['home_artwork_prepared'])
                    with patch.object(library,'home_dashboard_manifest',side_effect=AssertionError('Status must not scan the library')):
                        self.assertFalse(engine.status()['faceplate']['home_artwork_prepared'])
                        self.assertFalse(engine.faceplate_delivery_status()['home_artwork_prepared'])
                # The reverse transition must also work without a reset/detour.
                asyncio.run(plugin.set_faceplate_routing('dashboard','artwork',prefs.read().revision))
                self.assertEqual(worker.submit.call_args.args[1]['kind'],'dashboard')
                self.assertEqual(engine._faceplate_dashboard_target_minute.utcoffset() is not None,zoned)
            finally:
                engine.stop()

    def test_removed_creation_cannot_be_hidden_by_a_stale_home_appid(self):
        self.exercise(remove=True)

    def test_direct_switch_and_return_with_provider_wall_time(self):
        self.exercise()

    def test_direct_switch_and_return_with_zoned_provider(self):
        self.exercise(zoned=True)

    def test_existing_detour_still_works(self):
        self.exercise(via_artwork=True)

    def test_home_apply_from_weather_uses_the_same_corrected_transition(self):
        self.exercise(apply=True)

    def test_nonregression_is_preserved_inside_each_clock_domain(self):
        naive=datetime(2026,10,25,14,18)
        aware=naive.replace(tzinfo=timezone(timedelta(hours=1)))
        for previous in (naive,aware):
            with self.subTest(previous=previous):
                self.assertEqual(Engine._faceplate_dashboard_nonregressing(
                    previous-timedelta(minutes=1),previous),previous)
                self.assertEqual(Engine._faceplate_dashboard_nonregressing(
                    previous+timedelta(minutes=1),previous),previous+timedelta(minutes=1))
        self.assertEqual(Engine._faceplate_dashboard_nonregressing(aware,naive),aware)
        self.assertEqual(Engine._faceplate_dashboard_nonregressing(naive,aware),naive)
