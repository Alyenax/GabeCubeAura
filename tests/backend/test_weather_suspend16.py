"""Separate animation, suspend-inclusive and civil clocks using the real worker."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from signalbar.providers import weather
from signalbar.providers.weather import WeatherProvider
from signalbar.settings.store import DEFAULTS
from signalbar.backend import Engine

CITY = {'name':'Test', 'latitude':0.0, 'longitude':0.0}
SAMPLE = {'condition':'clear_night','is_day':False,'weather_code':0,
          'observed_at':'2026-11-08T00:00','temperature_c':12.0}
VALUES = dict(DEFAULTS, weather_location=CITY, weather_display='home', night_mode_enabled=True)

class Clocks:
    def __init__(self):self.mono=100.;self.boot=1000.;self.wall=1000000.
    def advance(self, seconds, asleep=False):
        self.boot+=seconds;self.wall+=seconds
        if not asleep:self.mono+=seconds

class SuspendTests(unittest.TestCase):
    def provider(self, clocks, fetch=None, **kwargs):
        p=WeatherProvider(clock=lambda:clocks.mono, elapsed_clock=lambda:clocks.boot,
            wall_clock=lambda:clocks.wall, fetch=fetch or Mock(return_value=dict(SAMPLE)), **kwargs)
        p.configure(CITY,'home');return p

    def cycle(self, p, on_wait=None):
        """Run the real worker synchronously, stopping at its next idle wait."""
        waits=[]
        class Wake:
            def set(self):pass
            def clear(self):pass
            def wait(self, seconds):
                waits.append(seconds)
                if on_wait:on_wait()
                p._stop.set()
        p._stop.clear();p._wake=Wake();p._run();return waits

    def test_eight_hour_sleep_expires_all_live_consumers_in_one_clock_domain(self):
        c=Clocks();p=self.provider(c);self.cycle(p);c.advance(28800,asleep=True)
        s=p.status(VALUES)
        self.assertEqual(s['age_s'],28800);self.assertEqual(s['phase'],'waiting')
        self.assertIsNone(s['temperature_c']);self.assertEqual(s['faceplate_weather_state'],'background-only')
        self.assertFalse(s['night_mode_active']);self.assertFalse(p.solar_status(VALUES)['available'])
        self.assertIsNone(p.output(VALUES).frame)
        self.assertGreaterEqual(c.boot,p._next_fetch)

    def test_short_sleep_ages_cache_but_preserves_valid_temperature_and_night(self):
        c=Clocks();p=self.provider(c);self.cycle(p);c.advance(120,asleep=True)
        s=p.status(VALUES);self.assertEqual(s['age_s'],120)
        self.assertEqual(s['temperature_c'],12);self.assertTrue(s['night_mode_active'])
        self.assertEqual(s['faceplate_weather_state'],'fresh');self.assertIsNotNone(p.output(VALUES).frame)
        self.assertEqual(p._next_fetch-c.boot,780)

    def test_no_resume_notification_still_refreshes_an_overdue_deadline(self):
        c=Clocks();fetch=Mock(return_value=dict(SAMPLE));p=self.provider(c,fetch)
        self.cycle(p);c.advance(28800,asleep=True);fetch.return_value=dict(SAMPLE,is_day=True,condition='clear_day',temperature_c=19)
        self.cycle(p)
        self.assertEqual(fetch.call_count,2);s=p.status(VALUES)
        self.assertEqual(s['age_s'],0);self.assertEqual(s['temperature_c'],19);self.assertFalse(s['night_mode_active'])

    def test_short_sleep_without_notification_does_not_fetch_before_deadline(self):
        c=Clocks();fetch=Mock(return_value=dict(SAMPLE));p=self.provider(c,fetch)
        self.cycle(p);c.advance(60,asleep=True)
        self.assertEqual(self.cycle(p),[30]);self.assertEqual(fetch.call_count,1)
        c.advance(840,asleep=True);self.cycle(p);self.assertEqual(fetch.call_count,2)

    def test_explicit_short_resume_requests_refresh_without_network_in_callback(self):
        c=Clocks();fetch=Mock(return_value=dict(SAMPLE));p=self.provider(c,fetch);self.cycle(p)
        c.advance(5,asleep=True);self.assertTrue(p.request_refresh());self.assertEqual(fetch.call_count,1)
        self.cycle(p);self.assertEqual(fetch.call_count,2)

    def test_zero_elapsed_timestamp_is_a_valid_fresh_sample(self):
        c=Clocks();c.boot=0;p=self.provider(c);self.cycle(p)
        self.assertEqual(p.status(VALUES)['age_s'],0);self.assertEqual(p.status(VALUES)['temperature_c'],12)

    def test_civil_clock_changes_do_not_change_boottime_age_or_network_deadline(self):
        c=Clocks();p=self.provider(c);self.cycle(p);deadline=p._next_fetch
        for jump in [-86400,172800,-86400]:
            c.wall+=jump;c.advance(10)
            self.assertEqual(p._next_fetch,deadline)
            self.assertEqual(p.status(VALUES)['age_s'],c.boot-1000)
        self.assertEqual(p.status(VALUES)['age_s'],30)

    def test_cache_age_is_converted_once_then_keeps_aging_during_sleep(self):
        c=Clocks()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'weather.json';self.provider(c,cache_path=cache)._persist_cached(CITY,SAMPLE)
            c.advance(4000,asleep=True);p=self.provider(c,cache_path=cache)
            self.assertEqual(p.status(VALUES)['age_s'],4000)
            self.assertEqual(p.status(VALUES)['faceplate_weather_state'],'cached')
            self.assertIsNone(p.status(VALUES)['temperature_c'])
            c.advance(4000,asleep=True)
            self.assertEqual(p.status(VALUES)['faceplate_weather_state'],'background-only')
            self.assertFalse(p.status(VALUES)['night_mode_active'])

    def test_failed_fetch_keeps_original_cache_age_across_sleep(self):
        c=Clocks();fetch=Mock(return_value=dict(SAMPLE));p=self.provider(c,fetch);self.cycle(p)
        c.advance(28800,asleep=True);fetch.side_effect=OSError('offline');self.cycle(p)
        self.assertEqual(p.status(VALUES)['age_s'],28800);self.assertIsNone(p.status(VALUES)['temperature_c'])
        self.assertEqual(p._next_fetch-c.boot,30)

    def test_pre_refresh_response_cannot_replace_current_generation(self):
        c=Clocks();calls=[];p=None
        def fetch(city):
            calls.append(dict(city))
            if len(calls)==1:
                c.advance(28800,asleep=True);p.request_refresh();return dict(SAMPLE,temperature_c=99)
            self.assertIsNone(p._sample);return dict(SAMPLE,temperature_c=20)
        p=self.provider(c,fetch);self.cycle(p)
        self.assertEqual(len(calls),2);self.assertEqual(p.status(VALUES)['temperature_c'],20)

    def test_pre_refresh_failure_cannot_consume_the_new_generations_retry_budget(self):
        c=Clocks();calls=[];p=None
        def fetch(city):
            calls.append(1)
            if len(calls)==1:p.request_refresh();raise OSError('old request')
            return dict(SAMPLE)
        p=self.provider(c,fetch);self.cycle(p)
        self.assertEqual(len(calls),2);self.assertIsNone(p._retry_deadline);self.assertEqual(p._error,'')

    def test_resume_notifications_do_not_reset_an_exhausted_outage_window(self):
        c=Clocks();p=self.provider(c,Mock(side_effect=OSError('offline')));self.cycle(p);deadline=p._retry_deadline
        c.advance(301,asleep=True);p.request_refresh();self.cycle(p)
        self.assertEqual(p._retry_deadline,deadline);self.assertEqual(p._next_fetch-c.boot,900)

    def test_animation_preview_keeps_its_monotonic_phase_when_freshness_time_advances(self):
        c=Clocks();p=self.provider(c);self.assertTrue(p.preview('rain',0))
        before=p.status(VALUES)['preview_remaining_s'];c.advance(28800,asleep=True)
        self.assertEqual(p.status(VALUES)['preview_remaining_s'],before)
        self.assertTrue(p.status(VALUES)['preview_active'])

    def test_disabled_weather_stays_inactive_after_resume(self):
        c=Clocks();fetch=Mock();p=self.provider(c,fetch);p.configure(CITY,'off')
        self.assertFalse(p.request_refresh());self.cycle(p);fetch.assert_not_called()

    def test_refresh_signal_delivered_before_wait_is_not_cleared_afterwards(self):
        c=Clocks();p=self.provider(c);self.cycle(p)
        events=[]
        class Wake:
            def clear(self):events.append('clear')
            def set(self):events.append('set')
            def wait(self, seconds):
                p.request_refresh();events.append('wait-return');p._stop.set()
        p._stop.clear();p._wake=Wake();p._run()
        self.assertEqual(events,['clear','set','wait-return'])

    def test_default_linux_clock_uses_boottime_and_preserves_animation_clock(self):
        with patch.object(weather.time,'CLOCK_BOOTTIME',777,create=True), patch.object(weather.time,'clock_gettime',return_value=4321,create=True) as boot:
            p=WeatherProvider()
            self.assertIs(p._clock,weather.time.monotonic);self.assertEqual(p._elapsed_clock(),4321)
            boot.assert_called_with(777)

    def test_paired_fallback_counts_sleep_without_rejuvenation_on_wall_rollback(self):
        c=Clocks();p=WeatherProvider(clock=lambda:c.mono,wall_clock=lambda:c.wall)
        p.configure(CITY,'home');p._sample=dict(SAMPLE);p._fetched_at=p._elapsed_clock()
        c.advance(28800,asleep=True);self.assertEqual(p.status(VALUES)['age_s'],28800)
        c.wall-=28800;self.assertEqual(p.status(VALUES)['age_s'],28800)

    def test_resume_requests_weather_before_all_nonautomatic_panel_early_returns(self):
        for enabled,mode,control in [(False,'auto','automatic'),(True,'manual','automatic'),(True,'auto','other-app')]:
            with self.subTest(enabled=enabled,mode=mode,control=control):
                e=object.__new__(Engine);e.weather=Mock();e.countdown=Mock();e.faceplate_worker=Mock()
                e.settings=Mock();e.settings.all.return_value=dict(DEFAULTS,faceplate_lab_enabled=enabled,faceplate_power_mode=mode,faceplate_control_mode=control)
                e.set_screen_sync_context=Mock();e._assistant_wake_policy=Mock(return_value=False)
                e._apply_faceplate_power=Mock()
                self.assertTrue(e.resume_faceplate()['skipped']);e.weather.request_refresh.assert_called_once_with("steam-resume")
                e._apply_faceplate_power.assert_not_called()

    def test_manually_powered_off_panel_stays_off_through_system_resume(self):
        import test_native_clock as fixtures
        f=fixtures.NativeSceneTests();f.setUp();self.addCleanup(f.doCleanups);e=f.engine
        e._reconcile_faceplate=Mock()
        self.assertTrue(e.set_faceplate_power(False)['ok'])
        e.suspend_faceplate('sleep');f.calls.clear()
        e.weather.request_refresh=Mock()
        self.assertTrue(e.resume_faceplate()['skipped'])
        e.weather.request_refresh.assert_called_once_with("steam-resume")
        from signalbar.faceplate import protocol
        self.assertNotIn(protocol.power(True),f.calls)

if __name__=='__main__':unittest.main()
