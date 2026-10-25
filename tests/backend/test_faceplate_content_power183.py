"""Encoded colour estimates and actual transport packets; no physical proof."""
from collections import OrderedDict
from pathlib import Path
import hashlib
import io
import json
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence
from signalbar.faceplate import gif, power
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard
from signalbar.faceplate.weather_artwork import build_weather_artwork_scene, WEATHER_ARTWORK_V2_THEME
from signalbar.faceplate.transport import TransferCancelled
import test_screensaver_restore148 as restore_fixture


def scene(colour, frames=1):
    return gif.encode(64, 54, [(0, 0, 0), colour], [bytes([1])*3456]*frames)


class ContentPowerTests(unittest.TestCase):
    def fixture(self):
        fixture = restore_fixture.Restore148Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.coordinator.configure(True, 100)
        return fixture

    @staticmethod
    def levels(fixture):
        return [data[0] for kind, command, data in fixture.panel.events if (kind, command) == (1, 2)]

    def send(self, fixture, data, **kwargs):
        return fixture.coordinator.synchronize_scene(data, 'dashboard', hashlib.sha256(data).hexdigest(), **kwargs)

    def test_maximum_includes_the_last_frame_not_the_temporal_average(self):
        data = gif.encode(64, 54, [(0, 0, 0), (255, 255, 255)],
                          [bytes(3456)]*79 + [bytes([1])*3456])
        self.assertEqual(power.profile(data)['peak_load'], 1)
        with patch.object(power, '_cache', OrderedDict()):
            self.assertEqual(power.profile(data)['peak_load'], 1)

    def test_estimate_matches_decoded_quantised_dashboard_not_original_rgb(self):
        data = build_artwork_dashboard((bytes((128, 128, 128))*3456,),
            '2026-10-21T13:00:00+02:00', 0, show_clock=True,
            weather={'condition': 'rain', 'temperature_c': 12}).gif()
        with Image.open(io.BytesIO(data)) as image:
            expected = max(sum(f.convert('RGB').tobytes())/(3456*765) for f in ImageSequence.Iterator(image))
        self.assertAlmostEqual(power.profile(data)['peak_load'], expected)
        with patch.object(power, '_cache', OrderedDict()):
            self.assertAlmostEqual(power.profile(data)['peak_load'], expected)

    def test_prepared_and_hot_profiles_do_not_decode_again(self):
        data = scene((30, 50, 80), 80)
        prepared = power.profile(data)
        with patch.object(power, '_cache', OrderedDict()), patch.object(power, '_decode_profile', side_effect=AssertionError('unexpected decode')):
            self.assertEqual(power.profile(data, prepared), prepared)
            self.assertEqual(power.profile(data), prepared)

    def test_legacy_assistant_end_token_boundary_matches_pillow_and_rotates_unchanged(self):
        from signalbar.faceplate.gif_transform import rotate_gif
        data = (Path(__file__).resolve().parents[1]/'fixtures/power-profile-reference.gif').read_bytes()
        with Image.open(io.BytesIO(data)) as image:
            frames = [f.convert('RGB').tobytes() for f in ImageSequence.Iterator(image)]
        expected = max(sum(f)/(3456*765) for f in frames)
        with patch.object(power, '_cache', OrderedDict()):
            self.assertEqual(power.profile(data)['frames'], len(frames))
            self.assertAlmostEqual(power.profile(data)['peak_load'], expected)
            self.assertAlmostEqual(power.profile(rotate_gif(data))['peak_load'], expected)

    def test_changed_bytes_or_invalid_profile_require_a_new_measurement(self):
        dark, bright = scene((20, 30, 40)), scene((255, 255, 255))
        prepared = power.profile(dark)
        with patch.object(power, '_cache', OrderedDict()):
            self.assertEqual(power.profile(bright, prepared)['peak_load'], 1)
        for invalid in (float('nan'), float('inf'), -1, 2, True):
            self.assertFalse(power.valid_profile(dark, {**prepared, 'peak_load': invalid}))

    def test_profile_cache_is_bounded_and_does_not_retain_gif_bytes(self):
        with patch.object(power, '_cache', OrderedDict()):
            for n in range(300):
                data = scene((n%256, n//256, 10))
                power.profile(data)
            self.assertEqual(len(power._cache), power.MAX_CACHE)
            self.assertTrue(all(set(value) == {'revision', 'sha256', 'peak_load', 'frames'} for value in power._cache.values()))

    def test_bright_weather_pixels_remain_intact_and_profile_exceeds_the_limit(self):
        raw = bytes((255, 255, 255))*3456
        with patch('signalbar.faceplate.weather_artwork._backgrounds', return_value=(raw,)):
            result, metadata = build_weather_artwork_scene('rain', 0, 12, 'celsius', 'day',
                visual_theme=WEATHER_ARTWORK_V2_THEME)
        self.assertEqual(result.frames[0][20*64*3:20*64*3+3], b'\xff\xff\xff')
        self.assertEqual(metadata['power_scale'], 1)
        self.assertGreater(power.profile(result.gif())['peak_load'], .5)

    def test_dark_bright_dark_transition_keeps_manual_level_and_pixels(self):
        f = self.fixture()
        for data, expected in ((scene((20, 40, 60)), 100), (scene((255, 255, 255)), 100), (scene((10, 30, 50)), 100)):
            self.assertTrue(self.send(f, data)['synchronized'])
            self.assertEqual(f.coordinator.effective_brightness, expected)
            self.assertEqual(f.panel.stored, data)
        self.assertEqual(self.levels(f), [100])

    def test_identical_content_and_resume_do_not_reintroduce_unknown_fifty_percent(self):
        f = self.fixture(); data = scene((20, 40, 60))
        self.assertTrue(self.send(f, data)['synchronized']); f.panel.events.clear()
        self.assertTrue(self.send(f, data)['synchronized'])
        self.assertEqual(self.levels(f), [])
        f.coordinator.set_power(False, 'manual'); f.coordinator.set_power(True, 'manual')
        self.assertEqual(self.levels(f), [100])
        self.assertEqual(f.coordinator.cached_status()['brightness_control']['last_commanded_percent'], 100)

    def test_rejected_begin_restores_known_old_brightness(self):
        f = self.fixture(); self.send(f, scene((20, 40, 60))); f.panel.events.clear()
        f.panel.refuse_begin = True
        result = self.send(f, scene((255, 255, 255)))
        self.assertFalse(result['synchronized'])
        self.assertEqual(self.levels(f), [])
        self.assertEqual(f.coordinator.cached_status()['brightness_control']['target_percent'], 100)

    def test_partial_body_cancellation_keeps_manual_level_and_unknown_content(self):
        f = self.fixture(); self.send(f, scene((20, 40, 60)))
        def interrupt():
            raise TransferCancelled('fixture cancellation')
        f.panel.after_chunk = interrupt
        result = self.send(f, scene((255, 255, 255)))
        self.assertTrue(result['cancelled'])
        self.assertEqual(f.coordinator.displayed_peak_load, 1)
        self.assertEqual(f.coordinator._displayed_power_identity, '')
        self.assertEqual(f.coordinator.effective_brightness, 100)
        f.panel.after_chunk = None
        self.assertTrue(self.send(f, scene((10, 20, 30)))['synchronized'])
        self.assertEqual(f.coordinator.effective_brightness, 100)

    def test_lost_final_ack_never_adopts_a_bright_image_as_known_dark(self):
        f = self.fixture(); self.send(f, scene((20, 40, 60)))
        f.panel.lose_end = True
        result = self.send(f, scene((255, 255, 255)))
        self.assertTrue(result['sent_unconfirmed'])
        self.assertEqual(f.coordinator.displayed_peak_load, 1)
        self.assertEqual(f.coordinator.effective_brightness, 100)

    def test_restart_keeps_manual_level_without_reusing_or_recalculating_profiles(self):
        f = self.fixture(); data = scene((20, 40, 60))
        self.send(f, data)
        restarted = f.new_coordinator(); restarted.configure(True, 100)
        self.assertEqual(restarted.cached_status()['brightness_control']['target_percent'], 100)
        self.assertNotIn('power_profiles', restarted.state)
        with patch.object(power, 'profile', side_effect=AssertionError('unexpected profile')):
            self.assertTrue(restarted.synchronize_scene(data, 'dashboard', 'restart')['synchronized'])
        self.assertTrue(restarted._displayed_power_identity)

    def test_new_usb_identity_reapplies_manual_level_before_replacement(self):
        f = self.fixture(); data = scene((20, 40, 60)); self.send(f, data)
        f.panel.events.clear(); f.panel.token = 'reconnected-device'
        self.assertTrue(self.send(f, data)['synchronized'])
        self.assertEqual(self.levels(f), [100])

    def test_delegate_cannot_change_brightness_or_send_over_limit_content(self):
        f = self.fixture(); self.send(f, scene((20, 40, 60))); f.panel.events.clear()
        result = f.coordinator.synchronize_scene(scene((255,255,255)), 'screensaver', 'white', peak_load=1, delegated=True)
        self.assertEqual(result['policy_reason'], 'CONTENT_INVALID')
        self.assertEqual(self.levels(f), [])
        for invalid in (float('nan'), float('inf'), -1, 2):
            invalid_result = f.coordinator.synchronize_scene(scene((10,20,30)), 'screensaver', 'invalid', peak_load=invalid, delegated=True)
            self.assertEqual(invalid_result['policy_reason'], 'CONTENT_INVALID')
        result = f.coordinator.synchronize_scene(scene((10,20,30)), 'screensaver', 'dark', peak_load=.1, delegated=True)
        self.assertTrue(result['synchronized'])
        self.assertEqual(self.levels(f), [])

    def test_manual_brightness_and_power_on_check_the_usb_identity_first(self):
        for action in ('brightness', 'power'):
            with self.subTest(action=action):
                f = self.fixture(); self.send(f, scene((20, 40, 60)))
                f.panel.events.clear(); f.panel.token = 'new-usb-session'
                result = (f.coordinator.set_brightness(100) if action == 'brightness'
                          else f.coordinator.set_power(True))
                self.assertTrue(result['ok'])
                self.assertEqual(self.levels(f), [100])
                self.assertEqual(f.coordinator._displayed_power_identity, '')
                if action == 'brightness':
                    self.assertEqual(f.panel.events[0], (1, 1, bytes([0])))
                    self.assertLess(f.panel.events.index((1, 2, bytes([100]))),
                                    f.panel.events.index((1, 1, bytes([1]))))
                else:
                    self.assertEqual(f.panel.events[0], (1, 2, bytes([100])))

    def test_cancellation_after_commit_keeps_the_new_confirmed_load(self):
        f = self.fixture(); self.send(f, scene((255, 255, 255)))
        cancelled = [False]
        f.panel.after_end = lambda: cancelled.__setitem__(0, True)
        result = self.send(f, scene((10, 20, 30)), cancelled=lambda: cancelled[0])
        self.assertTrue(result['cancelled'])
        self.assertIsNone(f.coordinator.cached_status()['brightness_control']['peak_rgb_load'])
        self.assertEqual(f.coordinator.effective_brightness, 100)
        self.assertTrue(f.coordinator._displayed_power_identity)

    def test_assistant_and_delegated_exit_restore_the_confirmed_current_content_level(self):
        f = self.fixture(); white = scene((255,255,255)); dark = scene((10,20,30))
        self.send(f, white)
        self.assertTrue(f.coordinator.synchronize_scene(dark, 'gabe', 'assistant')['synchronized'])
        self.assertEqual(f.coordinator.effective_brightness, 100)
        self.assertTrue(f.coordinator.synchronize_scene(scene((15,25,35)), 'screensaver', 'delegate', peak_load=.1, delegated=True)['synchronized'])
        self.assertTrue(f.coordinator.set_power(False, 'screensaver-exit')['ok'])
        f.panel.events.clear()
        result = self.send(f, white, reason='broker-current-route-restore')
        self.assertTrue(result['synchronized'])
        self.assertEqual(f.coordinator.effective_brightness, 100)
        self.assertEqual(self.levels(f), [100])
        self.assertFalse(f.coordinator.restoration_status()['pending'])
