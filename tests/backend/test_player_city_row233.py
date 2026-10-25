"""City rail pixels and overlay writes remain separate from hourly Steam facts."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from signalbar.faceplate import player_city as city
from signalbar.faceplate import player_city_row as row_pixels
from signalbar.faceplate.gif_transform import rotate_gif
from signalbar.faceplate.player_city_animation import animated_rgb, projection_source
from signalbar.faceplate.playtime import COLOURS, timer_facts
from signalbar.faceplate.source_projection import background_key, cache_key
from signalbar.providers.current_players import MAX_COUNT
import test_flash_protection as fixture


COUNTS = (999, 1000, 1001, 999999, MAX_COUNT)
ROWS = (
    {'mode': 'controllers', 'percent': 100},
    {'mode': 'controllers', 'percent': None},
    {'mode': 'session', 'session_minutes': 125},
    {'mode': 'session', 'session_minutes': None},
    {'mode': 'session', 'session_minutes': 999999999},
    {'mode': 'achievements', 'achieved': 2, 'achievements_total': 99},
    {'mode': 'achievements', 'achieved': 123456, 'achievements_total': 999999},
    {'mode': 'achievements'},
    {'mode': 'total', 'total_minutes': 12345},
    {'mode': 'total', 'total_minutes': 999999999},
    {'mode': 'total', 'total_minutes': None},
    {'countdown': timer_facts(59)},
    {'countdown': timer_facts(300)},
    {'countdown': timer_facts(900)},
    {'countdown': timer_facts(3600)},
    {'countdown': timer_facts(9999 * 60)},
    {'countdown': {'state': 'ended'}},
)


class CityRowPixels233(unittest.TestCase):
    def test_k_threshold_uses_native_count_without_millions_unit(self):
        expected = ('999', '1k', '1k', '999k', '4294967k')
        self.assertEqual(tuple(row_pixels.compact_players(count) for count in COUNTS), expected)
        self.assertEqual(row_pixels.compact_players(1999), '1.9k')
        self.assertTrue(all('m' not in value.lower() for value in expected))
        self.assertEqual(city.population_tier(1001), '1000_9999')

    def test_every_visible_format_fits_the_exact_nine_rows(self):
        for players in COUNTS:
            for row in ROWS:
                with self.subTest(players=players, row=row):
                    rail = row_pixels.build_rail(players, row)
                    self.assertEqual(len(rail), 64 * 9 * 3)
                    self.assertIn(bytes(row_pixels.WHITE), rail, 'Player count survives every mode')
                    colours = {rail[offset:offset+3] for offset in range(0, len(rail), 3)}
                    self.assertLessEqual(len(colours), 6)

    def test_timer_has_priority_over_hidden_mode_and_true_urgency(self):
        for countdown in ({'state': 'ended'}, timer_facts(59), timer_facts(300), timer_facts(901)):
            rails = []
            for row in ROWS[:11]:
                rails.append(row_pixels.build_rail(32809, {**row, 'countdown': countdown}))
            self.assertEqual(len(set(rails)), 1, 'Hidden row facts cannot leak through the timer')
        icon, label, colour = row_pixels.row_label({'countdown': timer_facts(59)}, 60)
        self.assertEqual(label, '<1MIN'); self.assertEqual(colour, COLOURS['urgent'])
        self.assertIsNone(icon)
        self.assertEqual(row_pixels.row_label({'countdown': timer_facts(300)}, 60)[2], COLOURS['urgent'])
        self.assertEqual(row_pixels.row_label({'countdown': timer_facts(301)}, 60)[2], COLOURS['warning'])
        icon, label, colour = row_pixels.row_label({'countdown': {'state': 'ended'}}, 60)
        self.assertIsNone(icon); self.assertEqual(label, "TIME'S UP")
        self.assertEqual(colour, COLOURS['urgent'])
        self.assertEqual(row_pixels.row_label({'mode': 'controllers', 'percent': 100}, 60)[1], '100%')

    def test_rail_does_not_change_city_art_and_gifs_fit_losslessly_in_both_orientations(self):
        rows = (ROWS[0], ROWS[2], ROWS[6], ROWS[9], ROWS[11], ROWS[12], ROWS[15], ROWS[16])
        art = animated_rgb('STR', 'night', city.population_tier(MAX_COUNT))
        for row in rows:
            with self.subTest(row=row):
                result = city.build_player_city('STR', 'night', MAX_COUNT, row=row)
                self.assertEqual(len(result.frames), len(art))
                for number, frame in enumerate(result.frames):
                    self.assertEqual(frame[:45*64*3], art[number])
                    self.assertEqual(frame[45*64*3:], row_pixels.fit_rail_palette(art, row_pixels.build_rail(MAX_COUNT, row)))
                colours = {frame[p:p+3] for frame in result.frames for p in range(0, len(frame), 3)}
                self.assertLessEqual(len(colours), 256, 'Native global palette fits')
                payload = result.gif()
                for rotated in (False, True):
                    data = rotate_gif(payload) if rotated else payload
                    self.assertLess(len(data), 196608)
                    decoded = Image.open(BytesIO(data))
                    self.assertEqual(decoded.size, (64, 54)); self.assertEqual(decoded.n_frames, 192)
                    duration = 0
                    for number, frame in enumerate(result.frames):
                        decoded.seek(number)
                        expected = Image.frombytes('RGB', (64, 54), frame)
                        if rotated:
                            expected = expected.transpose(Image.Transpose.ROTATE_180)
                        self.assertEqual(decoded.convert('RGB').tobytes(), expected.tobytes())
                        duration += decoded.info['duration']
                    self.assertEqual(duration, 24000)

    def test_source_projection_keys_ignore_all_bottom_row_facts(self):
        base = dict(kind='player-city', appid=620, weather='STR', phase='night', players=32809)
        source = projection_source('STR', 'night', city.population_tier(base['players']))
        expected = background_key(base, 'game', 620)
        for row in ROWS:
            self.assertEqual(background_key({**base, 'row': row}, 'game', 620), expected)
        for mapping in ('bottom', 'whole'):
            for rotated in (False, True):
                key = cache_key(source, mapping, rotated)
                changed = {**source, 'delivery_signature': 'new-row-gif', 'asset': 'new-row.gif',
                           'background_generation': 99}
                self.assertEqual(cache_key(changed, mapping, rotated), key)


class CityRowCadence233(unittest.TestCase):
    def test_row_acks_and_late_failed_row_never_delay_the_hourly_measurement(self):
        clock = fixture.Clock()
        with tempfile.TemporaryDirectory() as folder:
            cadence = city.PlayerCityCadence(Path(folder) / 'city.json', clock=clock.wall)
            sample = dict(appid=620, usable=True, players=32809, sampled_at=clock.wall())
            weather = dict(condition='storm', phase='night')
            payload = cadence.plan(620, sample, weather)
            payload['row'] = {'mode': 'controllers', 'percent': 100}
            cadence.reserve(payload); cadence.receipt(payload, {'synchronized': True})
            confirmed_at = cadence.confirmed['at']; count_attempt = deepcopy(cadence.attempt)
            clock.advance(60)
            row = {'mode': 'session', 'session_minutes': 5}
            update = cadence.plan_row(620, row)
            self.assertEqual(update['players'], sample['players'])
            self.assertEqual(update['sampled_at'], sample['sampled_at'])
            cadence.reserve(update)
            self.assertIsNone(cadence.plan_row(620, row), 'One pending row write is enough')
            cadence.receipt(update, {'synchronized': True})
            self.assertEqual(cadence.status()['displayed']['row'], row)
            self.assertEqual(cadence.confirmed['at'], confirmed_at)
            self.assertEqual(cadence.attempt, count_attempt)
            self.assertIsNone(cadence.plan_row(620, row), 'The acknowledged row is unchanged')
            clock.advance(3530)
            timer_row = {'countdown': timer_facts(59)}
            failed = cadence.plan_row(620, timer_row)
            cadence.reserve(failed); cadence.receipt(failed, {'error': 'USB transfer failed'})
            self.assertEqual(cadence.status()['displayed']['row'], row)
            self.assertEqual(cadence.confirmed['at'], confirmed_at)
            self.assertEqual(cadence.attempt, count_attempt)
            fresh = {**sample, 'players': 98765, 'sampled_at': clock.wall()}
            self.assertIsNone(cadence.plan(620, fresh, weather))
            self.assertIsNone(cadence.plan_row(620, timer_row), 'Failed row retry has a bounded wait')
            clock.advance(10)
            due = cadence.plan(620, fresh, weather)
            self.assertEqual(due['players'], 98765)
            self.assertEqual(cadence.confirmed['at'], confirmed_at)
            self.assertEqual(cadence.attempt, count_attempt)


if __name__ == '__main__':
    unittest.main()
