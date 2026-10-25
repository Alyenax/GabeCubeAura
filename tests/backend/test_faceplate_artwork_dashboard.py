"""Artwork Dashboard preparation, composition and timing contracts."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.faceplate.artwork_dashboard import (
    COMPRESSION_LEVELS, PALETTE_332, build_artwork_dashboard, quantize_battery,
    stabilize_dashboard_loop,
)
from signalbar.faceplate.coordinator import validate_gif
from signalbar.faceplate.steamgriddb import (
    DASHBOARD_PACK_REVISION, SteamGridDBFaceplate,
)
from signalbar.settings import SettingsStore


FRAME_BYTES = 64 * 54 * 3


def colour_positions(frame, colour, *, top=0, bottom=54):
    marker = bytes(colour)
    return {
        (x, y)
        for y in range(top, bottom)
        for x in range(64)
        if frame[(y * 64 + x) * 3:(y * 64 + x + 1) * 3] == marker
    }


class ArtworkDashboardTests(unittest.TestCase):
    def test_hidden_clock_has_no_upper_readability_fade_in_any_treatment(self):
        background = bytes((140, 180, 210)) * (64 * 54)
        for treatment in ("none", "cinema", "hero-cut", "palette-echo"):
            for game_running in (False, True):
                with self.subTest(treatment=treatment, game_running=game_running):
                    frame = build_artwork_dashboard(
                        (background,), "2026-10-21T13:00:00+02:00", 0,
                        treatment=treatment, show_clock=game_running,
                        game_running=game_running, show_weather_notch=False,
                        show_status_rail=False,
                    ).frames[0]
                    centre = frame[20 * 64 * 3:20 * 64 * 3 + 3]
                    self.assertEqual(centre * (64 * 16), frame[:64 * 16 * 3])
                    if treatment == "none":
                        self.assertEqual(background, frame)

    def test_clock_readability_and_weather_notch_remain_independent(self):
        background = bytes((140, 180, 210)) * (64 * 54)
        arguments = dict(treatment="cinema", show_status_rail=False,
                         show_weather_notch=True,
                         weather={"condition": "rain", "temperature_c": 12})
        off = build_artwork_dashboard((background,), "2026-10-21T13:00:00+02:00", 0,
                                      show_clock=False, **arguments).frames[0]
        on = build_artwork_dashboard((background,), "2026-10-21T13:00:00+02:00", 0,
                                     show_clock=True, **arguments).frames[0]
        self.assertLess(sum(on[:3]), sum(off[:3]))
        for y in range(11):
            start = (y * 64 + 38) * 3
            self.assertEqual(on[start:(y * 64 + 63) * 3], off[start:(y * 64 + 63) * 3])

    def test_weather_is_independent_of_home_clock_in_home_and_game(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            self.addCleanup(engine.stop)
            with patch.object(engine, "_faceplate_weather_payload", return_value=(
                {"condition": "rain", "temperature_c": 12}, {}, "",
            )):
                for clock in (False, True):
                    for weather in (False, True):
                        values = {**settings.all(), "faceplate_dashboard_show_clock": clock,
                                  "faceplate_dashboard_show_weather": weather}
                        for game in (False, True):
                            facts = engine._faceplate_artwork_dashboard_facts(values, game)
                            self.assertEqual(clock and not game, facts["dashboard_show_clock"])
                            visible = weather
                            self.assertEqual(visible, facts["show_weather_notch"])
                            self.assertEqual({"condition": "rain", "temperature_c": 12}
                                             if visible else {}, facts["weather"])

    def test_home_preview_obeys_global_clock_and_game_preview_ignores_saved_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            self.addCleanup(engine.stop)
            library = engine.faceplate.steamgriddb
            captured = []

            def render(request, ticket):
                captured.append(dict(request))
                return b"GIF89a", {"signature": "test", "frames": 1, "delay_cs": 100}

            with patch.object(engine, "_render_faceplate_scene", side_effect=render), \
                    patch.object(library, "home_dashboard_pack_reference") as home_pack, \
                    patch.object(library, "selected_dashboard_pack_reference") as game_pack:
                for legacy_clock in (False, True):
                    manifest = {"dashboard_show_clock": legacy_clock,
                                "dashboard_pack_frames": 1, "dashboard_pack_sha256": "old"}
                    home_pack.return_value = game_pack.return_value = (manifest, Path(folder) / "pack.rgb")
                    for enabled in (False, True):
                        settings.update({"faceplate_dashboard_show_clock": enabled})
                        engine.faceplate_artwork_dashboard_preview(620, home=True)
                        self.assertEqual(enabled, captured[-1]["dashboard_show_clock"])
                        engine.faceplate_artwork_dashboard_preview(620, home=False)
                        self.assertFalse(captured[-1]["dashboard_show_clock"])
                        engine.faceplate_artwork_dashboard_preview(620, draft=True, home=True)
                        self.assertEqual(enabled, captured[-1]["dashboard_show_clock"])

    def test_game_clock_is_removed_even_when_legacy_artwork_requests_it(self):
        arguments = dict(
            backgrounds=(bytes((30, 60, 90)) * (64 * 54),),
            session_minutes=27, game_running=True, show_game_session=True,
            bottom_mode="controllers", controllers=({"percent": 87},),
            connected_controller_count=1, show_weather_notch=False,
        )
        legacy = build_artwork_dashboard(
            **arguments, instant="2026-10-18T21:48:00+02:00", show_clock=True,
        )
        clock_off = build_artwork_dashboard(
            **arguments, instant="2026-10-18T21:49:00+02:00", show_clock=False,
        )
        self.assertEqual(legacy.frames, clock_off.frames)
        self.assertEqual(legacy.signature, clock_off.signature)
        self.assertFalse(colour_positions(legacy.frames[0], (255, 231, 190), bottom=11))
        # Controllers is now a pure row; session belongs to its explicit choice.
        no_session = build_artwork_dashboard(
            **{**arguments, "show_game_session": False},
            instant="2026-10-18T21:48:00+02:00",
        )
        self.assertEqual(legacy.frames, no_session.frames)

    def test_dashboard_clock_format_persists_and_rejects_unknown_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = SettingsStore(str(path))
            self.assertEqual("24h", settings.all()["faceplate_dashboard_clock_format"])
            self.assertEqual(
                "12h", settings.update({
                    "faceplate_dashboard_clock_format": "12h",
                })["faceplate_dashboard_clock_format"],
            )
            path.write_text(json.dumps({
                "faceplate_dashboard_clock_format": "locale-ish",
            }), encoding="utf-8")
            self.assertEqual(
                "24h",
                SettingsStore(str(path)).all()["faceplate_dashboard_clock_format"],
            )

    def test_dashboard_clock_supports_24h_and_small_am_pm_without_notch_overlap(self):
        background = (bytes((30, 60, 90)) * (64 * 54),)
        twenty_four = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 0,
            clock_24h=True, show_clock=True,
        ).frames[0]
        twelve = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 0,
            clock_24h=False, show_clock=True,
        ).frames[0]
        warm_24 = colour_positions(twenty_four, (255, 231, 190), top=0, bottom=11)
        warm_12 = colour_positions(twelve, (255, 231, 190), top=0, bottom=11)
        suffix = {
            point for point in colour_positions(
                twelve, (125, 152, 181), top=0, bottom=11,
            ) if point[0] < 30
        }
        self.assertLessEqual(max(x for x, _ in warm_24), 20)
        self.assertLessEqual(max(x for x, _ in warm_12), 16)
        self.assertTrue(suffix)
        self.assertGreaterEqual(min(x for x, _ in suffix), 17)
        self.assertLessEqual(max(x for x, _ in suffix), 26)
        self.assertLess(max(x for x, _ in suffix), 30)

    def test_no_filter_preserves_every_background_pixel_outside_live_masks(self):
        background = bytes(
            channel
            for y in range(54)
            for x in range(64)
            for channel in ((x * 4) % 256, (y * 5) % 256, (x + y) % 256)
        )
        frame = build_artwork_dashboard(
            (background,), "2026-10-09T21:48:45+02:00", 0,
            treatment="none", show_weather_notch=False,
        ).frames[0]
        # Centre pixels outside the top readability fade and bottom rail are
        # byte-identical to the prepared artwork.
        for x, y in ((0, 12), (31, 20), (63, 30), (7, 43)):
            start = (y * 64 + x) * 3
            self.assertEqual(background[start:start + 3], frame[start:start + 3])

    def test_compatible_dashboard_gif_uses_lab56_fixed_332_palette(self):
        frames = tuple(
            bytes(channel
                  for y in range(54) for x in range(64)
                  for channel in (
                      (x * 17 + index) % 256,
                      (y * 29) % 256,
                      (x + y) % 256,
                  ))
            for index in range(3)
        )
        payload = build_artwork_dashboard(
            frames, "2026-10-09T21:48:45+02:00", 0,
            treatment="none", compression="compatible",
        ).gif()
        palette = tuple(
            tuple(payload[offset:offset + 3])
            for offset in range(13, 13 + 256 * 3, 3)
        )
        self.assertEqual(PALETTE_332, palette)

    def test_three_compression_levels_preserve_frames_and_global_palette(self):
        frames = tuple(
            bytes(channel
                  for y in range(54) for x in range(64)
                  for channel in (
                      (x * 3 + y * 2 + index) % 256,
                      (x * 2 + y * 5 + index * 3) % 256,
                      (x * 5 + y + index * 7) % 256,
                  ))
            for index in range(4)
        )
        results = {
            level: build_artwork_dashboard(
                frames, "2026-10-09T21:48:45+02:00", 0,
                treatment="none", compression=level,
            )
            for level in COMPRESSION_LEVELS
        }
        payloads = {level: result.gif() for level, result in results.items()}
        for level, result in results.items():
            self.assertEqual(4, len(result.frames), level)
            self.assertEqual(10, result.delay_cs, level)
            self.assertEqual(level, result.compression)
            validate_gif(payloads[level])
            self.assertEqual(4, payloads[level].count(b"\x21\xF9\x04"))
            palette = tuple(
                tuple(payloads[level][offset:offset + 3])
                for offset in range(13, 13 + 256 * 3, 3)
            )
            self.assertEqual(PALETTE_332, palette, level)
        self.assertEqual(3, len(set(payloads.values())))
        self.assertEqual(3, len({result.signature for result in results.values()}))

    def test_unknown_compression_falls_back_to_lab56_compatible(self):
        background = (bytes((12, 60, 130)) * (64 * 54),)
        unknown = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 0,
            compression="maximum-ish",
        )
        compatible = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 0,
            compression="compatible",
        )
        self.assertEqual("compatible", unknown.compression)
        self.assertEqual(compatible.signature, unknown.signature)
        self.assertEqual(compatible.gif(), unknown.gif())

    def test_removed_performance_rail_migrates_to_next_hour(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({
                "faceplate_dashboard_bottom_mode": "performance",
            }), encoding="utf-8")
            settings = SettingsStore(str(path))
        self.assertEqual(
            "next_hour", settings.all()["faceplate_dashboard_bottom_mode"],
        )

    def test_connected_controller_without_percentage_keeps_its_dashboard_seat(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({
                "faceplate_dashboard_bottom_mode": "controllers",
                "faceplate_dashboard_clock_format": "12h",
            })
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            engine.controllers.update([{
                "id": "p1", "name": "Pad", "percent": None,
                "level": None, "charging": False,
            }], settings.all())
            facts = engine._faceplate_artwork_dashboard_facts(
                settings.all(), False,
            )
        self.assertEqual([{
            "level": None, "charging": False, "percent": None,
        }], facts["controllers"])
        self.assertFalse(facts["clock_24h"])

    def test_compositor_keeps_all_overlay_values_stable_across_background_frames(self):
        backgrounds = (
            bytes((12, 60, 130)) * (64 * 54),
            bytes((150, 35, 70)) * (64 * 54),
        )
        result = build_artwork_dashboard(
            backgrounds, "2026-10-09T21:48:45+02:00", 102,
            quantize_battery(66), treatment="cinema",
            background_signature="prepared-pack",
        )
        payload = result.gif()
        validate_gif(payload)
        self.assertEqual(2, len(result.frames))
        self.assertEqual(10, result.delay_cs)
        # Overlay pixels stay fixed while the artwork moves beneath them.
        for colour in ((255, 231, 190), (66, 220, 255), (255, 188, 65)):
            first = colour_positions(result.frames[0], colour)
            second = colour_positions(result.frames[1], colour)
            self.assertTrue(first)
            self.assertEqual(first, second)

    def test_header_reserves_a_compact_clock_and_weather_notch(self):
        result = build_artwork_dashboard(
            (bytes((12, 60, 130)) * (64 * 54),),
            "2026-10-09T21:48:45+02:00", 102,
            treatment="cinema", show_clock=True,
            weather={"condition": "rain", "temperature_c": 13},
            forecast={"next_hour_condition": "rain",
                      "next_hour_temperature_c": 12,
                      "next_hour_precipitation_probability": 80},
        )
        frame = result.frames[0]
        clock = colour_positions(frame, (255, 231, 190), top=0, bottom=11)
        temperature = colour_positions(frame, (255, 188, 65), top=0, bottom=11)
        self.assertTrue(clock)
        self.assertTrue(temperature)
        self.assertLessEqual(max(x for x, _ in clock), 18)
        self.assertGreaterEqual(min(x for x, _ in temperature), 43)
        self.assertLessEqual(max(x for x, _ in temperature), 61)
        for y in (0, 10):
            self.assertTrue(all(
                frame[(y * 64 + x) * 3:(y * 64 + x + 1) * 3]
                == bytes((30, 116, 157))
                for x in range(38, 63)
            ))
        for x, y in ((37, 1), (63, 1), (37, 9), (63, 9)):
            self.assertEqual(
                frame[(y * 64 + x) * 3:(y * 64 + x + 1) * 3],
                bytes((30, 116, 157)),
            )

    def test_background_only_fallback_keeps_clock_and_hides_weather_notch(self):
        frame = build_artwork_dashboard(
            (bytes((12, 60, 130)) * (64 * 54),),
            "2026-10-09T21:48:45+02:00", 0,
            weather={"condition": "rain", "temperature_c": 13},
            bottom_mode="controllers", controllers=({"percent": 87},),
            show_weather_notch=False, show_clock=True,
        ).frames[0]
        self.assertTrue(colour_positions(frame, (255, 231, 190), top=0, bottom=11))
        self.assertFalse(colour_positions(frame, (30, 116, 157), top=0, bottom=11))
        self.assertFalse(colour_positions(frame, (255, 188, 65), top=0, bottom=11))
        self.assertTrue(colour_positions(frame, (66, 220, 255), top=46))

    def test_legacy_overlay_switches_do_not_change_the_fixed_dashboard(self):
        background = (bytes((12, 60, 130)) * (64 * 54),)
        large = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 7,
            clock_size="large", status={"recent_event": "notification"},
        )
        compact = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 7,
            clock_size="compact", status={"recent_event": "notification"},
        )
        plain = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 7,
            clock_size="large", status={},
        )
        self.assertEqual(large.frames[0], compact.frames[0])
        self.assertEqual(large.frames[0], plain.frames[0])
        self.assertEqual(large.signature, plain.signature)

    def test_strict_bottom_layouts_stay_inside_their_pixel_rails(self):
        background = (bytes((30, 60, 90)) * (64 * 54),)
        common = dict(weather={"condition": "breaks", "temperature_c": 18})
        next_hour = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 7,
            bottom_mode="next_hour", forecast={
                "next_hour_condition": "rain", "next_hour_temperature_c": 13,
                "next_hour_precipitation_probability": 80,
            }, **common,
        ).frames[0]
        today = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 7,
            bottom_mode="today", forecast={
                "today_condition": "breaks", "morning_temperature_c": 9,
                "afternoon_temperature_c": 14,
            }, **common,
        ).frames[0]
        controllers = build_artwork_dashboard(
            background, "2026-10-09T21:48:45+02:00", 7,
            bottom_mode="controllers", controllers=(
                {"percent": 87}, {"percent": 64},
            ), show_p2=True, **common,
        ).frames[0]
        for frame in (next_hour, today, controllers):
            self.assertTrue(all(
                frame[(45 * 64 + x) * 3:(45 * 64 + x + 1) * 3] == bytes((20, 83, 111))
                for x in range(64)
            ))
        p2 = colour_positions(controllers, (255, 188, 65), top=46)
        p1 = colour_positions(controllers, (66, 220, 255), top=46)
        self.assertLessEqual(max(x for x, _ in p2), 24)
        self.assertGreaterEqual(min(x for x, _ in p1), 39)

    def test_today_rail_keeps_a_dark_column_around_the_slash(self):
        frame = build_artwork_dashboard(
            (bytes(64 * 54 * 3),), "2026-10-09T21:48:45+02:00", 0,
            weather={"condition": "breaks", "temperature_c": 18},
            bottom_mode="today", forecast={
                "today_condition": "breaks", "morning_temperature_c": 12,
                "afternoon_temperature_c": 14,
            },
        ).frames[0]
        morning = colour_positions(frame, (102, 190, 255), top=46)
        separator = colour_positions(frame, (125, 152, 181), top=46)
        afternoon = colour_positions(frame, (255, 145, 72), top=46)
        morning_right = max(x for x, _ in morning)
        separator_left = min(x for x, _ in separator)
        separator_right = max(x for x, _ in separator)
        afternoon_left = min(x for x, _ in afternoon)
        self.assertGreaterEqual(separator_left - morning_right, 2)
        self.assertGreaterEqual(afternoon_left - separator_right, 2)

    def test_next_hour_risk_uses_approved_umbrella_beside_unchanged_forecast_rain(self):
        frame = build_artwork_dashboard(
            (bytes(64 * 54 * 3),), "2026-10-09T21:48:45+02:00", 0,
            weather={"condition": "breaks", "temperature_c": 18}, ux_enabled=True,
            bottom_mode="next_hour", forecast={
                "next_hour_condition": "rain", "next_hour_temperature_c": 13,
                "next_hour_precipitation_probability": 80,
            },
        ).frames[0]
        cyan = set(colour_positions(frame, (66, 220, 255), top=46))
        expected={(41+x,47+y) for y,line in enumerate((
            "0011100","0111110","1111111","1001001","0001000","0101000","0011000"))
            for x,bit in enumerate(line) if bit=='1'}
        self.assertEqual({p for p in cyan if 41<=p[0]<=47},expected)
        # The actual rain forecast remains a grey cloud with cyan rain strokes.
        self.assertTrue(any(x<25 for x,y in colour_positions(frame,(125,152,181),top=46)))

    def test_clear_day_uses_the_same_solid_sun_in_notch_and_bottom_rail(self):
        frame = build_artwork_dashboard(
            (bytes(64 * 54 * 3),), "2026-10-09T12:48:45+02:00", 0,
            weather={"condition": "clear_day", "temperature_c": 18},
            bottom_mode="next_hour", forecast={
                "next_hour_condition": "clear_day",
                "next_hour_temperature_c": 19,
                "next_hour_precipitation_probability": 0,
            },
        ).frames[0]
        yellow = set(colour_positions(frame, (255, 200, 75)))
        shape = {
            (0, 0), (5, 0), (2, 1), (3, 1),
            (1, 2), (2, 2), (3, 2), (4, 2),
            (1, 3), (2, 3), (3, 3), (4, 3),
            (2, 4), (3, 4), (0, 5), (5, 5),
        }
        self.assertTrue({(39 + x, 3 + y) for x, y in shape}.issubset(yellow))
        self.assertTrue({(17 + x, 47 + y) for x, y in shape}.issubset(yellow))

    def test_approved_model_header_and_three_rails_match_every_pixel(self):
        """Pin the Lab 75 approved native header and revised 8 x 8 rail."""
        background = (bytes(64 * 54 * 3),)
        common = dict(
            backgrounds=background, instant="2026-10-09T21:48:00+02:00",
            show_clock=True,
            session_minutes=0, weather={"condition": "rain", "temperature_c": 12},
        )
        modes = {
            "controllers": dict(
                bottom_mode="controllers",
                controllers=({"percent": 87}, {"percent": 64}), show_p2=True,
            ),
            "next_hour": dict(
                bottom_mode="next_hour", forecast={
                    "next_hour_condition": "rain",
                    "next_hour_temperature_c": 13,
                    "next_hour_precipitation_probability": 80,
                },
            ),
            "today": dict(
                bottom_mode="today", forecast={
                    "today_condition": "breaks", "morning_temperature_c": 9,
                    "afternoon_temperature_c": 14,
                },
            ),
        }
        expected_rails = {
            "controllers": "db39e4afacc38bfde4c8c33222bcb72c356b78d5812ef15e3ebfce474b2d1ef4",
            "next_hour": "5de8116a304f028e7b30f2d1307e682cfee888816a6989064f0fc8d1404c844b",
            "today": "15a4207b93be04193362020ddbb09b983a25b3cee2262c66ac45d39f0907bc3e",
        }
        expected_header = "854322cbf5deaafe2bbca303708d278434d86fcb80ffe9f37f740e1d1931aca8"
        for name, arguments in modes.items():
            with self.subTest(mode=name):
                frame = build_artwork_dashboard(**common, **arguments).frames[0]
                header = b"".join(
                    frame[(y * 64) * 3:((y + 1) * 64) * 3]
                    for y in range(11)
                )
                rail = b"".join(
                    frame[(y * 64) * 3:((y + 1) * 64) * 3]
                    for y in range(45, 54)
                )
                self.assertEqual(hashlib.sha256(header).hexdigest(), expected_header)
                self.assertEqual(hashlib.sha256(rail).hexdigest(), expected_rails[name])

    def test_animation_keeps_source_frame_count_and_ten_fps_cadence(self):
        backgrounds = tuple(
            bytes((index, 30, 80)) * (64 * 54) for index in range(80)
        )
        short = build_artwork_dashboard(
            backgrounds[:20], "2026-10-09T21:48:45+02:00", 0,
            source_frame_count=20,
        )
        long = build_artwork_dashboard(
            backgrounds, "2026-10-09T21:48:45+02:00", 0,
            source_frame_count=80,
        )
        self.assertEqual(10, short.delay_cs)
        self.assertEqual(10, long.delay_cs)
        self.assertEqual(80, len(long.frames))
        self.assertEqual(800, long.delay_cs * len(long.frames))
        payload = long.gif()
        validate_gif(payload)
        self.assertEqual(80, payload.count(b"\x21\xF9\x04"))

    def test_dashboard_loop_repairs_terminal_edge_without_removing_frames(self):
        ordinary = bytes((30, 80, 140)) * (64 * 54)
        damaged = bytearray(bytes((40, 90, 150)) * (64 * 54))
        damaged[:64 * 3] = bytes(64 * 3)
        repaired = stabilize_dashboard_loop((ordinary, bytes(damaged)))
        self.assertEqual(2, len(repaired))
        self.assertEqual(ordinary[:64 * 3], repaired[-1][:64 * 3])
        self.assertEqual(bytes(damaged)[64 * 3:], repaired[-1][64 * 3:])

    def test_dashboard_loop_preserves_authored_terminal_hold(self):
        first = bytes((10, 30, 70)) * (64 * 54)
        moving = bytes((90, 40, 20)) * (64 * 54)
        repaired = stabilize_dashboard_loop((first, moving, moving, moving))
        self.assertEqual((first, moving, moving, moving), repaired)

    def test_dashboard_loop_preserves_hard_authored_seam(self):
        backgrounds = tuple(
            bytes((10 + index * 8, 20, 90)) * (64 * 54)
            for index in range(12)
        )
        repaired = stabilize_dashboard_loop(backgrounds)
        self.assertEqual(backgrounds, repaired)

    def test_dashboard_loop_never_imports_first_frame_black_edge_into_tail(self):
        frames = [
            bytes((20 + index * 6, 60 + index * 4, 120 + index * 2))
            * (64 * 54)
            for index in range(12)
        ]
        first = bytearray(frames[0])
        first[:64 * 3] = bytes(64 * 3)
        frames[0] = bytes(first)
        repaired = stabilize_dashboard_loop(tuple(frames))
        self.assertEqual(tuple(frames), repaired)
        self.assertTrue(all(any(frame[:64 * 3]) for frame in repaired[-4:]))

    def test_dashboard_loop_restores_bounded_blank_tail_without_shortening(self):
        visible = bytes((30, 80, 140)) * (64 * 54)
        black = bytes(64 * 54 * 3)
        repaired = stabilize_dashboard_loop((visible, visible, black, black))
        self.assertEqual(4, len(repaired))
        self.assertEqual((visible, visible, visible, visible), repaired)

    def test_unknown_battery_is_hidden_and_levels_are_coarse(self):
        self.assertIsNone(quantize_battery(None))
        self.assertEqual(0, quantize_battery(4)["level"])
        self.assertEqual(2, quantize_battery(51)["level"])
        self.assertEqual(4, quantize_battery(99, True)["level"])
        self.assertTrue(quantize_battery(99, True)["charging"])

    def test_target_uses_measured_full_handler_time_and_five_minute_buckets(self):
        ordinary = datetime(2026, 10, 9, 12, 32, 0, tzinfo=timezone.utc)
        target, lead = Engine._faceplate_artwork_dashboard_target(ordinary, 5, 5000)
        self.assertEqual("12:30", target.strftime("%H:%M"))
        self.assertGreater(lead, 5)
        near_boundary = datetime(2026, 10, 9, 12, 34, 54, tzinfo=timezone.utc)
        target, _lead = Engine._faceplate_artwork_dashboard_target(
            near_boundary, 5, 5000,
        )
        self.assertEqual("12:35", target.strftime("%H:%M"))

    def test_active_background_pack_is_read_without_decoding_source_media(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            root = Path(directory) / "artwork" / "620" / "prepared" / "animated"
            root.mkdir(parents=True)
            compiled = b"GIF89a" + (64).to_bytes(2, "little") + (54).to_bytes(2, "little") + b"\x80\0\0compiled"
            pack = bytes((20, 40, 80)) * (64 * 54) + bytes((80, 20, 40)) * (64 * 54)
            (root / "faceplate.gif").write_bytes(compiled)
            (root / "artwork-dashboard.rgb").write_bytes(pack)
            (root / "manifest.json").write_text(json.dumps({
                "schema": 2, "appid": 620, "mode": "animated", "ready": True,
                "sha256": hashlib.sha256(compiled).hexdigest(),
                "dashboard_pack": "artwork-dashboard.rgb",
                "dashboard_pack_frames": 2,
                "dashboard_pack_sha256": hashlib.sha256(pack).hexdigest(),
                "dashboard_pack_revision": DASHBOARD_PACK_REVISION,
            }), encoding="utf-8")
            (root.parents[1] / "active.json").write_text(json.dumps({
                "schema": 1, "appid": 620, "mode": "animated",
            }), encoding="utf-8")
            selected = library.selected_dashboard_pack(620)
        self.assertIsNotNone(selected)
        self.assertEqual(2, len(selected[0]))
        self.assertTrue(all(len(frame) == FRAME_BYTES for frame in selected[0]))

    def test_saved_library_listing_is_manifest_only_and_exact_delete_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            root = Path(directory) / "artwork" / "620" / "prepared" / "static"
            root.mkdir(parents=True)
            pack = bytes((20, 40, 80)) * (64 * 54)
            (root / "faceplate.gif").write_bytes(b"GIF89a-library")
            (root / "artwork-dashboard.rgb").write_bytes(pack)
            (root / "manifest.json").write_text(json.dumps({
                "schema": 2, "appid": 620, "asset_id": 44,
                "mode": "static", "ready": True,
                "thumb": "https://steamgriddb.com/example.webp",
                "animated": False, "frames": 1, "prepared_at": 42,
                "dashboard_pack": "artwork-dashboard.rgb",
                "dashboard_pack_frames": 1,
                "dashboard_pack_sha256": hashlib.sha256(pack).hexdigest(),
                "dashboard_pack_revision": DASHBOARD_PACK_REVISION,
            }), encoding="utf-8")
            (root.parents[1] / "active.json").write_text(json.dumps({
                "schema": 1, "appid": 620, "mode": "static",
            }), encoding="utf-8")
            entries = library.library_entries()
            self.assertEqual(1, len(entries))
            self.assertTrue(entries[0]["active"])
            self.assertTrue(entries[0]["dashboard_ready"])
            self.assertTrue(library.prepared_dashboard_manifest(620, "static"))
            self.assertEqual(620, entries[0]["appid"])
            self.assertTrue(library.delete_prepared(620, "static"))
            self.assertFalse(root.exists())
            self.assertFalse((root.parents[1] / "active.json").exists())
            self.assertEqual([], library.library_entries())

    def test_old_saved_gif_is_visible_but_not_assignable_as_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            root = Path(directory) / "artwork" / "730" / "prepared" / "animated"
            root.mkdir(parents=True)
            compiled = b"GIF89a-old-prepared-copy"
            (root / "faceplate.gif").write_bytes(compiled)
            (root / "manifest.json").write_text(json.dumps({
                "schema": 2, "appid": 730, "asset_id": 45,
                "mode": "animated", "ready": True, "animated": True,
                "sha256": hashlib.sha256(compiled).hexdigest(),
                "prepared_at": 43,
            }), encoding="utf-8")
            entries = library.library_entries()
            dashboard_manifest = library.prepared_dashboard_manifest(730, "animated")
        self.assertEqual(1, len(entries))
        self.assertFalse(entries[0]["dashboard_ready"])
        self.assertEqual({}, dashboard_manifest)


if __name__ == "__main__":
    unittest.main()
