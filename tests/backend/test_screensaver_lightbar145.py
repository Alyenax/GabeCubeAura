"""Actual bounded decode/projection and settings. No physical LED/Steam proof."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from signalbar.settings import SettingsStore
from signalbar.faceplate.gif import encode
from signalbar.faceplate.steamgriddb import PALETTE_332
from signalbar.faceplate.source_projection import project_backgrounds
from signalbar.faceplate.screensaver_projection import ScreensaverProjection,prepare,whole_frame
from signalbar.backend import Engine
from signalbar.models import GameState
import test_broker_adapter as fixtures

class Lightbar145Tests(unittest.TestCase):
    def test_both_mappings_fractional_bins_match_existing_extension_exactly(self):
        indices=bytes((x+y)%256 for y in range(54) for x in range(64))
        rgb=bytes(c for index in indices for c in PALETTE_332[index])
        for mapping in ('whole','bottom'):
            self.assertEqual(whole_frame(indices,mapping),bytes(c for pixel in project_backgrounds((rgb,),mapping) for c in pixel))

    def test_switch_routing_mapping_live_uses_cached_profiles_without_reencoding(self):
        # Red above a blue bottom edge: the two configured views must differ.
        indices=bytes([224])*(64*46)+bytes([3])*(64*8)
        data=encode(64,54,PALETTE_332,[indices,indices],delay_cs=[100,100])
        digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'content.gif';path.write_bytes(data)
            cache=ScreensaverProjection();self.addCleanup(cache.stop);cache.prepare(digest,path)
            self.assertEqual(cache.snapshot()['state'],'ready')
            whole=cache.output(digest,1,'whole');bottom=cache.output(digest,1,'bottom')
            self.assertNotEqual(whole,bottom);self.assertEqual(bottom,((0,0,255),)*17)
            self.assertEqual(cache.output(digest,5,'whole'),whole)
            self.assertIsNone(cache.process)

    def test_real_isolated_projection_plays_all_frames_and_repeats_without_usb(self):
        data=encode(64,54,PALETTE_332,[bytes([224])*3456,bytes([3])*3456],delay_cs=[100,200])
        digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'content.gif';path.write_bytes(data)
            cache=ScreensaverProjection();self.addCleanup(cache.stop);cache.prepare(digest,path)
            self.assertEqual(cache.snapshot(),{'state':'ready','cached_collections':1,'error':''})
            for n in range(201):
                self.assertEqual(cache.output(digest,n*3),(tuple(PALETTE_332[224]),)*17)
                self.assertEqual(cache.output(digest,n*3+1),(tuple(PALETTE_332[3]),)*17)
            self.assertIsNone(cache.output('not-registered',0))
            self.assertEqual(prepare(path,digest)['duration_cs'],300)
            with self.assertRaises(ValueError):prepare(path,'0'*64)

    def test_malformed_sidecar_and_cache_growth_are_bounded(self):
        cache=ScreensaverProjection();self.addCleanup(cache.stop)
        for value in ({},{'rows':[[1,'bad']],'duration_cs':1},{'rows':[[1,'00'*51]],'duration_cs':2}):
            with self.assertRaises(ValueError):cache.install('a',value)
        for n in range(8):cache.install(str(n),{'rows':[[1,'00'*51]],'duration_cs':1})
        self.assertEqual(cache.snapshot()['cached_collections'],4)
        cache.stop();self.assertIsNone(cache.output('7',0))

    def test_legacy_migration_and_dropdown_do_not_change_home_game_or_brightness(self):
        for legacy in (False,True):
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'settings.json';path.write_text(json.dumps({'screen_sync_screensaver_enabled':legacy}))
                store=SettingsStore(str(path));before=store.all()
                self.assertEqual(before['screensaver_light_bar_mode'],'screen_sync' if legacy else 'none')
                for mode in ('faceplate_extension','none','screen_sync'):
                    store.update({'screensaver_light_bar_mode':mode});after=store.all()
                    self.assertEqual(after['screen_sync_screensaver_enabled'],mode=='screen_sync')
                    for key in ('home_display','game_display','light_bar_day_brightness','faceplate_extension_mapping'):
                        self.assertEqual(after[key],before[key])
                store.update({'screen_sync_screensaver_enabled':False})
                self.assertEqual(store.all()['screensaver_light_bar_mode'],'none')

    def test_adapter_only_plays_confirmed_current_scene_and_clears_on_cancel(self):
        f=fixtures.BrokerAdapterTests();f.setUp();self.addCleanup(f.tearDown)
        f.adapter.projection.install(f.job['content_id'],{'rows':[[100,'ff0000'*17]],'duration_cs':100})
        self.assertIsNone(f.adapter.extension_frame(f.clock()))
        f.start();self.assertEqual(f.adapter.extension_frame(f.clock()),((255,0,0),)*17)
        for _ in range(301):
            f.clock.now+=2;f.adapter.observe_steam(True,source='poll')
            self.assertEqual(f.adapter.extension_frame(f.clock()),((255,0,0),)*17)
        f.adapter.cancel('operation');self.assertIsNone(f.adapter.extension_frame(f.clock()))
        f.adapter.observe_steam(False,source='notification')
        observations=f.adapter.diagnostic_snapshot()['steam_observations']
        self.assertEqual(observations[-1]['source'],'notification')
        self.assertEqual(observations[-1]['observed'],'inactive')

    def test_delegated_led_output_never_reads_pixels_or_mutates_source_settings(self):
        engine=object.__new__(Engine);engine.faceplate_extension=Mock()
        engine._faceplate_suspended=False;engine._faceplate_extension_present=True
        engine.faceplate=Mock(powered=True)
        engine.jsaux_broker_adapter=Mock();engine.jsaux_broker_adapter.holds_display.return_value=True
        engine.jsaux_broker_adapter.extension_frame.return_value=((10,20,30),)*17
        result=engine._faceplate_extension_output({'faceplate_lab_enabled':True,'faceplate_extension_saturation':100,'faceplate_extension_mapping':'bottom'},GameState(0,''),'customization',123,screensaver=True)
        self.assertEqual(result.frame,((10,20,30),)*17)
        engine.faceplate_extension.configure.assert_not_called()
        engine.jsaux_broker_adapter.extension_frame.assert_called_once_with(123,'bottom')
