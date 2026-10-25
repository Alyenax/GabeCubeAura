"""Live row selection must win over legacy saved-artwork metadata."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.faceplate.scene_renderer import render_isolated
from signalbar.faceplate.routing import FaceplateSceneTicket
from signalbar.faceplate.weather_artwork import build_weather_artwork_dashboard_snapshot

RGB = bytes((40, 70, 110)) * (64 * 54)


class DashboardBottomRowTests(unittest.TestCase):
    def test_home_and_game_preview_and_worker_obey_live_choice_without_repreparing(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / 'settings.json'))
            engine = Engine(settings, str(Path(folder) / 'artwork.json'))
            self.addCleanup(engine.stop)
            pack = Path(folder) / 'pack.rgb'
            pack.write_bytes(RGB)
            # Existing logo-bottom artwork deliberately carries the old veto.
            manifest = {'dashboard_show_status_rail': False, 'dashboard_pack_frames': 1,
                        'dashboard_pack_sha256': hashlib.sha256(RGB).hexdigest()}
            captured = []
            def render(request, _ticket):
                data, meta = render_isolated(request)
                captured.append((dict(request), meta, data))
                return data, meta
            engine.faceplate_router = Mock()
            engine.faceplate_router.status.return_value = {'generation': 0}
            engine.faceplate_router.commit.return_value = False
            with patch.object(engine, '_dashboard_background', return_value=(manifest, {'dashboard_pack_path': str(pack)}, None)), \
                    patch.object(engine, '_render_faceplate_scene', side_effect=render), \
                    patch.object(engine, '_publish_faceplate_extension_source'), \
                    patch.object(engine, '_write_faceplate_runtime_status'), \
                    patch.object(engine, '_synchronize_faceplate_handoff', return_value={'synchronized': True}), \
                    patch.object(engine, '_faceplate_weather_payload', return_value=({}, {}, '')):
                for home in (True, False):
                    images = {}
                    for enabled in (False, True):
                        with self.subTest(home=home, enabled=enabled):
                            settings.update({'faceplate_dashboard_show_bottom_row': enabled})
                            engine.faceplate_artwork_dashboard_preview(620, home=home)
                            self.assertEqual(enabled, captured[-1][0]['dashboard_show_status_rail'])
                            images[enabled] = captured[-1][2]
                            facts = engine._faceplate_artwork_dashboard_facts(settings.all(), not home)
                            ticket = FaceplateSceneTicket(generation=0, scene='artwork-dashboard',
                                context='home' if home else 'game', content_key=f'{home}:{enabled}', preference_revision=0)
                            result = engine._handle_faceplate_scene({'payload': {
                                'kind': 'artwork-dashboard', 'appid': 620, 'home_dashboard': home,
                                'display_at': '2026-10-22T15:00:00+02:00', 'ticket': ticket, **facts}})
                            self.assertTrue(result['synchronized'])
                            self.assertEqual(enabled, captured[-1][0]['dashboard_show_status_rail'])
                            self.assertEqual(images[enabled], captured[-1][2])
                    self.assertNotEqual(images[True], images[False])
                # No rewrite of the prepared background was needed.
                self.assertEqual(RGB, pack.read_bytes())
                self.assertFalse(manifest['dashboard_show_status_rail'])

    def test_hidden_row_does_not_probe_controllers_and_timer_keeps_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / 'settings.json'))
            engine = Engine(settings, str(Path(folder) / 'artwork.json'))
            self.addCleanup(engine.stop)
            values = {**settings.all(), 'faceplate_dashboard_show_bottom_row': False}
            with patch.object(engine, '_faceplate_weather_payload', return_value=({}, {}, '')), \
                    patch.object(engine, '_faceplate_playtime_facts', return_value={}) as timer, \
                    patch.object(engine.controllers, 'faceplate_batteries') as controllers:
                for game in (False, True):
                    facts = engine._faceplate_artwork_dashboard_facts(values, game)
                    self.assertEqual('hidden', facts['bottom_mode'])
                    self.assertNotIn('forecast', facts)
                    controllers.assert_not_called()
                timer.return_value = {'state': 'active', 'remaining_seconds': 600}
                self.assertEqual('countdown', engine._faceplate_artwork_dashboard_facts(values, False)['bottom_mode'])

    def test_weather_dashboard_shares_toggle_and_settings_survive_reload(self):
        args = ('2026-10-22T15:00:00+02:00', 'rain', 0, 12, 'celsius',
                '2026-10-22T07:00:00+02:00', '2026-10-22T19:00:00+02:00')
        shown, _ = build_weather_artwork_dashboard_snapshot(*args, show_status_rail=True)
        hidden, _ = build_weather_artwork_dashboard_snapshot(*args, show_status_rail=False)
        self.assertNotEqual(shown.frames[0][46 * 64 * 3:], hidden.frames[0][46 * 64 * 3:])
        self.assertEqual(shown.frames[0][:45 * 64 * 3], hidden.frames[0][:45 * 64 * 3])
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.json')
            settings = SettingsStore(path)
            self.assertTrue(settings.all()['faceplate_dashboard_show_bottom_row'])
            settings.update({'faceplate_dashboard_show_bottom_row': False})
            self.assertFalse(SettingsStore(path).all()['faceplate_dashboard_show_bottom_row'])
