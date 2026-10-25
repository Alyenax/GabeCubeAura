"""No USB: Lab 138 durable admission and visible-content regressions."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.faceplate.flash import FlashWearProtection, UploadDeferred, identity
from signalbar.faceplate.transport import Link, TransferCancelled, ReplyTimeout, GifCommitUnconfirmed, coordinated_transfer_ms, timing_admission
from signalbar.faceplate import protocol
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.settings import SettingsStore
from signalbar.jsaux_broker.server import provision_runtime
from signalbar.faceplate.steamgriddb import prepared_compatibility, SteamGridDBFaceplate
from signalbar.faceplate.coordinator import FaceplateCoordinator
from test_flash_protection import Clock


class V2PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.clock = Clock()
        self.path = self.root / "flash-protection.json"
        self.guard = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)

    def reserve(self, value, priority="restore"):
        self.guard.reserve_body(identity(str(value).encode()), priority)
        self.guard.receipt(identity(str(value).encode()), wrote=True)

    def test_legacy_consent_and_switch_off_do_not_bypass_admission(self):
        self.guard.configure(False)
        self.guard.configure_performance(True)
        for index in range(8):
            self.reserve(index)
        self.guard.reserve_body(identity(b"legacy"), "performance-consented")
        self.assertFalse(self.guard.status()["performance_unlimited"])

    def test_switch_off_still_persists_before_body(self):
        self.guard.configure(False)
        self.guard.reserve_body(identity(b"pending"), "restore")
        raw = json.loads(self.path.read_text())
        self.assertEqual(identity(b"pending"), raw["pending"])
        self.assertEqual(2, raw["schema"])

    def test_known_install_lost_journal_does_not_get_new_allowance(self):
        self.reserve(1)
        self.path.unlink()
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.assertEqual("lost", restored.status()["history_state"])
        self.assertEqual(0, restored.status()["attempts_last_day"])
        self.assertEqual(restored.delay("restore"),0)

    def test_existing_usage_without_journal_is_conservative(self):
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall, prior_usage=True)
        self.assertEqual("lost", restored.status()["history_state"])

    def test_nested_corrupt_journal_cannot_crash_startup(self):
        self.path.write_text('[' * 2000 + '0' + ']' * 2000)
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.assertEqual("corrupt", restored.status()["history_state"])
        self.assertEqual(0, restored.status()["attempts_last_day"])
        self.assertEqual(restored.delay("restore"),0)
        restored.preflight(b'repair-history','restore')
        self.assertFalse(restored.status()['persistence_error'])

    def test_background_has_24_shared_slots_not_an_extra_allowance(self):
        for index in range(24):
            self.reserve(index, "background")
            self.clock.advance(600)
        self.reserve(25, "background")
        self.assertEqual(25, self.guard.status()["attempts_last_day"])
        self.reserve("return", "restore")
        self.assertEqual(26, self.guard.status()["attempts_last_day"])

    def test_four_returns_are_inside_the_128_limit(self):
        for index in range(124):
            self.reserve(index, "interactive")
            self.clock.advance(600)
        self.reserve("normal", "assistant")
        for index in range(4):
            self.reserve("return"+str(index))
            self.clock.advance(31)
        self.reserve("130")
        self.assertEqual(130, self.guard.status()["session"]["confirmed"])
        self.assertEqual(0,self.guard.status()['day_limit'])

    def test_daily_history_survives_restart(self):
        self.reserve(1, "background")
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.assertEqual(1, restored.status()["background_attempts_last_day"])

    def test_durability_error_never_refuses_an_upload(self):
        self.guard.configure(False)
        with patch.object(self.guard, "flush", return_value=False):
            self.reserve(1)
        self.assertEqual(self.guard.status()['session']['confirmed'],1)

    def test_cancel_during_crc_begin_never_sends_end(self):
        link = Link("/dev/null")
        link.flash_manager = self.guard
        cancelled, calls = [False], []
        def command(data, **kwargs):
            calls.append(data[3]); cancelled[0] = True
            return protocol.Reply(data[2], data[3], b"\x02")
        link.command = command
        with self.assertRaises(TransferCancelled):
            link.send_gif(b"cached", cancelled=lambda: cancelled[0])
        self.assertEqual([protocol.CMD_GIF_BEGIN], calls)

    def test_end_retry_count_is_one_for_new_and_reused_data(self):
        for reused in (False, True):
            link = Link("/dev/null"); link.flash_manager = self.guard
            seen = []
            def command(data, **kwargs):
                seen.append((data[3], kwargs.get("retries")))
                return protocol.Reply(data[2], data[3], b"\x02" if reused and data[3] == 4 else b"\x01")
            link.command = command
            with patch("signalbar.faceplate.transport.time.sleep"):
                link.send_gif(b"scene"+bytes([reused]))
            self.assertEqual([] if reused else [(11, 1)], [item for item in seen if item[0] == 11])

    def test_crc_reuse_end_ack_loss_does_not_retry_via_auto_profile(self):
        link = Link("/dev/null", transport_profile="auto")
        link.activate_stored_gif = True  # Explicit transition from a native mode.
        link.flash_manager = self.guard
        calls = []
        def command(data, **kwargs):
            calls.append(data[3])
            if data[3] == protocol.CMD_GIF_END:
                raise ReplyTimeout("ACK lost")
            return protocol.Reply(data[2], data[3], b"\x02")
        link.command = command
        with self.assertRaises(GifCommitUnconfirmed): link.send_gif(b"reuse")
        self.assertEqual([4, 11], calls)

    def test_timing_sizes_and_remaining_deadline(self):
        self.assertFalse(timing_admission(16384, 2500))
        self.assertTrue(timing_admission(1024, 2500))
        self.assertFalse(timing_admission(32768, 2500))
        self.assertFalse(timing_admission(196608, 15000))
        self.assertTrue(timing_admission(81920, 15000))
        self.assertFalse(timing_admission(81920, 2500))
        self.assertFalse(timing_admission(196608, 2500))
        self.assertFalse(timing_admission(32768, 1000))
        self.assertGreater(coordinated_transfer_ms(49152), coordinated_transfer_ms(32768))

    def test_fresh_clock_off_and_explicit_choice_preserved(self):
        settings = SettingsStore(str(self.root/"settings.json"))
        self.assertFalse(settings.all()["faceplate_dashboard_show_clock"])
        settings.update({"faceplate_dashboard_show_clock": True})
        again = SettingsStore(str(self.root/"settings.json"))
        self.assertTrue(again.all()["faceplate_dashboard_show_clock"])
        self.assertEqual("explicit", again.all()["faceplate_dashboard_clock_choice"])

    def test_legacy_clock_choice_is_not_falsely_declared_explicit(self):
        path = self.root/"settings.json"; path.write_text('{}')
        settings = SettingsStore(str(path))
        self.assertEqual("legacy-unreviewed", settings.all()["faceplate_dashboard_clock_choice"])

    def test_clock_off_minute_does_not_change_pixels_or_identity(self):
        background = (bytes((5, 6, 7))*3456, bytes((7, 8, 9))*3456)
        kwargs = dict(show_clock=False, show_weather_notch=False, bottom_mode="controllers")
        a = build_artwork_dashboard(background, "2026-10-18T10:00:00", 0, **kwargs)
        b = build_artwork_dashboard(background, "2026-10-18T10:01:00", 0, **kwargs)
        self.assertEqual(a.frames, b.frames)
        self.assertEqual(a.signature, b.signature)
        self.assertEqual(2, len(a.frames))

    def test_old_routes_migrate_but_new_requests_are_rejected(self):
        store = FaceplatePreferencesStore(self.root/"routes.json")
        raw = store.defaults().as_dict(); raw["routes"] = {"home":"performance", "game":"performance"}
        store.path.write_text(json.dumps(raw))
        self.assertEqual("dashboard", store.read().home_scene)
        self.assertEqual("dashboard", store.read().game_scene)
        with self.assertRaises(ValueError):
            store.update(home_scene="performance")
        store.update(home_scene="weather")
        self.assertEqual("performance", json.loads(store.path.read_text())["retired_performance_routes"]["home"])

    def test_runtime_directory_never_repairs_symlinks_or_wrong_mode(self):
        good = provision_runtime(self.root/"runtime")
        self.assertEqual(0o700, good.stat().st_mode & 0o777)
        alias = self.root/"alias"; alias.symlink_to(good)
        with self.assertRaises(PermissionError): provision_runtime(alias)
        bad = self.root/"bad"; bad.mkdir(mode=0o755)
        with self.assertRaises(PermissionError): provision_runtime(bad)

    def test_old_baked_overlay_is_classified_not_claimed_clean(self):
        self.assertEqual("retired-overlay", prepared_compatibility({"matrix_components":["cpu"]}))
        self.assertEqual("legacy-unverified", prepared_compatibility({"schema":2}))
        self.assertEqual("current", prepared_compatibility({"matrix_policy":"no-cpu-v2"}))

    def test_known_retired_legacy_file_is_preserved_but_not_auto_selected(self):
        library = SteamGridDBFaceplate(self.root/"library")
        app = library.artwork_root/"440"; app.mkdir(parents=True)
        data = b"old-data"; compiled = app/"faceplate.gif"; compiled.write_bytes(data)
        (app/"manifest.json").write_text(json.dumps({"schema":1, "appid":440,
            "sha256":hashlib.sha256(data).hexdigest(), "matrix_components":["gpu"]}))
        self.assertIsNone(library.selected(440))
        self.assertEqual(data, compiled.read_bytes())

    def test_brightness_deduplicates_only_within_device_continuity(self):
        coordinator = FaceplateCoordinator(self.root, self.root/"state.json", port_finder=lambda: None)
        calls = []
        class FakeLink:
            def write(self, value): calls.append(value)
        link = FakeLink()
        coordinator.device_token = "first"
        self.assertTrue(coordinator._write_brightness(link, 50))
        self.assertFalse(coordinator._write_brightness(link, 50))
        coordinator.device_token = "second"
        self.assertTrue(coordinator._write_brightness(link, 50))
        self.assertEqual(2, len(calls))

    def test_restore_priority_is_not_specific_to_one_assistant(self):
        coordinator = FaceplateCoordinator(self.root, self.root/"state.json", port_finder=lambda: None)
        for reason in ("gabe-finished-current-route", "current-route-restore", "broker-current-route-restore"):
            self.assertEqual("restore", coordinator._upload_priority("dashboard", reason))
