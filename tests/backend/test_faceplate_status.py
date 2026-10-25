"""Truthful Steam status and compact Faceplate rail contracts."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.faceplate.artwork_dashboard import (
    build_artwork_dashboard, quantize_battery,
)
from signalbar.faceplate.scenes import WIDTH, render_dashboard_frame
from signalbar.faceplate.status import FaceplateSteamState
from signalbar.faceplate.v3_scenes import V3_THEME, build_v3_dashboard_snapshot
from signalbar.settings import SettingsStore


FRAME_BYTES = 64 * 54 * 3


class _Coordinator:
    def configure(self, _enabled, _brightness):
        pass

    def status(self):
        return {"available": False, "port": "", "busy": False, "phase": "test"}


def crop(frame, left, top, right, bottom):
    output = bytearray()
    for y in range(top, bottom):
        start = (y * WIDTH + left) * 3
        output.extend(frame[start:start + (right - left) * 3])
    return bytes(output)


class FaceplateStatusTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.state = FaceplateSteamState(
            clock=lambda: self.now, heartbeat_timeout=8, recent_event_seconds=60,
        )

    def test_recording_is_unknown_until_a_real_callback_and_never_revives_from_heartbeat(self):
        self.assertEqual("unknown", self.state.snapshot().recording)
        self.state.heartbeat()
        self.assertEqual("unknown", self.state.snapshot().recording)
        self.assertTrue(self.state.observe_event("record-start"))
        self.assertEqual("active", self.state.snapshot().recording)
        self.assertFalse(self.state.observe_event("record-start"))
        self.assertEqual(1, self.state.snapshot().recording_sequence)

        self.now += 9
        stale = self.state.snapshot()
        self.assertEqual("unknown", stale.recording)
        self.assertFalse(stale.observer_fresh)
        self.state.heartbeat()
        self.assertEqual("unknown", self.state.snapshot().recording)

    def test_only_authoritative_event_kind_is_exposed_without_a_fake_count(self):
        self.state.observe_event("notification")
        snapshot = self.state.snapshot()
        self.assertEqual("notification", snapshot.recent_event)
        self.assertNotIn("count", snapshot.render_payload(snapshot.recent_event))
        self.now += 61
        self.assertEqual("", self.state.snapshot().recent_event)

    def test_integrated_dashboard_rail_prioritizes_rec_and_hides_unknown(self):
        instant = datetime(2026, 10, 9, 12, 34, tzinfo=timezone.utc)
        sunrise = instant.replace(hour=7, minute=30)
        sunset = instant.replace(hour=19, minute=30)
        unknown = render_dashboard_frame(
            instant, "clear_day", 0, 18, "celsius", sunrise, sunset,
            status={"recording": "unknown"}, context="SUNSET 19:30",
        )
        active = render_dashboard_frame(
            instant, "clear_day", 0, 18, "celsius", sunrise, sunset,
            status={"recording": "active", "recording_sequence": 1},
            context="SUNSET 19:30",
        )
        self.assertNotEqual(crop(unknown, 0, 45, 64, 54), crop(active, 0, 45, 64, 54))
        self.assertIn(bytes((238, 50, 68)), crop(active, 0, 45, 20, 54))

    def test_v3_removes_decorative_rec_count_and_battery(self):
        instant = datetime(2026, 10, 9, 21, 48, tzinfo=timezone.utc)
        result = build_v3_dashboard_snapshot(
            V3_THEME, instant, "clear_night", 0, 12, "celsius",
            instant.replace(hour=7), instant.replace(hour=19),
            status={"recording": "unknown"}, battery=None,
        )
        bottom = crop(result.frames[0], 0, 45, 64, 54)
        colours = {bottom[index:index + 3] for index in range(0, len(bottom), 3)}
        self.assertIn(bytes((2, 5, 14)), colours)
        self.assertIn(bytes((171, 218, 255)), colours)
        self.assertNotIn(bytes((238, 50, 68)), colours)
        self.assertNotIn(bytes((80, 236, 142)), colours)

    def test_recent_events_use_three_distinct_pictograms_without_moving_battery(self):
        instant = datetime(2026, 10, 9, 12, 34, tzinfo=timezone.utc)
        sunrise = instant.replace(hour=7, minute=30)
        sunset = instant.replace(hour=19, minute=30)
        battery = {"level": 2, "percent": 55, "charging": False}
        rails = {}
        for sequence, kind in enumerate(("notification", "achievement", "screenshot"), 1):
            frame = render_dashboard_frame(
                instant, "clear_day", 0, 18, "celsius", sunrise, sunset,
                status={
                    "recording": "inactive", "recent_event": kind,
                    "event_sequence": sequence,
                }, battery=battery,
            )
            rails[kind] = crop(frame, 0, 45, 64, 54)
        self.assertEqual(3, len(set(rails.values())))
        right = {kind: crop(rail, 43, 0, 64, 9) for kind, rail in rails.items()}
        self.assertEqual(1, len(set(right.values())))

    def test_v3_clock_is_dominant_and_temperature_keeps_its_unit(self):
        instant = datetime(2026, 10, 9, 21, 48, tzinfo=timezone.utc)
        result = build_v3_dashboard_snapshot(
            V3_THEME, instant, "clear_night", 0, 12, "celsius",
            instant.replace(hour=7), instant.replace(hour=19),
        )
        frame = result.frames[0]
        ivory = (244, 231, 199)
        clock_x = []
        for y in range(0, 18):
            for x in range(64):
                offset = (y * 64 + x) * 3
                if tuple(frame[offset:offset + 3]) == ivory:
                    clock_x.append(x)
        self.assertGreaterEqual(max(clock_x) - min(clock_x), 50)
        self.assertIn(bytes((207, 216, 225)), crop(frame, 42, 29, 64, 38))

    def test_artwork_dashboard_keeps_its_compact_bottom_row_stable(self):
        backgrounds = (
            bytes((12, 60, 130)) * (64 * 54),
            bytes((150, 35, 70)) * (64 * 54),
        )
        result = build_artwork_dashboard(
            backgrounds, "2026-10-09T21:48:00+02:00", 102,
            quantize_battery(66), status={
                "recording": "active", "recording_sequence": 2,
            },
        )
        rails = [crop(frame, 0, 45, 64, 54) for frame in result.frames]
        self.assertEqual(rails[0], rails[1])
        # Artwork Dashboard deliberately has no giant notification/recording
        # badge. Steam recording still owns the light-bar event channel; the
        # 64 x 54 artwork keeps its selected compact information row.
        self.assertNotIn(bytes((238, 50, 68)), rails[0])
        self.assertIn(bytes((66, 220, 255)), rails[0])
        self.assertEqual(len(result.frames[0]), FRAME_BYTES)

    def test_notification_waits_for_a_natural_dashboard_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True, "events_enabled": True,
                             "faceplate_dashboard_show_clock": True})
            engine = Engine(
                settings, str(Path(folder) / "artwork.json"), faceplate=_Coordinator(),
            )
            engine.faceplate_preferences.update(home_scene="dashboard")
            weather = {
                "condition": "clear_day", "variant": 0,
                "temperature_c": 18, "unit": "celsius", "phase": "day",
                "city": "Paris", "now": "2026-10-09T12:34:10+00:00",
                "sunrise": "2026-10-09T07:00:00+00:00",
                "sunset": "2026-10-09T19:00:00+00:00",
                "precipitation_probability": 0, "signature": "weather-key",
            }
            submitted = []
            engine.faceplate_worker.submit = lambda _name, payload, _metadata: submitted.append(payload) or len(submitted)
            engine.faceplate_worker.status = lambda: {
                "busy": False, "queued": False, "ack_ema_ms": 0,
                "handler_ema_ms": 0, "last_rejection": "",
            }
            with patch.object(
                    engine, "_faceplate_weather_payload",
                    side_effect=lambda *_args: (dict(weather), {}, "")):
                engine._reconcile_faceplate("initial")
                self.assertEqual("", submitted[-1]["status"]["recent_event"])
                engine.trigger_event("notification")
                engine._reconcile_faceplate("periodic")
                self.assertEqual(1, len(submitted))

                weather["now"] = "2026-10-09T12:35:10+00:00"
                engine._reconcile_faceplate("periodic")
                self.assertEqual(2, len(submitted))
                self.assertEqual(
                    "notification", submitted[-1]["status"]["recent_event"],
                )


if __name__ == "__main__":
    unittest.main()
