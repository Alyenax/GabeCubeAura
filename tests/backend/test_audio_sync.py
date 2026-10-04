import colorsys
import json
import math
import struct
import tempfile
import time
from pathlib import Path
import unittest

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.models import GameState, ProviderOutput
from signalbar.providers.audio_sync import (
    AudioCaptureService, AudioSyncProcessor, AudioSyncProvider,
    ADAPTIVE_STYLES, BLOCK_BYTES, BLOCK_FRAMES, BYTES_PER_SECOND,
    EXPERIMENTAL_STYLES, LED_COUNT, PALETTES, VALID_STYLES,
)
from signalbar.settings import SettingsStore
from signalbar.settings.store import AUDIO_SYNC_STYLE_TUNING


def stereo_tone(frequency, amplitude=0.7, left=1.0, right=1.0):
    values = []
    for index in range(BLOCK_FRAMES):
        sample = math.sin(2.0 * math.pi * frequency * index / 48000.0) * amplitude
        values.extend((
            int(max(-1.0, min(1.0, sample * left)) * 32767),
            int(max(-1.0, min(1.0, sample * right)) * 32767),
        ))
    return struct.pack(f"<{len(values)}h", *values)


class FakeCapture:
    def __init__(self, raw=None, now=None):
        self.raw = raw
        self.now = time.monotonic() if now is None else now
        self.active = False
        self.sequence = 1
        self.pending = []

    def set_active(self, active):
        self.active = bool(active)

    def stop(self):
        self.active = False

    def latest(self):
        return self.raw, self.sequence, self.now

    def pending_after(self, sequence):
        return [block for block in self.pending if block[1] > sequence]

    def status(self):
        return {"phase": "capturing" if self.active else "off", "error": ""}


class AudioSyncTests(unittest.TestCase):
    @staticmethod
    def palette_lightness(colour):
        return colorsys.rgb_to_hls(*(channel / 255.0 for channel in colour))[1]

    @staticmethod
    def palette_hue(colour):
        return colorsys.rgb_to_hls(*(channel / 255.0 for channel in colour))[0]

    def values(self, **changes):
        values = {
            "audio_sync_style": "spectrum",
            "audio_sync_brightness": 200,
            "audio_sync_sensitivity": 100,
            "audio_sync_reactivity": "fast",
            "audio_sync_palette": "aurora",
            "audio_sync_lab_crest_strength": 100,
            "audio_sync_lab_edge_reach": 100,
            "audio_sync_lab_background": 100,
            "audio_sync_colour_low": [0, 170, 255],
            "audio_sync_colour_middle": [112, 42, 255],
            "audio_sync_colour_high": [255, 48, 140],
        }
        values.update(changes)
        return values

    def test_spectrum_maps_low_middle_and_high_tones_to_ordered_leds(self):
        peaks = []
        for frequency in (90, 900, 9000):
            processor = AudioSyncProcessor()
            processor.process(stereo_tone(frequency), **{
                "style": "spectrum", "brightness": 200, "sensitivity": 100,
                "reactivity": "fast", "palette": "aurora",
            })
            peaks.append(max(range(LED_COUNT), key=lambda index: processor.levels[index]))
        self.assertLess(peaks[0], peaks[1])
        self.assertLess(peaks[1], peaks[2])
        self.assertGreaterEqual(peaks[2] - peaks[0], 8)

    def test_magma_and_forest_keep_the_exact_requested_rgb_anchors(self):
        self.assertEqual(
            PALETTES["magma"],
            ((255, 255, 46), (255, 173, 41), (255, 4, 0)),
        )
        self.assertEqual(
            PALETTES["forest"],
            ((138, 255, 196), (72, 224, 115), (57, 122, 41)),
        )

    def test_hardware_lab_palette_bank_keeps_three_bounded_roles(self):
        expected = {
            "copper", "solar", "pearl", "glacier", "lagoon", "lime",
            "orchid", "plasma", "sunset", "deep-sea", "silver", "candy",
        }
        self.assertTrue(expected.issubset(PALETTES))
        for name in expected:
            self.assertEqual(len(PALETTES[name]), 3, name)
            self.assertTrue(
                all(0 <= channel <= 255 for colour in PALETTES[name] for channel in colour),
                name,
            )

    def test_every_style_returns_exactly_seventeen_bounded_pixels(self):
        screen = [(index * 12, 60, 220 - index * 8) for index in range(LED_COUNT)]
        for style in (
            "hifi-crest", *sorted(EXPERIMENTAL_STYLES), "spectrum",
            "spatial", "bass", "audio-pulse",
        ):
            frame = AudioSyncProcessor().process(
                stereo_tone(220), style=style, brightness=180, sensitivity=110,
                reactivity="balanced", palette="ice", screen_colours=screen,
            )
            self.assertEqual(len(frame), LED_COUNT)
            self.assertTrue(all(0 <= channel <= 255 for pixel in frame for channel in pixel))

    def test_every_style_uses_the_shared_adaptive_programme_window(self):
        self.assertEqual(ADAPTIVE_STYLES, VALID_STYLES)
        legacy_styles = {
            "spectrum", "spatial", "bass", "audio-pulse",
        }
        for style in sorted(VALID_STYLES):
            processor = AudioSyncProcessor()
            initial_db_range = tuple(processor._spectrum_db_range)
            for index in range(24):
                processor.process(
                    stereo_tone(330, amplitude=0.04 if index < 12 else 0.32),
                    style=style, brightness=180, sensitivity=100,
                    reactivity="balanced", palette="artwork",
                    artwork_colours=((30, 80, 180), (90, 40, 190), (220, 90, 150)),
                )
            self.assertAlmostEqual(processor.hifi_metrics["window_s"], 1.44, places=2)
            self.assertEqual(processor.palette_source, "artwork", style)
            if style in legacy_styles:
                self.assertNotEqual(tuple(processor._spectrum_db_range), initial_db_range, style)

    def test_experimental_patterns_are_distinct_and_keep_the_optical_guard(self):
        signatures = {}
        for style in sorted(EXPERIMENTAL_STYLES):
            processor = AudioSyncProcessor()
            frames = []
            for _ in range(12):
                frames.append(processor.process(
                    stereo_tone(330, amplitude=0.28), style=style,
                    brightness=255, sensitivity=100, reactivity="balanced",
                    palette="custom",
                    custom_colours=((255, 255, 255),) * 3,
                ))
            frames.append(processor.process(
                stereo_tone(90, amplitude=0.92), style=style,
                brightness=255, sensitivity=100, reactivity="balanced",
                palette="custom", custom_colours=((255, 255, 255),) * 3,
            ))
            frame = frames[-1]
            lit = [pixel for pixel in frame if pixel != (0, 0, 0)]
            self.assertTrue(lit, style)
            self.assertTrue(all(max(pixel) >= 34 for pixel in lit), style)
            self.assertTrue(all(max(pixel) <= 212 for pixel in lit), style)
            signatures[style] = frame
        self.assertEqual(len(set(signatures.values())), len(EXPERIMENTAL_STYLES))

    def test_velvet_relay_moves_one_impact_from_centre_toward_the_edges(self):
        processor = AudioSyncProcessor()
        common = {
            "style": "velvet-relay", "brightness": 255, "sensitivity": 100,
            "reactivity": "balanced", "palette": "custom",
            "custom_colours": ((255, 255, 255),) * 3,
        }
        silence = stereo_tone(90, amplitude=0.0)
        for _ in range(14):
            processor.process(silence, **common)
        frames = [processor.process(stereo_tone(90, amplitude=0.92), **common)]
        frames.extend(processor.process(silence, **common) for _ in range(5))
        distances = []
        for frame in frames:
            peak = max(range(LED_COUNT), key=lambda index: sum(frame[index]))
            distances.append(abs(peak - LED_COUNT // 2))
        self.assertLessEqual(distances[0], 1)
        self.assertGreaterEqual(max(distances[2:]), 5)

    def test_negative_bloom_uses_true_black_instead_of_dark_tinted_rgb(self):
        processor = AudioSyncProcessor()
        common = {
            "style": "negative-bloom", "brightness": 220, "sensitivity": 100,
            "reactivity": "balanced", "palette": "ember",
        }
        for _ in range(14):
            processor.process(stereo_tone(330, amplitude=0.25), **common)
        frame = processor.process(stereo_tone(90, amplitude=0.92), **common)
        self.assertIn((0, 0, 0), frame)
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in frame))

    def test_stereo_lanterns_preserve_left_and_right_direction(self):
        common = {
            "style": "stereo-lanterns", "brightness": 220,
            "sensitivity": 120, "reactivity": "fast", "palette": "aurora",
        }
        left = AudioSyncProcessor().process(
            stereo_tone(440, left=1.0, right=0.02), **common,
        )
        right = AudioSyncProcessor().process(
            stereo_tone(440, left=0.02, right=1.0), **common,
        )
        power = lambda pixel: sum(pixel)
        self.assertGreater(sum(map(power, left[:7])), sum(map(power, left[-7:])))
        self.assertGreater(sum(map(power, right[-7:])), sum(map(power, right[:7])))

    def test_hifi_crest_maps_bass_mid_and_high_to_broad_optical_zones(self):
        white = ((255, 255, 255),) * 3
        frames = {}
        for name, frequency in (("bass", 90), ("mid", 900), ("high", 8000)):
            frames[name] = AudioSyncProcessor().process(
                stereo_tone(frequency), style="hifi-crest", brightness=255,
                sensitivity=100, reactivity="balanced", palette="custom",
                custom_colours=white,
            )
        power = lambda frame, indexes: sum(sum(frame[index]) for index in indexes)
        self.assertGreater(power(frames["bass"], range(6, 11)), power(frames["bass"], (0, 1, 15, 16)))
        self.assertGreater(power(frames["mid"], (3, 4, 5, 11, 12, 13)), power(frames["mid"], range(7, 10)))
        self.assertGreater(power(frames["high"], (0, 1, 15, 16)), power(frames["high"], range(7, 10)))

    def test_hifi_crest_preserves_stereo_direction_without_changing_roles(self):
        settings = {
            "style": "hifi-crest", "brightness": 255, "sensitivity": 100,
            "reactivity": "balanced", "palette": "custom",
            "custom_colours": ((255, 255, 255),) * 3,
        }
        left = AudioSyncProcessor().process(
            stereo_tone(440, left=1.0, right=0.02), **settings,
        )
        right = AudioSyncProcessor().process(
            stereo_tone(440, left=0.02, right=1.0), **settings,
        )
        self.assertGreater(sum(map(sum, left[:7])), sum(map(sum, left[-7:])))
        self.assertGreater(sum(map(sum, right[-7:])), sum(map(sum, right[:7])))
        mirrored_right = tuple(reversed(right))
        for index in range(LED_COUNT):
            self.assertLessEqual(
                max(abs(a - b) for a, b in zip(left[index], mirrored_right[index])),
                3,
            )

    def test_hifi_crest_screen_sync_palette_uses_three_live_colours(self):
        screen = [(225, 28, 22)] * 204 + [(24, 210, 72)] * 204 + [(30, 68, 230)] * 204
        processor = AudioSyncProcessor()
        frame = processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
            screen_colours=screen,
        )
        self.assertEqual(len(processor.screen_palette), 3)
        self.assertEqual(processor.palette_source, "screen-sync")
        self.assertEqual(len(frame), LED_COUNT)
        self.assertGreater(len(set(frame)), 8)

    def test_experimental_patterns_share_contextual_palette_sources(self):
        screen = [(225, 28, 22)] * 204 + [(24, 210, 72)] * 204 + [(30, 68, 230)] * 204
        artwork = [(218, 42, 30), (36, 190, 78), (42, 76, 220)]
        for style in EXPERIMENTAL_STYLES:
            screen_processor = AudioSyncProcessor()
            screen_processor.process(
                stereo_tone(330), style=style, brightness=220,
                sensitivity=100, reactivity="balanced", palette="screen-sync",
                screen_colours=screen,
            )
            self.assertEqual(screen_processor.palette_source, "screen-sync", style)
            self.assertEqual(len(screen_processor.screen_palette), 3, style)

            artwork_processor = AudioSyncProcessor()
            artwork_processor.process(
                stereo_tone(330), style=style, brightness=220,
                sensitivity=100, reactivity="balanced", palette="artwork",
                artwork_colours=artwork,
            )
            self.assertEqual(artwork_processor.palette_source, "artwork", style)
            self.assertEqual(len(artwork_processor.screen_palette), 3, style)

    def test_hifi_crest_screen_sync_assigns_dark_edges_mid_shoulders_and_light_centre(self):
        # Large white and black areas previously became raw palette anchors,
        # which made the mirrored centre flash white or disappear completely.
        screen = (
            [(255, 255, 255)] * 180
            + [(0, 0, 0)] * 180
            + [(26, 104, 218)] * 90
            + [(116, 42, 194)] * 62
        )
        processor = AudioSyncProcessor()
        processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
            screen_colours=screen,
        )
        outer, shoulder, centre = processor.screen_palette
        lightness = tuple(self.palette_lightness(colour) for colour in processor.screen_palette)
        self.assertGreater(lightness[1] - lightness[0], 0.14)
        self.assertGreater(lightness[2] - lightness[1], 0.20)
        self.assertLess(max(centre), 250)
        self.assertGreater(sum(centre), 180)
        self.assertGreater(sum(shoulder), sum(outer))

        centre_hue = self.palette_hue(centre)
        for colour, maximum in ((shoulder, 33.0), (outer, 21.0)):
            hue = self.palette_hue(colour)
            distance = abs((hue - centre_hue + 0.5) % 1.0 - 0.5) * 360.0
            self.assertLessEqual(distance, maximum)

    def test_hifi_crest_black_screen_keeps_the_last_structured_palette(self):
        processor = AudioSyncProcessor()
        processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
            screen_colours=[(26, 104, 218)] * 300 + [(116, 42, 194)] * 312,
        )
        previous = processor.screen_palette
        processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
            screen_colours=[(0, 0, 0)] * 612,
        )
        self.assertEqual(processor.screen_palette, previous)
        self.assertTrue(any(channel > 0 for colour in previous for channel in colour))

    def test_hifi_crest_screen_sync_falls_back_to_artwork_then_sapphire(self):
        processor = AudioSyncProcessor()
        artwork = [(225, 28, 22), (24, 210, 72), (30, 68, 230)]
        processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
            artwork_colours=artwork,
        )
        self.assertEqual(processor.palette_source, "artwork")
        self.assertEqual(len(processor.screen_palette), 3)
        processor.reset()
        processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
        )
        self.assertEqual(processor.palette_source, "sapphire-fallback")
        self.assertEqual(processor.screen_palette, ())
        self.assertEqual(
            processor._hifi_palette,
            tuple(tuple(float(channel) for channel in colour) for colour in PALETTES["sapphire"]),
        )

    def test_hifi_crest_artwork_palette_uses_the_active_game_palette(self):
        processor = AudioSyncProcessor()
        artwork = [(225, 28, 22), (24, 210, 72), (30, 68, 230)]
        frame = processor.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="artwork",
            artwork_colours=artwork,
        )
        self.assertEqual(processor.palette_source, "artwork")
        self.assertEqual(len(processor.screen_palette), 3)
        self.assertGreater(len(set(frame)), 8)

    def test_hifi_crest_artwork_and_screen_sync_share_the_same_optical_roles(self):
        source = [
            (250, 250, 250), (2, 2, 2), (26, 104, 218),
            (116, 42, 194), (38, 178, 160),
        ] * 30
        screen = AudioSyncProcessor()
        screen.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="screen-sync",
            screen_colours=source,
        )
        artwork = AudioSyncProcessor()
        artwork.process(
            stereo_tone(330), style="hifi-crest", brightness=255,
            sensitivity=100, reactivity="balanced", palette="artwork",
            artwork_colours=source,
        )
        self.assertEqual(screen.screen_palette, artwork.screen_palette)
        lightness = [self.palette_lightness(colour) for colour in artwork.screen_palette]
        self.assertLess(lightness[0], lightness[1])
        self.assertLess(lightness[1], lightness[2])

    def test_hifi_crest_window_and_envelopes_reset_with_capture(self):
        processor = AudioSyncProcessor()
        arguments = {
            "style": "hifi-crest", "brightness": 200, "sensitivity": 100,
            "reactivity": "balanced", "palette": "aurora",
        }
        processor.process(stereo_tone(90), **arguments)
        self.assertGreater(processor.hifi_metrics["impact"], 0.5)
        self.assertGreater(processor.hifi_metrics["window_s"], 0.0)
        processor.reset()
        self.assertEqual(processor.hifi_metrics["impact"], 0.0)
        self.assertEqual(processor.hifi_metrics["window_s"], 0.0)

    def test_hifi_crest_lab_controls_isolate_strength_reach_and_background(self):
        silence = stereo_tone(90, amplitude=0.0)
        impact = stereo_tone(90, amplitude=0.92)
        common = {
            "style": "hifi-crest", "brightness": 160, "sensitivity": 100,
            "reactivity": "balanced", "palette": "custom",
            "custom_colours": ((255, 255, 255),) * 3,
        }

        def sequence(**lab):
            processor = AudioSyncProcessor()
            for _ in range(14):
                processor.process(silence, **common, **lab)
            frames = [processor.process(impact, **common, **lab)]
            frames.extend(processor.process(silence, **common, **lab) for _ in range(6))
            return frames

        reference = sequence(crest_strength=100, edge_reach=100, background_level=100)
        peak_distances = []
        for frame in reference[:5]:
            peak = max(range(LED_COUNT), key=lambda index: frame[index][0])
            peak_distances.append(abs(peak - LED_COUNT // 2))
        self.assertEqual(peak_distances, [0, 1, 3, 4, 5])

        weak = sequence(crest_strength=0, edge_reach=100, background_level=100)
        strong = sequence(crest_strength=250, edge_reach=100, background_level=100)
        self.assertGreater(strong[1][7][0], weak[1][7][0])

        short = sequence(crest_strength=100, edge_reach=50, background_level=100)
        long = sequence(crest_strength=100, edge_reach=200, background_level=100)
        self.assertGreater(long[6][0][0], short[6][0][0])

        no_background = sequence(crest_strength=0, edge_reach=100, background_level=0)
        self.assertTrue(all(channel == 0 for pixel in no_background[0] for channel in pixel))

    def test_spatial_mode_follows_stereo_balance(self):
        left = AudioSyncProcessor().process(
            stereo_tone(440, left=1.0, right=0.02), style="spatial",
            brightness=220, sensitivity=120, reactivity="fast", palette="aurora",
        )
        right = AudioSyncProcessor().process(
            stereo_tone(440, left=0.02, right=1.0), style="spatial",
            brightness=220, sensitivity=120, reactivity="fast", palette="aurora",
        )
        power = lambda pixel: sum(pixel)
        self.assertGreater(sum(map(power, left[:5])), sum(map(power, left[-5:])))
        self.assertGreater(sum(map(power, right[-5:])), sum(map(power, right[:5])))

    def test_bass_pulse_prefers_low_frequency_energy(self):
        low = AudioSyncProcessor().process(
            stereo_tone(80), style="bass", brightness=220, sensitivity=100,
            reactivity="fast", palette="aurora",
        )
        high = AudioSyncProcessor().process(
            stereo_tone(8000), style="bass", brightness=220, sensitivity=100,
            reactivity="fast", palette="aurora",
        )
        self.assertGreater(sum(sum(pixel) for pixel in low), sum(sum(pixel) for pixel in high) * 2)
        self.assertEqual(low, tuple(reversed(low)))
        self.assertGreater(len(set(low)), 8)

    def test_audio_pulse_keeps_screen_hues_and_silence_turns_off(self):
        screen = [(20 + index * 8, 100, 200 - index * 5) for index in range(LED_COUNT)]
        active = AudioSyncProcessor().process(
            stereo_tone(330), style="audio-pulse", brightness=255,
            sensitivity=130, reactivity="fast", palette="screen-sync", screen_colours=screen,
        )
        silent = AudioSyncProcessor().process(
            bytes(BLOCK_FRAMES * 4), style="audio-pulse", brightness=255,
            sensitivity=100, reactivity="fast", palette="screen-sync", screen_colours=screen,
        )
        self.assertGreater(sum(sum(pixel) for pixel in active), 0)
        self.assertLess(sum(sum(pixel) for pixel in silent), sum(sum(pixel) for pixel in active))

    def test_audio_pulse_reduces_live_image_to_three_harmonized_optical_roles(self):
        red = (225, 28, 22)
        green = (24, 210, 72)
        blue = (30, 68, 230)
        screen = [red] * 6 + [green] * 6 + [blue] * 5
        processor = AudioSyncProcessor()
        frame = processor.process(
            stereo_tone(330), style="audio-pulse", brightness=255,
            sensitivity=130, reactivity="fast", palette="screen-sync", screen_colours=screen,
        )
        palette = processor.screen_palette
        self.assertEqual(len(palette), 3)
        lightness = [self.palette_lightness(colour) for colour in palette]
        self.assertGreater(lightness[1] - lightness[0], 0.14)
        self.assertGreater(lightness[2] - lightness[1], 0.20)
        self.assertTrue(any(max(colour) - min(colour) > 80 for colour in palette))
        self.assertEqual(len(frame), LED_COUNT)
        self.assertEqual(frame, tuple(reversed(frame)))
        self.assertGreater(len(set(frame)), 8)

    def test_stereo_field_accepts_the_screen_sync_palette_independently(self):
        screen = [(225, 28, 22)] * 6 + [(24, 210, 72)] * 6 + [(30, 68, 230)] * 5
        left_processor = AudioSyncProcessor()
        left = left_processor.process(
            stereo_tone(440, left=1.0, right=0.02), style="spatial",
            brightness=255, sensitivity=130, reactivity="fast", palette="screen-sync",
            screen_colours=screen,
        )
        exact_stereo = AudioSyncProcessor().process(
            stereo_tone(440, left=1.0, right=0.02), style="spatial",
            brightness=255, sensitivity=130, reactivity="fast", palette="custom",
            custom_colours=left_processor.screen_palette,
        )
        right_processor = AudioSyncProcessor()
        right = right_processor.process(
            stereo_tone(440, left=0.02, right=1.0), style="spatial",
            brightness=255, sensitivity=130, reactivity="fast", palette="screen-sync",
            screen_colours=screen,
        )
        self.assertEqual(len(left_processor.screen_palette), 3)
        self.assertEqual(len(right_processor.screen_palette), 3)
        self.assertEqual(left, exact_stereo)
        self.assertGreater(len(set(left)), 10)
        power = lambda pixel: sum(pixel)
        self.assertGreater(sum(map(power, left[:5])), sum(map(power, left[-5:])))
        self.assertGreater(sum(map(power, right[-5:])), sum(map(power, right[:5])))

    def test_audio_pulse_uses_any_selected_palette_without_video_colours(self):
        processor = AudioSyncProcessor()
        frame = processor.process(
            stereo_tone(330), style="audio-pulse", brightness=255,
            sensitivity=130, reactivity="fast", palette="aurora",
        )
        self.assertEqual(processor.screen_palette, ())
        self.assertEqual(frame, tuple(reversed(frame)))
        self.assertGreater(len(set(frame)), 8)

    def test_capture_command_requests_the_sink_monitor_as_raw_stereo(self):
        command = AudioCaptureService.capture_command("/usr/bin/pw-record")
        self.assertIn("--raw", command)
        self.assertIn("--rate=48000", command)
        self.assertIn("--channels=2", command)
        self.assertTrue(any("stream.capture.sink" in argument for argument in command))

    def test_capture_keeps_fifty_ms_remainders_and_emits_exact_sixty_ms_blocks(self):
        capture = AudioCaptureService(clock=lambda: 10.0)
        fifty_ms = int(BYTES_PER_SECOND * 0.05)
        first = bytes([1]) * fifty_ms
        second = bytes([2]) * fifty_ms
        third = bytes([3]) * fifty_ms

        self.assertEqual(capture.ingest(first, 10.05), 0)
        self.assertEqual(capture.status()["buffered_ms"], 50.0)
        self.assertEqual(capture.ingest(second, 10.10), 1)
        self.assertAlmostEqual(capture.status()["buffered_ms"], 40.0)
        self.assertEqual(capture.ingest(third, 10.15), 1)
        self.assertAlmostEqual(capture.status()["buffered_ms"], 30.0)

        pending = capture.pending_after(-1)
        self.assertEqual(len(pending), 2)
        self.assertEqual(len(pending[0][0]), BLOCK_BYTES)
        self.assertEqual(pending[0][0], first + second[:BLOCK_BYTES - len(first)])
        self.assertAlmostEqual(pending[1][2] - pending[0][2], 0.06, places=6)
        self.assertEqual(capture.status()["dropped_blocks"], 0)

    def test_provider_processes_every_queued_audio_block_in_order(self):
        first = stereo_tone(90)
        second = stereo_tone(900)
        capture = FakeCapture(second, now=10.06)
        capture.sequence = 2
        capture.pending = [(first, 1, 10.0), (second, 2, 10.06)]
        provider = AudioSyncProvider(capture=capture, clock=lambda: 10.06)
        provider.set_active(True)

        self.assertIsNotNone(provider.output(self.values(audio_sync_style="hifi-crest")).frame)
        self.assertAlmostEqual(provider.processor.hifi_metrics["window_s"], 0.12)

    def test_reactivity_reports_discrete_ninety_percent_response_times(self):
        balanced = AudioSyncProcessor.response_timing("balanced")
        self.assertEqual(balanced["level"], {"rise_ms": 180.0, "fall_ms": 840.0})
        self.assertEqual(balanced["impact"], {"rise_ms": 60.0, "fall_ms": 780.0})
        self.assertEqual(balanced["texture"], {"rise_ms": 60.0, "fall_ms": 420.0})

        punchy = AudioSyncProcessor.response_timing("punchy")
        for envelope in ("level", "impact", "attack", "texture", "background"):
            self.assertEqual(punchy[envelope], {"rise_ms": 60.0, "fall_ms": 60.0})
        self.assertEqual(punchy["crest"], {
            "cooldown_ms": 120.0,
            "centre_to_edge_ms": 120.0,
            "lifetime_ms": 180.0,
        })

    def test_provider_rejects_stale_audio_and_exposes_live_frame(self):
        now = [10.0]
        capture = FakeCapture(stereo_tone(440), now=10.0)
        provider = AudioSyncProvider(capture=capture, clock=lambda: now[0])
        provider.set_active(True)
        self.assertIsNotNone(provider.output(self.values()).frame)
        now[0] = 12.0
        self.assertIsNone(provider.output(self.values()).frame)
        provider.set_active(False)
        self.assertFalse(capture.active)

    def test_audio_is_a_permanent_base_below_system_and_temporary_priority(self):
        frame = tuple([(20, 40, 80)] * LED_COUNT)
        output = ProviderOutput("audio-sync:spectrum", frame, "audio")
        empty = ProviderOutput("none", None, "")
        arbiter = Arbiter()
        base = dict(
            mode="audio_sync", guard_allows=True, game=GameState(),
            performance=empty, artwork=empty, idle=empty, audio_sync_base=output,
        )
        self.assertEqual(arbiter.choose(**base).provider, "audio-sync:spectrum")
        self.assertEqual(arbiter.choose(**base, steam_priority=True).provider, "valve")
        event = ProviderOutput("event:notification", frame, "event")
        self.assertEqual(arbiter.choose(**base, event=event).provider, "event:notification")

    def test_audio_context_transition_waits_for_a_real_screen_palette(self):
        frame = ProviderOutput("audio-sync:slow-prism", tuple([(20, 40, 80)] * 17), "audio")
        empty = ProviderOutput("audio-sync", None, "waiting")
        ready = Engine._audio_transition_ready
        self.assertFalse(ready(empty, True, "held-transition"))
        self.assertFalse(ready(frame, True, "held-transition"))
        self.assertFalse(ready(frame, True, "sapphire-fallback"))
        self.assertTrue(ready(frame, True, "screen-sync"))
        self.assertTrue(ready(frame, False, "selected"))

    def test_audio_context_transition_holds_only_noncritical_empty_outputs(self):
        empty = ProviderOutput("none", None, "waiting")
        valve = ProviderOutput("valve", None, "ordinary native write")
        live = ProviderOutput("audio-sync:slow-prism", tuple([(20, 40, 80)] * 17), "audio")
        hold = Engine._hold_context_frame
        self.assertTrue(hold(True, True, True, False, False, False, empty))
        self.assertTrue(hold(True, True, False, False, False, False, valve))
        self.assertFalse(hold(False, True, True, False, False, False, empty))
        self.assertFalse(hold(True, False, True, False, False, False, empty))
        self.assertFalse(hold(True, True, True, True, False, False, valve))
        self.assertFalse(hold(True, True, True, False, True, False, empty))
        self.assertFalse(hold(True, True, True, False, False, True, empty))
        self.assertFalse(hold(True, True, True, False, False, False, live))

    def test_screensaver_screen_sync_replaces_audio_then_audio_can_restart(self):
        audio_frame = tuple([(20, 40, 80)] * LED_COUNT)
        screen_frame = tuple([(80, 40, 20)] * LED_COUNT)
        empty = ProviderOutput("none", None, "")
        decision = Arbiter().choose(
            mode="screen_sync", guard_allows=True, game=GameState(),
            performance=empty, artwork=empty, idle=empty,
            audio_sync_base=ProviderOutput("audio-sync:spectrum", audio_frame, "audio"),
            screen_sync_base=ProviderOutput("screen-sync", screen_frame, "screensaver"),
        )
        self.assertEqual(decision.provider, "screen-sync")
        capture = FakeCapture(stereo_tone(440))
        provider = AudioSyncProvider(capture=capture)
        provider.set_active(True)
        provider.set_active(False)
        self.assertFalse(capture.active)
        provider.set_active(True)
        self.assertTrue(capture.active)

    def test_settings_validate_audio_routes_and_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            values = store.update({
                "home_display": "audio_sync", "game_display": "audio_sync",
                "audio_sync_style": "velvet-relay", "audio_sync_sensitivity": 999,
                "audio_sync_reactivity": "punchy",
                "audio_sync_brightness": 1, "audio_sync_palette": "game",
                "audio_sync_lab_crest_strength": 999,
                "audio_sync_lab_edge_reach": 1,
                "audio_sync_lab_background": -50,
                "audio_sync_colour_low": [-2, 40, 999],
            })
            self.assertEqual(values["home_display"], "audio_sync")
            self.assertEqual(values["game_display"], "audio_sync")
            self.assertEqual(values["mode"], "audio_sync")
            self.assertEqual(values["audio_sync_style"], "velvet-relay")
            self.assertEqual(values["audio_sync_reactivity"], "punchy")
            self.assertEqual(values["audio_sync_palette"], "screen-sync")
            self.assertEqual(values["audio_sync_sensitivity"], 100)
            self.assertEqual(values["audio_sync_brightness"], 34)
            self.assertEqual(values["audio_sync_lab_crest_strength"], 250)
            self.assertEqual(values["audio_sync_lab_edge_reach"], 50)
            self.assertEqual(values["audio_sync_lab_background"], 0)
            self.assertEqual(values["audio_sync_colour_low"], [0, 40, 255])
            self.assertEqual(values["audio_sync_home_colour_low"], [0, 40, 255])
            self.assertEqual(values["audio_sync_game_colour_low"], [0, 40, 255])

    def test_home_and_game_pattern_palettes_are_independent_and_legacy_migrates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({
                "audio_sync_style": "slow-prism",
                "audio_sync_palette": "pearl",
                "audio_sync_colour_low": [12, 34, 56],
                "audio_sync_colour_middle": [78, 90, 123],
                "audio_sync_colour_high": [145, 167, 189],
            }), encoding="utf-8")
            store = SettingsStore(str(path))
            migrated = store.all()
            self.assertEqual(migrated["audio_sync_home_style"], "slow-prism")
            self.assertEqual(migrated["audio_sync_game_style"], "slow-prism")
            self.assertEqual(migrated["audio_sync_home_palette"], "pearl")
            self.assertEqual(migrated["audio_sync_game_palette"], "pearl")
            self.assertEqual(migrated["audio_sync_home_colour_low"], [12, 34, 56])
            self.assertEqual(migrated["audio_sync_game_colour_high"], [145, 167, 189])

            changed = store.update({
                "audio_sync_home_style": "hifi-crest",
                "audio_sync_home_palette": "forest",
                "audio_sync_game_style": "stereo-lanterns",
                "audio_sync_game_palette": "artwork",
                "audio_sync_home_colour_low": [99, 135, 233],
                "audio_sync_game_colour_low": [11, 94, 142],
            })
            self.assertEqual(changed["audio_sync_home_style"], "hifi-crest")
            self.assertEqual(changed["audio_sync_home_palette"], "forest")
            self.assertEqual(changed["audio_sync_game_style"], "stereo-lanterns")
            self.assertEqual(changed["audio_sync_game_palette"], "artwork")
            self.assertEqual(changed["audio_sync_home_colour_low"], [99, 135, 233])
            self.assertEqual(changed["audio_sync_game_colour_low"], [11, 94, 142])

    def test_combined_screen_styles_migrate_to_independent_pattern_and_palette(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({
                "audio_sync_style": "screen-pulse",
                "audio_sync_home_style": "screen-pulse",
                "audio_sync_game_style": "screen-spatial",
                "audio_sync_home_palette": "screen-sync",
                "audio_sync_game_palette": "screen-sync",
            }), encoding="utf-8")
            migrated = SettingsStore(str(path)).all()
            self.assertEqual(migrated["audio_sync_style"], "audio-pulse")
            self.assertEqual(migrated["audio_sync_home_style"], "audio-pulse")
            self.assertEqual(migrated["audio_sync_game_style"], "spatial")
            self.assertEqual(migrated["audio_sync_home_palette"], "screen-sync")
            self.assertEqual(migrated["audio_sync_game_palette"], "screen-sync")

    def test_engine_resolves_the_audio_pair_for_the_current_context(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            store.update({
                "home_display": "audio_sync",
                "game_display": "audio_sync",
                "audio_sync_home_style": "slow-prism",
                "audio_sync_home_palette": "pearl",
                "audio_sync_game_style": "stereo-lanterns",
                "audio_sync_game_palette": "artwork",
                "audio_sync_home_colour_low": [99, 135, 233],
                "audio_sync_game_colour_low": [11, 94, 142],
            })
            engine = Engine(store, str(Path(directory) / "artwork.json"))
            home = engine.status()
            self.assertEqual(home["audio_sync_style"], "slow-prism")
            self.assertEqual(home["audio_sync_palette"], "pearl")
            self.assertEqual(home["audio_sync_home_colour_low"], [99, 135, 233])
            self.assertEqual(home["audio_sync_game_colour_low"], [11, 94, 142])

            engine.set_game(42, "Example Game")
            game = engine.status()
            self.assertEqual(game["audio_sync_style"], "stereo-lanterns")
            self.assertEqual(game["audio_sync_palette"], "artwork")

    def test_sapphire_and_coastline_keep_the_physically_tested_led_order(self):
        self.assertEqual(PALETTES["sapphire"], (
            (99, 135, 233), (78, 118, 228), (78, 118, 228),
        ))
        self.assertEqual(PALETTES["coastline"], (
            (11, 94, 142), (8, 127, 191), (26, 159, 255),
        ))

    def test_contextual_palette_holds_last_colour_during_session_restart(self):
        processor = AudioSyncProcessor()
        block = stereo_tone(110)
        processor.process(
            block, style="hifi-crest", palette="pearl",
            brightness=160, sensitivity=100, reactivity="balanced",
            timestamp_s=1.0,
        )
        pearl = processor._hifi_palette
        self.assertIsNotNone(pearl)

        processor.reset(preserve_palette=True)
        processor.process(
            block, style="hifi-crest", palette="artwork",
            brightness=160, sensitivity=100, reactivity="balanced",
            artwork_colours=(), timestamp_s=1.06,
        )
        self.assertEqual(processor.palette_source, "held-transition")
        self.assertEqual(processor._hifi_palette, pearl)
        self.assertNotEqual(processor._hifi_palette, tuple(
            tuple(float(channel) for channel in colour)
            for colour in PALETTES["aurora"]
        ))

    def test_selecting_each_style_loads_its_hardware_tuned_recommendation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            for style, expected in AUDIO_SYNC_STYLE_TUNING.items():
                values = store.update({"audio_sync_style": style})
                for key, value in expected.items():
                    self.assertEqual(values[key], value, f"{style}: {key}")

            values = store.update({
                "audio_sync_style": "constellation",
                "audio_sync_brightness": 150,
                "audio_sync_sensitivity": 93,
                "audio_sync_reactivity": "calm",
            })
            self.assertEqual(values["audio_sync_brightness"], 150)
            self.assertEqual(values["audio_sync_sensitivity"], 100)
            self.assertEqual(values["audio_sync_reactivity"], "calm")


if __name__ == "__main__":
    unittest.main()
