from pathlib import Path
import tempfile
import unittest

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.models import GameState, ProviderOutput
from signalbar.providers.artwork import ArtworkProvider
from signalbar.providers.launch_artwork import LaunchArtworkProvider, PATTERNS, launch_frame
from signalbar.settings import SettingsStore


PALETTES = {
    "2": [[255, 214, 0], [0, 210, 255]],
    "3": [[255, 214, 0], [0, 210, 255], [255, 38, 120]],
}
ARTWORK_FRAME = [(20, 40, 80)] * 17


class ManualClock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class LaunchArtworkTests(unittest.TestCase):
    @staticmethod
    def _belongs_to_palette(pixel, palette):
        if pixel == (0, 0, 0):
            return True
        for colour in palette:
            scale = max(pixel) / max(colour)
            if all(abs(channel - round(source * scale)) <= 1
                   for channel, source in zip(pixel, colour)):
                return True
        return False

    def test_arbiter_places_launch_below_alerts_and_countdown_above_artwork(self):
        arbiter = Arbiter()
        game = GameState(42, "Test")
        launch = ProviderOutput("launch-artwork:ripple", tuple(ARTWORK_FRAME), "launch")
        artwork = ProviderOutput("artwork", tuple(ARTWORK_FRAME), "artwork")
        empty = ProviderOutput("none", None, "")
        kwargs = dict(mode="artwork", game=game, performance=empty, artwork=artwork, idle=empty)
        self.assertEqual(arbiter.choose(guard_allows=True, launch_artwork=launch, **kwargs).provider,
                         "launch-artwork:ripple")
        self.assertEqual(arbiter.choose(guard_allows=False, launch_artwork=launch, **kwargs).provider,
                         "valve")
        self.assertEqual(arbiter.choose(guard_allows=True, launch_artwork=launch,
                                       signal=ProviderOutput("countdown", tuple(ARTWORK_FRAME), "timer"),
                                       **kwargs).provider, "launch-artwork:ripple")
        self.assertEqual(arbiter.choose(guard_allows=True, launch_artwork=launch,
                                       signal=ProviderOutput("countdown", tuple(ARTWORK_FRAME), "timer"),
                                       signal_critical=True, **kwargs).provider, "countdown")
        self.assertEqual(arbiter.choose(guard_allows=True, launch_artwork=launch,
                                       event=ProviderOutput("event:notification", tuple(ARTWORK_FRAME), "alert"),
                                       **kwargs).provider, "event:notification")

    def test_every_pattern_is_deterministic_bounded_and_fades_to_black(self):
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                first = launch_frame(pattern, PALETTES["3"], 1.7, 8)
                self.assertEqual(first, launch_frame(pattern, PALETTES["3"], 1.7, 8))
                self.assertEqual(len(first), 17)
                self.assertTrue(any(pixel != (0, 0, 0) for pixel in first))
                self.assertTrue(all(0 <= channel <= 255 for pixel in first for channel in pixel))
                self.assertTrue(all(max(pixel) <= 70 for pixel in launch_frame(pattern, PALETTES["2"], .05, 8)))
                self.assertEqual(launch_frame(pattern, PALETTES["2"], 8, 8), ((0, 0, 0),) * 17)

    def test_every_pattern_stays_inside_exact_two_and_three_hue_families(self):
        palettes = (
            [(255, 0, 0), (0, 0, 255)],
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
        )
        for pattern in PATTERNS:
            for palette in palettes:
                with self.subTest(pattern=pattern, colours=len(palette)):
                    frames = [launch_frame(pattern, palette, tick / 20, 8) for tick in range(1, 160)]
                    self.assertTrue(any(pixel != (0, 0, 0) for frame in frames for pixel in frame))
                    self.assertTrue(all(
                        self._belongs_to_palette(pixel, palette)
                        for frame in frames for pixel in frame
                    ))

    def test_provider_waits_for_palette_starts_once_and_expires(self):
        clock = ManualClock()
        provider = LaunchArtworkProvider(clock=clock)
        provider.configure(True, "scanner", 2, 5)
        self.assertTrue(provider.arm(42))
        self.assertIsNone(provider.output(42, allow_start=True).frame)
        provider.set_palettes(42, PALETTES)
        self.assertIsNone(provider.output(42, allow_start=False).frame)
        output = provider.output(42, allow_start=True)
        self.assertEqual(output.provider, "launch-artwork:scanner")
        self.assertEqual(len(output.frame), 17)
        clock.advance(5.1)
        self.assertIsNone(provider.output(42, allow_start=True).frame)
        self.assertFalse(provider.status()["active"])

    def test_manual_preview_runs_even_when_automatic_launches_are_disabled(self):
        clock = ManualClock()
        provider = LaunchArtworkProvider(clock=clock)
        provider.configure(False, "crescendo", 2, 5)
        provider.set_palettes(42, PALETTES)
        self.assertTrue(provider.arm(42, preview=True))
        provider.output(42, allow_start=True)
        clock.advance(.5)
        output = provider.output(42, allow_start=True)
        self.assertEqual(output.provider, "launch-artwork:crescendo")
        self.assertTrue(provider.status(42)["active"])
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in output.frame))

    def test_pending_launch_drops_after_safe_ownership_timeout(self):
        clock = ManualClock()
        provider = LaunchArtworkProvider(clock=clock)
        provider.configure(True, "ripple", 3, 8)
        provider.set_palettes(42, PALETTES)
        provider.arm(42)
        clock.advance(12.1)
        self.assertIsNone(provider.output(42, allow_start=False).frame)
        self.assertFalse(provider.status()["pending"])

    def test_short_alert_pauses_visible_duration_then_launch_resumes(self):
        clock = ManualClock()
        provider = LaunchArtworkProvider(clock=clock)
        provider.configure(True, "legato", 2, 5)
        provider.set_palettes(42, PALETTES)
        provider.arm(42)
        provider.output(42, allow_start=True)
        clock.advance(1)
        provider.output(42, paused=True)
        before = provider.status()["remaining_seconds"]
        clock.advance(2)
        self.assertIsNone(provider.output(42, paused=True).frame)
        self.assertAlmostEqual(provider.status()["remaining_seconds"], before)
        self.assertTrue(provider.status()["paused"])
        self.assertIsNotNone(provider.output(42, paused=False).frame)
        self.assertFalse(provider.status()["paused"])

    def test_inactive_status_uses_current_game_palette_for_preview(self):
        provider = LaunchArtworkProvider(clock=ManualClock())
        provider.configure(True, "ripple", 2, 8)
        provider.set_palettes(42, PALETTES)
        self.assertFalse(provider.status(42)["active"])
        self.assertEqual(provider.status(42)["dominant_colors"], PALETTES["2"])
        self.assertEqual(provider.status(99)["dominant_colors"], [])

    def test_artwork_cache_requires_and_restores_both_dominant_palettes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "art.json")
            provider = ArtworkProvider(path)
            provider.submit(42, "fingerprint", "auto", .34, ARTWORK_FRAME, .55,
                            "hero.jpg", "hero", PALETTES)
            reloaded = ArtworkProvider(path)
            self.assertTrue(reloaded.activate_cached(42, "fingerprint", "auto", .34))
            self.assertEqual(reloaded.dominant_palettes(42), PALETTES)
            self.assertEqual(reloaded.status(2)["dominant_colors"], PALETTES["2"])
            self.assertEqual(reloaded.status(3)["dominant_colors"], PALETTES["3"])

    def test_launch_colour_source_uses_a_cache_separate_from_permanent_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            engine = Engine(store, str(Path(directory) / "artwork-cache.json"))
            permanent = {
                "2": [[20, 40, 60], [80, 100, 120]],
                "3": [[20, 40, 60], [80, 100, 120], [140, 160, 180]],
            }
            engine.submit_artwork(42, "hero", ARTWORK_FRAME, .5, permanent, "hero.jpg", "hero")
            engine.submit_launch_artwork(42, "header", ARTWORK_FRAME, .5, PALETTES,
                                         "header.jpg", "header")
            self.assertEqual(engine.artwork.status(2)["dominant_colors"], permanent["2"])
            self.assertEqual(engine.launch_palette.status(2)["dominant_colors"], PALETTES["2"])
            self.assertNotEqual(engine.artwork.cache_path, engine.launch_palette.cache_path)

    def test_artwork_vibrance_recolours_detected_launch_palette_but_not_custom_palette(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            engine = Engine(store, str(Path(directory) / "artwork-cache.json"))
            muted = {
                "2": [[108, 92, 78], [70, 88, 110]],
                "3": [[108, 92, 78], [70, 88, 110], [92, 74, 104]],
            }
            custom = {
                "2": [[255, 0, 0], [0, 0, 255]],
                "3": [[255, 0, 0], [0, 255, 0], [0, 0, 255]],
            }
            engine.set_game(42, "Example Game")
            engine.submit_launch_artwork(
                42, "header", ARTWORK_FRAME, .5, muted, "header.jpg", "header",
            )
            self.assertEqual(engine.launch_artwork.status(42)["dominant_colors"], muted["2"])

            engine.update_artwork_settings(42, {"vibrance": 200})
            boosted = engine.launch_artwork.status(42)["dominant_colors"]
            self.assertNotEqual(boosted, muted["2"])

            engine.update_launch_artwork_settings(42, {
                "palette_mode": "custom", "custom_palettes": custom,
            })
            engine.update_artwork_settings(42, {"vibrance": 0})
            self.assertEqual(engine.launch_artwork.status(42)["dominant_colors"], custom["2"])

    def test_launch_settings_default_to_approved_configuration_and_clamp(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "config.json"))
            self.assertTrue(store.all()["launch_artwork_animation_enabled"])
            self.assertEqual(store.all()["launch_artwork_duration_seconds"], 5)
            store.update({
                "launch_artwork_animation_enabled": True,
                "launch_artwork_pattern": "not-a-pattern",
                "launch_artwork_colour_count": 7,
                "launch_artwork_duration_seconds": 99,
            })
            values = store.all()
            self.assertTrue(values["launch_artwork_animation_enabled"])
            self.assertEqual(values["launch_artwork_pattern"], "arpege-crossed")
            self.assertEqual(values["launch_artwork_colour_count"], 2)
            self.assertEqual(values["launch_artwork_duration_seconds"], 45)

    def test_custom_launch_palettes_are_saved_per_appid_and_keep_both_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "config.json"))
            custom = {
                "2": [[255, 0, 0], [0, 0, 255]],
                "3": [[255, 0, 0], [0, 255, 0], [0, 0, 255]],
            }
            store.update_launch_artwork(42, {
                "palette_mode": "custom", "custom_palettes": custom,
            })
            profile = SettingsStore(str(Path(directory) / "config.json")).launch_artwork_for(42)
            self.assertEqual(profile["palette_mode"], "custom")
            self.assertEqual(profile["custom_palettes"], custom)
            self.assertEqual(store.launch_artwork_for(99)["palette_mode"], "artwork")
