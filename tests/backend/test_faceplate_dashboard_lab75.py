"""Exact approved Lab 75 matrices and Home/in-game layout contract."""

from datetime import datetime
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageSequence

from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.faceplate.artwork_dashboard import (
    build_artwork_dashboard, _weather_icon, _precipitation_risk_icon,
    MOON_IVORY, MOON_SHADOW, SEPARATOR_GREY, WEATHER_BLUE, WARM_WHITE,
    NOTCH_BORDER, TEMPERATURE_AMBER,
)
from signalbar.faceplate.scenes import Canvas, measure_text
from signalbar.faceplate.scene_renderer import render_isolated
from signalbar.faceplate.weather_artwork import (
    build_weather_artwork_dashboard_snapshot, build_weather_artwork_scene, _backgrounds,
)


RAIN = ("00000000", "000CCC00", "00CCCCC0", "0CCCCCCC",
        "00B0B0B0", "0B0B0B00", "00B00000", "00000000")
MOON = ("00000000", "00YYG000", "0YYGGG00", "0YYGGG00",
        "0YYYGG00", "00YYY000", "00000000", "00000000")
BLACK = bytes(64 * 54 * 3)


def positions(frame, colour, top=0, bottom=54):
    return {(x, y) for y in range(top, bottom) for x in range(64)
            if frame[(y * 64 + x) * 3:(y * 64 + x + 1) * 3] == bytes(colour)}


class Lab75DashboardTests(unittest.TestCase):
    def assert_matrix(self, canvas, rows, origin):
        colours = {"0": (0, 0, 0), "Y": MOON_IVORY, "G": MOON_SHADOW,
                   "C": SEPARATOR_GREY, "B": WEATHER_BLUE}
        frame = canvas.bytes()
        for y, row in enumerate(rows):
            for x, token in enumerate(row):
                offset = ((origin[1] + y) * 64 + origin[0] + x) * 3
                self.assertEqual(bytes(colours[token]), frame[offset:offset + 3],
                                 (x, y, token))

    def test_weather_matrices_remain_exact_and_risk_uses_approved_scalloped_umbrella(self):
        for condition, rows in (("rain", RAIN), ("clear_night", MOON)):
            for compact in (False, True):
                with self.subTest(condition=condition, compact=compact):
                    canvas = Canvas()
                    _weather_icon(canvas, condition, 20, 20, compact=compact)
                    self.assert_matrix(canvas, rows, (19 if compact else 20, 19 if compact else 20))
        canvas = Canvas()
        _precipitation_risk_icon(canvas, 20, 20)
        self.assert_matrix(canvas, (
            "00BBB00","0BBBBB0","BBBBBBB","B00B00B",
            "000B000","0B0B000","00BB000"), (20, 19))

    def test_weather_alone_shares_notch_and_releases_seven_columns_without_touching_motion(self):
        for condition in ("rain", "clear_night"):
            weather, metadata = build_weather_artwork_scene(
                condition, 0, 12, "celsius", "night", visual_theme="weather-artwork-v2",
            )
            source = _backgrounds("weather-artwork-v2", f"{condition}:0")
            dashboard = build_artwork_dashboard(
                (BLACK,), "2026-10-11T21:48:00", 0,
                weather={"condition": condition, "temperature_c": 12},
            ).frames[0]
            self.assertEqual(1.0, metadata["power_scale"])
            self.assertEqual(len(source), len(weather.frames))
            self.assertEqual(10, weather.delay_cs)
            for frame, background in zip(weather.frames, source):
                self.assertEqual(background[11 * 64 * 3:], frame[11 * 64 * 3:])
                for y in range(11):
                    self.assertEqual(background[(y * 64 + 30) * 3:(y * 64 + 37) * 3],
                                     frame[(y * 64 + 30) * 3:(y * 64 + 37) * 3])
                    for x in range(37, 64):
                        if (x, y) in {(37, 0), (63, 0), (37, 10), (63, 10)}:
                            continue
                        offset = (y * 64 + x) * 3
                        self.assertEqual(dashboard[offset:offset + 3], frame[offset:offset + 3])

    def test_notch_is_27_columns_and_all_clock_formats_clear_it(self):
        for hour in (0, 9, 12, 21, 23):
            for clock_24h in (True, False):
                for unit in ("celsius", "fahrenheit"):
                    for temperature in (-100, -12, 0, 12, 38, 100):
                        frame = build_artwork_dashboard(
                            (BLACK,), datetime(2026, 10, 11, hour, 48), 0,
                            weather={"condition": "rain", "temperature_c": temperature},
                            clock_24h=clock_24h, unit=unit,
                        ).frames[0]
                        border = positions(frame, NOTCH_BORDER, bottom=11)
                        self.assertEqual((37, 63), (min(x for x, _ in border), max(x for x, _ in border)))
                        self.assertTrue(all(x < 37 for x, _ in positions(frame, WARM_WHITE, bottom=11)))
                        temp = positions(frame, TEMPERATURE_AMBER, bottom=11)
                        self.assertGreaterEqual(min(x for x, _ in temp), 47)
                        self.assertLessEqual(max(x for x, _ in temp), 60)
                        # Free seven-column strip contains neither notch nor icon.
                        for y in range(11):
                            self.assertEqual(bytes(7 * 3), frame[(y * 64 + 30) * 3:(y * 64 + 37) * 3])

    def test_clock_alignment_measures_complete_24h_and_12h_am_pm_blocks(self):
        for hour in (0, 9, 12, 21):
            for clock_24h in (True, False):
                time = datetime(2026, 10, 11, hour, 48)
                label = time.strftime("%H:%M") if clock_24h else time.strftime("%I:%M").lstrip("0")
                width = measure_text(label) + (0 if clock_24h else 2 + measure_text("AM"))
                for alignment in ("left", "center", "right"):
                    frame = build_artwork_dashboard(
                        (BLACK,), time, 0, show_weather_notch=False,
                        clock_24h=clock_24h, clock_position=alignment, show_clock=True,
                    ).frames[0]
                    ink = positions(frame, WARM_WHITE, bottom=11)
                    if not clock_24h:
                        ink |= positions(frame, SEPARATOR_GREY, bottom=11)
                    expected_x = 2 if alignment == "left" else (64 - width) // 2 if alignment == "center" else 62 - width
                    self.assertEqual((expected_x, expected_x + width - 1),
                                     (min(x for x, _ in ink), max(x for x, _ in ink)))
                    # Saved alignment is ignored, not lost, while weather is on.
                    visible = build_artwork_dashboard(
                        (BLACK,), time, 0, clock_24h=clock_24h,
                        clock_position=alignment, show_clock=True,
                    ).frames[0]
                    self.assertEqual(2, min(x for x, _ in positions(visible, WARM_WHITE, bottom=11)))

    def test_controllers_never_adds_a_session_from_legacy_flags(self):
        for game in (False, True):
            for count in (0, 1, 2):
                for show_p2 in (False, True):
                    pads = tuple({"percent": 87} for _ in range(count))
                    frame = build_artwork_dashboard(
                        (BLACK,), "2026-10-11T21:48:00", 84,
                        bottom_mode="controllers", controllers=pads,
                        show_p2=show_p2, game_running=game, show_game_session=True,
                        connected_controller_count=count,
                    ).frames[0]
                    session = positions(frame, WARM_WHITE, top=46)
                    self.assertFalse(session)
                    no_session = build_artwork_dashboard(
                        (BLACK,), "2026-10-11T21:48:00", 0,
                        bottom_mode="controllers", controllers=pads,
                        show_p2=True, game_running=game, show_game_session=False,
                        connected_controller_count=count,
                    ).frames[0]
                    self.assertEqual(frame,no_session)
        disabled = build_artwork_dashboard(
            (BLACK,), "2026-10-11T21:48:00", 84,
            bottom_mode="controllers", controllers=({"percent": None},),
            game_running=True, show_game_session=False,
        ).frames[0]
        self.assertFalse(positions(disabled, WARM_WHITE, top=46))

    def test_settings_persist_and_engine_shows_both_connected_pads_without_session(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "settings.json")
            settings = SettingsStore(path)
            settings.update({"faceplate_dashboard_show_weather": False,
                             "faceplate_dashboard_clock_position": "right"})
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            engine._faceplate_game_started_monotonic = 100
            with patch("signalbar.backend.engine.time.monotonic", return_value=5140), \
                    patch.object(engine.controllers, "faceplate_batteries", return_value=[{"percent": 87}, {"percent": None}]):
                facts = engine._faceplate_artwork_dashboard_facts(settings.all(), True)
            self.assertEqual("controllers", facts["bottom_mode"])
            self.assertEqual(2, facts["connected_controller_count"])
            self.assertEqual(2, len(facts["controllers"]))
            self.assertEqual(0, facts["session_minutes"])
            with patch("signalbar.backend.engine.time.monotonic", return_value=5140), \
                    patch.object(engine.controllers, "faceplate_batteries", return_value=[{"percent": None}]):
                single = engine._faceplate_artwork_dashboard_facts(settings.all(), True)
            self.assertEqual(0, single["session_minutes"])
            self.assertFalse(facts["show_weather_notch"])
            self.assertEqual("right", facts["clock_position"])
            self.assertEqual("right", SettingsStore(path).all()["faceplate_dashboard_clock_position"])
            settings.update({"faceplate_dashboard_clock_position": "diagonal",
                             "faceplate_dashboard_game_session": False})
            self.assertEqual("left", settings.all()["faceplate_dashboard_clock_position"])
            self.assertEqual("next_hour", engine._faceplate_artwork_dashboard_facts(settings.all(), True)["bottom_mode"])

    def test_weather_dashboard_preview_cache_changes_with_layout_in_same_minute(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(str(Path(directory) / "settings.json"))
            engine = Engine(settings, str(Path(directory) / "artwork.json"))
            weather = dict(condition="rain", now="2026-10-11T21:48:00", temperature_c=12,
                           unit="celsius", sunrise="2026-10-11T07:30:00", sunset="2026-10-11T19:15:00")
            with patch.object(engine, "_faceplate_weather_payload", return_value=(weather, {}, "")), \
                    patch.object(engine, "_render_faceplate_scene", return_value=(b"GIF89a", {})) as render:
                engine.faceplate_dashboard_preview("rain", 0, "weather-artwork-v2")
                original = render.call_args.args[1].content_key
                settings.update({"faceplate_dashboard_show_weather": False,
                                 "faceplate_dashboard_clock_position": "center"})
                engine.faceplate_dashboard_preview("rain", 0, "weather-artwork-v2")
                changed = render.call_args.args[1].content_key
                self.assertNotEqual(original, changed)
                self.assertFalse(render.call_args.args[0]["show_weather_notch"])
                self.assertEqual("center", render.call_args.args[0]["clock_position"])

    def test_weather_and_artwork_share_the_same_header_rail_and_full_frame_cadence(self):
        keywords = dict(bottom_mode="controllers", controllers=({"percent": 87},),
                        clock_24h=False, clock_position="right", show_weather_notch=False,
                        game_running=True, show_game_session=True, session_minutes=84,
                        connected_controller_count=1)
        weather, _ = build_weather_artwork_dashboard_snapshot(
            "2026-10-11T21:48:00", "rain", 0, 12, "celsius",
            "2026-10-11T07:30:00", "2026-10-11T19:15:00",
            visual_theme="weather-artwork-v2", **keywords,
        )
        art = build_artwork_dashboard((BLACK,) * 24, "2026-10-11T21:48:00", **keywords)
        self.assertEqual(24, len(weather.frames))
        self.assertEqual(24, len(art.frames))
        self.assertEqual(10, weather.delay_cs)
        self.assertEqual(art.frames[0][45 * 64 * 3:], weather.frames[0][45 * 64 * 3:])
        for colour in (WARM_WHITE, SEPARATOR_GREY):
            self.assertEqual(positions(art.frames[0], colour, bottom=11),
                             positions(weather.frames[0], colour, bottom=11))

    def test_isolated_worker_receives_new_layout_for_both_background_types(self):
        pack = bytes((20, 40, 80)) * (64 * 54)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pack.rgb"
            path.write_bytes(pack)
            common = dict(display_at="2026-10-11T21:48:00", clock_24h=False,
                          clock_position="right", show_weather_notch=False,
                          game_running=True, show_game_session=True, session_minutes=84,
                          bottom_mode="controllers", controllers=[{"percent": 87}],
                          connected_controller_count=1)
            requests = [dict(common, kind="artwork-dashboard", dashboard_pack_path=str(path),
                             dashboard_pack_frames=1, dashboard_pack_sha256=hashlib.sha256(pack).hexdigest()),
                        dict(common, kind="dashboard", visual_theme="weather-artwork-v2",
                             condition="rain", variant=0, temperature_c=12, unit="celsius",
                             sunrise="2026-10-11T07:30:00", sunset="2026-10-11T19:15:00")]
            frames = []
            for request in requests:
                payload, _ = render_isolated(request)
                expected = build_artwork_dashboard(
                    (pack,), common["display_at"], common["session_minutes"],
                    **{key: value for key, value in common.items()
                       if key not in {"display_at", "session_minutes"}},
                ) if request["kind"] == "artwork-dashboard" else build_weather_artwork_dashboard_snapshot(
                    common["display_at"], "rain", 0, 12, "celsius",
                    request["sunrise"], request["sunset"], visual_theme="weather-artwork-v2",
                    **{key: value for key, value in common.items() if key != "display_at"},
                )[0]
                self.assertEqual(expected.gif(), payload)
                with Image.open(BytesIO(payload)) as image:
                    frames.append(image.convert("RGB").tobytes())
                    self.assertEqual(24 if request["kind"] == "dashboard" else 1,
                                     len(list(ImageSequence.Iterator(image))))
