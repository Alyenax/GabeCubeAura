"""Lab 5 faceplate framing, payload economy and shared-cadence contracts."""

import json
import hashlib
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from signalbar.faceplate import protocol
from signalbar.faceplate.flash import FlashWearProtection
from signalbar.faceplate.coordinator import (
    FaceplateCoordinator, encode_frame, safe_brightness, validate_gif,
)
from signalbar.faceplate.service import FaceplateWorker
from signalbar.faceplate.transport import (
    PROFILE_VENDOR, Link, LinkError, TransferCancelled, gif_end_timeout,
    port_owner_details,
)
from signalbar.backend import Engine
from signalbar.models import ProviderOutput
from signalbar.providers.weather import WeatherProvider, weather_frame
from signalbar.settings import SettingsStore
from signalbar.settings.store import DEFAULTS


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "assets" / "faceplate"


class FakeLink:
    def __init__(self, record, wrote, port=None, log=None, fail_power_cycle=False,
                 power_on_sent_at=None, transfer_timings=None):
        self.record = record
        self.wrote = wrote
        self.port = port
        self.log = log
        self.fail_power_cycle = fail_power_cycle
        self.power_on_sent_at = power_on_sent_at
        self.last_command_sent_at = None
        self.last_command_first_sent_at = None
        self.last_transfer_timings = dict(transfer_timings or {})

    def __enter__(self):
        self.record.append(("open",))
        return self

    def __exit__(self, *_):
        self.record.append(("close",))

    def command(self, data, timeout=1.0, retries=3):
        self.record.append(("command", data, timeout, retries))
        if self.fail_power_cycle and data == protocol.power(False):
            raise LinkError("power command failed")
        if data == protocol.power(True) and self.power_on_sent_at is not None:
            self.last_command_sent_at = self.power_on_sent_at
            self.last_command_first_sent_at = self.power_on_sent_at

    def write(self, data):
        self.record.append(("write", data))

    def send_gif(self, data, cancelled=None):
        self.record.append(("gif", data))
        return self.wrote


class FailingGifLink(FakeLink):
    def send_gif(self, data, cancelled=None):
        self.record.append(("gif", data))
        self.last_transfer_timings = {"begin_ack_ms": 321, "total_ms": 654}
        raise LinkError("simulated commit failure")


class CancelledGifLink(FakeLink):
    def send_gif(self, data, cancelled=None):
        self.record.append(("gif", data))
        self.last_transfer_timings = {"total_ms": 42, "cancelled": True}
        raise TransferCancelled("superseded")


class FakeCoordinator:
    def __init__(self, started_at):
        self.started_at = started_at
        self.configured = []
        self.calls = []
        self.artwork_calls = []
        self.scene_calls = []
        self.power_calls = []
        self.power_results = []

    def configure(self, enabled, brightness):
        self.configured.append((enabled, brightness))

    def synchronize_weather(self, condition, variant, loop_seconds):
        self.calls.append((condition, variant, loop_seconds))
        return {"attempted": True, "wrote": True, "synchronized": True,
                "started_at": self.started_at, "phase_seconds": 0.0,
                "frame_step_seconds": 0.1}

    def supports(self, condition, variant):
        return condition == "rain" and variant in (0, 1)

    def synchronize_artwork(self, appid, source="hero"):
        self.artwork_calls.append((appid, source))
        return {"attempted": True, "wrote": True, "found": True, "synchronized": True, "appid": appid}

    def synchronize_scene(self, data, scene, signature, peak_load=.5, reason="scene",
                          cancelled=None):
        self.scene_calls.append((scene, signature, reason, bytes(data[:6])))
        return {"attempted": True, "wrote": True, "synchronized": True,
                "scene": scene, "signature": signature}

    def status(self):
        return {}

    def set_power(self, enabled, reason="manual", lock_timeout=None):
        self.power_calls.append((bool(enabled), str(reason), lock_timeout))
        ok = self.power_results.pop(0) if self.power_results else True
        return {"ok": ok, "powered": bool(enabled) if ok else None,
                "error": "" if ok else "simulated communication failure"}


class StaticFirstSteamGridDB:
    def __init__(self):
        self.selected_calls = []

    def selected(self, appid):
        self.selected_calls.append(appid)
        return None

    def automatic(self, _appid):
        raise AssertionError("network compilation must not run before the static frame")


class FakeBackgroundPreparation:
    def __init__(self):
        self.calls = []
        self.stopped = False

    def preference(self):
        return "animated_any"

    def prepare_async(self, appid, callback):
        raise AssertionError("game launch must never prepare SteamGridDB artwork")

class FakeTwoStageCoordinator(FakeCoordinator):
    def __init__(self, started_at):
        super().__init__(started_at)
        self.steamgriddb = FakeBackgroundPreparation()

    def synchronize_artwork(self, appid, source="hero"):
        self.artwork_calls.append((appid, source))
        return {
            "attempted": True, "wrote": True, "found": True, "synchronized": True, "appid": appid,
            "selected_cached": False, "selected_animated": False,
            "selected_square": False,
        }


class FakeDashboardLibrary:
    def __init__(self):
        self.frame = bytes((24, 52, 96)) * (64 * 54)
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "artwork-dashboard.rgb"
        self.artwork_root = Path(self.directory.name)
        self.path.write_bytes(self.frame)
        self.sha256 = hashlib.sha256(self.frame).hexdigest()

    def selected_dashboard_manifest(self, appid):
        return {
            "appid": appid, "dashboard_pack_frames": 1,
            "dashboard_pack_sha256": self.sha256,
        } if appid == 620 else {}

    def selected_dashboard_pack_reference(self, appid):
        if appid != 620:
            return None
        return ({
            "appid": appid, "dashboard_treatment": "cinema",
            "dashboard_show_clock": True, "dashboard_clock_size": "compact",
            "dashboard_show_status_rail": True,
            "dashboard_show_session": True, "dashboard_show_battery": False,
            "dashboard_pack_frames": 1,
            "dashboard_pack_sha256": self.sha256, "frames": 1,
        }, self.path)

    def selected_dashboard_pack(self, appid):
        if appid != 620:
            return None
        return (self.frame,), {
            "appid": appid, "dashboard_treatment": "cinema",
            "dashboard_show_clock": True, "dashboard_clock_size": "compact",
            "dashboard_show_status_rail": True,
            "dashboard_show_session": True, "dashboard_show_battery": False,
            "dashboard_pack_sha256": self.sha256, "frames": 1,
        }, Path("artwork-dashboard.rgb")


class FakeDashboardCoordinator(FakeCoordinator):
    def __init__(self, started_at):
        super().__init__(started_at)
        self.steamgriddb = FakeDashboardLibrary()


class FaceplateTests(unittest.TestCase):
    def setUp(self):
        # Isolate protocol/timing fixtures from each other's global budgets.
        # Dedicated protection tests exercise the shared gate with fake clocks.
        factory = lambda path=None, **_: FlashWearProtection(path)
        self.guard_patch = patch("signalbar.faceplate.coordinator.FlashWearProtection", factory)
        self.guard_patch.start()
        self.addCleanup(self.guard_patch.stop)
        self.default_patch = patch("signalbar.faceplate.transport.default_manager", side_effect=lambda: FlashWearProtection())
        self.default_patch.start()
        self.addCleanup(self.default_patch.stop)

    def test_home_dashboard_can_use_a_prepared_game_background(self):
        faceplate = FakeDashboardCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({
                "faceplate_lab_enabled": True,
                "faceplate_dashboard_home_appid": 620,
                "faceplate_dashboard_home_source": "artwork",
            })
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            generation = engine._reconcile_faceplate("home-game-art", force=True)
            deadline = time.monotonic() + 2.0
            while not faceplate.scene_calls and time.monotonic() < deadline:
                time.sleep(0.01)
            engine.stop()
        self.assertGreater(generation, 0)
        self.assertEqual("artwork-dashboard", faceplate.scene_calls[0][0])

    def test_saved_home_artwork_uses_global_clock_instead_of_legacy_manifest(self):
        faceplate = FakeDashboardCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True,
                             "faceplate_dashboard_home_appid": 620,
                             "faceplate_dashboard_home_source": "artwork"})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            self.addCleanup(engine.stop)
            rendered = []

            def render(payload, ticket):
                rendered.append(dict(payload))
                return b"GIF89a", {"signature": ticket.content_key}

            with patch.object(engine, "_render_faceplate_scene", side_effect=render):
                for clock in (False, True, False):
                    before = len(rendered)
                    settings.update({"faceplate_dashboard_show_clock": clock})
                    engine._reconcile_faceplate("global-home-clock", force=True)
                    deadline = time.monotonic() + 2.0
                    while len(rendered) == before and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertGreater(len(rendered), before)
                    self.assertEqual(clock, rendered[-1]["dashboard_show_clock"])
                    self.assertTrue(rendered[-1]["show_weather_notch"])
                    self.assertEqual(faceplate.steamgriddb.sha256,
                                     rendered[-1]["dashboard_pack_sha256"])
            engine.stop()

    def test_weather_dashboard_ignores_but_keeps_remembered_artwork(self):
        faceplate = FakeDashboardCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({
                "faceplate_lab_enabled": True,
                "faceplate_dashboard_home_appid": 620,
                "faceplate_dashboard_home_source": "weather",
                "weather_display": "off", "weather_location": {
                    "name": "Paris", "country": "France",
                    "latitude": 48.8566, "longitude": 2.3522,
                },
            })
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.weather._location = dict(settings.all()["weather_location"])
            engine.weather._sample = {
                "condition": "cloud_night", "weather_code": 3, "is_day": False,
                "temperature_c": 9.0, "observed_at": "2026-10-09T22:00",
                "sunrise_at": "2026-10-09T07:30", "sunset_at": "2026-10-09T19:30",
                "next_solar_transition_at": "2026-10-10T07:30",
                "precipitation_probability": 20, "utc_offset_seconds": 7200,
            }
            engine.weather._fetched_at = time.monotonic()
            generation = engine._reconcile_faceplate("home-realistic", force=True)
            deadline = time.monotonic() + 2.0
            while not faceplate.scene_calls and time.monotonic() < deadline:
                time.sleep(0.01)
            engine.stop()
        self.assertGreater(generation, 0)
        self.assertEqual("dashboard", faceplate.scene_calls[0][0])
        self.assertEqual(620, settings.all()["faceplate_dashboard_home_appid"])

    def test_protocol_matches_vendor_capture_and_chunks_round_trip(self):
        expected = bytes.fromhex("445901040008000004A46CEAA0642CF6")
        self.assertEqual(protocol.crc16_kermit(expected[:-2]), 0x2CF6)
        self.assertEqual(protocol.frame(1, 4, expected[6:-2]), expected)
        data = bytes(range(256)) * 5
        chunks = list(protocol.gif_chunks(data))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(b"".join(chunk[8:-2] for chunk in chunks), data)
        self.assertEqual([int.from_bytes(chunk[6:8], "big") for chunk in chunks], [0, 1, 2])
        factory = protocol.factory_test(0)
        self.assertEqual(factory[:6], bytes.fromhex("445901F00001"))
        self.assertEqual(factory[6], 0)
        self.assertEqual(
            protocol.crc16_kermit(factory[:-2]),
            int.from_bytes(factory[-2:], "big"),
        )

    def test_protocol_parser_recovers_after_junk_and_bad_crc(self):
        good = protocol.frame(1, 2, b"\x00")
        bad = bytearray(protocol.frame(1, 1, b"\x00"))
        bad[-1] ^= 0xFF
        buffer = bytearray(b"\x00\xff" + bytes(bad) + good + good[:4])
        replies, junk = protocol.parse(buffer)
        self.assertTrue(junk)
        self.assertEqual([(item.kind, item.command, item.status) for item in replies], [(1, 2, 0)])
        self.assertEqual(bytes(buffer), good[:4])

    def test_transport_baseline_omits_f0_and_paces_chunks(self):
        link = Link(port="/dev/null")
        commands = []

        def command(data, timeout=1.0, retries=3):
            commands.append((data[2], data[3], data[6:-2], timeout, retries))
            return protocol.Reply(data[2], data[3], b"\x01")

        link.command = command
        data = bytes(range(256)) * 4
        with patch("signalbar.faceplate.transport.time.sleep") as sleeper:
            self.assertTrue(link.send_gif(data))
        self.assertEqual(commands[0][1], protocol.CMD_GIF_BEGIN)
        self.assertEqual([item[1] for item in commands[1:-1]], [protocol.CMD_GIF_CHUNK] * 3)
        self.assertEqual(commands[-1][1], protocol.CMD_GIF_END)
        self.assertEqual(sleeper.call_count, 3)
        self.assertEqual(link.last_transfer_timings["chunks"], 3)
        self.assertEqual(link.last_transfer_timings["active_profile"], "baseline")
        self.assertEqual(link.last_transfer_timings["attempt_profiles"], ["baseline"])
        self.assertFalse(link.last_transfer_timings["already_stored"])

    def test_vendor_f0_is_write_only_and_never_awaits_an_ack(self):
        link = Link(port="/dev/null", transport_profile=PROFILE_VENDOR)
        writes = []
        commands = []
        link.write = writes.append

        def command(data, timeout=1.0, retries=3):
            commands.append((data[3], timeout, retries))
            return protocol.Reply(data[2], data[3], b"\x01")

        link.command = command
        with patch("signalbar.faceplate.transport.time.sleep") as sleeper:
            self.assertTrue(link.send_gif(b"small gif"))
        self.assertEqual(writes, [protocol.factory_test(0)])
        self.assertNotIn(protocol.CMD_FACTORY_TEST, [item[0] for item in commands])
        self.assertEqual(commands[0][0], protocol.CMD_GIF_BEGIN)
        self.assertEqual(link.last_transfer_timings["active_profile"], "vendor")
        self.assertGreaterEqual(sleeper.call_count, 2)

    def test_vendor_failure_falls_back_once_to_baseline(self):
        link = Link(port="/dev/null", transport_profile=PROFILE_VENDOR)
        writes = []
        begins = 0
        link.write = writes.append

        def command(data, timeout=1.0, retries=3):
            nonlocal begins
            if data[3] == protocol.CMD_GIF_BEGIN:
                begins += 1
                if begins == 1:
                    raise LinkError("vendor begin failed")
            return protocol.Reply(data[2], data[3], b"\x01")

        link.command = command
        with patch("signalbar.faceplate.transport.time.sleep"):
            self.assertTrue(link.send_gif(b"small gif"))
        self.assertEqual(writes, [protocol.factory_test(0)])
        self.assertEqual(begins, 2)
        self.assertEqual(link.last_transfer_timings["transfer_retries"], 1)
        self.assertEqual(
            link.last_transfer_timings["attempt_profiles"], ["vendor", "baseline"],
        )
        self.assertEqual(link.last_transfer_timings["active_profile"], "baseline")

    def test_gif_end_timeout_grows_with_size_and_is_used(self):
        self.assertGreater(gif_end_timeout(96 * 1024), gif_end_timeout(1024))
        self.assertLessEqual(gif_end_timeout(20 * 1024 * 1024), 10.0)
        link = Link(port="/dev/null")
        end_calls = []

        def command(data, timeout=1.0, retries=3):
            if data[3] == protocol.CMD_GIF_END:
                end_calls.append((timeout, retries))
            return protocol.Reply(data[2], data[3], b"\x01")

        link.command = command
        data = b"x" * (60 * 1024)
        with patch("signalbar.faceplate.transport.time.sleep"):
            self.assertTrue(link.send_gif(data))
        self.assertEqual(end_calls, [(gif_end_timeout(len(data)), 1)])
        self.assertEqual(
            link.last_transfer_timings["end_timeout_seconds"], gif_end_timeout(len(data)),
        )

    def test_transport_crc_match_skips_body_but_confirms_stored_display(self):
        link = Link(port="/dev/null")
        commands = []

        def command(data, timeout=1.0, retries=3):
            commands.append(data[3])
            status = 0x02 if data[3] == protocol.CMD_GIF_BEGIN else 0x01
            return protocol.Reply(data[2], data[3], bytes((status,)))

        link.command = command
        with patch("signalbar.faceplate.transport.time.sleep"):
            self.assertFalse(link.send_gif(b"GIF89a-test"))
        self.assertEqual(commands, [protocol.CMD_GIF_BEGIN])
        self.assertTrue(link.last_transfer_timings["already_stored"])

    def test_transport_exposes_begin_and_end_ack_durations(self):
        link = Link(port="/dev/null")

        def command(data, timeout=1.0, retries=3):
            link.last_command_ack_ms = (
                37 if data[3] == protocol.CMD_GIF_BEGIN else 91
            )
            return protocol.Reply(data[2], data[3], b"\x01")

        link.command = command
        with patch("signalbar.faceplate.transport.time.sleep"):
            self.assertTrue(link.send_gif(b"GIF89a-test"))
        self.assertEqual(link.last_transfer_timings["begin_ack_ms"], 37)
        self.assertEqual(link.last_transfer_timings["end_ack_ms"], 91)

    def test_transport_cancels_a_superseded_payload_between_chunks(self):
        link = Link(port="/dev/null")
        commands = []

        def command(data, timeout=1.0, retries=3):
            commands.append(data[3])
            return protocol.Reply(data[2], data[3], b"\x01")

        link.command = command
        cancelled = lambda: commands.count(protocol.CMD_GIF_CHUNK) >= 1
        with patch("signalbar.faceplate.transport.time.sleep"), self.assertRaises(
            TransferCancelled,
        ):
            link.send_gif(bytes(range(256)) * 8, cancelled=cancelled)
        self.assertEqual(commands[0], protocol.CMD_GIF_BEGIN)
        self.assertEqual(commands.count(protocol.CMD_GIF_CHUNK), 1)
        self.assertNotIn(protocol.CMD_GIF_END, commands)
        self.assertTrue(link.last_transfer_timings["cancelled"])

    def test_coordinator_reports_route_cancellation_without_a_false_failure(self):
        record = []
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: CancelledGifLink(
                    record, False, **kwargs,
                ),
                port_finder=lambda: "/dev/ttyUSB0",
                identity_reader=lambda _port: "usb-a",
            )
            coordinator.configure(True, 100)
            data = (ASSET_ROOT / "weather/rain-bluewater-64x54.gif").read_bytes()
            result = coordinator.synchronize_scene(
                data, "weather", "new-route", cancelled=lambda: False,
            )
            status = coordinator.status()
        self.assertTrue(result["superseded"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(status["phase"], "superseded")
        self.assertEqual(status["error"], "")
        self.assertEqual(status["upload_observability"]["session"]["failed"], 0)

    def test_worker_is_optional_and_disabled_submit_is_non_blocking(self):
        calls = []
        worker = FaceplateWorker(calls.append)
        started = time.monotonic()
        self.assertEqual(worker.submit("rain", b"gif"), 0)
        self.assertLess(time.monotonic() - started, 0.1)
        self.assertEqual(calls, [])
        self.assertFalse(worker.status()["running"])
        self.assertEqual(worker.status()["capabilities"]["configured_profile"], "baseline")

    def test_worker_latest_pending_scene_wins(self):
        entered = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        scenes = []

        def handler(request):
            scenes.append(request["scene"])
            if request["scene"] == "first":
                entered.set()
                release.wait(1.0)
            if request["scene"] == "third":
                completed.set()
            return {"ok": True}

        worker = FaceplateWorker(handler, enabled=True)
        try:
            self.assertEqual(worker.submit("first", b"one"), 1)
            self.assertTrue(entered.wait(1.0))
            self.assertEqual(worker.submit("second", b"two"), 2)
            self.assertEqual(worker.submit("third", b"three"), 3)
            release.set()
            self.assertTrue(completed.wait(1.0))
            deadline = time.monotonic() + 1.0
            while worker.status()["busy"] and time.monotonic() < deadline:
                time.sleep(0.005)
            status = worker.status()
        finally:
            release.set()
            worker.stop()
        self.assertEqual(scenes, ["first", "third"])
        self.assertEqual(status["dropped"], 1)
        self.assertEqual(status["completed"], 2)
        self.assertEqual(status["completed_generation"], 3)
        self.assertEqual(status["last_scene"], "third")
        self.assertEqual(status["last_error"], "")

    def test_worker_contains_handler_failure_and_accepts_the_next_scene(self):
        completed = threading.Event()

        def handler(request):
            if request["scene"] == "bad":
                raise LinkError("serial unavailable")
            completed.set()
            return {"ok": True}

        worker = FaceplateWorker(handler, enabled=True)
        try:
            worker.submit("bad", b"one")
            deadline = time.monotonic() + 1.0
            while worker.status()["completed"] < 1 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertIn("serial unavailable", worker.status()["last_error"])
            worker.submit("good", b"two")
            self.assertTrue(completed.wait(1.0))
        finally:
            worker.stop()
        self.assertEqual(worker.status()["completed"], 2)

    def test_worker_rejects_retired_performance_even_with_legacy_capabilities(self):
        worker = FaceplateWorker(lambda _request: {"ok": True}, enabled=True)
        try:
            worker.set_capabilities({
                "performance_live_updates": True,
                "performance_min_upload_interval_seconds": 1,
            })
            self.assertGreater(worker.submit(
                "dashboard:hour-pack", b"gif",
                {"requires_long_gif_delays": True},
            ), 0)
            self.assertEqual(worker.submit(
                "performance:live", b"gif",
                {"live": True, "upload_interval_seconds": 1},
            ), 0)
            status = worker.status()
        finally:
            worker.stop()
        self.assertEqual(status["rejected"], 1)
        self.assertTrue(status["capabilities"]["long_gif_delays"])
        self.assertFalse(status["capabilities"]["performance_live_updates"])
        self.assertEqual(
            status["capabilities"]["performance_min_upload_interval_seconds"], 1.0,
        )
        self.assertEqual(
            status["capabilities"]["performance_policy"], "removed-from-faceplate",
        )

    def test_worker_accepts_each_changed_artwork_without_a_backlog(self):
        now = [100.0]
        handled = threading.Event()
        worker = FaceplateWorker(
            lambda _request: handled.set(), enabled=True, monotonic=lambda: now[0],
        )
        try:
            accepted = worker.submit(
                "artwork:snapshot", b"gif",
                {"upload_interval_seconds": 60},
            )
            self.assertGreater(accepted, 0)
            self.assertTrue(handled.wait(1.0))
            self.assertGreater(worker.submit(
                "artwork:snapshot", b"gif",
                {"upload_interval_seconds": 1},
            ), accepted)
            now[0] += 1.0
            self.assertGreater(worker.submit(
                "artwork:snapshot", b"gif",
                {"upload_interval_seconds": 1},
            ), accepted)
        finally:
            worker.stop()

    def test_slow_artwork_ack_keeps_only_the_newest_of_one_hundred_samples(self):
        entered = threading.Event()
        release = threading.Event()
        latest_completed = threading.Event()
        handled = []

        def handler(request):
            handled.append(request["scene"])
            if request["scene"] == "artwork:0":
                entered.set()
                release.wait(1.0)
            if request["scene"] == "artwork:99":
                latest_completed.set()
            return {"ack_ms": 5000}

        worker = FaceplateWorker(handler, enabled=True)
        try:
            worker.submit("artwork:0", b"0", {
                "scene_class": "artwork", "upload_interval_seconds": 1,
            })
            self.assertTrue(entered.wait(1.0))
            for index in range(1, 100):
                worker.submit(f"artwork:{index}", str(index).encode(), {
                    "scene_class": "artwork", "upload_interval_seconds": 1,
                })
            status_while_slow = worker.status()
            self.assertTrue(status_while_slow["busy"])
            self.assertTrue(status_while_slow["queued"])
            self.assertFalse(worker.active_request["_cancelled"].is_set())
            release.set()
            self.assertTrue(latest_completed.wait(1.0))
            deadline = time.monotonic() + 1.0
            while worker.status()["busy"] and time.monotonic() < deadline:
                time.sleep(0.005)
            status = worker.status()
        finally:
            release.set()
            worker.stop()
        self.assertEqual(handled, ["artwork:0", "artwork:99"])
        self.assertEqual(status["completed"], 2)
        self.assertEqual(status["dropped"], 98)
        self.assertEqual(status["ack_ema_ms"], 5000)

    def test_worker_keeps_active_artwork_transfer_but_cancels_it_for_a_new_route(self):
        entered = threading.Event()
        release = threading.Event()
        weather_completed = threading.Event()
        cancelled = []
        handled = []

        def handler(request):
            handled.append(request["scene"])
            if request["scene"] == "artwork:first":
                entered.set()
                while not release.wait(0.005):
                    if request["_cancelled"].is_set():
                        cancelled.append(True)
                        break
            if request["scene"] == "weather:new":
                weather_completed.set()
            return {"ack_ms": 4000}

        worker = FaceplateWorker(handler, enabled=True)
        try:
            worker.submit("artwork:first", b"one", {
                "scene_class": "artwork", "upload_interval_seconds": 1,
            })
            self.assertTrue(entered.wait(1.0))
            worker.submit("artwork:latest", b"two", {
                "scene_class": "artwork", "upload_interval_seconds": 1,
            })
            self.assertFalse(worker.active_request["_cancelled"].is_set())
            worker.submit("weather:new", b"three", {"scene_class": "weather"})
            self.assertTrue(worker.active_request["_cancelled"].is_set())
            self.assertTrue(weather_completed.wait(1.0))
            deadline = time.monotonic() + 1.0
            while worker.status()["busy"] and time.monotonic() < deadline:
                time.sleep(0.005)
            status = worker.status()
        finally:
            release.set()
            worker.stop()
        self.assertEqual(handled, ["artwork:first", "weather:new"])
        self.assertEqual(cancelled, [True])
        self.assertEqual(status["dropped"], 1)
        self.assertEqual(status["superseded_active"], 1)
        self.assertEqual(status["ack_ema_ms"], 4000)

    def test_dashboard_target_uses_ack_lead_and_never_exceeds_ten_seconds(self):
        before = datetime(2026, 10, 8, 12, 34, 49, tzinfo=timezone.utc)
        target, lead = Engine._faceplate_dashboard_target(before, 0)
        self.assertEqual(target, before.replace(second=0))
        self.assertEqual(lead, 3.0)

        near_boundary = before.replace(second=54)
        target, lead = Engine._faceplate_dashboard_target(near_boundary, 5000)
        self.assertEqual(target, before.replace(second=0, minute=35))
        self.assertEqual(lead, 7.0)

        target, lead = Engine._faceplate_dashboard_target(
            before.replace(second=50), 20000,
        )
        self.assertEqual(target, before.replace(second=0, minute=35))
        self.assertEqual(lead, 10.0)

        regressed_candidate, _ = Engine._faceplate_dashboard_target(
            before.replace(second=51), 0,
        )
        self.assertEqual(regressed_candidate, before.replace(second=0))
        self.assertEqual(
            Engine._faceplate_dashboard_nonregressing(target, None), target,
        )
        self.assertEqual(
            Engine._faceplate_dashboard_nonregressing(
                regressed_candidate, target,
            ),
            target,
        )

    def test_dashboard_transitions_stay_monotone_and_within_ten_seconds_for_three_hours(self):
        minute = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        previous_target = minute
        ack_ema_ms = 0.0
        transitions = []
        for index in range(1, 181):
            boundary = minute + timedelta(minutes=index)
            source_minute = boundary - timedelta(minutes=1)
            selected_at = None
            selected_target = None
            for second in range(60):
                requested_at = source_minute.replace(second=second)
                candidate, _lead = Engine._faceplate_dashboard_target(
                    requested_at, ack_ema_ms,
                )
                candidate = Engine._faceplate_dashboard_nonregressing(
                    candidate, previous_target,
                )
                if candidate > previous_target:
                    selected_at, selected_target = requested_at, candidate
                    break
            self.assertIsNotNone(selected_at)
            ack_ms = 1000 if index % 2 else 5000
            committed_at = selected_at + timedelta(milliseconds=ack_ms)
            offset = (committed_at - boundary).total_seconds()
            self.assertLessEqual(abs(offset), 10.0)
            self.assertGreater(selected_target, previous_target)
            transitions.append((selected_target, offset))
            previous_target = selected_target
            ack_ema_ms = (
                ack_ms if not ack_ema_ms else ack_ema_ms * 0.7 + ack_ms * 0.3
            )
        self.assertEqual(len(transitions), 180)

    def test_shipped_rain_assets_are_faceplate_native_and_bounded(self):
        expected = {
            "rain-bluewater-64x54.gif": "7456652e37094b3b64451627622e526c683f910ebfc106d61cd01d6055065d3a",
            "rain-pearl-64x54.gif": "37abf0cada669d9ff7ba3c4a57f30722919d4cab822a54bb05176397c76102ab",
        }
        import hashlib
        for filename, digest in expected.items():
            data = (ASSET_ROOT / "weather" / filename).read_bytes()
            validate_gif(data)
            self.assertEqual(data[10], 0x87)
            self.assertLess(len(data), 96 * 1024)
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)

    def test_static_artwork_encoder_produces_a_native_gif(self):
        from io import BytesIO
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        rgb = bytes((20, 80, 220)) * (64 * 54)
        data = encode_frame(rgb)
        validate_gif(data)
        with Image.open(BytesIO(data)) as decoded:
            self.assertEqual(decoded.convert("RGB").tobytes(), rgb)
        self.assertLess(len(data), 16 * 1024)

    def test_rain_assets_allow_full_brightness_under_the_power_budget(self):
        self.assertEqual(safe_brightness(100, 0.2871), 100)
        self.assertEqual(safe_brightness(100, 0.2872), 100)
        self.assertEqual(safe_brightness(100, 1.0), 100)

    def test_port_owner_diagnostic_names_the_process_without_exposing_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            port = root / "ttyUSB0"
            port.touch()
            fd = root / "123" / "fd"
            fd.mkdir(parents=True)
            (fd / "7").symlink_to(port)
            (root / "123" / "cmdline").write_bytes(
                b"/home/deck/.local/bin/jsaux-matrix-daemon\0--secret\0",
            )
            owners = port_owner_details(str(port), str(root))
        self.assertEqual(owners, ["jsaux-matrix-daemon (PID 123)"])
        self.assertNotIn("secret", owners[0])

    def test_disabled_coordinator_never_opens_the_serial_link(self):
        opened = []
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: opened.append(kwargs),
            )
            result = coordinator.synchronize_weather("rain", 0, 8.0)
        self.assertFalse(result["attempted"])
        self.assertEqual(opened, [])

    def test_power_button_is_volatile_and_preserves_the_stored_gif(self):
        record = []
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(record, False, **kwargs),
                port_finder=lambda: "/dev/ttyUSB0",
            )
            result = coordinator.set_power(False, "test")
        self.assertTrue(result["ok"])
        self.assertFalse(result["powered"])
        self.assertIn(("command", protocol.power(False), 0.7, 2), record)
        self.assertFalse(any(event[0] == "gif" for event in record))
        self.assertEqual(coordinator.state["writes"], 0)

    def test_fresh_upload_uses_final_ack_as_epoch_and_counts_one_write(self):
        record = []
        monotonic = iter((100.0, 101.25))
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "state.json"
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, state_path,
                link_factory=lambda **kwargs: FakeLink(record, True, **kwargs),
                monotonic=lambda: next(monotonic), wall_clock=lambda: 5000.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
            )
            coordinator.configure(True, 31)
            result = coordinator.synchronize_weather("rain", 0, 8.0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertTrue(result["wrote"])
        self.assertTrue(result["synchronized"])
        self.assertEqual(result["started_at"], 101.25)
        self.assertEqual(result["phase_seconds"], 0.0)
        self.assertEqual(result["frame_step_seconds"], 0.1)
        self.assertEqual(state["writes"], 1)
        self.assertEqual(coordinator.writes_session, 1)
        brightness_at = record.index(("write", protocol.brightness(31)))
        gif_at = next(index for index, event in enumerate(record) if event[0] == "gif")
        self.assertLess(brightness_at, gif_at)
        self.assertIn("acknowledged", coordinator.detail.lower())

    def test_upload_journal_records_hash_crc_ack_and_write_counters(self):
        record = []
        times = iter((100.0, 100.25))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(
                    record, True, transfer_timings={
                        "begin_ack_ms": 84, "total_ms": 250,
                    }, **kwargs,
                ),
                monotonic=lambda: next(times, 100.25), wall_clock=lambda: 1791331200.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
            )
            coordinator.configure(True, 100)
            self.assertTrue(coordinator.synchronize_weather("rain", 0, 8.0)["wrote"])
            observed = coordinator.status()["upload_observability"]
            persisted = json.loads((Path(folder) / "state.json").read_text())
        event = observed["journal"][-1]
        self.assertEqual(event["reason"], "weather:rain:0")
        self.assertEqual(len(event["sha256"]), 64)
        self.assertEqual(len(event["crc32"]), 8)
        self.assertEqual(event["ack_ms"], 84)
        self.assertEqual(event["duration_ms"], 250)
        self.assertEqual(event["outcome"], "written")
        self.assertTrue(event["wrote"])
        self.assertEqual(observed["session"]["writes"], 1)
        self.assertEqual(observed["today_utc"]["writes"], 1)
        self.assertEqual(observed["total"]["writes"], 1)
        self.assertNotIn("logical_flash_equivalents", observed["estimate"])
        self.assertEqual(observed["estimate"]["confidence"], "physical-endurance-unknown")
        self.assertEqual(persisted["schema"], 2)

    def test_identical_and_failed_uploads_are_observed_without_counting_writes(self):
        times = iter((1.0, 1.1, 2.0, 2.2))
        links = iter((
            lambda **kwargs: FakeLink(
                [], False, transfer_timings={"begin_ack_ms": 42}, **kwargs,
            ),
            lambda **kwargs: FailingGifLink([], False, **kwargs),
        ))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: next(links)(**kwargs),
                monotonic=lambda: next(times, 2.2), wall_clock=lambda: 1791331200.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
                sleeper=lambda _seconds: None,
            )
            coordinator.configure(True, 100)
            identical = coordinator.synchronize_weather("rain", 0, 8.0)
            failed = coordinator.synchronize_weather("rain", 1, 8.0)
            observed = coordinator.status()["upload_observability"]
        self.assertFalse(identical["wrote"])
        self.assertIn("error", failed)
        self.assertEqual([item["outcome"] for item in observed["journal"]], [
            "identical", "failed",
        ])
        self.assertEqual(observed["session"]["attempts"], 2)
        self.assertEqual(observed["session"]["writes"], 0)
        self.assertEqual(observed["session"]["identical"], 1)
        self.assertEqual(observed["session"]["failed"], 1)
        self.assertEqual(observed["today_utc"]["writes"], 0)

    def test_upload_journal_is_bounded_and_old_state_is_migrated(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "state.json"
            state_path.write_text(json.dumps({
                "schema": 1, "writes": 7, "assets": {"old": {"asset": "rain"}},
            }))
            coordinator = FaceplateCoordinator(ASSET_ROOT, state_path, wall_clock=lambda: 0.0)
            for index in range(70):
                coordinator._record_upload(
                    reason=f"test:{index}", data=f"gif-{index}".encode(),
                    wrote=False, duration_ms=index, transfer={"begin_ack_ms": index},
                )
            observed = coordinator.status()["upload_observability"]
        self.assertEqual(coordinator.state["schema"], 2)
        self.assertEqual(coordinator.state["writes"], 7)
        self.assertIn("old", coordinator.state["assets"])
        self.assertEqual(len(observed["journal"]), 64)
        self.assertEqual(observed["journal"][0]["reason"], "test:6")
        self.assertEqual(observed["journal"][-1]["reason"], "test:69")
        self.assertEqual(observed["session"]["identical"], 70)

    def test_identical_asset_skips_flash_and_rejoins_known_session_phase(self):
        record = []
        times = iter((200.0, 200.2, 205.0, 205.1))
        wall = [7000.0]
        writes = iter((True, False))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(record, next(writes), **kwargs),
                monotonic=lambda: next(times), wall_clock=lambda: wall[0],
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
            )
            coordinator.configure(True, 25)
            first = coordinator.synchronize_weather("rain", 1, 8.0)
            wall[0] += 3.25
            second = coordinator.synchronize_weather("rain", 1, 8.0)
        self.assertTrue(first["wrote"])
        self.assertFalse(second["wrote"])
        self.assertTrue(second["synchronized"])
        self.assertAlmostEqual(second["phase_seconds"], 3.25)
        self.assertAlmostEqual(second["started_at"], 201.85)
        self.assertEqual(coordinator.writes_session, 1)
        self.assertEqual(coordinator.state["writes"], 1)
        self.assertIn("known session phase", coordinator.detail)

    def test_unknown_epoch_soft_resynchronizes_without_a_flash_write(self):
        record = []
        times = iter((10.0, 10.1))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(record, False, **kwargs),
                monotonic=lambda: next(times), wall_clock=lambda: 1000.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
                sleeper=lambda _seconds: None,
            )
            coordinator.configure(True, 25)
            result = coordinator.synchronize_weather("rain", 0, 8.0)
        self.assertFalse(result["wrote"])
        self.assertTrue(result["synchronized"])
        self.assertEqual(result["phase_seconds"], 0.0)
        self.assertEqual(coordinator.phase, "synchronized")
        self.assertIn("power-on transmit epoch", coordinator.detail)
        commands = [event[1] for event in record if event[0] == "command"]
        self.assertEqual(commands[-2:], [protocol.power(False), protocol.power(True)])

    def test_soft_restart_uses_power_on_transmit_not_delayed_ack_as_epoch(self):
        record = []
        times = iter((10.0, 12.0))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(
                    record, False, power_on_sent_at=10.25, **kwargs,
                ),
                monotonic=lambda: next(times), wall_clock=lambda: 1002.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
                sleeper=lambda _seconds: None,
            )
            coordinator.configure(True, 100)
            result = coordinator.synchronize_weather("rain", 0, 8.0)
        self.assertTrue(result["synchronized"])
        self.assertAlmostEqual(result["started_at"], 10.25)
        self.assertAlmostEqual(result["phase_seconds"], 1.75)
        self.assertEqual(coordinator.last_start_ack_ms, 1750)
        self.assertEqual(coordinator.known_epochs[next(iter(coordinator.known_epochs))]["epoch_wall"], 1000.25)

    def test_failed_soft_resynchronization_is_reported_as_phase_unknown(self):
        times = iter((10.0, 10.1))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(
                    [], False, fail_power_cycle=True, **kwargs,
                ),
                monotonic=lambda: next(times), wall_clock=lambda: 1000.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
                sleeper=lambda _seconds: None,
            )
            coordinator.configure(True, 25)
            result = coordinator.synchronize_weather("rain", 0, 8.0)
        self.assertFalse(result["wrote"])
        self.assertFalse(result["synchronized"])
        self.assertEqual(coordinator.phase, "phase-unknown")
        self.assertIn("unknown", coordinator.detail)

    def test_restart_does_not_trust_an_epoch_persisted_on_disk(self):
        times = iter((1.0, 1.1, 9.0, 9.1))
        wall = [1000.0]
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "state.json"
            first = FaceplateCoordinator(
                ASSET_ROOT, state_path,
                link_factory=lambda **kwargs: FakeLink([], True, **kwargs),
                monotonic=lambda: next(times), wall_clock=lambda: wall[0],
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
                sleeper=lambda _seconds: None,
            )
            first.configure(True, 25)
            self.assertTrue(first.synchronize_weather("rain", 0, 8.0)["synchronized"])
            wall[0] += 4.0
            restarted = FaceplateCoordinator(
                ASSET_ROOT, state_path,
                link_factory=lambda **kwargs: FakeLink([], False, **kwargs),
                monotonic=lambda: next(times), wall_clock=lambda: wall[0],
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
            )
            restarted.configure(True, 25)
            result = restarted.synchronize_weather("rain", 0, 8.0)
        self.assertFalse(result["wrote"])
        self.assertTrue(result["synchronized"])
        self.assertEqual(restarted.state["writes"], 1)
        self.assertEqual(restarted.phase, "synchronized")

    def test_usb_reconnection_invalidates_the_known_session_epoch(self):
        times = iter((1.0, 1.1, 2.0, 2.1))
        token = ["usb-a"]
        writes = iter((True, False))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink([], next(writes), **kwargs),
                monotonic=lambda: next(times), wall_clock=lambda: 1000.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: token[0],
                sleeper=lambda _seconds: None,
            )
            coordinator.configure(True, 25)
            self.assertTrue(coordinator.synchronize_weather("rain", 1, 8.0)["synchronized"])
            token[0] = "usb-b"
            result = coordinator.synchronize_weather("rain", 1, 8.0)
        self.assertFalse(result["wrote"])
        self.assertTrue(result["synchronized"])
        self.assertEqual(coordinator.phase, "synchronized")

    def test_weather_preview_can_join_an_existing_animation_epoch(self):
        now = [103.25]
        provider = WeatherProvider(clock=lambda: now[0])
        self.assertTrue(provider.preview("rain", 0, started_at=100.0))
        current, variant, elapsed, preview = provider._current(DEFAULTS, now[0])
        self.assertTrue(preview)
        self.assertEqual(current["condition"], "rain")
        self.assertEqual(variant, 0)
        self.assertAlmostEqual(elapsed, 3.25)
        expected = weather_frame("rain", 0, 3.25, DEFAULTS)
        self.assertEqual(provider._frame(current, variant, elapsed, DEFAULTS), expected)

    def test_linked_weather_preview_holds_the_bar_on_the_faceplate_gif_frame(self):
        now = [101.89]
        provider = WeatherProvider(clock=lambda: now[0])
        self.assertTrue(provider.preview(
            "rain", 0, started_at=100.0, frame_step_seconds=0.1,
        ))
        current, variant, elapsed, preview = provider._current(DEFAULTS, now[0])
        self.assertTrue(preview)
        self.assertEqual(current["condition"], "rain")
        self.assertEqual(variant, 0)
        self.assertAlmostEqual(elapsed, 1.8)
        self.assertEqual(
            provider._frame(current, variant, elapsed, DEFAULTS),
            weather_frame("rain", 0, 1.8, DEFAULTS),
        )

    def test_engine_routes_faceplate_ack_epoch_into_the_weather_provider(self):
        now = [103.25]
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True, "faceplate_brightness": 30})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.weather = WeatherProvider(clock=lambda: now[0])
            self.assertTrue(engine.preview_weather(
                "rain", 0, "weather-artwork-v2",
            ))
            deadline = time.monotonic() + 2
            while (engine.faceplate_worker.status()["busy"] or engine.faceplate_worker.status()["queued"]) and time.monotonic() < deadline:
                time.sleep(.005)
            current, variant, elapsed, preview = engine.weather._current(settings.all(), now[0])
            engine.stop()
        self.assertEqual(faceplate.configured, [(True, 30)])
        self.assertEqual(faceplate.calls, [])
        self.assertEqual(len(faceplate.scene_calls), 1)
        self.assertEqual(faceplate.scene_calls[0][0], "weather")
        self.assertEqual(
            faceplate.scene_calls[0][2],
            "weather-preview",
        )
        self.assertEqual(faceplate.scene_calls[0][3], b"GIF89a")
        self.assertTrue(preview)
        self.assertEqual(current["condition"], "rain")
        self.assertEqual(variant, 0)
        self.assertAlmostEqual(elapsed, 0.0)

    def test_faceplate_continuity_detects_ntp_without_confusing_suspend(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            hardware = {"available": True, "port": "/dev/ttyUSB0", "busy": False}
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=1000.0, monotonic_clock=100.0, hardware=hardware,
            ), ("", False))
            # Ordinary elapsed time advances both clocks together.
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=4600.0, monotonic_clock=3700.0, hardware=hardware,
            ), ("", False))
            # An NTP/manual correction changes wall time without matching monotonic time.
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=4630.0, monotonic_clock=3701.0, hardware=hardware,
            ), ("clock-discontinuity", False))
            engine.stop()

    def test_faceplate_continuity_reasserts_after_usb_reconnect_or_busy_owner(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            available = {"available": True, "port": "/dev/ttyUSB0", "busy": False}
            engine._faceplate_continuity(
                wall_clock=1000.0, monotonic_clock=100.0, hardware=available,
            )
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=1001.0, monotonic_clock=101.0,
                hardware={"available": False, "port": "", "busy": False},
            ), ("", True))
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=1002.0, monotonic_clock=102.0, hardware=available,
            ), ("faceplate-reconnected", True))
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=1003.0, monotonic_clock=103.0,
                hardware={**available, "busy": True},
            ), ("", True))
            self.assertEqual(engine._faceplate_continuity(
                wall_clock=1004.0, monotonic_clock=104.0, hardware=available,
            ), ("faceplate-reconnected", True))
            engine.stop()

    def test_weather_faceplate_route_is_independent_from_led_weather_display(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True, "weather_rain_variant": 1,
                             "weather_display": "off", "weather_location": {
                                 "name": "Paris", "country": "France",
                                 "latitude": 48.8566, "longitude": 2.3522,
                             }})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.weather._location = dict(settings.all()["weather_location"])
            engine.weather._sample = {
                "condition": "rain", "weather_code": 61, "is_day": True,
                "temperature_c": 12.4, "observed_at": "2026-10-07T12:00",
                "sunrise_at": "2026-10-07T07:30", "sunset_at": "2026-10-07T19:30",
                "next_solar_transition_at": "2026-10-07T19:30",
                "precipitation_probability": 80, "utc_offset_seconds": 7200,
            }
            engine.weather._fetched_at = time.monotonic()
            engine.faceplate_preferences.update(
                home_scene="weather", scene_kind="weather",
                scene_theme="weather-artwork-v2",
            )
            expected = engine.faceplate_weather_preview(
                "rain", 1, "weather-artwork-v2",
            )
            first = engine._reconcile_faceplate("test-weather", force=True)
            deadline = time.monotonic() + 3.0
            while not faceplate.scene_calls and time.monotonic() < deadline:
                time.sleep(0.01)
            engine.stop()
        self.assertGreater(first, 0)
        self.assertEqual(faceplate.calls, [])
        self.assertEqual(faceplate.scene_calls[0][0], "weather")
        self.assertEqual(faceplate.scene_calls[0][1], expected["signature"])
        self.assertEqual(faceplate.scene_calls[0][3], b"GIF89a")

    def test_suspend_cancels_scene_worker_and_resume_reasserts_panel_power(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            off = engine.suspend_faceplate("sleep")
            self.assertTrue(off["ok"])
            self.assertFalse(engine.faceplate_worker.status()["enabled"])
            on = engine.resume_faceplate()
            self.assertTrue(on["ok"])
            self.assertTrue(engine.faceplate_worker.status()["enabled"])
            engine.stop()
        self.assertEqual([False, True], [call[0] for call in faceplate.power_calls])

    def test_failed_resume_power_is_retried_without_user_intervention(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            faceplate.power_results = [False, False, False, True]
            result = engine.resume_faceplate()
            self.assertFalse(result["ok"])
            self.assertIs(engine._faceplate_power_target, True)
            engine._faceplate_power_retry_at = 0.0
            self.assertTrue(engine._service_faceplate_power_retry())
            self.assertIsNone(engine._faceplate_power_target)
            engine.stop()

    def test_weather_older_than_two_hours_becomes_clock_and_controller_dashboard(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({
                "faceplate_lab_enabled": True,
                "weather_location": {
                    "name": "Paris", "country": "France",
                    "latitude": 48.8566, "longitude": 2.3522,
                },
            })
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.weather._sample = {
                "condition": "rain", "weather_code": 61, "is_day": True,
                "temperature_c": 12.4, "observed_at": "2026-10-07T12:00",
                "sunrise_at": "2026-10-07T07:30", "sunset_at": "2026-10-07T19:30",
                "utc_offset_seconds": 7200,
            }
            engine.weather._fetched_at = time.monotonic() - 7201
            engine.controllers.faceplate_batteries = lambda _count: [
                {"percent": 84, "charging": False},
            ]
            facts = engine._faceplate_artwork_dashboard_facts(
                settings.all(), False,
            )
            engine.stop()
        self.assertEqual("controllers", facts["bottom_mode"])
        self.assertFalse(facts["show_weather_notch"])
        self.assertEqual("background-only", facts["weather_fallback_state"])
        self.assertEqual(85, facts["controllers"][0]["percent"])

    def test_game_change_automatically_queues_local_artwork(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.set_game(4358690, "Test Game", launch=True, source="Steam callback")
            deadline = time.monotonic() + 1.0
            while not faceplate.artwork_calls and time.monotonic() < deadline:
                time.sleep(0.01)
            engine.stop()
        self.assertEqual(faceplate.artwork_calls, [(4358690, "hero")])

    def test_game_change_never_starts_background_animation_preparation(self):
        faceplate = FakeTwoStageCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.set_game(620, "Portal 2", launch=True, source="Steam callback")
            deadline = time.monotonic() + 1.0
            while not faceplate.artwork_calls and time.monotonic() < deadline:
                time.sleep(0.01)
            engine.stop()
        self.assertEqual(faceplate.artwork_calls, [(620, "hero")])
        self.assertEqual(faceplate.steamgriddb.calls, [])

    def test_artwork_dashboard_without_studio_automatically_composes_local_artwork(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            self.addCleanup(engine.stop)
            engine.faceplate_preferences.update(game_scene="artwork-dashboard")
            threads = []

            def local(*args):
                threads.append(threading.current_thread().name)
                return bytes((24, 52, 96)) * (64 * 54), "local.png", "hero"

            with patch.object(engine._automatic_dashboard_backgrounds, "get", side_effect=local):
                engine.set_game(620, "Portal 2", launch=True, source="Steam callback")
                deadline = time.monotonic() + 3.0
                while not faceplate.scene_calls and time.monotonic() < deadline:
                    time.sleep(0.01)
                first_generation = engine.faceplate_worker.status()["generation"]
                engine._reconcile_faceplate("periodic")
                engine._reconcile_faceplate("periodic")
                engine.stop()
            self.assertEqual("artwork-dashboard", faceplate.scene_calls[0][0])
            self.assertEqual(b"GIF89a", faceplate.scene_calls[0][3])
            self.assertEqual([], faceplate.artwork_calls)
            self.assertEqual(first_generation, engine.faceplate_worker.status()["generation"])
            self.assertTrue(threads)
            self.assertTrue(all(name == "gabecubeaura-faceplate" for name in threads))
            self.assertTrue(engine.faceplate_worker.status()["last_result"]["automatic_background"])

    def test_game_switch_cancels_automatic_artwork_before_render_and_usb(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            self.addCleanup(engine.stop)
            engine.faceplate_preferences.update(game_scene="artwork-dashboard")
            started, release = threading.Event(), threading.Event()
            self.addCleanup(release.set)
            rendered = []
            original = engine._render_faceplate_scene

            def background(appid, *args):
                if appid == 620:
                    started.set()
                    release.wait(3)
                return bytes((24, 52, 96)) * (64 * 54), "local.png", "hero"

            def render(payload, ticket):
                rendered.append(payload.get("appid"))
                return original(payload, ticket)

            with patch.object(engine._automatic_dashboard_backgrounds, "get", side_effect=background), \
                    patch.object(engine, "_render_faceplate_scene", side_effect=render):
                engine.set_game(620, "Portal 2", launch=True, source="Steam callback")
                self.assertTrue(started.wait(2))
                self.assertFalse(faceplate.scene_calls)
                engine.set_game(400, "Portal", launch=True, source="Steam callback")
                release.set()
                deadline = time.monotonic() + 3
                while not faceplate.scene_calls and time.monotonic() < deadline:
                    time.sleep(.01)
                engine.stop()
            self.assertEqual([400], rendered)
            self.assertEqual(1, len(faceplate.scene_calls))
            self.assertFalse(faceplate.artwork_calls)

    def test_missing_automatic_artwork_keeps_previous_picture_without_plain_artwork_upload(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"faceplate_lab_enabled": True})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            self.addCleanup(engine.stop)
            engine.faceplate_preferences.update(game_scene="artwork-dashboard")
            with patch.object(engine._automatic_dashboard_backgrounds, "get", return_value=None):
                engine.set_game(620, "Portal 2", launch=True, source="Steam callback")
                deadline = time.monotonic() + 2.0
                while not engine.faceplate_worker.status().get("last_result") and time.monotonic() < deadline:
                    time.sleep(.01)
                engine.stop()
            self.assertFalse(faceplate.artwork_calls)
            self.assertFalse(faceplate.scene_calls)
            self.assertIn("No local Steam artwork", engine.faceplate_worker.status()["last_result"]["error"])

    def test_enabling_faceplate_during_a_game_queues_current_artwork(self):
        faceplate = FakeCoordinator(started_at=100.0)
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({'faceplate_lab_enabled':False})
            engine = Engine(settings, str(Path(folder) / "artwork.json"), faceplate=faceplate)
            engine.set_game(42, "Running", launch=False, source="poll")
            engine.update_settings({"faceplate_lab_enabled": True})
            deadline = time.monotonic() + 1.0
            while not faceplate.artwork_calls and time.monotonic() < deadline:
                time.sleep(0.01)
            engine.stop()
        self.assertEqual(faceplate.artwork_calls, [(42, "hero")])

    def test_status_exposes_availability_and_flash_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                port_finder=lambda: "/dev/ttyUSB0",
            )
            coordinator.configure(True, 29)
            status = coordinator.status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["available"])
        self.assertFalse(status["busy"])
        self.assertEqual(status["owners"], [])
        self.assertEqual(status["port"], "/dev/ttyUSB0")
        self.assertEqual(status["phase"], "ready")
        self.assertIn("follow automatically", status["detail"])
        self.assertEqual(status["brightness"], 29)
        self.assertEqual(status["effective_brightness"], 29)
        self.assertEqual(status["last_start_ack_ms"], 0)
        self.assertEqual(status["last_transfer"], {})
        self.assertEqual(status["writes_total"], 0)

    def test_status_caches_expensive_serial_owner_scan_for_fifteen_seconds(self):
        now = [10.0]
        with tempfile.TemporaryDirectory() as folder, patch(
            "signalbar.faceplate.coordinator.port_owner_details", return_value=[]
        ) as owners:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                port_finder=lambda: "/dev/ttyUSB0", monotonic=lambda: now[0],
            )
            coordinator.status()
            coordinator.status()
            now[0] += 15.1
            coordinator.status()
        self.assertEqual(owners.call_count, 2)

    def test_status_never_waits_for_the_serial_transfer_lock(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "signalbar.faceplate.coordinator.port_owner_details", return_value=[]
        ) as owners:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                port_finder=lambda: "/dev/ttyUSB0",
            )
            coordinator.configure(True, 83)
            coordinator.lock.acquire()
            try:
                started = time.monotonic()
                status = coordinator.status()
                elapsed = time.monotonic() - started
            finally:
                coordinator.lock.release()
        self.assertLess(elapsed, 0.1)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["phase"], "ready")
        self.assertEqual(status["brightness"], 83)
        self.assertEqual(owners.call_count, 0)

    def test_continuity_probe_never_walks_process_file_descriptors(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "signalbar.faceplate.coordinator.port_owner_details", return_value=[]
        ) as owners:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                port_finder=lambda: "/dev/ttyUSB0",
            )
            self.assertEqual(coordinator.device_status(), {
                "available": True, "busy": False, "port": "/dev/ttyUSB0", "device_identity": None,
                "recently_detected": True, "last_detected_age_s": 0.0,
            })
            self.assertEqual(coordinator.device_status(), {
                "available": True, "busy": False, "port": "/dev/ttyUSB0", "device_identity": None,
                "recently_detected": True, "last_detected_age_s": 0.0,
            })
        self.assertEqual(owners.call_count, 0)

    def test_continuity_probe_expires_a_stale_external_owner_without_rescanning(self):
        now = [10.0]
        with tempfile.TemporaryDirectory() as folder, patch(
            "signalbar.faceplate.coordinator.port_owner_details",
            return_value=["jsaux-daemon (PID 42)"],
        ) as owners:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                port_finder=lambda: "/dev/ttyUSB0", monotonic=lambda: now[0],
            )
            self.assertTrue(coordinator.status()["busy"])
            self.assertTrue(coordinator.device_status()["busy"])
            now[0] += 15.1
            self.assertFalse(coordinator.device_status()["busy"])
        self.assertEqual(owners.call_count, 1)

    def test_full_brightness_is_sent_for_the_measured_safe_rain_assets(self):
        record = []
        monotonic = iter((100.0, 100.2))
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(record, True, **kwargs),
                monotonic=lambda: next(monotonic), wall_clock=lambda: 5000.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
            )
            coordinator.configure(True, 100)
            result = coordinator.synchronize_weather("rain", 0, 8.0)
        self.assertTrue(result["synchronized"])
        self.assertIn(("write", protocol.brightness(100)), record)
        self.assertEqual(coordinator.effective_brightness, 100)

    def test_automatic_artwork_renders_uploads_and_counts_one_write(self):
        record = []
        monotonic = iter((100.0, 100.3))
        frame = bytes((12, 80, 210)) * (64 * 54)
        steamgriddb = StaticFirstSteamGridDB()
        prepared_sources = []
        def source_ready(original):
            prepared_sources.append(original)
            record.append(('source-ready',))
        with tempfile.TemporaryDirectory() as folder, patch(
            "signalbar.faceplate.coordinator.artwork_render.artwork",
            return_value=(frame, "/steam/grid/42_hero.png", "hero"),
        ):
            coordinator = FaceplateCoordinator(
                ASSET_ROOT, Path(folder) / "state.json",
                link_factory=lambda **kwargs: FakeLink(record, True, **kwargs),
                monotonic=lambda: next(monotonic), wall_clock=lambda: 5000.0,
                port_finder=lambda: "/dev/ttyUSB0", identity_reader=lambda _port: "usb-a",
                steamgriddb=steamgriddb,
            )
            coordinator.configure(True, 100)
            result = coordinator.synchronize_artwork(42, "hero", source_ready=source_ready)
        self.assertTrue(result["found"])
        self.assertTrue(result["wrote"])
        self.assertEqual(result["source"], "hero")
        self.assertEqual(coordinator.last_asset, "artwork:42:42_hero.png")
        self.assertEqual(coordinator.writes_session, 1)
        self.assertEqual(steamgriddb.selected_calls, [42])
        self.assertEqual(len(prepared_sources), 1)
        self.assertEqual(prepared_sources[0]['kind'], 'artwork-strip')
        self.assertEqual(prepared_sources[0]['colours']['bottom'], [(12, 80, 210)] * 17)
        self.assertLess(record.index(('source-ready',)), next(i for i, value in enumerate(record) if value[0] == 'gif'))
        self.assertIn(("write", protocol.brightness(100)), record)


if __name__ == "__main__":
    unittest.main()
