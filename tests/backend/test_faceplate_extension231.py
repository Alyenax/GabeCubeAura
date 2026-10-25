"""City source projection and runtime Artwork fallback on Faceplate loss."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.faceplate.player_city_animation import animated_rgb, projection_source
from signalbar.faceplate.source_projection import background_key, load_source, project_backgrounds
from signalbar.models import GameState, ProviderOutput
from signalbar.providers.faceplate_extension import FaceplateExtension, BLACK
import test_faceplate_extension as extension_tests
wait_ready = extension_tests.wait_ready


class CityProjectionTests(unittest.TestCase):
    def test_city_original_bank_is_validated_and_excludes_count_rail(self):
        source = projection_source('STR', 'day', '1000_9999')
        frames = load_source(source)
        self.assertEqual(frames, animated_rgb('STR', 'day', '1000_9999'))
        self.assertEqual(len(frames), 192)
        self.assertTrue(all(len(frame) == 64 * 45 * 3 for frame in frames))
        for field, value in [('sha256', 'wrong'), ('height', 54), ('revision', 'old')]:
            with self.assertRaises(ValueError): load_source({**source, field: value})

    def test_whole_and_bottom_sample_urban_rows_in_both_orientations(self):
        raw = bytes(c for y in range(45) for x in range(64) for c in (x * 3, y * 4, 50))
        rotated = bytes(c for y in range(45) for x in range(64) for c in ((63-x) * 3, (44-y) * 4, 50))
        for mapping in ('bottom', 'whole'):
            expected = project_backgrounds((rotated,), mapping, height=45)
            self.assertEqual(project_backgrounds((raw,), mapping, True, height=45), expected)
        self.assertTrue(all(c[1] == 162 for c in project_backgrounds((raw,), 'bottom', height=45)))
        self.assertTrue(all(c[1] == 88 for c in project_backgrounds((raw,), 'whole', height=45)))

    def test_city_counter_refresh_keeps_source_while_tier_phase_weather_game_rekey(self):
        payload = dict(kind='player-city', appid=620, weather='STR', phase='day', players=1234)
        key = background_key(payload, 'game', 620)
        self.assertIsNotNone(key)
        self.assertEqual(key, background_key({**payload, 'players': 9999}, 'game', 620))
        for changes in ({'players': 10000}, {'phase': 'night'}, {'weather': 'SNW'}):
            self.assertNotEqual(key, background_key({**payload, **changes}, 'game', 620))
        self.assertNotEqual(key, background_key(payload, 'game', 621))
        self.assertIsNone(background_key({**payload, 'players': 0}, 'game', 620))

    def test_real_city_worker_is_nonblack_for_whole_and_bottom_day_and_night(self):
        with tempfile.TemporaryDirectory() as root:
            worker = FaceplateExtension(Path(root))
            self.addCleanup(worker.stop)
            for phase, mapping, rotated in [('day', 'whole', False), ('night', 'whole', True),
                                             ('day', 'bottom', True), ('night', 'bottom', False)]:
                source = projection_source('STR', phase, '1000_9999')
                worker.configure(True, source, mapping, rotated)
                wait_ready(worker)
                expected = project_backgrounds(animated_rgb('STR', phase, '1000_9999'), mapping, rotated, height=45)
                self.assertEqual(worker.status()['colours'], expected)
                self.assertNotEqual(worker.output(worker.ready_at + 1).frame, BLACK)
                self.assertEqual(worker.status()['source'], 'player-city')


class RuntimeFallbackTests(unittest.TestCase):
    make_engine = extension_tests.ProjectionRoutingTests.make_engine
    values = dict(faceplate_lab_enabled=True, signalbar_enabled=True,
                  faceplate_extension_mapping='whole', faceplate_rotate_180=False)

    def choose(self, engine, game, extension, **overrides):
        empty = ProviderOutput('none', None, '')
        arguments = dict(mode='faceplate_extension', guard_allows=True, game=game,
            performance=empty, artwork=ProviderOutput('artwork:620', ((90, 20, 5),) * 17, ''),
            idle=empty, faceplate_extension=extension)
        return Arbiter().choose(**{**arguments, **overrides})

    def test_confirmed_city_source_reaches_engine_instead_of_waiting_black(self):
        engine = self.make_engine()
        engine.faceplate_extension.stop()
        engine.faceplate_extension = FaceplateExtension(self.temp.name)
        self.addCleanup(engine.faceplate_extension.stop)
        payload = dict(kind='player-city', appid=620, weather='SNW', phase='day', players=1234)
        key = background_key(payload, 'game', 620)
        payload['_extension_background_key'] = key
        engine._faceplate_extension_target = dict(key=key, context='game', appid=620, generation=1)
        ticket = SimpleNamespace(context='game', generation=1)
        self.assertTrue(engine._publish_faceplate_extension_source(payload, ticket, {}))
        game = GameState(620, 'Portal 2')
        engine._faceplate_extension_output(self.values, game, 'faceplate_extension', 5)
        wait_ready(engine.faceplate_extension)
        output = engine._faceplate_extension_output(self.values, game, 'faceplate_extension', engine.faceplate_extension.ready_at + 1)
        self.assertEqual(output.provider, 'faceplate-extension:player-city')
        self.assertNotEqual(output.frame, BLACK)
        self.assertTrue(engine._faceplate_extension_status()['faceplate_confirmed'])
        self.assertFalse(engine._publish_faceplate_extension_source({**payload, 'appid': 621}, ticket, {}))

    def test_disconnect_falls_back_next_render_and_replug_requires_current_source(self):
        engine = self.make_engine(); game = GameState(620, 'Portal 2')
        engine._faceplate_extension_output(self.values, game, 'faceplate_extension', 5)
        wait_ready(engine.faceplate_extension)
        engine._faceplate_extension_present = False
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('read on renderer')):
            extension = engine._faceplate_extension_output(self.values, game, 'faceplate_extension', 6)
        self.assertIsNone(extension)
        self.assertEqual(self.choose(engine, game, extension).provider, 'artwork:620')
        self.assertIsNone(engine.faceplate_extension.output())
        # Replug while the confirmed scene is not ready keeps Artwork alive.
        engine._faceplate_extension_present = True
        engine._faceplate_extension_source = None
        extension = engine._faceplate_extension_output(self.values, game, 'faceplate_extension', 6)
        self.assertEqual(self.choose(engine, game, extension).provider, 'artwork:620')
        engine._remember_faceplate_extension_source(dict(kind='player-city', weather='STR', phase='night',
            players=1234, appid=620), SimpleNamespace(context='game', generation=2), {})
        engine._faceplate_extension_output(self.values, game, 'faceplate_extension', 6)
        wait_ready(engine.faceplate_extension)
        extension = engine._faceplate_extension_output(self.values, game, 'faceplate_extension', 7)
        self.assertEqual(self.choose(engine, game, extension).provider, 'faceplate-extension:player-city')
        self.assertEqual(self.values['faceplate_extension_mapping'], 'whole')

    def test_other_missing_panel_states_cannot_leak_cached_screensaver_projection(self):
        for state in ('disconnected', 'off', 'suspended', 'disabled'):
            with self.subTest(state=state):
                engine = self.make_engine(); values = dict(self.values)
                engine.jsaux_broker_adapter = SimpleNamespace(extension_frame=lambda *_: self.fail('ghost projection'))
                if state == 'disconnected': engine._faceplate_extension_present = False
                elif state == 'off': engine.faceplate.powered = False
                elif state == 'suspended': engine._faceplate_suspended = True
                else: values['faceplate_lab_enabled'] = False
                extension = engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 5, screensaver=True)
                self.assertIsNone(extension)

    def test_no_game_or_artwork_yields_and_explicit_off_system_alerts_still_win(self):
        engine = self.make_engine(); engine._faceplate_extension_present = False
        empty = ProviderOutput('none', None, '')
        game = GameState(620, 'Portal 2')
        self.assertIsNone(self.choose(engine, GameState(), None).frame)
        self.assertIsNone(self.choose(engine, game, None, artwork=empty).frame)
        for mode, provider in [('bar_off', 'blackout'), ('steam_control', 'valve'), ('disabled', 'none')]:
            self.assertEqual(self.choose(engine, game, None, mode=mode).provider, provider)
        for overrides in ({'steam_priority': True}, {'guard_allows': False}):
            self.assertEqual(self.choose(engine, game, None, **overrides).provider, 'valve')
        alert = ProviderOutput('countdown', ((255, 0, 0),) * 17, '')
        self.assertEqual(self.choose(engine, game, None, signal=alert, signal_critical=True), alert)
        self.assertEqual(self.choose(engine, game, None, event=alert), alert)
        self.assertEqual(self.choose(engine, game, None, recording_marker=True).provider, 'artwork:620+recording')
