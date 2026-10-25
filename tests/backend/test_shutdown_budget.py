"""Decky unload shares one wait budget; cancellation survives exhaustion."""
import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from signalbar.shutdown import ShutdownBudget
from signalbar.providers.weather import WeatherProvider
from signalbar.providers.countdown import CountdownProvider
from test_cinema_integration import plugin_class


class ShutdownTests(unittest.TestCase):
    def test_nested_waits_cannot_each_restart_the_deadline(self):
        now = [10.0]
        budget = ShutdownBudget(3, clock=lambda: now[0])
        seen = []
        def stop(timeout):
            seen.append(timeout)
            now[0] += 2.0
        for _ in range(4):
            budget.call(stop)
        self.assertEqual(seen, [3, 1, 0, 0])
        legacy = Mock()
        ShutdownBudget().call(legacy)
        legacy.assert_called_once_with()

    def test_zero_budget_weather_still_signals_without_seven_second_join(self):
        weather = WeatherProvider.__new__(WeatherProvider)
        weather._stop = threading.Event()
        weather._wake = threading.Event()
        release = threading.Event()
        weather._thread = threading.Thread(target=release.wait, daemon=True)
        weather._thread.start()
        try:
            started = time.monotonic()
            weather.stop(timeout=0)
            self.assertLess(time.monotonic()-started, .2)
            self.assertTrue(weather._stop.is_set())
            self.assertTrue(weather._wake.is_set())
        finally:
            release.set()
            weather._thread.join(1)

    def test_actual_plugin_cleanup_keeps_releasing_after_a_stage_failure(self):
        cls = plugin_class()
        # The integration loader intentionally doesn't register its test module.
        namespace = cls._shutdown_plugin.__globals__
        plugin = cls()
        events = []
        now = [0.0]
        def slow_stage(timeout):
            self.assertEqual(timeout, 3)
            now[0] += 3.1
            events.append('studio')
        def later(name, fail=False):
            def stop(timeout):
                self.assertEqual(timeout, 0)
                events.append(name)
                if fail: raise RuntimeError('fixture')
            return stop
        plugin.engine = SimpleNamespace(_stop=threading.Event(), stop=later('engine'), countdown=CountdownProvider())
        plugin.engine.countdown.start('free', 60, end_action='sleep')
        plugin.faceplate_artwork_jobs = SimpleNamespace(cancel=lambda: events.append('artwork'))
        plugin._stop_cinema = slow_stage
        plugin.faceplate_power_events = SimpleNamespace(stop=later('power', True))
        plugin.update_manager = SimpleNamespace(stop=later('updates'))
        plugin.faceplate_settings_dir = '/fixture/settings'
        plugin.diagnostics = Mock()
        with patch.dict(namespace, ShutdownBudget=lambda n: ShutdownBudget(n, clock=lambda: now[0])), \
             patch.object(namespace['faceplate_claim'], 'release', side_effect=lambda p: events.append('claim')):
            asyncio.run(plugin._unload())
        self.assertEqual(events, ['artwork','studio','power','updates','engine','claim'])
        self.assertTrue(plugin.engine._stop.is_set())
        self.assertEqual(plugin.engine.countdown.end_action.status()['phase'], 'cancelled')
        plugin.diagnostics.finish_session.assert_not_called()

    def test_engine_passes_the_remaining_budget_to_all_nested_stops(self):
        from signalbar.backend.engine import Engine
        engine = Engine.__new__(Engine)
        engine.faceplate_router = Mock()
        now = [0.0]
        calls = []
        def component(name):
            def stop(timeout):
                calls.append((name, timeout))
                now[0] += 1
            return SimpleNamespace(stop=stop)
        engine._stop = threading.Event()
        engine.countdown=CountdownProvider()
        engine._timer_power_thread=None
        for name in ('assistant','dashboard_stats','weather','faceplate_worker','faceplate_extension','screen_sync','audio_sync'):
            setattr(engine, name, component(name))
        engine.faceplate = object()
        engine._thread = None
        engine._write_faceplate_runtime_status = Mock()
        engine.screen_sync_activation = Mock()
        engine.screen_sync_trace = SimpleNamespace(close=component('screen_sync_trace').stop)
        engine._lock = threading.RLock()
        for name in ('events','launch_artwork','faceplate_steam_state','controllers','event_lease','stripmine_claim'):
            setattr(engine, name, Mock())
        engine._renderer = Mock()
        with patch('signalbar.backend.engine.ShutdownBudget', lambda n: ShutdownBudget(n, clock=lambda: now[0])):
            engine.stop(timeout=2)
        self.assertEqual([v for _,v in calls], [2,1,0,0,0,0,0,0])
        engine._renderer.relinquish.assert_called_once_with(restore_if_owned=True)
        engine.event_lease.release.assert_called_once_with()
