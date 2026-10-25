"""No hardware: exercise the common serial gate, faults and restart budget."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from signalbar.faceplate import protocol, gif
from signalbar.faceplate.artwork_dashboard import quantize_battery
from signalbar.faceplate.coordinator import FaceplateCoordinator
from signalbar.faceplate.flash import (
    FlashWearProtection, UploadDeferred, ContentCollision, identity, install_manager,
)
from signalbar.faceplate.transport import Link, LinkError, ReplyTimeout, GifCommitUnconfirmed, TransferCancelled
from signalbar.faceplate.service import FaceplateWorker
from signalbar.settings import SettingsStore


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now
    def wall(self): return 1800000000 + self.now
    def advance(self, seconds): self.now += seconds


class Panel:
    def __init__(self):
        self.stored = None
        self.incoming = None
        self.calls = []
        self.bodies = 0
        self.fail = ""

    def command(self, data, **_):
        kind, cmd = data[2:4]
        self.calls.append((kind, cmd))
        status = 1
        if cmd == protocol.CMD_GIF_BEGIN and kind == protocol.TYPE_CONTROL:
            if self.fail == "reject": status = 0
            elif data[6:-2] == self.stored: status = 2
            else: self.incoming = data[6:-2]
        elif cmd == protocol.CMD_GIF_CHUNK and kind == protocol.TYPE_DATA:
            self.bodies += 1
        elif cmd == protocol.CMD_GIF_END:
            if self.incoming is not None:
                self.stored, self.incoming = self.incoming, None
            if self.fail == "end": raise ReplyTimeout("end ACK lost")
        return protocol.Reply(kind, cmd, bytes([status]))


class FlashProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.path = Path(self.temp.name) / "protection.json"
        self.guard = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.panel = Panel()
        self.sleep_patch = patch("signalbar.faceplate.transport.time.sleep")
        self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)
        from signalbar.faceplate.flash import default_manager
        original = default_manager()
        self.addCleanup(install_manager, original)
        install_manager(self.guard)

    def link(self, scene="weather", priority="background"):
        link = Link("/dev/null")
        link.command = self.panel.command
        link.write = lambda _: None
        link.flash_scene, link.flash_priority = scene, priority
        return link

    def reserve(self, value=b"gif", priority="restore"):
        wanted = self.guard.preflight(value, priority)
        self.guard.reserve_body(wanted, priority)
        self.guard.receipt(wanted, wrote=True)

    def test_identical_device_content_skips_body_but_confirms_display(self):
        self.assertTrue(self.link().send_gif(b"GIF89a animated frames"))
        bodies = self.panel.bodies
        self.assertFalse(self.link("preview").send_gif(b"GIF89a animated frames"))
        self.assertEqual(self.panel.bodies, bodies)
        self.assertEqual(self.panel.calls[-1], (1, protocol.CMD_GIF_BEGIN))
        status = self.guard.status()
        self.assertEqual(status["session"]["confirmed"], 1)
        self.assertEqual(status["session"]["reused"], 1)
        self.assertEqual(status["attempts_last_hour"], 1)

    def test_real_multiframe_gif_is_one_transaction_not_one_per_frame(self):
        frames = [bytes([index % 2]) * (64 * 54) for index in range(30)]
        data = gif.encode(64, 54, ((0, 0, 0), (255, 0, 80)), frames, delay_cs=10)
        self.assertEqual(data.count(b"\x21\xf9\x04"), 30)
        self.assertTrue(self.link("companion", "assistant").send_gif(data))
        self.assertEqual(self.guard.status()["attempts_last_hour"], 1)

    def coordinator(self, port=lambda: "/dev/null"):
        panel = self.panel
        class ContextLink(Link):
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def command(self, data, **kwargs): return panel.command(data, **kwargs)
            def write(self, data): panel.calls.append(("write", data))
        coordinator = FaceplateCoordinator(Path(self.temp.name), Path(self.temp.name) / "coordinator.json",
            link_factory=ContextLink, port_finder=port, identity_reader=lambda _: "device",
            monotonic=self.clock, wall_clock=self.clock.wall)
        coordinator.configure(True, 100)
        return coordinator

    def test_recording_deferral_does_not_dim_previous_image_and_does_not_block_off(self):
        coordinator = self.coordinator()
        for index in range(8):
            wanted = identity(str(index).encode())
            coordinator.flash.reserve_body(wanted, "restore")
            coordinator.flash.receipt(wanted, wrote=True)
        data = gif.encode(64, 54, ((0, 0, 0), (255, 255, 255)), [bytes([1]) * 3456])
        with patch.object(coordinator.flash, 'preflight', side_effect=UploadDeferred(60)):
            result = coordinator.synchronize_scene(data, "weather", "sha", peak_load=1)
        self.assertTrue(result["deferred"])
        self.assertEqual(self.panel.calls, [])
        self.assertTrue(coordinator.set_power(False)["ok"])
        self.assertEqual(self.panel.calls[-1], (1, protocol.CMD_POWER))

    def test_disconnect_marks_previously_confirmed_device_unknown(self):
        port = ["/dev/null"]
        coordinator = self.coordinator(lambda: port[0])
        data = gif.encode(64, 54, ((0, 0, 0), (255, 0, 80)), [bytes([1]) * 3456])
        self.assertTrue(coordinator.synchronize_scene(data, "weather", "sha", peak_load=.2)["synchronized"])
        self.assertEqual(coordinator.flash.status()["hardware_state"], "acknowledged")
        port[0] = None
        self.assertFalse(coordinator.device_status()["available"])
        self.assertEqual(coordinator.flash.status()["hardware_state"], "unknown")

    def test_changed_gif_and_return_to_previous_require_new_bodies(self):
        for data in (b"first", b"second", b"first"):
            self.assertTrue(self.link().send_gif(data))
        self.assertEqual(self.guard.status()["session"]["confirmed"], 3)

    def test_all_features_can_transfer_without_a_burst_or_window_quota(self):
        for index, scene in enumerate(("performance", "weather", "dashboard", "timer", "artwork", "preview")):
            self.link(scene).send_gif(bytes([index]))
        for scene in ("clock", "settings", "studio"):
            self.assertTrue(self.link(scene).send_gif(scene.encode()))
        self.link("gabe", "assistant").send_gif(b"companion")
        self.link("dashboard", "restore").send_gif(b"return")
        self.assertTrue(self.link("gabe", "assistant").send_gif(b"old reaction"))
        self.assertEqual(self.guard.status()["session"]["confirmed"], 12)

    def test_more_than_120_and_128_transfers_have_no_quota_or_sleep(self):
        for index in range(160):
            self.reserve(str(index).encode())
        self.assertEqual(self.guard.status()['session']['confirmed'],160)
        self.assertEqual(self.guard.delay('background'),0)
        self.assertFalse(self.guard.status()['hard_limit_enabled'])

    def test_return_and_background_are_both_available_after_old_hour_threshold(self):
        for index in range(118):
            self.reserve(str(index).encode(), "interactive")
            self.clock.advance(30)
        self.reserve(b"background", "background")
        self.reserve(b"assistant", "assistant")
        self.reserve(b"restore", "restore")

    def test_economy_toggle_never_reintroduces_quotas_or_resets_history(self):
        self.guard.configure(False)
        for index in range(6): self.link().send_gif(str(index).encode())
        self.link().send_gif(b"seventh")
        self.assertEqual(self.guard.status()["session"]["confirmed"], 7)
        self.guard.configure(True)
        self.link().send_gif(b"eighth")
        self.assertEqual(self.guard.status()["session"]["confirmed"],8)

    def test_restart_keeps_budget_but_does_not_trust_hardware(self):
        self.reserve()
        self.guard.flush(force=True)
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.assertEqual(restored.status()["total"]["confirmed"], 1)
        self.assertEqual(restored.status()["hour_limit"],0)
        self.assertEqual(restored.status()["hardware_state"], "unknown")

    def test_crash_between_reservation_and_receipt_counted_uncertain_once(self):
        self.guard.reserve_body(identity(b"gif"), "restore")
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        again = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.assertEqual(restored.status()["total"]["uncertain"], 1)
        self.assertEqual(again.status()["total"]["uncertain"], 1)
        self.assertEqual(again.status()["total"]["confirmed"], 0)

    def test_backwards_wall_clock_cannot_refill_on_restart(self):
        self.reserve()
        restored = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=lambda: 1)
        self.assertEqual(restored.status()["total"]["uncertain"],1)
        self.assertEqual(restored.status()["hardware_state"],'unknown')
        self.assertEqual(restored.delay(),0)

    def test_corrupt_state_is_diagnostic_only_and_never_gates_display_or_power(self):
        self.path.write_text("[]", encoding="utf-8")
        broken = FlashWearProtection(self.path, monotonic=self.clock, wall_clock=self.clock.wall)
        self.assertTrue(broken.status()["persistence_error"])
        with patch.object(broken,'flush',return_value=False):
            self.assertEqual(broken.preflight(b"gif", "restore"),identity(b"gif"))
        broken.preflight(b'gif','restore')
        self.assertEqual(json.loads(self.path.read_text())['schema'],2)
        link = self.link()
        link.flash_manager = broken
        self.assertEqual(link.command(protocol.power(False)).status, 1)

    def test_storage_failure_records_warning_without_blocking_body(self):
        parent_file = Path(self.temp.name) / "file"
        parent_file.write_bytes(b"not a directory")
        broken = FlashWearProtection(parent_file / "state.json", monotonic=self.clock, wall_clock=self.clock.wall)
        broken.reserve_body(identity(b"gif"), "restore")
        self.assertTrue(broken.status()["persistence_error"])
        self.assertEqual(broken.status()["total"]["confirmed"], 0)

    def test_missing_commit_ack_is_uncertain_and_never_fallback_retransmitted(self):
        self.panel.fail = "end"
        link = self.link()
        link.transport_profile = "auto"
        with self.assertRaises(GifCommitUnconfirmed): link.send_gif(b"gif")
        self.assertEqual(self.guard.status()["session"]["uncertain"], 1)
        self.assertEqual(self.guard.status()["session"]["confirmed"], 0)
        self.assertEqual(len(link.last_transfer_timings["attempt_profiles"]), 1)
        self.assertEqual(self.panel.bodies, 1)

    def test_rejected_begin_is_not_success_and_spends_no_body_budget(self):
        self.panel.fail = "reject"
        with self.assertRaises(LinkError): self.link().send_gif(b"gif")
        self.assertEqual(self.guard.status()["attempts_last_hour"], 0)
        self.assertEqual(self.guard.status()["hardware_state"], "unknown")

    def test_crc_collision_does_not_claim_different_host_content_identical(self):
        self.link().send_gif(b"first")
        wanted = identity(b"first")
        self.guard.fingerprint = {**wanted, "sha256": "0" * 64}
        with self.assertRaises(ContentCollision): self.link().send_gif(b"first")
        self.assertEqual(self.guard.status()["session"]["reused"], 0)

    def test_cancelled_partial_body_is_not_a_confirmed_write(self):
        with self.assertRaises(TransferCancelled):
            self.link().send_gif(b"x" * 1200, cancelled=lambda: self.panel.bodies >= 1)
        self.assertEqual(self.guard.status()["session"]["uncertain"], 1)
        self.assertEqual(self.guard.status()["session"]["confirmed"], 0)

    def test_power_cycle_or_other_process_replacement_forces_device_recheck(self):
        self.link().send_gif(b"first")
        self.panel.stored = None
        self.guard.invalidate()
        self.assertTrue(self.link().send_gif(b"first"))
        self.assertEqual(self.guard.status()["session"]["confirmed"], 2)

    def test_direct_raw_gif_packets_cannot_bypass_gate(self):
        link = Link("/dev/null")
        for packet in (protocol.gif_begin(b"gif"), next(protocol.gif_chunks(b"gif")), protocol.gif_end()):
            with self.assertRaisesRegex(LinkError, "protected send_gif"): link.write(packet)

    def test_racing_features_cannot_overbook(self):
        admitted = []
        def send(index):
            try:
                self.guard.reserve_body(identity(str(index).encode()), "background")
                admitted.append(index)
            except UploadDeferred: pass
        threads = [threading.Thread(target=send, args=[index]) for index in range(32)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(admitted), 32)
        self.assertEqual(self.guard.ordinary_attempts_session,32)

    def test_settings_default_import_and_disabled_persistence(self):
        settings = SettingsStore(str(Path(self.temp.name) / "settings.json"))
        self.assertTrue(settings.all()["faceplate_flash_protection_enabled"])
        settings.update({"faceplate_flash_protection_enabled": False, "home_display": "performance"})
        again = SettingsStore(str(Path(self.temp.name) / "settings.json"))
        self.assertFalse(again.all()["faceplate_flash_protection_enabled"])
        self.assertEqual(again.all()["home_display"], "performance")
        settings.update({"faceplate_flash_protection_enabled": "malformed"})
        self.assertTrue(settings.all()["faceplate_flash_protection_enabled"])

    def test_battery_threshold_is_optional_and_never_changes_native_data(self):
        self.assertEqual(quantize_battery(84, step=5), quantize_battery(85, step=5))
        self.assertNotEqual(quantize_battery(85, step=5), quantize_battery(88, step=5))
        self.assertEqual(quantize_battery(84)["percent"], 84)

    def test_status_never_waits_for_a_durable_reservation(self):
        held, release = threading.Event(), threading.Event()
        def hold():
            with self.guard.lock:
                held.set()
                release.wait(2)
        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(held.wait(1))
        started = time.monotonic()
        try:
            self.assertTrue(self.guard.status()["enabled"])
            self.assertLess(time.monotonic() - started, .15)
        finally:
            release.set()
            thread.join(1)

    def test_idle_existing_worker_flushes_statistics_without_a_gif_or_extra_worker(self):
        self.reserve()
        self.clock.advance(61)
        flushed = threading.Event()
        def maintenance():
            self.guard.flush()
            flushed.set()
        with patch("signalbar.faceplate.service.STATISTICS_IDLE_SECONDS", .01):
            worker = FaceplateWorker(lambda _: self.fail("no image should be queued"), enabled=True,
                                     on_idle=maintenance)
            worker.start()
            try:
                self.assertTrue(flushed.wait(1))
                self.assertEqual(json.loads(self.path.read_text())["total"]["confirmed"], 1)
                self.assertEqual(worker.status()["completed"], 0)
            finally:
                worker.stop()


if __name__ == "__main__": unittest.main()
