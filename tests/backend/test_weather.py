"""Beta.10 weather loops, persistence, service and priority contracts."""

import io
import json
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, sentinel
from urllib.error import URLError

import signalbar.providers.weather as weather_module
from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.backend.engine import apply_rgb_brightness_fallback, resolve_light_bar_brightness
from signalbar.models import GameState, ProviderOutput, normalize_frame
from signalbar.providers.weather import (
    CONDITIONS, VARIANT_NAMES, WeatherProvider, condition_for_code,
    dim_weather_pixel, fetch_current, search_cities, weather_frame,
)
from signalbar.providers.weather_sequences import weather_loop_seconds, weather_sequence
from signalbar.settings import SettingsStore
from signalbar.settings.store import DEFAULTS, WEATHER_VARIANT_COUNTS

CITY = {"name": "Paris", "country": "France", "latitude": 48.85, "longitude": 2.35}
SAMPLE = {"weather_code": 2, "is_day": True, "condition": "breaks", "observed_at": "2026-09-23T10:00"}


class WeatherTests(unittest.TestCase):
    def test_global_brightness_resolves_day_night_alert_and_preview(self):
        values = dict(DEFAULTS, light_bar_day_brightness=9, night_mode_brightness=35)
        day = {"active": False}
        night = {"active": True}
        self.assertEqual(resolve_light_bar_brightness(values, "audio-sync", day), (9, "day"))
        self.assertEqual(resolve_light_bar_brightness(values, "audio-sync", night), (3, "night"))
        self.assertEqual(resolve_light_bar_brightness(values, "countdown", night), (9, "alert"))
        self.assertEqual(resolve_light_bar_brightness(values, "controller:low", night), (9, "alert"))
        self.assertEqual(resolve_light_bar_brightness(
            values, "customization:brightness-preview:day", night,
        ), (9, "day"))
        self.assertEqual(resolve_light_bar_brightness(
            values, "customization:brightness-preview:night", day,
        ), (3, "night"))

    def test_rgb_fallback_uses_nine_as_the_unchanged_reference(self):
        frame = [(90, 45, 9)] * 17
        self.assertEqual(apply_rgb_brightness_fallback(frame, 9), frame)
        self.assertEqual(apply_rgb_brightness_fallback(frame, 3)[0], (30, 15, 3))

    def test_variant_catalogue_and_frame_bounds(self):
        self.assertEqual({key: len(names) for key, names in VARIANT_NAMES.items()}, WEATHER_VARIANT_COUNTS)
        self.assertEqual(set(CONDITIONS), set(VARIANT_NAMES))
        raw = dict(DEFAULTS, weather_brightness=100, weather_shadow_cutoff=0)
        for condition in CONDITIONS:
            for variant in range(len(VARIANT_NAMES[condition])):
                unique = set()
                loop_seconds = weather_loop_seconds(condition, variant)
                for tick in range(round(loop_seconds * 10)):
                    elapsed = tick / 10
                    frame = weather_frame(condition, variant, elapsed, raw)
                    self.assertEqual(len(frame), 17)
                    self.assertTrue(all(0 <= channel <= 255 for pixel in frame for channel in pixel))
                    self.assertEqual(frame, normalize_frame(weather_sequence(condition, variant, elapsed)))
                    unique.add(frame)
                self.assertGreater(len(unique), 4, (condition, variant))
                self.assertEqual(weather_frame(condition, variant, 0, raw),
                                 weather_frame(condition, variant, loop_seconds, raw))
        with self.assertRaises(ValueError):
            weather_frame("rain", 2, 0, raw)

    def test_new_cloud_patterns_and_existing_selections(self):
        self.assertEqual(VARIANT_NAMES["cloud"], (
            "Passing shadow", "Passing shadows", "Cross & gather", "Slow convergence"))
        self.assertEqual(DEFAULTS["weather_cloud_variant"], 3)
        self.assertEqual(weather_loop_seconds("cloud", 0), 8)
        self.assertEqual(weather_loop_seconds("cloud", 1), 8)
        self.assertEqual(weather_loop_seconds("cloud", 2), 20)
        self.assertEqual(weather_loop_seconds("cloud", 3), 48)
        self.assertNotEqual(weather_sequence("cloud", 2, 1.2), weather_sequence("cloud", 2, 5))
        self.assertNotEqual(weather_sequence("cloud", 3, 2), weather_sequence("cloud", 3, 20))
        lit = lambda elapsed: [index for index, pixel in enumerate(
            weather_sequence("cloud", 3, elapsed)) if pixel[0] > 0]
        self.assertEqual(lit(0), [2, 14])
        self.assertEqual(lit(15), list(range(5, 13)))
        self.assertEqual(lit(25), list(range(8)))
        self.assertEqual(lit(39), list(range(9, 17)))
        self.assertEqual(lit(47), [])
        for variant in (2, 3):
            for tick in range(round(weather_loop_seconds("cloud", variant) * 10)):
                frame = weather_sequence("cloud", variant, tick / 10)
                self.assertTrue(all(red == green == blue for red, green, blue in frame))
                self.assertTrue(all(0 <= pixel[0] <= 242 for pixel in frame))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertEqual(SettingsStore(str(path)).all()["weather_cloud_variant"], 3)
            for existing in (0, 1):
                path.write_text(json.dumps({"weather_sequence_revision": 10,
                                            "weather_cloud_variant": existing}), encoding="utf-8")
                store = SettingsStore(str(path))
                self.assertEqual(store.all()["weather_cloud_variant"], existing)
                store.update({"weather_brightness": 70})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["weather_sequence_revision"], 12)
            path.write_text(json.dumps({"weather_sequence_revision": 11,
                                        "weather_cloud_variant": 3}), encoding="utf-8")
            self.assertEqual(SettingsStore(str(path)).all()["weather_cloud_variant"], 3)

    def test_long_cloud_preview_plays_one_complete_cycle(self):
        now = [100.0]
        provider = WeatherProvider(clock=lambda: now[0])
        values = dict(DEFAULTS, weather_display="off")
        for variant, duration in ((2, 20), (3, 48)):
            self.assertTrue(provider.preview("cloud", variant))
            now[0] += duration - .1
            self.assertTrue(provider.status(values)["preview_active"])
            self.assertAlmostEqual(provider.status(values)["preview_remaining_s"], .1)
            now[0] += .1
            self.assertFalse(provider.status(values)["preview_active"])

    def test_partly_cloudy_originals_remain_and_new_clouds_fade_to_black(self):
        self.assertEqual(len(VARIANT_NAMES["breaks"]), 2)
        self.assertEqual(len(VARIANT_NAMES["breaks_night"]), 2)
        for condition in ("breaks", "breaks_night"):
            self.assertEqual(weather_sequence(condition, 0, 0),
                             weather_sequence(condition, 1, 0))
            original = weather_sequence(condition, 0, 3)
            fading = weather_sequence(condition, 1, 3)
            for edge in (0, 1, 2, 14, 15, 16):
                if condition == "breaks_night":
                    self.assertEqual(original[edge], [35, 35, 35])
                    self.assertEqual(fading[edge], [0, 8, 38])
                else:
                    self.assertGreater(original[edge][0], 50)
                    self.assertEqual(fading[edge], [0, 0, 0])
            self.assertGreater(fading[8][0], 200)
            for variant in (0, 1):
                for tick in range(80):
                    for red, green, blue in weather_sequence(condition, variant, tick / 10):
                        if red == green == blue:
                            continue  # Clouds have only neutral-white or black pixels.
                        if condition == "breaks_night":
                            self.assertIn([red, green, blue], ([0, 8, 38], [128, 128, 128],
                                                             [192, 192, 192], [255, 255, 255]))
                        else:
                            self.assertGreaterEqual(red, 165)  # No dim warm/brown fringe.
                            self.assertGreaterEqual(green / red, .95)
                            self.assertGreaterEqual(blue, 30)
            for variant in (0, 1):
                for tick in range(80):
                    for red, green, blue in weather_frame(condition, variant, tick / 10, DEFAULTS):
                        if condition == "breaks_night":
                            self.assertIn((red, green, blue), (
                                (0, 8, 38), (35, 35, 35), (128, 128, 128),
                                (192, 192, 192), (255, 255, 255),
                            ))
                        elif red != green or green != blue:
                            self.assertGreaterEqual(green / red, .95)
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder) / "settings.json"))
            store.update({"weather_breaks_variant": 1, "weather_breaks_night_variant": 1})
            reloaded = SettingsStore(str(Path(folder) / "settings.json")).all()
            self.assertEqual(reloaded["weather_breaks_variant"], 1)
            self.assertEqual(reloaded["weather_breaks_night_variant"], 1)

    def test_snow_takes_hold_is_available_and_default(self):
        self.assertEqual(VARIANT_NAMES["snow"], ("Melting snowfall", "Snow takes hold"))
        self.assertEqual(DEFAULTS["weather_snow_variant"], 1)
        self.assertTrue(all(pixel == [0, 0, 0] for pixel in weather_sequence("snow", 1, 0)))
        self.assertTrue(all(pixel[0] > 150 for pixel in weather_sequence("snow", 1, 7.1)))
        self.assertNotEqual(weather_sequence("snow", 0, 3), weather_sequence("snow", 1, 3))

    def test_topbar_temperature_unit_retained_but_led_temperature_fields_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            old = {"weather_temperature_unit": "fahrenheit", "weather_soft_halos": True,
                   "weather_tip_width": 2, "weather_colour_hot": [255, 0, 0],
                   "weather_temperature_display": "thermometer", "weather_location": CITY,
                   "weather_display": "home", "weather_rain_variant": 3,
                   "weather_clear_night_variant": 3, "weather_storm_variant": 4}
            path.write_text(json.dumps(old), encoding="utf-8")
            store = SettingsStore(str(path))
            values = store.all()
            for field in ("weather_soft_halos", "weather_tip_width",
                          "weather_colour_hot", "weather_temperature_display"):
                self.assertNotIn(field, values)
            self.assertEqual(values["weather_temperature_unit"], "fahrenheit")
            self.assertEqual(values["weather_rain_variant"], 1)
            self.assertEqual(values["weather_clear_night_variant"], 1)
            self.assertEqual(values["weather_storm_variant"], 1)
            store.update({"weather_brightness": 60})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["weather_sequence_revision"], 12)
            self.assertEqual(saved["weather_temperature_unit"], "fahrenheit")
            self.assertEqual(SettingsStore(str(path)).all()["weather_rain_variant"], 1)

    def test_topbar_icon_family_persists_and_invalid_values_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            store = SettingsStore(str(path))
            self.assertEqual(store.all()["weather_icon_style"], "phosphor-duotone")
            for style in ("material-rounded", "phosphor-duotone", "current"):
                self.assertEqual(
                    store.update({"weather_icon_style": style})["weather_icon_style"], style,
                )
            self.assertEqual(
                store.update({"weather_icon_style": "remote-font"})["weather_icon_style"],
                "phosphor-duotone",
            )
            self.assertEqual(SettingsStore(str(path)).all()["weather_icon_style"], "phosphor-duotone")

    def test_service_parses_temperature_for_optional_top_bar_only(self):
        requested = []
        sample = fetch_current(CITY, lambda url: (
            requested.append(url), {"current": {"weather_code": 95, "is_day": 0,
                                                  "temperature_2m": 12.4,
                                                  "time": "2026-09-23T10:00"}})[1])
        self.assertEqual(sample["condition"], "storm")
        self.assertIn("temperature_2m", requested[0])
        self.assertIn("daily=sunrise%2Csunset", requested[0])
        self.assertEqual(sample["temperature_c"], 12.4)
        no_temp = fetch_current(CITY, lambda url: {"current": {"weather_code": 0, "is_day": 1}})
        self.assertIsNone(no_temp["temperature_c"])
        self.assertEqual(condition_for_code(2, 0), "breaks_night")
        self.assertEqual(condition_for_code(2, 1), "breaks")
        self.assertEqual(condition_for_code(3, 0), "cloud_night")
        self.assertEqual(condition_for_code(3, 1), "cloud")
        self.assertEqual(condition_for_code(75, 1), "snow")
        self.assertEqual(search_cities("Paris", lambda url: {"results": [CITY]}), [CITY])

    def test_service_exposes_local_solar_transition_and_night_mode_dims_safely(self):
        payload = {
            "current": {"weather_code": 0, "is_day": 0, "temperature_2m": 9,
                        "time": "2026-10-05T20:15"},
            "daily": {
                "sunrise": ["2026-10-05T07:58", "2026-10-06T07:59"],
                "sunset": ["2026-10-05T19:24", "2026-10-06T19:22"],
            },
        }
        sample = fetch_current(CITY, lambda url: payload)
        self.assertFalse(sample["is_day"])
        self.assertEqual(sample["sunset_at"], "2026-10-05T19:24")
        self.assertEqual(sample["next_solar_transition_at"], "2026-10-06T07:59")
        self.assertGreater(sample["seconds_until_solar_transition"], 0)

        now = [100.0]
        provider = WeatherProvider(clock=lambda: now[0])
        provider._location = dict(CITY)
        provider._sample = sample
        provider._fetched_at = now[0]
        values = dict(DEFAULTS, weather_location=CITY, night_mode_enabled=True,
                      night_mode_brightness=35)
        solar = provider.solar_status(values)
        self.assertTrue(solar["active"])
        self.assertEqual(resolve_light_bar_brightness(values, "audio-sync", solar), (3, "night"))
        self.assertEqual(resolve_light_bar_brightness(values, "countdown", solar), (9, "alert"))
        self.assertEqual(resolve_light_bar_brightness(values, "controller:low", solar), (9, "alert"))

    def test_night_mode_requires_a_city_and_legacy_users_skip_onboarding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            fresh = SettingsStore(str(path))
            self.assertFalse(fresh.all()["onboarding_completed"])
            self.assertEqual(fresh.all()["display_preset"], "immersive-plus")
            with self.assertRaisesRegex(ValueError, "city"):
                fresh.update({"night_mode_enabled": True})
            enabled = fresh.update({"weather_location": CITY, "night_mode_enabled": True,
                                    "night_mode_brightness": 42})
            self.assertTrue(enabled["night_mode_enabled"])
            self.assertEqual(enabled["night_mode_brightness"], 42)
            enabled = fresh.update({"weather_location": None})
            self.assertFalse(enabled["night_mode_enabled"])

            legacy_path = Path(folder) / "legacy.json"
            legacy_path.write_text(json.dumps({"signalbar_enabled": True}), encoding="utf-8")
            legacy = SettingsStore(str(legacy_path)).all()
            self.assertTrue(legacy["onboarding_completed"])
            self.assertEqual(legacy["display_preset"], "custom")

    def test_tls_failure_retries_with_verified_system_ca_bundle(self):
        missing_issuer = URLError(ssl.SSLCertVerificationError("missing issuer"))
        with patch.object(weather_module, "SYSTEM_CA_BUNDLES", ("/etc/ssl/cert.pem",)), \
                patch.object(weather_module.os.path, "isfile", return_value=True), \
                patch.object(weather_module.ssl, "create_default_context", return_value=sentinel.verified) as context, \
                patch.object(weather_module, "urlopen", side_effect=[missing_issuer, io.BytesIO(b'{"results": []}')]) as opener:
            self.assertEqual(weather_module._read_json("https://example.org"), {"results": []})
            context.assert_called_once_with(cafile="/etc/ssl/cert.pem")
            self.assertEqual(opener.call_args.kwargs["context"], sentinel.verified)

    def test_brightness_cutoff_and_neutral_palettes(self):
        self.assertEqual(dim_weather_pixel((200, 100, 40), 65, 25), (130, 65, 26))
        self.assertEqual(dim_weather_pixel((25, 12, 3), 100, 25), (0, 0, 0))
        values = dict(DEFAULTS, weather_brightness=100, weather_shadow_cutoff=0)
        for tick in range(80):
            t = tick / 10
            for variant in (0, 1):
                for red, green, blue in weather_frame("clear_day", variant, t, values):
                    self.assertGreaterEqual(red, green)
                    self.assertGreaterEqual(green, blue)
            for condition in ("cloud", "snow", "storm"):
                for variant in range(len(VARIANT_NAMES[condition])):
                    for pixel in weather_frame(condition, variant, t, values):
                        self.assertLessEqual(max(pixel) - min(pixel), 1)
        self.assertLess(max(weather_frame("rain", 1, 0, values)[0]),
                        max(weather_frame("cloud", 0, 0, values)[0]))

    def test_night_transpositions_match_mockup_palette_and_timing(self):
        night = [0, 8, 38]
        cloud = [35, 35, 35]
        clear_night_allowed = {tuple(night), (112, 112, 112),
                               (168, 168, 168), (224, 224, 224)}
        other_night_allowed = {tuple(night), tuple(cloud), (128, 128, 128),
                               (192, 192, 192), (255, 255, 255)}
        self.assertEqual(VARIANT_NAMES["clear_night"], ("Breathing moon", "Lunar bloom"))
        self.assertEqual(VARIANT_NAMES["cloud_night"], (
            "Night passing shadow", "Night passing shadows",
            "Night cross & gather", "Night slow convergence",
        ))
        self.assertEqual(DEFAULTS["weather_cloud_night_variant"], 2)
        self.assertEqual(weather_loop_seconds("clear_night", 0), 6)
        self.assertEqual(weather_loop_seconds("clear_night", 1), 8)
        self.assertEqual(weather_loop_seconds("cloud_night", 2), 20)
        self.assertEqual(weather_loop_seconds("cloud_night", 3), 48)

        start = weather_sequence("clear_night", 0, 0)
        self.assertEqual(start[8:10], [[168, 168, 168], [168, 168, 168]])
        self.assertTrue(all(pixel == night for pixel in start[:8] + start[10:]))
        full = weather_sequence("clear_night", 0, 3)
        self.assertEqual(full[7:11], [[224, 224, 224]] * 4)
        self.assertTrue(all(pixel == night for pixel in weather_sequence("cloud_night", 0, 0)))
        one_cloud = weather_sequence("cloud_night", 0, 4)
        self.assertIn(cloud, one_cloud)
        self.assertIn(night, one_cloud)
        self.assertEqual(one_cloud[8], cloud)
        first_pass = weather_sequence("cloud_night", 1, 2)
        second_pass = weather_sequence("cloud_night", 1, 6)
        self.assertIn(cloud, first_pass)
        self.assertIn(cloud, second_pass)
        self.assertGreater(first_pass[:9].count(cloud), first_pass[9:].count(cloud))
        self.assertGreater(second_pass[9:].count(cloud), second_pass[:9].count(cloud))
        fading = weather_sequence("breaks_night", 1, 3)
        self.assertEqual(fading[0], night)
        self.assertIn(tuple(fading[8]), other_night_allowed)

        for condition in ("clear_night", "cloud_night", "breaks_night"):
            allowed = clear_night_allowed if condition == "clear_night" else other_night_allowed
            for variant in range(len(VARIANT_NAMES[condition])):
                duration = weather_loop_seconds(condition, variant)
                for tick in range(round(duration * 5)):
                    frame = weather_sequence(condition, variant, tick / 5)
                    self.assertTrue(all(tuple(pixel) in allowed for pixel in frame),
                                    (condition, variant, tick, frame))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            store = SettingsStore(str(path))
            store.update({"weather_cloud_night_variant": 3})
            self.assertEqual(SettingsStore(str(path)).all()["weather_cloud_night_variant"], 3)

    def test_settings_contexts_and_preview_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder) / "settings.json"))
            with self.assertRaisesRegex(ValueError, "city"):
                store.update({"weather_display": "home"})
            store.update({"weather_location": CITY, "weather_display": "home"})
            values = store.all()
            self.assertEqual(values["controller_battery_display"], "off")
            provider = WeatherProvider()
            provider._sample, provider._fetched_at = dict(SAMPLE), time.monotonic()
            self.assertIsNotNone(provider.output(values, game_running=False).frame)
            self.assertIsNone(provider.output(values, game_running=True).frame)
            self.assertTrue(provider.preview("snow", 0))
            weather = provider.output(values)
            frame = normalize_frame([(10, 10, 10)] * 17)
            empty = ProviderOutput("none", None, "")
            args = dict(mode="performance", guard_allows=True, game=GameState(), performance=empty,
                        artwork=empty, idle=empty, signal=ProviderOutput("countdown", frame, "timer"),
                        weather_base=weather)
            self.assertEqual(Arbiter().choose(**args).provider, "countdown")
            self.assertEqual(Arbiter().choose(**{**args, "signal": empty}).provider, "weather:preview")
            self.assertEqual(Arbiter().choose(**{**args, "guard_allows": False}).provider, "valve")
            provider.stop_preview()
            self.assertFalse(provider.status(values)["preview_active"])
            self.assertIsNone(provider.status(values)["temperature_c"])
            self.assertTrue(values["weather_topbar_enabled"])
            store.update({"controller_battery_display": "game"})
            self.assertEqual(store.all()["weather_display"], "home")
            store.update({"weather_topbar_enabled": True})
            self.assertEqual(store.all()["controller_battery_display"], "game")
            self.assertEqual(store.all()["weather_display"], "home")
            self.assertTrue(Engine(store, str(Path(folder) / "cache")).status()["weather_topbar_enabled"])
            store.update({"weather_location": None})
            self.assertTrue(store.all()["weather_topbar_enabled"])

    def test_topbar_fetches_when_led_weather_is_off_and_expires(self):
        now = [100.0]
        provider = WeatherProvider(clock=lambda: now[0], fetch=lambda location: dict(SAMPLE, temperature_c=8.6))
        values = dict(DEFAULTS, weather_location=CITY, weather_topbar_enabled=True)
        provider.configure(CITY, "off", True)
        provider.start()
        try:
            deadline = time.monotonic() + 1
            while provider.status(values)["phase"] != "ready" and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(provider.status(values)["temperature_c"], 8.6)
            self.assertIsNone(provider.output(values).frame)
            now[0] += 3600
            self.assertIsNone(provider.status(values)["temperature_c"])
        finally:
            provider.stop()

    def test_topbar_can_wait_for_city_and_starts_without_opening_decky_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"weather_topbar_enabled": True})
            self.assertTrue(settings.all()["weather_topbar_enabled"])
            self.assertIsNone(settings.all()["weather_location"])
            settings.update({"weather_location": CITY, "weather_topbar_enabled": True})
            self.assertEqual(settings.all()["weather_display"], "off")
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            engine.weather = WeatherProvider(fetch=lambda location: dict(SAMPLE, temperature_c=11.2))
            engine.weather.configure(CITY, "off", True)
            engine.start()
            try:
                deadline = time.monotonic() + 2
                while engine.status()["weather"]["phase"] != "ready" and time.monotonic() < deadline:
                    time.sleep(.01)
                status = engine.status()
                self.assertEqual(status["weather"]["temperature_c"], 11.2)
                self.assertTrue(status["weather_topbar_enabled"])
                self.assertNotEqual(status["provider"], "weather")
            finally:
                engine.stop()


if __name__ == "__main__":
    unittest.main()
