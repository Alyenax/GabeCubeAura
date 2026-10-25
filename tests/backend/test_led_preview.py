"""Exercise the actual lightweight RPC and the brief rain contacts it displays."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from signalbar.backend.engine import Engine
from signalbar.providers.weather import WeatherProvider
from signalbar.providers.weather_sequences import RAIN_EVENTS
from signalbar.settings.store import DEFAULTS


class LedPreviewTests(unittest.TestCase):
    def engine(self):
        engine = Engine.__new__(Engine)
        engine.settings = Mock(); engine.settings.all.return_value = dict(DEFAULTS)
        engine._lock = threading.RLock(); engine._game = Mock(running=False)
        engine._renderer = None; engine._owner = 'Valve'; engine._decision_at = 0
        engine.status = Mock(side_effect=AssertionError('full status entered the fast path'))
        return engine

    def test_twenty_hz_samples_include_every_short_contact_for_both_variants_and_phases(self):
        engine = self.engine(); now = [100.0]
        engine.weather = WeatherProvider(clock=lambda: now[0])
        for variant in (0, 1):
            for condition in ('rain_day', 'rain_night'):
                now[0] = 100
                self.assertTrue(engine.weather.preview(condition, variant))
                sampled = []
                for step in range(160):
                    now[0] = 100 + step * .05
                    sampled.append(engine.led_preview(['weather'])['weather'])
                # At least one sampled frame shows each contact near its peak,
                # before it fades into the two expanding crests.
                for position, at in RAIN_EVENTS[variant]:
                    contact = [sampled[step][position] for step in range(160)
                               if 0 <= step * .05 - at <= .055]
                    self.assertTrue(contact, (condition, variant, position, at))
                    self.assertGreater(max(max(pixel) for pixel in contact), 185)
        engine.status.assert_not_called()
        engine.settings.update.assert_not_called()

    def test_quick_preview_reads_the_composed_renderer_frame_and_clears_after_handoff_or_stall(self):
        engine = self.engine(); frame = [[0, 100, 220] for _ in range(17)]
        engine._renderer = Mock(last_frame=frame); engine._owner = 'GabeCubeAura'
        with patch('signalbar.backend.engine.time.monotonic', return_value=100):
            engine._decision_at = 99.95
            self.assertEqual(engine.led_preview(['output']), {'output': frame})
            engine._owner = 'Valve'
            self.assertEqual(engine.led_preview(['output'])['output'], [[0, 0, 0]] * 17)
            engine._owner = 'GabeCubeAura'; engine._decision_at = 99
            self.assertEqual(engine.led_preview(['output'])['output'], [[0, 0, 0]] * 17)
        engine._renderer.render.assert_not_called()
        engine.status.assert_not_called()

    def test_only_requested_colour_channels_are_read(self):
        engine = self.engine(); engine.weather = Mock()
        for request in (None, '', ['unknown'], [{}]):
            self.assertEqual(engine.led_preview(request), {})
        engine.led_preview(['output'])
        engine.weather.preview_frame.assert_not_called()
        engine.settings.update.assert_not_called()

    def test_decky_rpc_uses_executor_and_returns_only_requested_colour_arrays(self):
        with patch.dict(sys.modules, {'decky': types.ModuleType('decky')}):
            spec = importlib.util.spec_from_file_location('gca_led_preview_rpc', Path(__file__).resolve().parents[2] / 'main.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            plugin = module.Plugin(); plugin.engine = Mock()
            caller = threading.get_ident()
            plugin.engine.led_preview.side_effect = lambda channels: {'thread': threading.get_ident(), 'channels': channels}
            result = asyncio.run(plugin.get_led_preview(['weather']))
            self.assertNotEqual(result['thread'], caller)
            self.assertEqual(result['channels'], ['weather'])
            plugin.engine.status.assert_not_called()
