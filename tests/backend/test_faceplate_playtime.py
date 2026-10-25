"""Approved timer rail, independent deadlines, deduplicated routing and expiry."""

from datetime import datetime
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.providers.countdown import CountdownProvider
from signalbar.settings import SettingsStore
from signalbar.faceplate.playtime import (
    timer_facts, draw_timer_rail, overlay_timer, WARM, COLOURS,
)
from signalbar.faceplate.scenes import Canvas, draw_text
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard
from signalbar.faceplate.scene_renderer import render_isolated
from signalbar.faceplate.weather_artwork import (
    build_weather_artwork_dashboard_snapshot, build_weather_artwork_scene,
)


FRAME = bytes((20, 40, 80)) * (64 * 54)
INSTANT = "2026-10-12T21:48:00+02:00"


class PlaytimeRailTests(unittest.TestCase):
    def test_minute_buckets_and_exact_15_and_5_minute_thresholds(self):
        cases = [(1440, 24, "normal", False), (1430, 24, "normal", False),
                 (901, 16, "normal", False), (900, 15, "warning", False),
                 (301, 6, "warning", False), (300, 5, "urgent", False),
                 (241, 5, "urgent", False), (240, 4, "urgent", False),
                 (60, 1, "urgent", False), (59, 1, "urgent", True),
                 (0.1, 1, "urgent", True), (5040, 84, "normal", False)]
        for remaining, minutes, urgency, last in cases:
            self.assertEqual(dict(state="remaining", minutes=minutes,
                                  urgency=urgency, last_minute=last), timer_facts(remaining))
        for remaining in (0, -10, float("nan"), float("inf")):
            self.assertEqual({}, timer_facts(remaining))

    def test_approved_layout_coordinates_for_remaining_over_hour_last_and_ended(self):
        cases = [(1440, [(2, 48, "LEFT"), (51, 48, "MIN")]),
                 (5040, [(2, 48, "LEFT"), (47, 48, "H")]),
                 (59, [(2, 48, "LEFT"), (43, 48, "<1MIN")])]
        for remaining, expected in cases:
            calls = []
            def text(canvas, x, y, label, colour):
                calls.append((x, y, label))
                return draw_text(canvas, x, y, label, colour)
            with patch("signalbar.faceplate.playtime.draw_text", side_effect=text):
                self.assertTrue(draw_timer_rail(Canvas(), timer_facts(remaining)))
            self.assertEqual(expected, calls)
        with patch("signalbar.faceplate.playtime.draw_text", wraps=draw_text) as text:
            draw_timer_rail(Canvas(), {"state": "ended"})
            self.assertEqual((15, 48, "TIME'S UP"), text.call_args.args[1:4])

    def test_native_large_24_matches_approved_pixels_no_scaling_or_overlap(self):
        canvas = Canvas()
        draw_timer_rail(canvas, timer_facts(1440))
        rows = ("01110", "10001", "00001", "00010", "00100", "01000", "11111")
        four = ("00010", "00110", "01010", "10010", "11111", "00010", "00010")
        for origin, shape in ((37, rows), (43, four)):
            for y, row in enumerate(shape):
                for x, bit in enumerate(row):
                    self.assertEqual(COLOURS["normal"] if bit == "1" else (1, 5, 14),
                                     canvas.pixels[(46 + y) * 64 + origin + x])
        for y in range(46, 54):
            for x in range(17, 37):
                self.assertEqual((1, 5, 14), canvas.pixels[y * 64 + x])

    def test_timer_changes_only_nine_bottom_rows_and_absence_is_byte_identical(self):
        for seconds in (1, 60, 300, 900, 1440, 5040, 14400, 86400):
            with self.subTest(seconds=seconds):
                output = overlay_timer(FRAME, timer_facts(seconds))
                self.assertEqual(FRAME[:45 * 64 * 3], output[:45 * 64 * 3])
                self.assertEqual(len(FRAME), len(output))
        self.assertEqual(FRAME, overlay_timer(FRAME, {}))
        self.assertEqual(FRAME, overlay_timer(FRAME, None))

    def test_active_countdown_temporarily_replaces_controllers_or_forecasts(self):
        common = dict(backgrounds=(FRAME,), instant=INSTANT, session_minutes=84,
                      weather={"condition": "rain", "temperature_c": 12})
        outputs = []
        for mode in ("controllers", "next_hour", "today"):
            outputs.append(build_artwork_dashboard(**common, bottom_mode=mode,
                controllers=({"percent": 87},), countdown=timer_facts(1440)).frames[0])
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        normal = build_artwork_dashboard(**common, bottom_mode="controllers",
                                         controllers=({"percent": 87},)).frames[0]
        self.assertEqual(normal[:45 * 64 * 3], outputs[0][:45 * 64 * 3])
        self.assertNotEqual(normal[45 * 64 * 3:], outputs[0][45 * 64 * 3:])

    def test_weather_and_artwork_keep_full_animation_and_same_timer_row(self):
        timer = timer_facts(300)
        art = build_artwork_dashboard((FRAME,) * 80, INSTANT, 0, countdown=timer)
        weather, _ = build_weather_artwork_dashboard_snapshot(
            INSTANT, "rain", 0, 12, "celsius", "2026-10-12T07:00:00+02:00",
            "2026-10-12T19:00:00+02:00", visual_theme="weather-artwork-v2", countdown=timer)
        only, _ = build_weather_artwork_scene("rain", 0, 12, "celsius", "night",
                                             visual_theme="weather-artwork-v2", countdown=timer)
        self.assertEqual((80, 24, 24), (len(art.frames), len(weather.frames), len(only.frames)))
        self.assertEqual((10, 10, 10), (art.delay_cs, weather.delay_cs, only.delay_cs))
        self.assertTrue(all(frame[45 * 64 * 3:] == art.frames[0][45 * 64 * 3:]
                            for frame in (*art.frames, *weather.frames, *only.frames)))

    def test_real_isolated_workers_render_all_three_routes_with_timer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "background.rgb"
            path.write_bytes(FRAME)
            timer = timer_facts(5040)
            requests = [
                dict(kind="artwork-dashboard", display_at=INSTANT, countdown=timer,
                     dashboard_pack_path=str(path), dashboard_pack_frames=1,
                     dashboard_pack_sha256=hashlib.sha256(FRAME).hexdigest()),
                dict(kind="dashboard", visual_theme="weather-artwork-v2", countdown=timer,
                     display_at=INSTANT, condition="rain", variant=0, temperature_c=12,
                     unit="celsius", sunrise="2026-10-12T07:00:00+02:00", sunset="2026-10-12T19:00:00+02:00"),
                dict(kind="weather", visual_theme="weather-artwork-v2", countdown=timer,
                     condition="rain", variant=0, temperature_c=12, unit="celsius", phase="night"),
            ]
            for request in requests:
                payload, manifest = render_isolated(request)
                self.assertTrue(payload.startswith(b"GIF89a"))
                self.assertEqual(len(payload), manifest["size_bytes"])
                without, _ = render_isolated({**request, "countdown": None})
                self.assertNotEqual(payload, without)


class CountdownDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.provider = CountdownProvider(clock=lambda: self.now)

    def test_led_polling_and_personal_status_keep_natural_expiry_for_faceplate(self):
        for poll in (self.provider.status, self.provider.output, self.provider.personal_status):
            self.provider.start("free", 60)
            self.now += 60
            poll()
            snapshot = self.provider.faceplate_snapshot()
            self.assertFalse(snapshot["active"])
            self.assertTrue(snapshot["completion_id"].startswith("free:"))
            self.provider.stop()

    def test_stop_is_cancellation_not_completion_and_retention_is_bounded(self):
        self.provider.start("free", 60)
        self.now += 59
        self.provider.stop("free")
        self.assertNotIn("completion_id", self.provider.faceplate_snapshot())
        self.provider.start("free", 1)
        self.now += 1
        self.assertIn("completion_id", self.provider.faceplate_snapshot())
        self.now += 60
        self.assertNotIn("completion_id", self.provider.faceplate_snapshot())

    def test_priority_is_preview_then_families_then_free_and_no_false_end(self):
        self.provider.start("free", 3600)
        self.provider.start("parental", 1200)
        self.provider.start("preview", 15)
        self.assertEqual("preview", self.provider.faceplate_snapshot()["source"])
        self.now += 15
        self.assertEqual("parental", self.provider.faceplate_snapshot()["source"])
        self.assertEqual("free", self.provider.faceplate_snapshot(allow_parental=False)["source"])
        self.now += 1185
        self.assertEqual("free", self.provider.faceplate_snapshot()["source"])

    def test_extension_uses_real_deadline_and_does_not_reset_elapsed_time(self):
        self.provider.start("free", 60)
        self.now += 10
        self.assertTrue(self.provider.extend_personal(60))
        self.assertEqual(110, self.provider.faceplate_snapshot()["remaining_seconds"])
        self.now += 110
        self.assertIn("completion_id", self.provider.faceplate_snapshot())


class EnginePlaytimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = SettingsStore(str(Path(self.folder.name) / "settings.json"))
        self.engine = Engine(self.settings, str(Path(self.folder.name) / "artwork.json"))
        self.now = 100.0
        self.engine.countdown = CountdownProvider(clock=lambda: self.now)

    def facts(self):
        with patch("signalbar.backend.engine.time.monotonic", return_value=self.now):
            return self.engine._faceplate_playtime_facts(self.settings.all(), True)

    def test_semantic_facts_stay_identical_for_sixty_samples_within_a_minute(self):
        self.engine.countdown.start("free", 1440)
        first = self.facts()
        for second in range(60):
            self.now = 100 + second
            self.assertEqual(first, self.facts())
        self.now = 160
        self.assertEqual(23, self.facts()["minutes"])

    def test_end_waits_for_ack_then_holds_eight_seconds_and_never_reappears(self):
        self.engine.countdown.start("free", 1)
        self.now += 1
        self.assertEqual({"state": "ended"}, self.facts())
        self.now += 21  # Slow hardware ACK must not consume the message's hold.
        self.assertEqual({"state": "ended"}, self.facts())
        self.engine._faceplate_timer_end["ack_at"] = self.now
        self.now += 7.9
        self.assertEqual({"state": "ended"}, self.facts())
        self.now += .1
        self.assertEqual({}, self.facts())
        self.assertEqual({}, self.facts())

    def test_disable_or_cancel_restores_rail_and_no_ack_times_out(self):
        self.engine.countdown.start("free", 1)
        self.now += 1
        self.assertEqual({"state": "ended"}, self.facts())
        self.engine.stop_free_timer()
        self.assertEqual({}, self.facts())
        self.engine.countdown.start("free", 60)
        self.settings.update({"faceplate_playtime_enabled": False})
        self.assertEqual({}, self.facts())
        self.settings.update({"faceplate_playtime_enabled": True})
        self.assertEqual(1, self.facts()["minutes"])
        self.now += 60
        self.assertEqual({"state": "ended"}, self.facts())
        self.now += 61
        self.assertEqual({}, self.facts())

    def test_engine_facts_and_settings_status_expose_timer_without_changing_routing(self):
        self.engine.countdown.start("free", 300)
        preferences = self.engine.faceplate_preferences.read()
        facts = self.engine._faceplate_artwork_dashboard_facts(self.settings.all(), False)
        self.assertEqual("urgent", facts["countdown"]["urgency"])
        self.assertEqual(preferences, self.engine.faceplate_preferences.read())
        self.assertTrue(self.engine.status()["faceplate_playtime_enabled"])
        self.assertTrue(SettingsStore(self.settings.path).all()["faceplate_playtime_enabled"])

    def test_hidden_battery_session_and_forecast_never_invalidate_timer_facts(self):
        self.engine.countdown.start("free", 1440)
        self.settings.update({"faceplate_dashboard_bottom_mode": "controllers"})
        with patch.object(self.engine.controllers, "faceplate_batteries") as batteries:
            first = self.engine._faceplate_artwork_dashboard_facts(self.settings.all(), True)
            self.assertNotIn("controllers", first)
            self.assertEqual("countdown", first["bottom_mode"])
            batteries.assert_not_called()
            self.now += 20
            second = self.engine._faceplate_artwork_dashboard_facts(self.settings.all(), True)
            self.assertEqual(first, second)

    def test_real_reconcile_only_queues_one_update_per_timer_minute_and_restores_weather(self):
        self.settings.update({"faceplate_lab_enabled": True})
        self.engine.faceplate_preferences.update(home_scene="weather")
        self.engine.countdown.start("free", 1440)
        weather = dict(condition="rain", variant=0, temperature_c=12, unit="celsius",
                       phase="night", now=INSTANT, sunrise="2026-10-12T07:00:00+02:00",
                       sunset="2026-10-12T19:00:00+02:00", signature="stable-weather")
        with patch.object(self.engine, "_faceplate_continuity", return_value=("", False)), \
                patch.object(self.engine.weather, "configure"), \
                patch.object(self.engine, "_faceplate_weather_payload", return_value=(weather, {}, "")), \
                patch.object(self.engine, "_write_faceplate_runtime_status"), \
                patch.object(self.engine.faceplate_worker, "submit", return_value=1) as submit:
            for second in range(60):
                self.now = 100 + second
                self.engine._reconcile_faceplate()
            self.assertEqual(1, submit.call_count)
            self.assertEqual(24, submit.call_args.args[1]["countdown"]["minutes"])
            self.now = 160
            self.engine._reconcile_faceplate()
            self.assertEqual(2, submit.call_count)
            self.assertEqual(23, submit.call_args.args[1]["countdown"]["minutes"])
            self.engine.stop_free_timer()
            self.engine._reconcile_faceplate()
            self.assertEqual(3, submit.call_count)
            self.assertEqual({}, submit.call_args.args[1]["countdown"])

    def test_successful_scene_handler_records_real_completion_ack_not_queue_time(self):
        self.engine.countdown.start("free", 1)
        self.now += 1
        self.facts()
        completion = self.engine._faceplate_timer_end["id"]
        ticket = self.engine.faceplate_router.reconcile(
            game_running=False, content_key="timer-ended", reason="test")
        self.now += 21
        with patch("signalbar.backend.engine.time.monotonic", return_value=self.now), \
                patch.object(self.engine, "_render_faceplate_scene", return_value=(b"GIF89a", {"signature": "end"})), \
                patch.object(self.engine.faceplate, "synchronize_scene", return_value={"synchronized": True}), \
                patch.object(self.engine, "_write_faceplate_runtime_status"):
            self.engine._handle_faceplate_scene({
                "payload": {"kind": "weather", "ticket": ticket},
                "metadata": {"timer_completion_id": completion},
            })
        self.assertEqual(self.now, self.engine._faceplate_timer_end["ack_at"])
