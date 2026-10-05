"""Regression coverage for the two-controller and stale-Performance reports."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from signalbar.backend import Engine
from signalbar.arbiter.guard import ManualClock
from signalbar.models import PerformanceSample, normalize_frame
from signalbar.providers.performance import PerformanceProvider
from signalbar.providers.controller import ControllerProvider, VARIANTS, controller_frame
from signalbar.settings import SettingsStore


class Metrics:
    def __init__(self, clock):
        self.calls = 0
        self.clock = clock
        self.fail = False

    def sample(self):
        self.calls += 1
        if self.fail:
            raise OSError("sensor temporarily missing")
        return PerformanceSample(gpu_load=self.calls * 10, cpu_load=self.calls * 5,
                                 gpu_temp_c=50 + self.calls, cpu_temp_c=40 + self.calls,
                                 sampled_at=self.clock())


class FeedbackTests(unittest.TestCase):
    def test_home_and_game_displays_route_independently_with_game_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder) / "settings.json"))
            store.update({
                "weather_location": {
                    "name": "Paris", "country": "France",
                    "latitude": 48.8566, "longitude": 2.3522,
                },
                "home_display": "weather",
                "game_display": "performance",
            })
            self.assertEqual(store.display_for(0)["selected"], "weather")
            self.assertEqual(store.display_for(0)["mode"], "events")
            self.assertEqual(store.display_for(42)["selected"], "performance")
            self.assertEqual(store.display_for(42)["mode"], "performance")
            engine = Engine(store, str(Path(folder) / "artwork-cache.json"))
            self.assertEqual(engine.status()["current_display"], "weather")
            engine.set_game(42, "Test")
            self.assertEqual(engine.status()["current_display"], "performance")
            store.update_display(42, "artwork")
            self.assertEqual(store.display_for(42)["selected"], "artwork")
            self.assertEqual(store.display_for(99)["selected"], "performance")
            store.update({"signalbar_enabled": False})
            self.assertEqual(store.display_for(0)["mode"], "disabled")
            self.assertEqual(store.display_for(42)["mode"], "disabled")

    def test_game_weather_override_keeps_weather_service_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(store, str(Path(folder) / "artwork-cache.json"))
            store.update({
                "weather_location": {
                    "name": "Paris", "country": "France",
                    "latitude": 48.8566, "longitude": 2.3522,
                },
            })
            configure_calls = []
            engine.weather.configure = lambda *args: configure_calls.append(args)
            engine.update_display(42, "weather")
            self.assertEqual(store.all()["weather_display"], "game")
            self.assertEqual(configure_calls[-1][1], "game")
            engine.update_display(42, "inherit")
            self.assertEqual(store.all()["weather_display"], "off")
            self.assertEqual(configure_calls[-1][1], "off")

    def test_sampling_starts_without_performance_and_continues_after_switching_back(self):
        clock = ManualClock(100)
        metrics = Metrics(clock)
        provider = PerformanceProvider(metrics=metrics, clock=clock)
        self.assertIsNone(provider.output(enabled=False).frame)
        self.assertEqual(provider.sample.gpu_load, 10)
        for _ in range(20):
            provider.output(enabled=False)
        self.assertEqual(metrics.calls, 1)
        clock.advance(.5)
        self.assertIsNotNone(provider.output(enabled=True).frame)
        clock.advance(.5)
        self.assertIsNone(provider.output(enabled=False).frame)
        self.assertEqual(metrics.calls, 3)
        self.assertEqual(provider.sample.gpu_temp_c, 53)
        metrics.fail = True
        clock.advance(.5)
        provider.refresh()
        self.assertIsNone(provider.sample.gpu_load)
        self.assertIn("missing", provider.error)
        metrics.fail = False
        clock.advance(.5)
        provider.refresh()
        self.assertEqual(provider.error, "")
        clock.advance(3)
        self.assertIsNone(provider.sample.cpu_load)
        self.assertEqual(sum(pixel != (0, 0, 0) for pixel in provider.frame()), 0)

    def test_engine_collects_in_artwork_and_disabled_even_without_led_hardware(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"home_display": "controller", "game_display": "performance"})
            attempts = []

            def unavailable():
                attempts.append(1)
                raise OSError("no LEDs")

            engine = Engine(settings, str(Path(folder) / "cache"), hardware_factory=unavailable)
            engine.update_settings({"mode": "artwork"})
            metrics = Metrics(time.monotonic)
            engine.performance = PerformanceProvider(metrics=metrics)
            engine.start()
            try:
                deadline = time.monotonic() + 2
                while metrics.calls < 2 and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertGreaterEqual(metrics.calls, 2)
                state = engine.status()
                self.assertEqual(state["mode"], "events")
                self.assertEqual(state["current_display"], "controller")
                self.assertEqual(state["game_display"], "artwork")
                self.assertIsNotNone(state["performance"]["cpu_load"])
                self.assertEqual(len(attempts), 1)
                before = metrics.calls
                engine.update_settings({"mode": "disabled"})
                deadline = time.monotonic() + 2
                while metrics.calls <= before and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertGreater(metrics.calls, before)
                self.assertEqual(engine.status()["mode"], "disabled")
            finally:
                engine.stop()

    def test_per_game_modes_persist_fallback_and_never_override_global_off_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "settings.json")
            settings = SettingsStore(path)
            settings.update({"game_display": "performance"})
            engine = Engine(settings, str(Path(folder) / "cache"))
            settings.update_display(42, "performance")
            settings.update_display(99, "artwork")
            settings.update_artwork(42, {"mode": "manual", "manual_y": .83})
            engine.set_game(42, "Heavy")
            self.assertEqual(engine.status()["mode"], "performance")
            self.assertEqual(engine.status()["default_mode"], "performance")
            self.assertEqual(engine.status()["artwork_manual_y"], .83)
            self.assertEqual(engine.status()["artwork_default_mode"], settings.all()["artwork_mode"])
            self.assertEqual(engine.status()["artwork_default_manual_y"], settings.all()["artwork_manual_y"])
            self.assertEqual(engine.status()["artwork_default_source"], settings.all()["artwork_source"])
            self.assertNotEqual(engine.status()["artwork_manual_y"], engine.status()["artwork_default_manual_y"])
            engine.set_game(99, "Indie")
            self.assertEqual(engine.status()["mode"], "artwork")
            engine.set_game(0)
            self.assertEqual(engine.status()["display_override"], "inherit")
            engine.set_game(43, "New")
            self.assertEqual(engine.status()["mode"], "performance")
            restored = SettingsStore(path)
            self.assertEqual(restored.display_for(42)["mode"], "performance")
            restored.update({"mode": "disabled"})
            self.assertEqual(restored.display_for(42)["mode"], "disabled")
            restored.update({"mode": "events"})
            self.assertEqual(restored.display_for(42)["mode"], "performance")
            restored.update({"mode": "performance"})
            self.assertEqual(restored.display_for(99)["mode"], "artwork")
            restored.update_display(99, "inherit")
            self.assertEqual(restored.display_for(99)["mode"], "performance")
            self.assertNotIn("99", restored.all()["display_profiles"])
            with self.assertRaises(ValueError):
                restored.update_display(0, "artwork")
            with self.assertRaises(ValueError):
                restored.update_display(42, "disabled")

    def test_invalid_display_profiles_and_colours_are_sanitized(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"mode": "performance", "display_profiles": {
                "42": "artwork", "bad": "performance", "43": [], "0": "performance", "44": "disabled"},
                "controller_colour_normal": [999, -4, 80], "controller_gauge_brightness": 999}))
            store = SettingsStore(str(path))
            self.assertEqual(store.all()["display_profiles"], {"42": "artwork"})
            self.assertEqual(store.all()["controller_colour_normal"], [255, 0, 80])
            self.assertEqual(store.all()["controller_gauge_brightness"], 100)
            store.update({"controller_colour_low": [float("inf"), 0, 0], "controller_gauge_brightness": None})
            self.assertEqual(store.all()["controller_colour_low"], [220, 12, 24])
            self.assertEqual(store.all()["controller_gauge_brightness"], 65)
            values = store.update({
                "controller_colour_mode": "players",
                "controller_player_colour_3": [300, 119, -1],
            })
            self.assertEqual(values["controller_colour_mode"], "players")
            self.assertEqual(values["controller_player_colour_3"], [255, 119, 0])
            values = store.update({"controller_colour_mode": "mirrored"})
            self.assertEqual(values["controller_colour_mode"], "battery")
            values = store.update({"controller_colour_preset": "fixed"})
            self.assertEqual(values["controller_colour_preset"], "automatic")

    def test_legacy_signals_only_does_not_reactivate_dormant_game_displays(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({
                "mode": "events",
                "display_profiles": {"42": "artwork", "99": "performance"},
                "artwork_profiles": {"42": {"mode": "manual", "manual_y": .72}},
                "controller_battery_display": "off",
                "weather_display": "off",
            }), encoding="utf-8")

            store = SettingsStore(str(path))
            values = store.all()
            self.assertEqual(values["game_display"], "steam")
            self.assertEqual(values["display_profiles"], {})
            self.assertEqual(store.display_for(42)["selected"], "steam")
            self.assertEqual(store.artwork_for(42)["mode"], "manual")
            self.assertEqual(store.artwork_for(42)["manual_y"], .72)

    def test_current_routing_keeps_explicit_game_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({
                "mode": "events",
                "signalbar_enabled": True,
                "home_display": "steam",
                "game_display": "steam",
                "display_profiles": {"42": "artwork"},
            }), encoding="utf-8")

            store = SettingsStore(str(path))
            self.assertEqual(store.display_for(42)["selected"], "artwork")

    def test_custom_gauge_colours_and_brightness_apply_to_both_players_and_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder) / "settings.json"))
            values = store.update({"controller_battery_display": "everywhere", "controller_gauge_brightness": 50,
                "controller_colour_preset": "manual", "controller_colour_mode": "battery",
                "controller_colour_normal": [0, 100, 200], "controller_colour_medium": [200, 100, 0],
                "controller_colour_low": [120, 0, 80], "controller_colour_charging": [0, 80, 160]})
            self.assertEqual(SettingsStore(store.path).all()["controller_colour_normal"], [0, 100, 200])
            frame = controller_frame("duo", "twin", 2, 96, 41, values=values)
            self.assertEqual(frame[0], (0, 50, 100))
            self.assertEqual(frame[-1], (0, 50, 100))
            self.assertEqual(frame[8], (0, 0, 0))
            self.assertEqual(sum(x != (0, 0, 0) for x in frame[:8]), 8)
            self.assertEqual(sum(x != (0, 0, 0) for x in frame[9:]), 3)
            for percent, expected in ((30, (100, 50, 0)), (10, (60, 0, 40))):
                self.assertEqual(controller_frame("persistent", "clean", 2, percent, values=values)[0], expected)
            for kind, variants in VARIANTS.items():
                for variant in variants:
                    result = controller_frame(kind, variant, .8, values=values)
                    self.assertEqual(len(result), 17)
                    self.assertTrue(all(0 <= channel <= 128 for pixel in result for channel in pixel))
            provider = ControllerProvider()
            provider.preview("persistent", values, "clean")
            self.assertEqual(provider.event_output().frame[0], (0, 50, 100))
            values["controller_colour_normal"] = [200, 0, 0]
            provider.cancel_for_settings(values)
            self.assertEqual(provider.event_output().frame[0], (100, 0, 0))

    def test_resolved_game_mode_is_used_by_real_engine_arbitration(self):
        class Hardware:
            device_path = "/fake/valve-leds"
            reverse = False
            frame = normalize_frame([(0, 0, 0)] * 17)
            def set_reverse(self, value): self.reverse = value
            def read_frame(self): return self.frame
            def read_signature(self): return self.frame
            def write_frame(self, value): self.frame = value
            def try_restore(self, value): self.frame = value

        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"mode": "performance", "home_display": "steam",
                             "game_display": "performance"})
            settings.update_display(42, "performance")
            engine = Engine(settings, str(Path(folder) / "cache"), hardware_factory=Hardware)
            seen = []
            choose = engine.arbiter.choose
            def record(**kwargs):
                seen.append((kwargs["game"].appid, kwargs["mode"]))
                return choose(**kwargs)
            engine.arbiter.choose = record
            engine.start()
            try:
                for appid, mode in ((42, "performance"), (99, "performance"), (0, "events")):
                    engine.set_game(appid)
                    deadline = time.monotonic() + 2
                    while (appid, mode) not in seen and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertIn((appid, mode), seen)
            finally:
                engine.stop()

    def test_atmosphere_uses_audio_sync_until_home_weather_is_available(self):
        class Hardware:
            device_path = "/fake/valve-leds"
            reverse = False
            frame = normalize_frame([(0, 0, 0)] * 17)
            def set_reverse(self, value): self.reverse = value
            def read_frame(self): return self.frame
            def read_signature(self): return self.frame
            def write_frame(self, value): self.frame = value
            def try_restore(self, value): self.frame = value

        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"display_preset": "atmosphere"})
            engine = Engine(settings, str(Path(folder) / "cache"), hardware_factory=Hardware)
            modes = []
            choose = engine.arbiter.choose
            def record(**kwargs):
                modes.append(kwargs["mode"])
                return choose(**kwargs)
            engine.arbiter.choose = record
            engine.start()
            try:
                deadline = time.monotonic() + 2
                while "audio_sync" not in modes and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertIn("audio_sync", modes)
                self.assertEqual(engine.status()["current_display"], "weather")
            finally:
                engine.stop()
