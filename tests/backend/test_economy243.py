"""One Economy control owns battery precision and all GIF Dashboard clock paths."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile
import unittest
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.faceplate.artwork_dashboard import quantize_battery
import test_native_clock as native

class WallClock(datetime):
    instant=datetime(2026,10,25,14,3,20,tzinfo=timezone.utc)
    @classmethod
    def now(cls,tz=None):return cls.instant

class Economy243Tests(unittest.TestCase):
    def test_single_master_controls_clock_boundaries_and_legacy_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(str(Path(directory)/'config.json'))
            for enabled in (True,False):
                values=store.update({'faceplate_flash_protection_enabled':enabled})
                interval=Engine._faceplate_refresh_interval(values)
                self.assertEqual(5 if enabled else 1,interval)
                self.assertEqual('economy' if enabled else 'minute',values['faceplate_artwork_dashboard_refresh'])
                target,_=Engine._faceplate_dashboard_target(WallClock.instant,interval_minutes=interval)
                self.assertEqual('14:00' if enabled else '14:03',target.strftime('%H:%M'))
                self.assertEqual(75 if enabled else 77,quantize_battery(77,step=interval)['percent'])
                other='minute' if enabled else 'economy'
                self.assertEqual(values['faceplate_artwork_dashboard_refresh'],store.update({'faceplate_artwork_dashboard_refresh':other})['faceplate_artwork_dashboard_refresh'])

    def test_five_minute_clock_lead_stays_bounded_across_midnight(self):
        for text,expected in [('2026-10-25T14:04:20+00:00','14:00'),('2026-10-25T14:04:58+00:00','14:05'),('2026-10-25T23:59:58+00:00','00:00')]:
            target,lead=Engine._faceplate_dashboard_target(datetime.fromisoformat(text),interval_minutes=5)
            self.assertEqual(expected,target.strftime('%H:%M'));self.assertLessEqual(lead,10)

    def test_live_dashboard_weather_artwork_and_neutral_paths_follow_the_master(self):
        for mode in ('weather','artwork','neutral'):
            for enabled in (True,False):
                with self.subTest(mode=mode,economy=enabled):
                    f=native.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight');f.setUp()
                    try:
                        f.settings.update({'faceplate_flash_protection_enabled':enabled,'faceplate_dashboard_show_clock':True,
                            'faceplate_dashboard_home_source':'artwork' if mode=='artwork' else 'weather',
                            'faceplate_dashboard_home_appid':620 if mode=='artwork' else 0})
                        f.prefs.update(home_scene='dashboard');f.engine._faceplate_power_target=None
                        f.engine._faceplate_continuity=Mock(return_value=('',False))
                        f.engine.faceplate_worker.submit.side_effect=lambda *args:1
                        f.engine.weather.status=Mock(return_value={'phase':'off','condition':'','sunrise_at':'','sunset_at':'','faceplate_weather_state':'unavailable'})
                        weather={'signature':'stable-weather','now':WallClock.instant.isoformat(),'sunrise':'2026-10-25T07:00:00+00:00','sunset':'2026-10-25T19:00:00+00:00','temperature_c':18,'condition':'clear','unit':'celsius'}
                        f.engine._faceplate_weather_payload=Mock(return_value=(None if mode=='neutral' else weather,{},''))
                        if mode=='artwork':
                            f.engine.faceplate.steamgriddb.home_dashboard_manifest=Mock(return_value={'dashboard_pack_sha256':'source-artwork'})
                        with patch('signalbar.backend.engine.datetime',WallClock):f.engine._reconcile_faceplate('settings',force=True)
                        payload=f.engine.faceplate_worker.submit.call_args.args[1]
                        expected=WallClock.instant if mode=='weather' else WallClock.instant.astimezone()
                        expected=expected.replace(minute=0 if enabled else 3)
                        self.assertEqual(expected.strftime('%H:%M'),datetime.fromisoformat(payload['display_at']).strftime('%H:%M'))
                        self.assertTrue(payload['dashboard_show_clock'])
                    finally:f.doCleanups()

    def test_in_game_artwork_cadence_uses_economy_not_the_legacy_field(self):
        from signalbar.models import GameState
        for enabled in (True,False):
            f=native.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight');f.setUp()
            try:
                f.settings.update({'faceplate_flash_protection_enabled':enabled})
                f.prefs.update(game_scene='artwork-dashboard');f.engine._game=GameState(620,'Portal')
                f.engine._faceplate_power_target=None;f.engine._faceplate_continuity=Mock(return_value=('',False))
                f.engine.controllers.primary_battery=Mock(return_value={'percent':77,'charging':False})
                f.engine.faceplate_worker.submit.side_effect=lambda *args:1
                f.engine.faceplate.steamgriddb.selected_dashboard_manifest=Mock(return_value={'dashboard_pack_sha256':'ready'})
                with patch('signalbar.backend.engine.datetime',WallClock):f.engine._reconcile_faceplate('settings',force=True)
                payload=f.engine.faceplate_worker.submit.call_args.args[1];metadata=f.engine.faceplate_worker.submit.call_args.args[2]
                self.assertEqual('economy' if enabled else 'minute',payload['refresh_policy'])
                self.assertEqual(300 if enabled else 60,metadata['upload_interval_seconds'])
                self.assertEqual(75 if enabled else 77,payload['battery']['percent'])
            finally:f.doCleanups()

    def test_economy_starts_enabled_on_real_first_install_and_reset_but_keeps_opt_out(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            store=SettingsStore(str(path),first_install_defaults=True)
            self.assertTrue(store.all()['faceplate_flash_protection_enabled'])
            self.assertEqual('economy',store.all()['faceplate_artwork_dashboard_refresh'])
            store.update({'faceplate_flash_protection_enabled':False})
            reloaded=SettingsStore(str(path),first_install_defaults=True)
            self.assertFalse(reloaded.all()['faceplate_flash_protection_enabled'])
            self.assertTrue(reloaded.reset_configuration()['faceplate_flash_protection_enabled'])
