import hashlib
import unittest
from datetime import datetime, timezone

from signalbar.faceplate.scenes import (
    BLACK,
    HEIGHT,
    MAX_SCENE_GIF_BYTES,
    SCENE_REVISION,
    WEATHER_VARIANTS,
    WIDTH,
    build_dashboard_hour_pack,
    build_dashboard_snapshot,
    build_performance_snapshot,
    build_weather_scene,
    display_temperature,
    encode_rgb_gif,
    format_temperature,
    frame_colours,
    measure_text,
    render_dashboard_frame,
    render_performance_frame,
    render_weather_frame,
    select_dashboard_context,
    solar_phase,
    validate_variant,
    visual_signature,
)


class FaceplateSceneTests(unittest.TestCase):
    sunrise = datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc)
    sunset = datetime(2026, 10, 7, 19, 30, tzinfo=timezone.utc)

    def test_catalog_maps_all_nine_conditions_and_22_native_variants(self):
        self.assertEqual(len(WEATHER_VARIANTS), 9)
        self.assertEqual(sum(map(len, WEATHER_VARIANTS.values())), 22)
        self.assertEqual(len(WEATHER_VARIANTS["cloud"]), 4)
        self.assertEqual(len(WEATHER_VARIANTS["cloud_night"]), 4)

    def test_every_weather_variant_is_deterministic_bounded_and_visually_distinct(self):
        hashes = set()
        for condition, variants in WEATHER_VARIANTS.items():
            for variant in range(len(variants)):
                first = render_weather_frame(condition, variant, 1.37, 12.4, "celsius", "day")
                second = render_weather_frame(condition, variant, 1.37, 12.4, "celsius", "day")
                self.assertEqual(first, second)
                self.assertEqual(len(first), WIDTH * HEIGHT * 3)
                self.assertIn(BLACK, frame_colours(first))
                self.assertLessEqual(len(frame_colours(first)), 32)
                hashes.add(hashlib.sha256(first).hexdigest())
        self.assertEqual(len(hashes), 22)

    def test_weather_scene_gifs_are_native_and_under_the_software_limit(self):
        for condition, variants in WEATHER_VARIANTS.items():
            for variant in range(len(variants)):
                scene = build_weather_scene(
                    condition, variant, -3.5, "fahrenheit", "dusk", "Paris", frame_count=8,
                )
                payload = scene.gif()
                self.assertEqual(payload[:6], b"GIF89a")
                self.assertEqual(int.from_bytes(payload[6:8], "little"), 64)
                self.assertEqual(int.from_bytes(payload[8:10], "little"), 54)
                self.assertLess(len(payload), MAX_SCENE_GIF_BYTES)
                self.assertEqual(len(scene.frames), 8)

    def test_temperature_format_never_adds_a_plus_and_uses_degree_before_unit(self):
        self.assertEqual(format_temperature(12.4, "celsius"), "12°C")
        self.assertEqual(format_temperature(-3.5, "celsius"), "-4°C")
        self.assertEqual(format_temperature(0, "fahrenheit"), "32°F")
        self.assertEqual(display_temperature(12.6, "c"), (13, "C"))
        self.assertNotIn("+", format_temperature(18, "celsius"))

    def test_solar_phases_use_45_minutes_on_both_sides(self):
        cases = {
            datetime(2026, 10, 7, 6, 44, tzinfo=timezone.utc): "night",
            datetime(2026, 10, 7, 6, 45, tzinfo=timezone.utc): "dawn",
            datetime(2026, 10, 7, 8, 14, tzinfo=timezone.utc): "dawn",
            datetime(2026, 10, 7, 8, 15, tzinfo=timezone.utc): "day",
            datetime(2026, 10, 7, 18, 44, tzinfo=timezone.utc): "day",
            datetime(2026, 10, 7, 18, 45, tzinfo=timezone.utc): "dusk",
            datetime(2026, 10, 7, 20, 14, tzinfo=timezone.utc): "dusk",
            datetime(2026, 10, 7, 20, 15, tzinfo=timezone.utc): "night",
        }
        for instant, expected in cases.items():
            self.assertEqual(solar_phase(instant, self.sunrise, self.sunset), expected)

    def test_dashboard_keeps_clock_weather_temperature_and_context_in_fixed_regions(self):
        now = datetime(2026, 10, 7, 12, 34, tzinfo=timezone.utc)
        frame = render_dashboard_frame(
            now, "breaks", 1, 12, "celsius", self.sunrise, self.sunset,
            city="Paris", precipitation_probability=70,
        )
        self.assertEqual(len(frame), WIDTH * HEIGHT * 3)
        self.assertLessEqual(len(frame_colours(frame)), 32)
        # Each fixed content band contains signal and the blank separating rows
        # stay black, proving that text boxes do not overlap vertically.
        rows = [frame[y * WIDTH * 3:(y + 1) * WIDTH * 3] for y in range(HEIGHT)]
        self.assertTrue(any(rows[y] != bytes(WIDTH * 3) for y in range(1, 16)))
        self.assertEqual(rows[16], bytes(WIDTH * 3))
        self.assertEqual(rows[17], bytes(WIDTH * 3))
        self.assertTrue(any(rows[y] != bytes(WIDTH * 3) for y in range(18, 45)))
        self.assertEqual(rows[46], bytes(WIDTH * 3))
        self.assertEqual(rows[47], bytes(WIDTH * 3))
        self.assertTrue(any(rows[y] != bytes(WIDTH * 3) for y in range(48, 53)))

    def test_context_selects_one_bounded_datum(self):
        noon = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(select_dashboard_context(noon, "day", self.sunrise, self.sunset, 70), "RAIN 70%")
        self.assertEqual(select_dashboard_context(noon, "day", self.sunrise, self.sunset, 5), "SUNSET 19:30")
        late = datetime(2026, 10, 7, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(select_dashboard_context(late, "night", self.sunrise, self.sunset), "DAWN 07:30")
        self.assertLessEqual(measure_text("SUNSET 19:30"), 60)

    def test_visual_signature_covers_every_visual_identity_field(self):
        base = visual_signature("rain", 0, 12.4, "celsius", "day", "Paris")
        changes = (
            visual_signature("snow", 0, 12.4, "celsius", "day", "Paris"),
            visual_signature("rain", 1, 12.4, "celsius", "day", "Paris"),
            visual_signature("rain", 0, 13.0, "celsius", "day", "Paris"),
            visual_signature("rain", 0, 12.4, "fahrenheit", "day", "Paris"),
            visual_signature("rain", 0, 12.4, "celsius", "dusk", "Paris"),
            visual_signature("rain", 0, 12.4, "celsius", "day", "Lyon"),
            visual_signature("rain", 0, 12.4, "celsius", "day", "Paris", "revision-2"),
        )
        self.assertTrue(all(item != base for item in changes))
        self.assertEqual(base, visual_signature("rain", 0, 12.4, "celsius", "day", "Paris"))
        # Sub-degree changes that keep the displayed integer do not rewrite.
        self.assertEqual(base, visual_signature("rain", 0, 12.49, "celsius", "day", "Paris"))

    def test_hour_pack_has_60_minute_frames_long_delays_and_no_transport(self):
        hour = datetime(2026, 10, 7, 12, 27, tzinfo=timezone.utc)
        pack = build_dashboard_hour_pack(
            hour, "clear_day", 0, 18.2, "celsius", self.sunrise, self.sunset,
            city="Paris", precipitation_probability=10,
        )
        self.assertEqual(len(pack.frames), 60)
        self.assertEqual(pack.delay_cs, 6000)
        self.assertEqual(pack.delays_cs, (6000,) * 60)
        self.assertEqual(pack.revision, SCENE_REVISION)
        self.assertNotEqual(pack.frames[0], pack.frames[1])
        payload = pack.gif()
        self.assertEqual(payload[:6], b"GIF89a")
        self.assertLess(len(payload), MAX_SCENE_GIF_BYTES)

        offset = build_dashboard_hour_pack(
            hour.replace(minute=34, second=45), "clear_day", 0, 18.2,
            "celsius", self.sunrise, self.sunset, city="Paris",
        )
        self.assertEqual(offset.delays_cs[0], 1500)
        self.assertEqual(offset.delays_cs[1:], (6000,) * 59)

    def test_performance_matrix_builders_are_retired(self):
        for builder in (build_performance_snapshot, render_performance_frame):
            with self.assertRaisesRegex(ValueError, "removed"):
                builder(51, 73, 68, 78)

    def test_dashboard_snapshot_is_single_frame_and_cannot_loop_back(self):
        instant = datetime(2026, 10, 7, 12, 35, 42, tzinfo=timezone.utc)
        snapshot = build_dashboard_snapshot(
            instant, "clear_day", 0, 18.2, "celsius",
            self.sunrise, self.sunset, city="Paris",
        )
        payload = snapshot.gif()
        self.assertEqual(len(snapshot.frames), 1)
        self.assertNotIn(b"NETSCAPE2.0", payload)
        self.assertIn("12:35", instant.strftime("%H:%M"))

    def test_input_validation_rejects_unknown_or_oversized_scenes(self):
        with self.assertRaises(ValueError):
            validate_variant("hail", 0)
        with self.assertRaises(ValueError):
            validate_variant("rain", 2)
        with self.assertRaises(ValueError):
            build_weather_scene("rain", 0, 12, "celsius", "day", frame_count=33)
        with self.assertRaises(ValueError):
            encode_rgb_gif([bytes(WIDTH * HEIGHT * 3)] * 61, 10)


if __name__ == "__main__":
    unittest.main()
