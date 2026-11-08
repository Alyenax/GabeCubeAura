import math
import random
import struct
import unittest
from unittest.mock import patch

from signalbar.providers import audio_sync as audio


class Uncached(audio.AudioSyncProcessor):
    def _contextual_palette(self, colours):
        return audio._three_colour_palette(colours, self._screen_palette)


class AudioPaletteCacheTests(unittest.TestCase):
    def colours(self):
        return [[230, 35, 25], [20, 190, 65], [35, 65, 220]] * 8

    def test_three_coordinate_distance_keeps_exact_legacy_sum(self):
        rng = random.Random(260)
        for size in (0, 1, 2, 3, 4):
            for _ in range(4000):
                first = [rng.uniform(-1, 1) for _ in range(size)]
                second = [rng.uniform(-1, 1) for _ in range(size)]
                self.assertEqual(audio._lab_distance(first, second),
                                 sum((a-b)**2 for a, b in zip(first, second)))

    def test_unchanged_samples_reuse_reduction_and_mutation_invalidates(self):
        processor = audio.AudioSyncProcessor();colours = self.colours()
        with patch.object(audio, '_three_colour_palette', wraps=audio._three_colour_palette) as reduce:
            first = processor._hifi_target_palette('screen-sync', None, colours, None)
            processor._hifi_target_palette('screen-sync', None, colours, None)
            self.assertEqual(reduce.call_count, 1)
            colours[0][:] = [180, 15, 150]
            processor._hifi_target_palette('screen-sync', None, colours, None)
            self.assertEqual(reduce.call_count, 2)
            processor._hifi_target_palette('screen-sync', None, colours, None)
            self.assertEqual(reduce.call_count, 2)
            self.assertIsNotNone(first)

    def test_dark_fallback_tracks_previous_palette_and_reset_clears_cache(self):
        for preserve in (False, True):
            processor = audio.AudioSyncProcessor()
            processor._hifi_target_palette('screen-sync', None, self.colours(), None)
            dark = [(0, 0, 0)] * 24
            before = processor.screen_palette
            processor._hifi_target_palette('screen-sync', None, dark, None)
            self.assertEqual(processor.screen_palette, before)
            processor._screen_palette = ((12, 20, 30), (30, 50, 80), (100, 120, 160))
            processor._hifi_target_palette('screen-sync', None, dark, None)
            self.assertEqual(processor.screen_palette, ((12, 20, 30), (30, 50, 80), (100, 120, 160)))
            processor.reset(preserve_palette=preserve)
            self.assertIsNone(processor._palette_sample_key)
            self.assertIsNone(processor._palette_sample_result)

    def test_source_fallback_and_palette_smoothing_match_uncached_reference(self):
        cached, reference = audio.AudioSyncProcessor(), Uncached()
        source, artwork = self.colours(), [(220, 10, 30), (25, 170, 50), (25, 60, 210)]
        sequence = [('screen-sync', source, artwork), ('screen-sync', source, artwork),
                    ('screen-sync', [], artwork), ('artwork', [], artwork),
                    ('sapphire', [], []), ('custom', [], []),
                    ('screen-sync', [(0, 0, 0)] * 24, []), ('screen-sync', [], []),
                    ('screen-sync', source, [])]
        custom = [(255, 20, 10), (30, 180, 20), (10, 30, 220)]
        for palette, screen, art in sequence * 3:
            self.assertEqual(cached._hifi_target_palette(palette, custom, screen, art),
                             reference._hifi_target_palette(palette, custom, screen, art))
            self.assertEqual(cached.palette_source, reference.palette_source)
            self.assertEqual(cached.screen_palette, reference.screen_palette)

    def test_all_patterns_keep_frames_metrics_and_timing_with_cache(self):
        samples = [int(math.sin(2*math.pi*330*n/48000)*18000) for n in range(audio.BLOCK_FRAMES)]
        pcm = struct.pack('<%dh' % (len(samples)*2), *(v for sample in samples for v in (sample, sample)))
        for style in sorted(audio.VALID_STYLES):
            cached, reference = audio.AudioSyncProcessor(), Uncached()
            colours = self.colours()
            for block in range(24):
                if block == 13:colours[0][:] = [20, 190, 70]
                options = dict(style=style, brightness=160, sensitivity=100, reactivity='balanced',
                               palette='screen-sync', screen_colours=colours, timestamp_s=100+block*.06)
                self.assertEqual(cached.process(pcm, **options), reference.process(pcm, **options), (style, block))
                self.assertEqual(cached.hifi_metrics, reference.hifi_metrics)
                self.assertEqual(cached.levels, reference.levels)
                self.assertEqual(cached.screen_palette, reference.screen_palette)
                self.assertEqual(cached.response_timing('balanced'), reference.response_timing('balanced'))


if __name__ == '__main__':unittest.main()
