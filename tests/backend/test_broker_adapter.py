"""Real worker/fake USB tests; these do not establish physical acceptance."""
import hashlib
import json
import base64
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from signalbar.faceplate.broker_adapter import FaceplateBrokerAdapter
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.service import FaceplateWorker
from signalbar.faceplate.transport import PhysicalOwnership, install_ownership_manager
from signalbar.faceplate import protocol
from signalbar.faceplate.flash import FlashWearProtection, UploadDeferred


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now


class BrokerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.clock = Clock()
        self.port = self.root/"ttyUSB0"
        self.port.touch()
        self.calls = []
        self.power_calls = []
        self.receipts = []
        self.block = None
        self.finished = threading.Event()
        self.enabled = True
        self.on = True
        self.priority = False
        self.result = {"synchronized": True, "wrote": True,
                       "transfer": {"end_sent": True, "active_profile": "baseline"}}
        def send(data, *args, **kwargs):
            self.calls.append((data, args, kwargs))
            if self.block:
                self.block.wait(2)
            self.finished.set()
            return dict(self.result)
        self.engine = SimpleNamespace(
            _faceplate_suspended=False, _faceplate_power_target=None,
            _stop=threading.Event(), thermal_protection=SimpleNamespace(active=False),
            settings=SimpleNamespace(all=lambda: {"faceplate_lab_enabled": self.enabled}),
            _display_panel_off=lambda values=None: not self.on,
            _broker_allowed=lambda values: self.enabled and self.on and not self.priority,
            _faceplate_next_reconcile=10.0, _faceplate_resume_requested=False,
            _faceplate_follow_key="old-home",
            faceplate=SimpleNamespace(powered=True, flash=SimpleNamespace(
                status=lambda: {"policy": "precaution-v1", "hardware_state": "acknowledged"},
                delay=lambda priority: 0),
                device_status=lambda: {"port": str(self.port), "available": True, "busy": False},
                port_finder=lambda: str(self.port), synchronize_scene=send,
                set_power=lambda on,reason: self.power_calls.append((on,reason)) or dict(ok=True,powered=on)))
        self.engine.faceplate_worker = FaceplateWorker(lambda request: self.adapter.execute_exit(request)
            if request['payload'].get('kind')=='broker-exit' else self.adapter.execute(request), enabled=True)
        self.adapter = FaceplateBrokerAdapter(self.engine, self.root/"ownership", self.clock)
        self.adapter.observe_steam(False)
        self.adapter.observe_steam(True)
        self.data = b"validated-by-core"
        self.path = self.root/"content.gif"
        self.path.write_bytes(self.data)
        self.job = {"operation_id": "operation", "lease_id": "lease", "generation": 1,
                    "activation_id": self.adapter.snapshot()["steam"]["activation_id"],
                    "content_path": str(self.path), "content_id": hashlib.sha256(self.data).hexdigest(),
                    "collection_id": "a"*64, "mode": "async", "deadline_mono_ms": None,
                    "peak_load": .25, "valid": lambda: True}

    def tearDown(self):
        if self.block: self.block.set()
        self.engine.faceplate_worker.stop(3)
        self.adapter.stop()
        install_ownership_manager(None)
        self.temp.cleanup()

    def report(self, operation_id, **receipt):
        self.receipts.append({"operation_id": operation_id, **receipt})

    def wait(self):
        deadline = time.monotonic()+3
        while True:
            state = self.engine.faceplate_worker.status()
            if not state["busy"] and not state["queued"]:
                break
            if time.monotonic() > deadline: self.fail("worker did not finish")
            time.sleep(.01)

    def start(self):
        self.assertTrue(self.adapter.reserve(self.job))
        self.assertTrue(self.adapter.submit(self.job, self.report))
        self.wait()

    def test_reservation_has_no_usb_and_blocks_normal_refresh(self):
        self.assertTrue(self.adapter.reserve(self.job))
        self.assertTrue(self.adapter.holds_display())
        self.assertEqual([], self.calls)
        self.assertEqual([], self.receipts)

    def test_priority_capture_is_frozen_before_restore_and_has_no_usb_effect(self):
        data=dict(first_blocker='steam-effective-priority',evaluated={'steam-effective-priority':True},
            steam_inputs={'policy':'cooperative','native_effect':True,'raw':'PRIVATE'})
        self.engine._broker_decision=lambda values:(not self.priority,data)
        self.priority=True;self.adapter.snapshot()
        self.adapter.record_revocation('operation','PRIORITY_ACTIVE','preempted')
        data['first_blocker']='none';self.priority=False;self.adapter.snapshot()
        proof=self.adapter.diagnostic_snapshot()['priority_evidence']
        self.assertEqual(proof['revocations'][0]['decision']['first_blocker'],'steam-effective-priority')
        self.assertEqual(proof['revocations'][0]['correlation_id'],hashlib.sha256(b'operation').hexdigest()[:16])
        self.assertNotIn('PRIVATE',json.dumps(proof))
        self.assertEqual(self.calls,[]);self.assertEqual(self.power_calls,[])

    def test_repeated_priority_reads_and_revocations_are_bounded(self):
        for n in range(100):
            self.priority=n%2==0;self.adapter.snapshot();self.adapter.record_revocation('operation','PRIORITY_ACTIVE','preempted')
        proof=self.adapter.diagnostic_snapshot()['priority_evidence']
        self.assertLessEqual(len(proof['observations']),24);self.assertEqual(len(proof['revocations']),8)
        self.assertLess(len(json.dumps(proof)),30000);self.assertEqual(self.calls,[])

    def test_restoration_trace_distinguishes_revocation_pending_deferred_and_ack(self):
        self.adapter.restore('operation',self.report)
        self.clock.now+=.2
        trace=self.adapter.diagnostic_snapshot()['normal_route_restoration']
        self.assertEqual(trace['state'],'pending');self.assertEqual(trace['elapsed_ms'],200)
        self.adapter.normal_completed(dict(deferred=True))
        self.clock.now+=.3
        self.assertEqual(self.adapter.diagnostic_snapshot()['normal_route_restoration']['state'],'deferred')
        self.adapter.normal_completed(dict(synchronized=True))
        self.clock.now+=5
        trace=self.adapter.diagnostic_snapshot()['normal_route_restoration']
        self.assertEqual(trace['state'],'confirmed');self.assertEqual(trace['elapsed_ms'],500)
        self.assertEqual(trace['physical_playback'],'not-measured')
        self.assertNotIn('started_at',trace);self.assertEqual(self.calls,[])

    def test_impossible_sync_profile_does_not_use_usb_or_cooldown(self):
        self.path.write_bytes(bytes(81920))
        self.job.update(content_id=hashlib.sha256(self.path.read_bytes()).hexdigest(),
                        mode="sync", deadline_mono_ms=102500)
        self.start()
        self.assertEqual([], self.calls)
        self.assertIsNone(self.adapter._last_attempt)
        self.assertEqual("ALIGNMENT_EXPIRED", self.receipts[-1]["reason"])

    def test_queue_delay_rechecks_remaining_budget_before_usb(self):
        self.job.update(mode="sync", deadline_mono_ms=100100)
        self.start()
        self.assertEqual([], self.calls)
        self.assertIsNone(self.adapter._last_attempt)

    def test_single_worker_and_fresh_ack_receipt(self):
        self.start()
        self.assertEqual(1, len(self.calls))
        self.assertTrue(self.receipts[-1]["fresh_ack"])
        self.assertEqual("confirmed", self.receipts[-1]["transfer_state"])
        self.assertTrue(self.calls[0][2]["delegated"])
        self.assertFalse(self.adapter.submit(self.job, self.report))

    def test_playlist_replacement_keeps_owner_and_never_restores_home(self):
        self.start();self.clock.now+=6;self.adapter.observe_steam(True)
        path=self.root/'next.gif';path.write_bytes(b'next-validated-loop')
        job={**self.job,'content_path':str(path),'content_id':hashlib.sha256(path.read_bytes()).hexdigest()}
        reports=[]
        self.assertTrue(self.adapter.replace(job,lambda op,**kw:reports.append(kw)))
        self.wait()
        self.assertEqual(len(self.calls),2);self.assertEqual(self.calls[-1][0],path.read_bytes())
        self.assertEqual(reports[-1]['transfer_state'],'confirmed')
        self.assertTrue(self.adapter.holds_display());self.assertFalse(self.power_calls)
        self.assertEqual(self.engine._faceplate_follow_key,'old-home')

    def test_playlist_replacement_cannot_borrow_an_owner_or_outlive_exit(self):
        self.start();self.clock.now+=6;self.adapter.observe_steam(True)
        self.assertFalse(self.adapter.replace({**self.job,'operation_id':'other'},self.report))
        self.priority=True
        self.assertFalse(self.adapter.replace(self.job,self.report))
        self.priority=False;self.adapter.cancel(self.job['operation_id'])
        self.assertFalse(self.adapter.replace(self.job,self.report));self.assertEqual(len(self.calls),1)

    def test_crc_reuse_is_not_phase_candidate(self):
        self.result["wrote"] = False
        self.start()
        self.assertFalse(self.receipts[-1]["fresh_ack"])

    def test_missing_ack_is_unconfirmed_not_resent(self):
        self.result = {"sent_unconfirmed": True, "synchronized": False}
        self.start()
        self.assertEqual("unconfirmed", self.receipts[-1]["transfer_state"])
        self.assertEqual(1, len(self.calls))

    def test_stale_steam_requires_new_inactive_edge(self):
        self.clock.now += 6
        self.assertEqual("unknown", self.adapter.snapshot()["steam"]["observed"])
        self.adapter.observe_steam(True)
        self.assertFalse(self.adapter.reserve(self.job))
        self.adapter.observe_steam(False)
        self.adapter.observe_steam(True)
        current = self.adapter.snapshot()["steam"]
        self.assertNotEqual(self.job["activation_id"], current["activation_id"])
        self.assertFalse(current["activation_closed"])

    def test_initial_active_does_not_grant_activation(self):
        other = FaceplateBrokerAdapter(self.engine, self.root/"other-owner", self.clock)
        try:
            other.observe_steam(True)
            self.assertTrue(other.snapshot()["steam"]["activation_closed"])
            self.assertIsNone(other.snapshot()["steam"]["activation_id"])
        finally: other.stop()

    def test_observer_error_preserves_recent_proof_but_suspend_closes_activation(self):
        self.adapter.observe_steam(True, "error")
        self.assertTrue(self.adapter.reserve(self.job))
        self.adapter.observe_steam(False)
        self.adapter.observe_steam(True)
        self.engine._faceplate_suspended = True
        self.assertTrue(self.adapter.snapshot()["steam"]["activation_closed"])

    def test_policy_prevents_work_even_with_fresh_steam(self):
        for attr in ("enabled", "on", "priority"):
            setattr(self, attr, attr == "priority")
            self.assertFalse(self.adapter.reserve(self.job))
            setattr(self, attr, attr != "priority")
        self.assertEqual([], self.calls)

    def test_gate_expired_before_serial_has_no_usb(self):
        self.job["deadline_mono_ms"] = 99999
        self.assertFalse(self.adapter.reserve(self.job))
        self.assertEqual([], self.calls)

    def test_content_mutation_never_reaches_usb(self):
        self.path.write_bytes(b"changed")
        self.start()
        self.assertEqual([], self.calls)
        self.assertEqual("USB_FAILED", self.receipts[-1]["reason"])

    def test_cancel_during_commit_keeps_ownership_until_quiescent(self):
        self.block = threading.Event()
        self.assertTrue(self.adapter.reserve(self.job))
        self.assertTrue(self.adapter.submit(self.job, self.report))
        deadline = time.monotonic()+2
        while not self.calls and time.monotonic() < deadline: time.sleep(.01)
        self.assertFalse(self.adapter.cancel("operation", "player-ended"))
        self.assertTrue(self.adapter.holds_display())
        self.assertTrue(self.calls[0][2]["cancelled"]())
        self.adapter.restore("operation", self.report)
        self.block.set(); self.wait()
        self.assertFalse(self.adapter.holds_display())
        self.assertEqual(0, self.engine._faceplate_next_reconcile)
        self.assertTrue(any(r.get("transfer_state") == "confirmed" for r in self.receipts))
        self.assertNotEqual("cancelled", self.receipts[-1].get("transfer_state"))

    def test_release_resolves_current_route_only_on_normal_receipt(self):
        self.start()
        self.assertTrue(self.adapter.cancel("operation"))
        self.adapter.restore("operation", self.report)
        self.wait()
        self.assertTrue(self.engine._faceplate_resume_requested)
        self.assertEqual("pending", self.receipts[-1]["restore_state"])
        self.adapter.normal_completed({"deferred": True})
        self.assertEqual("deferred", self.receipts[-1]["restore_state"])
        self.adapter.normal_completed({"synchronized": True})
        self.assertEqual("confirmed", self.receipts[-1]["restore_state"])

    def test_blocked_restore_is_terminal_not_fake_confirmation(self):
        self.start(); self.adapter.cancel("operation")
        self.on = False
        self.adapter.restore("operation", self.report)
        self.assertEqual("blocked", self.receipts[-1]["restore_state"])
        self.assertIsNone(self.adapter._restore_pending)

    def test_five_second_continuity_guard_survives_client_new_session(self):
        self.start(); self.adapter.cancel("operation")
        self.adapter.observe_steam(False); self.adapter.observe_steam(True)
        self.assertGreaterEqual(self.adapter.snapshot()["flash"]["retry_after_ms"], 4900)
        self.clock.now+=6
        self.assertEqual(self.adapter.snapshot()['flash']['retry_after_ms'],0)

    def test_actual_core_expiry_during_commit_finishes_release_without_late_reclaim(self):
        from signalbar.jsaux_broker import Broker
        from signalbar.jsaux_broker.validator import validate_bytes
        from signalbar.faceplate.gif import encode
        from signalbar.faceplate.steamgriddb import PALETTE_332
        broker = Broker(self.root/"core", self.adapter, self.clock,
                        validator=lambda path, sha: validate_bytes(path.read_bytes()))
        token = broker.connect(os.geteuid())
        sequence = [0]
        def call(op, args):
            sequence[0] += 1
            request = {"protocol": "jsaux-broker", "version": "1.0", "request_id": "r"+str(sequence[0]), "op": op, "args": args}
            if op != "hello": request["boot_id"] = broker.boot_id
            result = broker.handle(token, request)
            self.assertTrue(result["ok"], result)
            return result["result"]
        try:
            call("hello", {"capability": broker.capability, "client_instance_id": str(uuid.uuid4()), "supported_versions": ["1.0"]})
            data = encode(64, 54, PALETTE_332, [bytes([5])*3456, bytes([9])*3456], delay_cs=10)
            sha = hashlib.sha256(data).hexdigest()
            upload = call("register_content", {"sha256": sha, "size_bytes": len(data), "collection_id": "a"*64})
            call("content_chunk", {"upload_id": upload["upload_id"], "offset": 0, "data_base64": base64.b64encode(data).decode()})
            validation = call("commit_content", {"upload_id": upload["upload_id"]})
            deadline = time.monotonic()+2
            while True:
                status = call("operation_status", {"validation_id": validation["validation_id"]})
                if status["state"] != "validating": break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            self.assertEqual("ready", status["state"], status)
            activation = self.adapter.snapshot()["steam"]["activation_id"]
            lease = call("acquire_display", {"activation_id": activation, "session_id": "player", "content_id": sha, "collection_id": "a"*64, "mode": "async"})
            self.assertEqual([], self.calls)
            self.block = threading.Event()
            call("player_ready", {"lease_id": lease["lease_id"], "generation": lease["generation"], "alignment_attempt_id": None, "ready_mono_ms": None, "deadline_mono_ms": None, "clock_uncertainty_ms": None})
            deadline = time.monotonic()+2
            while not self.calls:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            self.clock.now += 9
            broker.tick()
            self.assertEqual("revoking", broker.lease["lease_state"])
            self.assertTrue(self.adapter.holds_display())
            self.block.set(); self.wait()
            self.assertEqual("expired", broker.lease["lease_state"])
            self.assertEqual("confirmed", broker.lease["transfer_state"])
            self.assertFalse(self.adapter.holds_display())
            self.assertEqual("pending", broker.lease["restore_state"])
            self.adapter.normal_completed({"synchronized": True})
            self.assertEqual("confirmed", broker.lease["restore_state"])
            self.assertEqual(1, len(self.calls))
        finally:
            if self.block: self.block.set()
            broker.stop(); broker.worker.shutdown(wait=True)


class PhysicalOwnershipTests(unittest.TestCase):
    def tearDown(self): install_ownership_manager(None)

    def test_aliases_share_lock_without_open_tty_and_release_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); port = root/"tty"; port.touch()
            alias = root/"alias"; alias.symlink_to(port)
            one = PhysicalOwnership(root/"locks"); two = PhysicalOwnership(root/"locks")
            try:
                self.assertEqual(one.key(str(port)), one.key(str(alias)))
                self.assertTrue(one.claim(str(port)))
                self.assertFalse(two.claim(str(alias)))
                self.assertEqual(0, port.stat().st_size)
                one.close()
                self.assertTrue(two.claim(str(port)))
            finally: one.close(); two.close()

    def test_symlink_and_world_readable_lock_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); port = root/"tty"; port.touch()
            real = root/"real"; real.mkdir(mode=0o700)
            linked = root/"linked"; linked.symlink_to(real)
            self.assertFalse(PhysicalOwnership(linked).claim(str(port)))
            manager = PhysicalOwnership(real)
            lock = real/(manager.key(str(port))+".lock")
            lock.write_bytes(b""); lock.chmod(0o644)
            self.assertFalse(manager.claim(str(port)))

    def test_lock_survives_serial_descriptor_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); port = root/"tty"; port.touch()
            one = PhysicalOwnership(root/"locks"); two = PhysicalOwnership(root/"locks")
            try:
                self.assertTrue(one.claim(str(port)))
                with port.open("rb"): pass
                self.assertFalse(two.claim(str(port)))
            finally: one.close(); two.close()


class DelegatedCoordinatorTests(unittest.TestCase):
    def coordinator(self, root, records):
        class Link:
            last_transfer_timings = {}
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def write(self, data): records.append(("write", data))
            def command(self, data, **kwargs): records.append(("command", data))
            def send_gif(self, data): records.append(("gif", data)); return True
        coordinator = FaceplateCoordinator(root, Path(root)/"state.json", link_factory=Link,
            port_finder=lambda: "fake", identity_reader=lambda port: "device")
        coordinator.configure(True, 100)
        coordinator.powered = True
        return coordinator

    def test_delegation_never_changes_brightness_or_rotates_content(self):
        with tempfile.TemporaryDirectory() as root:
            records = []; coordinator = self.coordinator(root, records)
            coordinator.rotate_180 = True
            data = encode_frame(bytes([10, 0, 0])*3456)
            result = coordinator.synchronize_scene(data, "screensaver", "digest", peak_load=.1, delegated=True)
            self.assertTrue(result["synchronized"])
            self.assertEqual(data, next(row[1] for row in records if row[0] == "gif"))
            self.assertFalse(any(row[0] == "write" for row in records))
            self.assertEqual(100, coordinator.brightness)

    def test_power_budget_and_off_reject_without_usb(self):
        with tempfile.TemporaryDirectory() as root:
            records = []; coordinator = self.coordinator(root, records)
            data = encode_frame(bytes([255, 255, 255])*3456)
            coordinator.effective_brightness = 100
            self.assertEqual("CONTENT_INVALID", coordinator.synchronize_scene(data, "screensaver", "d", peak_load=1, delegated=True)["policy_reason"])
            coordinator.powered = False
            self.assertEqual("DISPLAY_OFF", coordinator.synchronize_scene(data, "screensaver", "d", peak_load=.1, delegated=True)["policy_reason"])
            self.assertEqual([], records)


class BrokerAttemptPersistenceTests(unittest.TestCase):
    def test_process_restart_does_not_clear_screensaver_attempt_cooldown(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = Clock(); wall = [1700000000.]
            path = Path(folder)/"flash-protection.json"
            first = FlashWearProtection(path, monotonic=clock, wall_clock=lambda: wall[0])
            first.reserve_screensaver_attempt()
            self.assertEqual(5, first.screensaver_delay())
            # A new process has a different monotonic epoch; wall elapsed time
            # only reduces the persisted existing cooldown, never grants a write.
            clock.now = 5; wall[0] += 2
            second = FlashWearProtection(path, monotonic=clock, wall_clock=lambda: wall[0])
            self.assertEqual(3, second.screensaver_delay())
            self.assertRaises(UploadDeferred, second.reserve_screensaver_attempt)
            self.assertEqual(0, second.ordinary_attempts_session)
            self.assertEqual(0, second.performance_attempts_session)

    def test_backwards_wall_clock_cannot_reset_screensaver_window(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = Clock(); wall = [1700000000.]
            path = Path(folder)/"flash-protection.json"
            first = FlashWearProtection(path, monotonic=clock, wall_clock=lambda: wall[0])
            first.reserve_screensaver_attempt()
            wall[0] -= 3600; clock.now = 5
            second = FlashWearProtection(path, monotonic=clock, wall_clock=lambda: wall[0])
            self.assertEqual(5, second.screensaver_delay())
