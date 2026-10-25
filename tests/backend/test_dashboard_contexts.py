"""Context persistence, legacy upgrades and actual Dashboard GIF isolation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.dashboard_settings import dashboard_context
from signalbar.faceplate.scene_renderer import render_isolated
from signalbar.settings import SettingsStore
from signalbar.settings.export import read_configuration_import, write_configuration_export
from test_dashboard_bottom_row import RGB


class DashboardContextTests(unittest.TestCase):
    def test_illustrated_game_dashboard_can_request_weather_without_a_home_weather_route(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / 'settings.json'))
            engine = Engine(settings, str(Path(folder) / 'artwork.json')); self.addCleanup(engine.stop)
            engine.faceplate_preferences.update(home_scene='native-clock', game_scene='artwork-dashboard')
            values = {**settings.all(), 'faceplate_lab_enabled': True,
                      'faceplate_dashboard_contexts': {'game': {'show_weather':False,
                          'show_bottom_row':False, 'bottom_mode':'controllers'}}}
            self.assertFalse(engine._faceplate_weather_required(values))
            values['faceplate_dashboard_contexts']['game']['show_weather'] = True
            self.assertTrue(engine._faceplate_weather_required(values))
            values['faceplate_dashboard_contexts']['game'].update(show_weather=False,
                show_bottom_row=True, bottom_mode='today')
            self.assertTrue(engine._faceplate_weather_required(values))
            values['faceplate_dashboard_contexts']['game']['bottom_mode'] = 'controllers'
            self.assertFalse(engine._faceplate_weather_required(values))
            for variant in 'abcde':
                values['faceplate_dashboard_contexts']['game'].update(bottom_mode='today',game_row=variant)
                self.assertFalse(engine._faceplate_weather_required(values))

    def test_legacy_upgrade_preserves_weather_row_and_game_controller_override(self):
        for mode in ('next_hour', 'today', 'controllers'):
            for session in (False, True):
                with self.subTest(mode=mode, session=session), tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / 'settings.json'
                    path.write_text(json.dumps({'faceplate_dashboard_bottom_mode': mode,
                        'faceplate_dashboard_game_session': session,
                        'faceplate_dashboard_show_weather': False,
                        'faceplate_dashboard_show_bottom_row': False,
                        'faceplate_dashboard_battery_style': 'bar',
                        'faceplate_dashboard_show_p2': True}))
                    values = SettingsStore(str(path)).all()
                    for game in (False, True):
                        content = dashboard_context(values, game)
                        self.assertEqual('controllers' if game and session else mode, content['bottom_mode'])
                        self.assertEqual(game and session, content['show_session'])
                        self.assertFalse(content['show_weather']); self.assertFalse(content['show_bottom_row'])
                        self.assertEqual('bar', content['battery_style']); self.assertTrue(content['show_p2'])

    def test_separate_profiles_survive_reload_and_reject_invalid_import_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.json')
            store = SettingsStore(path)
            store.update({'faceplate_dashboard_contexts': {
                'home': {'show_weather': False, 'show_bottom_row': False, 'bottom_mode': 'today'},
                'game': {'show_weather': True, 'bottom_mode': 'controllers', 'battery_style': 'bar',
                         'show_p2': True, 'show_session': False}}})
            profiles = deepcopy(store.all()['faceplate_dashboard_contexts'])
            profiles['home']['bottom_mode'] = 'next_hour'
            store.update({'faceplate_dashboard_contexts': profiles})
            values = SettingsStore(path).all()
            self.assertEqual('next_hour', dashboard_context(values)['bottom_mode'])
            self.assertEqual(profiles['game'], values['faceplate_dashboard_contexts']['game'])
            export = str(Path(folder) / 'export.json')
            write_configuration_export(store, export, '1.4.1-lab.203', {'appid':0})
            restored = SettingsStore(str(Path(folder) / 'restored.json'))
            restored.replace_configuration(*read_configuration_import(export))
            self.assertEqual(profiles, restored.all()['faceplate_dashboard_contexts'])
            store.update({'faceplate_dashboard_contexts': {'home': {'bottom_mode': 'invalid',
                'show_weather': 'false', 'unknown': 1}, 'game': profiles['game'], 'other': {}}})
            validated = store.all()['faceplate_dashboard_contexts']
            self.assertEqual({}, validated['home']); self.assertNotIn('other', validated)
            self.assertEqual(profiles['game'], validated['game'])

    def test_previews_and_worker_use_only_their_context_without_repreparing_artwork(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / 'settings.json'))
            settings.update({'faceplate_dashboard_contexts': {
                'home': {'show_weather': False, 'show_bottom_row': False},
                'game': {'show_weather': True, 'show_bottom_row': True,
                         'bottom_mode': 'today', 'show_session': False}}})
            engine = Engine(settings, str(Path(folder) / 'artwork.json'))
            self.addCleanup(engine.stop)
            pack = Path(folder) / 'pack.rgb'; pack.write_bytes(RGB)
            manifest = {'dashboard_pack_frames': 1, 'dashboard_pack_sha256': hashlib.sha256(RGB).hexdigest()}
            captures = []
            def render(payload, _ticket):
                data, meta = render_isolated(payload)
                captures.append((dict(payload), data))
                return data, meta
            with patch.object(engine, '_dashboard_background', return_value=(manifest, {'dashboard_pack_path': str(pack)}, None)), \
                    patch.object(engine, '_render_faceplate_scene', side_effect=render), \
                    patch.object(engine, '_faceplate_weather_payload', return_value=({'condition':'rain','temperature_c':12}, {}, '')), \
                    patch.object(engine, '_faceplate_playtime_facts', return_value={}):
                home = engine.faceplate_artwork_dashboard_preview(620, home=True)['gif']
                self.assertFalse(captures[-1][0]['dashboard_show_status_rail'])
                game = engine.faceplate_artwork_dashboard_preview(620, home=False)['gif']
                self.assertTrue(captures[-1][0]['dashboard_show_status_rail'])
                self.assertEqual('today', captures[-1][0]['bottom_mode'])
                self.assertNotEqual(home, game)
                profiles = deepcopy(settings.all()['faceplate_dashboard_contexts'])
                profiles['home'].update(show_weather=True, show_bottom_row=True, bottom_mode='controllers')
                settings.update({'faceplate_dashboard_contexts': profiles})
                self.assertEqual(game, engine.faceplate_artwork_dashboard_preview(620, home=False)['gif'])
                updated_home = engine.faceplate_artwork_dashboard_preview(620, home=True)['gif']
                self.assertNotEqual(home, updated_home)
                profiles['game'].update(show_weather=False, show_bottom_row=False)
                settings.update({'faceplate_dashboard_contexts': profiles})
                self.assertEqual(updated_home, engine.faceplate_artwork_dashboard_preview(620, home=True)['gif'])
                self.assertNotEqual(game, engine.faceplate_artwork_dashboard_preview(620, home=False)['gif'])
                # Both physical scene paths consume these same context-resolved facts.
                rendered = {'dashboard': {}, 'artwork-dashboard': {}}
                for game_running in (False, True):
                    facts = engine._faceplate_artwork_dashboard_facts(settings.all(), game_running)
                    for kind in ('dashboard', 'artwork-dashboard'):
                        payload = {'kind':kind, 'visual_theme':'weather-artwork-v2',
                            'condition':'rain', 'variant':0, 'temperature_c':12, 'unit':'celsius',
                            'display_at':'2026-10-22T15:00:00+02:00',
                            'sunrise':'2026-10-22T07:00:00+02:00', 'sunset':'2026-10-22T19:00:00+02:00',
                            'dashboard_background_rgb':RGB.hex(), 'dashboard_pack_frames':1,
                            'dashboard_pack_sha256':hashlib.sha256(RGB).hexdigest(), **facts}
                        data, meta = render_isolated(payload)
                        self.assertTrue(data.startswith(b'GIF'))
                        rendered[kind][game_running] = data
                for kind in rendered:
                    self.assertNotEqual(rendered[kind][False], rendered[kind][True])
                self.assertEqual(RGB, pack.read_bytes())

    def test_editing_other_context_does_not_force_a_serial_scene_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / 'settings.json'))
            engine = Engine(settings, str(Path(folder) / 'artwork.json')); self.addCleanup(engine.stop)
            with patch.object(engine, '_reconcile_faceplate') as reconcile:
                engine.update_settings({'faceplate_dashboard_contexts': {'home': {'show_weather': False}}})
                reconcile.assert_not_called()
                self.assertEqual(0, engine._faceplate_next_reconcile)

    def test_hidden_game_row_does_not_hide_home_or_override_timer_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / 'settings.json'))
            engine = Engine(settings, str(Path(folder) / 'artwork.json')); self.addCleanup(engine.stop)
            values = {**settings.all(), 'faceplate_dashboard_contexts': {
                'home': {'show_bottom_row': True, 'bottom_mode': 'today'},
                'game': {'show_bottom_row': False}}}
            with patch.object(engine, '_faceplate_weather_payload', return_value=({}, {}, '')), \
                    patch.object(engine, '_faceplate_playtime_facts', return_value={}) as timer:
                self.assertEqual('today', engine._faceplate_artwork_dashboard_facts(values, False)['bottom_mode'])
                self.assertEqual('hidden', engine._faceplate_artwork_dashboard_facts(values, True)['bottom_mode'])
                timer.return_value = {'state':'active','remaining_seconds':600}
                for game in (False, True):
                    self.assertEqual('countdown', engine._faceplate_artwork_dashboard_facts(values, game)['bottom_mode'])
