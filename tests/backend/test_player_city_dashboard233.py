"""Dashboard rails inside City preserve native layout and immutable artwork."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from signalbar.backend import Engine
from signalbar.faceplate.artwork_dashboard import _draw_bottom_row, RAIL_BACKGROUND, WARM_WHITE
from signalbar.faceplate.player_city import build_player_city, population_tier
from signalbar.faceplate.player_city_animation import animated_rgb
from signalbar.faceplate.player_city_row import BACKGROUND, build_rail, fit_rail_palette
from signalbar.faceplate.playtime import COLOURS, timer_facts
from signalbar.faceplate.scenes import Canvas
from signalbar.settings.store import DEFAULTS


CHOICES = ('next_hour', 'today', 'controllers', 'a', 'b', 'c', 'd', 'e')


def dashboard_row(choice, *, style='percent', percent=100, unit='celsius', temperature=-12):
    forecast = dict(next_hour_temperature_c=temperature, next_hour_condition='rain',
        next_hour_precipitation_probability=65, morning_temperature_c=temperature,
        afternoon_temperature_c=None if temperature is None else temperature+7, today_condition='snow')
    facts = dict(bottom_mode=choice if choice in CHOICES[:3] else 'controllers',
        game_row='existing' if choice in CHOICES[:3] else choice, game_running=True,
        controllers=[dict(percent=percent, charging=False), dict(percent=None, charging=True)],
        battery_style=style, show_p2=True, connected_controller_count=2,
        game_stats=dict(achieved=42, achievements_total=100, total_minutes=123456),
        session_minutes=125, unit=unit, ux_enabled=False, forecast=forecast)
    return dict(mode='dashboard', dashboard=facts)


def native_rail(row):
    canvas = Canvas(BACKGROUND)
    facts = deepcopy(row.get('dashboard', {}))
    mode = facts.pop('bottom_mode', 'controllers')
    _draw_bottom_row(canvas, mode, countdown=row.get('countdown'), **facts)
    return canvas.bytes()[45*64*3:]


class CityDashboardPixels233(unittest.TestCase):
    def assert_scene(self, row, *, code='SUN', phase='day', players=1, exact=True):
        art = animated_rgb(code, phase, population_tier(players))
        scene = build_player_city(code, phase, players, row=row)
        rail = scene.frames[0][45*64*3:]
        self.assertEqual(len(rail), 64*9*3)
        if exact:
            self.assertEqual(rail, native_rail(row), 'Native Dashboard pixels survive when the palette has room')
        for index, frame in enumerate(scene.frames):
            self.assertEqual(frame[:45*64*3], art[index])
            self.assertEqual(frame[45*64*3:], rail, 'Rail colour is stable throughout all 192 frames')
        colours = {frame[p:p+3] for frame in scene.frames for p in range(0, len(frame), 3)}
        self.assertLessEqual(len(colours), 256, 'Native global palette fits')
        payload = scene.gif()
        self.assertLessEqual(len(payload), 196608)
        decoded = Image.open(BytesIO(payload))
        self.assertEqual(decoded.size, (64, 54)); self.assertEqual(decoded.n_frames, 192)
        for index in (0, 1, 95, 191):
            decoded.seek(index)
            self.assertEqual(decoded.convert('RGB').tobytes(), scene.frames[index])
        return scene

    def test_all_eight_dashboard_rows_reuse_native_pixels_and_fit_gifs(self):
        for choice in CHOICES:
            for style in ('percent', 'bar'):
                for percent in (100, None):
                    with self.subTest(choice=choice, style=style, percent=percent):
                        row = dashboard_row(choice, style=style, percent=percent)
                        self.assertEqual(build_rail(1, row), native_rail(row))
                        self.assertEqual(build_rail(999999, row), native_rail(row), 'No player count remains')
                        self.assert_scene(row)

    def test_forecasts_keep_native_units_negative_and_missing_values(self):
        for choice in ('next_hour', 'today'):
            for unit in ('celsius', 'fahrenheit'):
                for temperature in (-80, 22, None):
                    with self.subTest(choice=choice, unit=unit, temperature=temperature):
                        self.assert_scene(dashboard_row(choice, unit=unit, temperature=temperature))
        celsius = build_rail(1, dashboard_row('today', unit='celsius'))
        fahrenheit = build_rail(1, dashboard_row('today', unit='fahrenheit'))
        self.assertNotEqual(celsius, fahrenheit)

    def test_full_width_timer_has_no_count_or_hidden_dashboard_information(self):
        for countdown in (timer_facts(59), timer_facts(300), timer_facts(3600), {'state': 'ended'}):
            with self.subTest(countdown=countdown):
                row = dict(mode='dashboard', countdown=countdown)
                expected = native_rail(row)
                for choice in CHOICES:
                    hidden = {**dashboard_row(choice), 'countdown': countdown}
                    self.assertEqual(build_rail(4294967295, hidden), expected)
                self.assert_scene(row)

    def test_dense_storm_quantises_only_rail_and_preserves_critical_timer_colours(self):
        art = animated_rgb('STR', 'day', '100000_plus')
        original = tuple(art)
        row = dict(mode='dashboard', countdown=timer_facts(300))
        raw = native_rail(row)
        fitted = fit_rail_palette(art, raw)
        for colour in (RAIL_BACKGROUND, WARM_WHITE, COLOURS['urgent']):
            self.assertIn(bytes(colour), raw)
            self.assertIn(bytes(colour), fitted)
        # More rail colours than the real bank can hold: keep essential labels
        # and red urgency exact while remapping only secondary rail accents.
        stress = bytearray(raw)
        for index, colour in enumerate(((252, 1, 2), (1, 252, 2), (2, 1, 252), (211, 13, 91), (13, 211, 91))):
            stress[index*3:index*3+3] = bytes(colour)
        stress = bytes(stress)
        adapted = fit_rail_palette(art, stress)
        self.assertNotEqual(adapted, stress)
        for colour in (RAIL_BACKGROUND, WARM_WHITE, COLOURS['urgent']):
            for offset in range(0, len(stress), 3):
                if stress[offset:offset+3] == bytes(colour):
                    self.assertEqual(adapted[offset:offset+3], bytes(colour))
        self.assertEqual(tuple(art), original)
        all_colours = {frame[n:n+3] for frame in art for n in range(0, len(frame), 3)}
        all_colours.update(adapted[n:n+3] for n in range(0, len(adapted), 3))
        self.assertLessEqual(len(all_colours), 256)
        self.assert_scene(row, code='STR', phase='day', players=100000, exact=False)
        self.assert_scene(dashboard_row('today', unit='fahrenheit', temperature=-80),
                          code='STR', phase='day', players=100000, exact=False)


class CityDashboardFacts233(unittest.TestCase):
    def engine(self):
        engine = Engine.__new__(Engine)
        engine._game = SimpleNamespace(appid=620)
        engine._faceplate_playtime_facts = Mock(return_value={})
        engine._faceplate_weather_payload = Mock(return_value=({}, dict(faceplate_background_only=True,
            next_hour_temperature_c=-12, next_hour_condition='snow', next_hour_precipitation_probability=70,
            morning_temperature_c=-14, afternoon_temperature_c=-2, today_condition='snow'), ''))
        engine.controllers = SimpleNamespace(faceplate_batteries=Mock(return_value=[dict(percent=100, charging=False)]))
        engine.dashboard_stats = SimpleNamespace(snapshot=Mock(return_value=dict(
            achieved=42, achievements_total=100, total_minutes=12345)))
        engine._faceplate_game_started_monotonic = 0
        engine._session_start_known = True
        return engine

    def test_city_context_ignores_hidden_dashboard_and_background_only_without_mutating_preferences(self):
        engine = self.engine()
        values = {**deepcopy(DEFAULTS), 'faceplate_player_city_row': 'dashboard',
            'faceplate_player_city_battery_style': 'bar', 'faceplate_dashboard_show_bottom_row': False,
            'faceplate_dashboard_contexts': {'home': {'bottom_mode': 'today'},
                'game': {'show_bottom_row': False, 'bottom_mode': 'next_hour', 'game_row': 'b', 'battery_style': 'percent'}}}
        original = deepcopy(values)
        for choice in CHOICES:
            with self.subTest(choice=choice), patch('signalbar.backend.engine.time.monotonic', return_value=601):
                selected = {**values, 'faceplate_player_city_dashboard_row': choice}
                facts = engine._faceplate_player_city_facts(selected)
                self.assertEqual(facts['mode'], 'dashboard')
                native = facts['dashboard']
                self.assertEqual(native['bottom_mode'], choice if choice in CHOICES[:3] else 'controllers')
                self.assertEqual(native.get('game_row', 'existing'), 'existing' if choice in CHOICES[:3] else choice)
                if choice in ('next_hour', 'today'):
                    self.assertIn('forecast', native)
                if choice in ('controllers', 'a', 'c', 'e'):
                    self.assertEqual(native['battery_style'], 'bar')
                self.assertEqual(selected['faceplate_dashboard_contexts'], original['faceplate_dashboard_contexts'])
        self.assertEqual(values, original)

    def test_timer_skips_all_hidden_weather_controller_and_stats_queries(self):
        engine = self.engine()
        for provider in (engine.controllers.faceplate_batteries, engine.dashboard_stats.snapshot, engine._faceplate_weather_payload):
            provider.side_effect = AssertionError('Hidden facts must not be sampled')
        for countdown in (timer_facts(59), {'state': 'ended'}):
            engine._faceplate_playtime_facts.return_value = countdown
            for choice in CHOICES:
                facts = engine._faceplate_player_city_facts({**DEFAULTS, 'faceplate_player_city_row': 'dashboard',
                    'faceplate_player_city_dashboard_row': choice})
                self.assertEqual(facts, dict(mode='dashboard', countdown=countdown))


if __name__ == '__main__':
    unittest.main()
