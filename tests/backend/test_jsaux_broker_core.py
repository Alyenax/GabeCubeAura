"""Actual broker core/parser/Unix socket with fake USB and host monotonic clock.

These tests do not establish Steam identity provisioning, panel visibility,
physical alignment or Linux memory-limit enforcement on a Darwin test host.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import socket
import stat
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from signalbar.faceplate.gif import encode
from signalbar.faceplate.steamgriddb import PALETTE_332
from signalbar.jsaux_broker import Broker, BrokerServer
from signalbar.jsaux_broker.core import BrokerError
from signalbar.jsaux_broker.limits import CAPABILITIES, LIMITS
from signalbar.jsaux_broker.server import decode_message
from signalbar.jsaux_broker.validator import InvalidGIF, validate_bytes, validate_isolated


class Clock:
    now = 1000.
    def __call__(self):
        return self.now


class Adapter:
    def __init__(self):
        self.state = dict(hardware="available",
                          policy=dict(faceplate_enabled=True, display_on=True, suspended=False,
                                      thermal_blocked=False, priority_active=False, reason=None),
                          steam=dict(observed="active", observation_age_ms=0, activation_id="activation-1", activation_closed=False),
                          ownership=dict(logical_owner="GabeCubeAura", serial_busy=False, device_key="test-device"),
                          flash=dict(allowed=True, retry_after_ms=0, policy_revision="test", receipt_state="known"))
        self.jobs, self.reservations, self.cancellations, self.restorations = [], [], [], []
        self.quiescent = True
    def snapshot(self):
        return copy.deepcopy(self.state)
    def reserve(self, job):
        self.reservations.append(job)
        return True
    def submit(self, job, report):
        self.jobs.append(job)
        self.report = report
    def cancel(self, operation_id):
        self.cancellations.append(operation_id)
        return self.quiescent
    def restore(self, operation_id, report):
        self.restorations.append(operation_id)
        report(operation_id, restore_state="unconfirmed")


def gif(animated=True, seed=1):
    frames = [bytes((seed,)) * 3456]
    if animated:
        frames.append(bytes((seed + 1,)) * 3456)
    return encode(64, 54, PALETTE_332, frames, delay_cs=10)


class CoreTests(unittest.TestCase):
    def test_safety_revocation_captures_before_cancel_and_survives_diagnostic_failure(self):
        lease=self.acquire();seen=[]
        def capture(operation,reason,state,source):seen.append((reason,len(self.adapter.cancellations),source))
        self.adapter.record_revocation=capture;self.adapter.state['policy']['priority_active']=True
        self.broker.tick()
        self.assertEqual(seen,[('PRIORITY_ACTIVE',0,'lease-revocation')])
        self.assertEqual(len(self.adapter.cancellations),1)
        self.assertEqual(len(self.adapter.restorations),1)

    def test_diagnostic_hook_error_cannot_prevent_revocation(self):
        lease=self.acquire()
        def fail(*args,**kw):raise RuntimeError('PRIVATE')
        self.adapter.record_revocation=fail;self.adapter.state['policy']['priority_active']=True
        self.broker.tick()
        self.assertEqual(len(self.adapter.restorations),1)
        self.assertEqual(self.broker.lease['reason'],'PRIORITY_ACTIVE')

    def test_failed_reservation_is_distinct_from_a_policy_preemption(self):
        self.adapter.reserve=lambda job:False;seen=[]
        self.adapter.record_revocation=lambda operation,reason,state,source:seen.append((reason,state,source))
        content,collection=self.content()
        self.error('DEVICE_BUSY','acquire_display',dict(activation_id='activation-1',session_id='session-1',content_id=content,collection_id=collection,mode='async'))
        self.assertEqual(seen,[('PRIORITY_ACTIVE','rejected','reservation-failed')])
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="broker-test-", dir="/private/tmp")
        self.clock, self.adapter = Clock(), Adapter()
        self.broker = Broker(Path(self.temporary.name) / "private", self.adapter, clock=self.clock)
        self.client = str(uuid.uuid4())
        self.token = self.broker.connect(os.geteuid())
        self.seq = 0
        self.assertTrue(self.call("hello", dict(capability=self.broker.capability,
                             client_instance_id=self.client, supported_versions=["1.0"]))["ok"])
    def tearDown(self):
        self.broker.stop()
        self.broker.worker.shutdown(wait=True)
        self.temporary.cleanup()
    def call(self, op, args=None, request_id=None, token=None, **changes):
        self.seq += 1
        value = dict(protocol="jsaux-broker", version="1.0", request_id=request_id or "req-" + str(self.seq), op=op, args=args or {})
        if op != "hello":
            value["boot_id"] = self.broker.boot_id
        value.update(changes)
        return self.broker.handle(token or self.token, value)
    def ok(self, op, args=None, **kwargs):
        value = self.call(op, args, **kwargs)
        self.assertTrue(value["ok"], value)
        return value["result"]
    def error(self, code, op, args=None, **kwargs):
        value = self.call(op, args, **kwargs)
        self.assertFalse(value["ok"], value)
        self.assertEqual(value["error"]["code"], code, value)
        return value
    def content(self, animated=True, seed=1):
        data = gif(animated, seed)
        sha = hashlib.sha256(data).hexdigest()
        collection = hashlib.sha256(b"spec" + bytes((seed,))).hexdigest()
        register = self.ok("register_content", dict(sha256=sha, size_bytes=len(data), collection_id=collection))
        if "content_id" in register:
            return register["content_id"], collection
        upload_id = register["upload_id"]
        self.ok("content_chunk", dict(upload_id=upload_id, offset=0, data_base64=base64.b64encode(data).decode()))
        validation_id = self.ok("commit_content", dict(upload_id=upload_id))["validation_id"]
        for _ in range(200):
            with self.broker.lock:
                status = dict(self.broker.validations[validation_id])
            if status["state"] != "validating":
                break
            time.sleep(.01)
        self.assertEqual(status["state"], "ready", status)
        return status["content_id"], collection
    def acquire(self, mode="async", **changes):
        content_id, collection_id = self.content()
        args = dict(activation_id="activation-1", session_id="session-1", content_id=content_id, collection_id=collection_id, mode=mode)
        args.update(changes)
        return self.ok("acquire_display", args)

    def test_acquire_requeues_optional_projection_for_an_already_registered_collection(self):
        import threading
        content_id,collection_id=self.content()
        prepared=threading.Event();calls=[]
        self.adapter.prepare_extension=lambda key,path:(calls.append((key,path)),prepared.set())
        lease=self.ok('acquire_display',dict(activation_id='activation-1',session_id='session-1',content_id=content_id,collection_id=collection_id,mode='async'))
        self.assertTrue(prepared.wait(2));self.assertEqual(calls[0][0],content_id)
        self.assertEqual(self.adapter.jobs,[]) # Projection admission is not USB.
    def ready(self, lease, mode="async", **changes):
        args = dict(lease_id=lease["lease_id"], generation=lease["generation"],
                    alignment_attempt_id=lease.get("alignment_attempt_id"), ready_mono_ms=None,
                    deadline_mono_ms=None, clock_uncertainty_ms=None)
        if mode == "sync":
            args.update(ready_mono_ms=self.broker.now_ms(), deadline_mono_ms=self.broker.now_ms() + 2500, clock_uncertainty_ms=10)
        args.update(changes)
        return args
    def test_hello_exact_schema_no_credential_or_paths(self):
        token = self.broker.connect(os.geteuid())
        value = self.ok("hello", dict(capability=self.broker.capability, client_instance_id=self.client,
                                     supported_versions=["1.0"]), token=token)
        self.assertEqual(set(value), {"negotiated_version", "contract_revision", "connection_id", "broker_mono_ms", "clock_domain", "capabilities", "limits", "state"})
        self.assertEqual(value["contract_revision"], 4)
        self.assertEqual(value["capabilities"], CAPABILITIES)
        self.assertEqual(value["limits"], LIMITS)
        self.assertNotIn(self.broker.capability, json.dumps(value))
        self.assertNotIn(self.temporary.name, json.dumps(value))
        self.assertEqual(set(value["state"]), {"hardware", "policy", "steam", "ownership", "flash", "lease", "cache"})
    def test_wrong_credential_peer_and_version(self):
        with self.assertRaises(BrokerError):
            self.broker.connect(os.geteuid() + 1)
        token = self.broker.connect(os.geteuid())
        args = dict(capability="wrong", client_instance_id=str(uuid.uuid4()), supported_versions=["1.0"])
        self.error("AUTH_DENIED", "hello", args, token=token)
        args.update(capability=self.broker.capability, supported_versions=["2.0"])
        self.error("VERSION_UNSUPPORTED", "hello", args, token=token)
    def test_registration_is_real_isolated_validation_and_no_usb(self):
        self.content()
        self.assertFalse(self.adapter.jobs)
        self.assertFalse(self.adapter.reservations)
        self.assertFalse(self.adapter.restorations)
        self.assertEqual(self.ok("status")["cache"]["completed_count"], 1)
    def test_completed_content_revalidated_after_restart_without_reupload(self):
        content, collection = self.content()
        root = self.broker.root
        self.broker.stop()
        self.broker.worker.shutdown(wait=True)
        self.broker = Broker(root, self.adapter, clock=self.clock)
        self.broker.worker.shutdown(wait=True)
        self.token = self.broker.connect(os.geteuid())
        self.ok("hello", dict(capability=self.broker.capability, client_instance_id=self.client, supported_versions=["1.0"]))
        result = self.ok("register_content", dict(sha256=content, size_bytes=len(gif()), collection_id=collection))
        self.assertEqual(result, dict(content_id=content))
        self.assertFalse(self.broker.uploads)
    def test_cache_evicts_inactive_only_and_enforces_four_contents(self):
        lease = self.acquire()
        for seed in range(5, 10):
            self.content(seed=seed)
        self.assertEqual(len(self.broker.contents), 4)
        self.assertIn(self.broker.lease["content_id"], self.broker.contents)
        self.assertEqual(len(list(self.broker.contents_dir.glob("*.gif"))), 4)
    def test_admission_size_and_global_staging_cap(self):
        self.error("CONTENT_TOO_LARGE", "register_content", dict(sha256="a" * 64, collection_id="b" * 64, size_bytes=196609))
        self.ok("register_content", dict(sha256="a" * 64, collection_id="b" * 64, size_bytes=196608))
        self.error("RATE_LIMITED", "register_content", dict(sha256="c" * 64, collection_id="d" * 64, size_bytes=10))
    def test_bad_hash_rejected_without_usb(self):
        data = gif()
        value = self.ok("register_content", dict(sha256="a" * 64, size_bytes=len(data), collection_id="b" * 64))
        self.ok("content_chunk", dict(upload_id=value["upload_id"], offset=0, data_base64=base64.b64encode(data).decode()))
        validation_id = self.ok("commit_content", dict(upload_id=value["upload_id"]))["validation_id"]
        self.broker.worker.shutdown(wait=True)
        result = self.ok("operation_status", dict(validation_id=validation_id))
        self.assertEqual(result, dict(state="rejected", reason="HASH_MISMATCH"))
        self.assertFalse(self.adapter.jobs)
    def test_chunk_receipt_duplicate_and_different_overlap(self):
        data = gif()
        value = self.ok("register_content", dict(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), collection_id="a" * 64))
        args = dict(upload_id=value["upload_id"], offset=0, data_base64=base64.b64encode(data[:10]).decode())
        first = self.call("content_chunk", args, request_id="chunk")
        self.assertEqual(first, self.call("content_chunk", args, request_id="chunk"))
        self.error("REQUEST_CONFLICT", "content_chunk", {**args, "data_base64": "AAAA"}, request_id="chunk")
        self.error("REQUEST_CONFLICT", "content_chunk", args)
    def test_upload_expiration_and_abort_idempotence(self):
        value = self.ok("register_content", dict(sha256="a" * 64, size_bytes=10, collection_id="b" * 64))
        self.clock.now += 61
        self.broker.tick()
        self.assertFalse(self.broker.uploads)
        self.assertEqual(list(self.broker.staging_dir.iterdir()), [])
        self.assertTrue(self.ok("abort_content", dict(upload_id=value["upload_id"]))["aborted"])
    def test_acquire_reserves_but_never_submits_before_ready(self):
        lease = self.acquire()
        self.assertEqual(len(self.adapter.reservations), 1)
        self.assertFalse(self.adapter.jobs)
        status = self.ok("operation_status", dict(operation_id=lease["operation_id"]))
        self.assertEqual(status["transfer_state"], "not-started")
        self.assertEqual(status["lease_state"], "pending")
        self.ok("player_ready", self.ready(lease))
        self.assertEqual(len(self.adapter.jobs), 1)
    def test_duplicate_acquire_ready_and_renew_no_second_write(self):
        lease = self.acquire()
        args = self.ready(lease)
        self.ok("player_ready", args, request_id="ready")
        self.ok("player_ready", args, request_id="ready")
        self.ok("player_ready", args)
        for seq in range(1, 6):
            self.clock.now += .1
            self.ok("renew_display", dict(lease_id=lease["lease_id"], generation=lease["generation"], sequence=seq))
        self.assertEqual(len(self.adapter.jobs), 1)
        before = self.broker.lease["expires"]
        self.error("STALE_GENERATION", "renew_display", dict(lease_id=lease["lease_id"], generation=lease["generation"], sequence=5))
        self.assertEqual(self.broker.lease["expires"], before)
    def test_submit_false_releases_reserved_route(self):
        lease = self.acquire()
        self.adapter.submit = lambda *_: False
        self.error("USB_FAILED", "player_ready", self.ready(lease))
        self.assertEqual(self.broker.lease["lease_state"], "rejected")
        self.assertEqual(self.adapter.restorations, [lease["operation_id"]])
    def test_policy_change_before_ready_revokes_without_submission(self):
        lease = self.acquire()
        self.adapter.state["flash"]["allowed"] = False
        self.error("FLASH_DEFERRED", "player_ready", self.ready(lease))
        self.assertFalse(self.adapter.jobs)
        self.assertEqual(self.broker.lease["lease_state"], "rejected")
    def test_absolute_ready_gate_cannot_extend(self):
        lease = self.acquire("sync")
        ready = self.ready(lease, "sync", ready_mono_ms=999500, deadline_mono_ms=1004500)
        result = self.ok("player_ready", ready)
        self.assertEqual(result["remaining_ms"], 4500)
        self.error("GATE_CONFLICT", "player_ready", {**ready, "deadline_mono_ms": 1005000})
        self.clock.now += 4.5
        self.broker.tick()
        self.assertEqual(self.broker.lease["alignment_state"], "abandoned")
        self.assertFalse(self.adapter.jobs[0]["valid"]())
    def test_expired_ready_gate_never_queues(self):
        lease = self.acquire("sync")
        self.error("ALIGNMENT_EXPIRED", "player_ready", self.ready(lease, "sync", ready_mono_ms=990000, deadline_mono_ms=992500))
        self.assertFalse(self.adapter.jobs)
    def test_clock_uncertainty_or_future_ready_rejected(self):
        lease = self.acquire("sync")
        self.error("CLOCK_UNAVAILABLE", "player_ready", self.ready(lease, "sync", clock_uncertainty_ms=51))
        self.error("CLOCK_UNAVAILABLE", "player_ready", self.ready(lease, "sync", ready_mono_ms=1000001, deadline_mono_ms=1002501))
        self.assertFalse(self.adapter.jobs)
    def test_timed_candidate_and_software_start_no_optical_claim(self):
        lease = self.acquire("sync")
        self.ok("player_ready", self.ready(lease, "sync"))
        self.broker.report(lease["operation_id"], "confirmed", fresh_ack=True)
        status = self.ok("operation_status", dict(operation_id=lease["operation_id"]))
        self.assertEqual(status["alignment_state"], "candidate")
        self.assertEqual(status["candidate"]["optical_alignment"], "unknown")
        result = self.ok("tv_started", dict(lease_id=lease["lease_id"], generation=lease["generation"], alignment_attempt_id=lease["alignment_attempt_id"], started_mono_ms=self.broker.now_ms(), outcome="software-coordinated", candidate_id=status["candidate"]["candidate_id"]))
        self.assertEqual(result["alignment_state"], "software-coordinated")
        self.clock.now += 3
        self.broker.tick()
        self.assertEqual(self.broker.lease["lease_state"], "active")
    def test_crc_reuse_cannot_qualify_candidate(self):
        lease = self.acquire("sync")
        self.ok("player_ready", self.ready(lease, "sync"))
        self.broker.report(lease["operation_id"], "confirmed", fresh_ack=False)
        self.assertIsNone(self.broker.lease["candidate"])
        self.assertEqual(self.broker.lease["alignment_state"], "unconfirmed")

    def test_ten_minutes_and_many_loops_keep_one_coordinated_upload_until_real_exit(self):
        lease=self.acquire('sync');self.ok('player_ready',self.ready(lease,'sync'))
        self.broker.report(lease['operation_id'],'confirmed',fresh_ack=True)
        candidate=self.ok('operation_status',dict(operation_id=lease['operation_id']))['candidate']
        self.ok('tv_started',dict(lease_id=lease['lease_id'],generation=lease['generation'],
            alignment_attempt_id=lease['alignment_attempt_id'],started_mono_ms=self.broker.now_ms(),
            outcome='software-coordinated',candidate_id=candidate['candidate_id']))
        for n in range(1,302):
            self.clock.now+=2
            self.ok('renew_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],sequence=n))
            self.broker.tick();self.assertEqual(self.broker.lease['lease_state'],'active')
        self.assertEqual(len(self.adapter.jobs),1)
        self.adapter.state['steam']['observed']='inactive';self.broker.tick()
        self.assertEqual(self.broker.lease['reason'],'STEAM_INACTIVE')
    def test_repeated_ack_keeps_same_candidate(self):
        lease = self.acquire("sync")
        self.ok("player_ready", self.ready(lease, "sync"))
        self.broker.report(lease["operation_id"], "confirmed", fresh_ack=True)
        candidate = dict(self.broker.lease["candidate"])
        self.clock.now += .1
        self.broker.report(lease["operation_id"], "confirmed", fresh_ack=True)
        self.assertEqual(self.broker.lease["candidate"], candidate)
    def test_late_ack_preserved_but_no_reactivation(self):
        lease = self.acquire("sync")
        self.ok("player_ready", self.ready(lease, "sync"))
        self.adapter.quiescent = False
        self.clock.now += 3
        self.broker.tick()
        self.assertEqual(self.broker.lease["lease_state"], "revoking")
        self.broker.report(lease["operation_id"], "confirmed", fresh_ack=True)
        self.assertEqual(self.broker.lease["transfer_state"], "confirmed")
        self.assertEqual(self.broker.lease["lease_state"], "expired")
        self.assertIsNone(self.broker.lease["candidate"])
    def test_missing_ack_fences_current_activation(self):
        lease = self.acquire()
        self.ok("player_ready", self.ready(lease))
        self.broker.report(lease["operation_id"], "unconfirmed", reason="USB_UNCONFIRMED")
        self.error("ACTIVATION_CLOSED", "acquire_display", dict(activation_id="activation-1", session_id="fresh-session", content_id=self.broker.lease["content_id"], collection_id=self.broker.lease["collection_id"], mode="async"))
        self.assertEqual(len(self.adapter.jobs), 1)
    def test_inactive_immediate_revoke_not_eight_second_delay(self):
        lease = self.acquire()
        self.ok("player_ready", self.ready(lease))
        self.adapter.state["steam"]["observed"] = "inactive"
        self.broker.tick()
        self.assertEqual(self.broker.lease["lease_state"], "preempted")
        self.assertEqual(self.adapter.cancellations, [lease["operation_id"]])
        self.assertEqual(self.adapter.restorations, [lease["operation_id"]])
    def test_expiration_while_transfer_does_not_restore_before_quiescent(self):
        lease = self.acquire()
        self.ok("player_ready", self.ready(lease))
        self.adapter.quiescent = False
        self.clock.now += 9
        self.broker.tick()
        self.assertEqual(self.broker.lease["lease_state"], "revoking")
        self.assertFalse(self.adapter.restorations)
        self.broker.report(lease["operation_id"], transfer_state="cancelled")
        self.assertEqual(self.adapter.restorations, [lease["operation_id"]])
        self.assertEqual(self.broker.lease["lease_state"], "expired")
    def test_stale_boot_precedes_receipt(self):
        self.ok("status", request_id="same")
        self.error("STALE_BOOT", "status", request_id="same", boot_id="old")
    def test_receipt_eviction_cannot_reupload_fenced_activation(self):
        lease = self.acquire()
        self.ok("release_display", dict(lease_id=lease["lease_id"], generation=lease["generation"], reason="player-ended"))
        self.broker.receipts.clear()
        self.error("ACTIVATION_CLOSED", "acquire_display", dict(activation_id="activation-1", session_id="new", content_id=self.broker.lease["content_id"], collection_id=self.broker.lease["collection_id"], mode="async"))
    def test_priority_usb_off_and_flash_policy_fail_closed(self):
        content, collection = self.content()
        args = dict(activation_id="activation-1", session_id="session", content_id=content, collection_id=collection, mode="async")
        for key, code in (("faceplate_enabled", "FACEPLATE_DISABLED"), ("display_on", "DISPLAY_OFF"), ("suspended", "SUSPENDED"), ("priority_active", "PRIORITY_ACTIVE")):
            original = self.adapter.state["policy"][key]
            self.adapter.state["policy"][key] = not original
            self.error(code, "acquire_display", args)
            self.adapter.state["policy"][key] = original
        self.adapter.state["steam"]["observation_age_ms"] = 5001
        self.error("STEAM_STATE_STALE", "acquire_display", args)
        self.adapter.state["steam"]["observation_age_ms"] = 0
        self.adapter.state["flash"]["allowed"] = False
        self.error("FLASH_DEFERRED", "acquire_display", args)
        self.adapter.state["flash"]["allowed"] = True
        self.error("ACTIVATION_CLOSED", "acquire_display", args)
        self.assertFalse(self.adapter.reservations)
    def test_static_no_sync_capability(self):
        content, collection = self.content(animated=False)
        self.error("CONTENT_PROFILE_UNSUPPORTED", "acquire_display", dict(activation_id="activation-1", session_id="session", content_id=content, collection_id=collection, mode="sync"))
    def test_other_client_cannot_inspect_or_release_lease(self):
        lease = self.acquire()
        token = self.broker.connect(os.geteuid())
        self.ok("hello", dict(capability=self.broker.capability, client_instance_id=str(uuid.uuid4()), supported_versions=["1.0"]), token=token)
        self.assertIsNone(self.ok("status", token=token)["lease"])
        self.error("LEASE_EXPIRED", "operation_status", dict(operation_id=lease["operation_id"]), token=token)
        self.error("LEASE_EXPIRED", "release_display", dict(lease_id=lease["lease_id"], generation=lease["generation"], reason="player-ended"), token=token)
    def test_client_gc_reclaims_restart_slots_not_live_lease(self):
        lease = self.acquire()
        self.broker.disconnect(self.token)
        for _ in range(3):
            token = self.broker.connect(os.geteuid())
            self.ok("hello", dict(capability=self.broker.capability, client_instance_id=str(uuid.uuid4()), supported_versions=["1.0"]), token=token)
            self.broker.disconnect(token)
        token = self.broker.connect(os.geteuid())
        self.error("RATE_LIMITED", "hello", dict(capability=self.broker.capability, client_instance_id=str(uuid.uuid4()), supported_versions=["1.0"]), token=token)
        self.clock.now += 11
        self.broker.tick()
        self.ok("hello", dict(capability=self.broker.capability, client_instance_id=str(uuid.uuid4()), supported_versions=["1.0"]), token=token)
        self.assertEqual(len(self.broker.clients), 1)
        self.assertIn("activation-1", self.broker.fenced)
    def test_old_generation_never_mutates_current_lease(self):
        lease = self.acquire()
        self.error("STALE_GENERATION", "renew_display", dict(lease_id=lease["lease_id"], generation=lease["generation"] + 1, sequence=1))
        self.assertEqual(self.broker.lease["sequence"], 0)
    def test_rate_limit_burst_is_bounded(self):
        for _ in range(40):
            self.ok("status")
        self.error("RATE_LIMITED", "status")
        self.clock.now += .1
        self.ok("status")
    def test_unknown_fields_and_operations_rejected(self):
        self.error("INVALID_REQUEST", "status", dict(extra=True))
        self.error("INVALID_REQUEST", "shell", dict(command="anything"))
        self.error("INVALID_REQUEST", "status", extra=True)
    def test_hex_uuid_instance_and_nonascii_capability(self):
        token = self.broker.connect(os.geteuid())
        self.error("AUTH_DENIED", "hello", dict(capability="é" * 64, client_instance_id=uuid.uuid4().hex, supported_versions=["1.0"]), token=token)
        self.ok("hello", dict(capability=self.broker.capability, client_instance_id=uuid.uuid4().hex, supported_versions=["1.0"]), token=token)
    def test_diagnostic_snapshot_never_contains_secret_or_content(self):
        self.acquire()
        value = json.dumps(self.broker.diagnostic_snapshot())
        self.assertNotIn(self.broker.capability, value)
        self.assertNotIn(self.broker.lease["content_id"], value)
        self.assertNotIn(str(self.broker.root), value)


class GIFValidationTests(unittest.TestCase):
    def reject(self, data, code="CONTENT_PROFILE_UNSUPPORTED"):
        with self.assertRaises(InvalidGIF) as error:
            validate_bytes(data)
        self.assertEqual(error.exception.code, code)
    def test_real_encoder_random_clear_codes_and_peak(self):
        randomizer = random.Random(7)
        frame = bytes(randomizer.randrange(256) for _ in range(3456))
        value = validate_bytes(encode(64, 54, PALETTE_332, [frame, bytes([255]) * 3456], delay_cs=[1, 65535]))
        self.assertEqual(value["frames"], 2)
        self.assertEqual(value["duration_cs"], 65536)
        self.assertEqual(value["peak_load"], 1.)
    def test_profile_rejects_gif87_palette_dimensions_local_palette(self):
        data = gif()
        self.reject(b"GIF87a" + data[6:])
        modified = bytearray(data); modified[13] = 1; self.reject(modified)
        modified = bytearray(data); modified[6] = 63; self.reject(modified)
        pos = data.index(b"\x2c", 781)
        modified = bytearray(data); modified[pos + 9] = 0x80; self.reject(modified)
    def test_transparency_composition_interlace_rejected(self):
        data = gif()
        pos = data.index(b"\x21\xf9")
        for packed in (0, 5, 8, 12):
            changed = bytearray(data); changed[pos + 3] = packed; self.reject(changed)
        pos = data.index(b"\x2c", 781)
        changed = bytearray(data); changed[pos + 9] = 0x40; self.reject(changed)
    def test_truncation_trailing_payload_and_bad_lzw(self):
        data = gif()
        self.reject(data[:-1], "CONTENT_INVALID")
        self.reject(data + b"payload", "CONTENT_INVALID")
        pos = data.index(b"\x2c", 781)
        changed = bytearray(data); changed[pos + 12] = 0xff; self.reject(changed, "CONTENT_INVALID")
    def test_static_profile_no_inferred_clock(self):
        value = validate_bytes(gif(False))
        self.assertTrue(value["static"])
        self.assertFalse(value["timed_loop"])
        self.assertEqual(value["duration_cs"], 0)
    def test_subrectangle_other_extensions_and_zero_delay(self):
        data = gif()
        pos = data.index(b"\x2c", 781)
        changed = bytearray(data); changed[pos + 1] = 1; self.reject(changed)
        self.reject(data[:781] + b"\x21\xfe\x01x\x00" + data[781:])
        pos = data.index(b"\x21\xf9")
        changed = bytearray(data); changed[pos + 4:pos + 6] = b"\x00\x00"; self.reject(changed, "CONTENT_INVALID")
    def test_actual_isolated_child_hash_and_parse(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "one.gif"; data = gif(); path.write_bytes(data)
            value = validate_isolated(path, hashlib.sha256(data).hexdigest())
            self.assertEqual(value["frames"], 2)
            self.assertEqual(validate_isolated(path, "0" * 64), dict(error="HASH_MISMATCH"))


class UnixServerTests(unittest.TestCase):
    def setUp(self):
        # Unix path must fit Darwin's 104-byte sockaddr_un path bound.
        self.temporary = tempfile.TemporaryDirectory(prefix="jb-", dir="/private/tmp")
        root = Path(self.temporary.name)
        self.broker = Broker(root / "data", Adapter())
        self.server = BrokerServer(self.broker, root / "run")
        self.server.start()
    def tearDown(self):
        self.server.stop()
        self.broker.stop()
        self.broker.worker.shutdown(wait=True)
        self.temporary.cleanup()
    def exchange(self, sock, message):
        sock.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        output = bytearray()
        while not output.endswith(b"\n"):
            part = sock.recv(4096)
            if not part:
                break
            output.extend(part)
        return json.loads(output)
    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(str(self.server.socket_path))
        self.addCleanup(sock.close)
        return sock
    def hello(self, capability=None):
        return dict(protocol="jsaux-broker", version="1.0", request_id="hello", op="hello", args=dict(capability=capability or self.broker.capability, client_instance_id=str(uuid.uuid4()), supported_versions=["1.0"]))
    def test_actual_socket_permissions_auth_status_goodbye(self):
        self.assertEqual(stat.S_IMODE(self.server.runtime_dir.stat().st_mode), 0o700)
        for path in (self.server.socket_path, self.server.credential_path):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        credential = json.loads(self.server.credential_path.read_text())
        self.assertEqual(set(credential), {"protocol", "major", "boot_id", "socket_path", "capability"})
        sock = self.connect()
        self.assertTrue(self.exchange(sock, self.hello())["ok"])
        result = self.exchange(sock, dict(protocol="jsaux-broker", version="1.0", request_id="status", boot_id=self.broker.boot_id, op="status", args={}))
        self.assertTrue(result["ok"])
        self.assertNotIn(self.broker.capability, json.dumps(result))
        result = self.exchange(sock, dict(protocol="jsaux-broker", version="1.0", request_id="bye", boot_id=self.broker.boot_id, op="goodbye", args={}))
        self.assertEqual(result["result"], {"closed": True})
        self.assertEqual(sock.recv(1), b"")
    def test_wrong_capability_closes_without_side_effect(self):
        sock = self.connect()
        value = self.exchange(sock, self.hello("bad"))
        self.assertEqual(value["error"]["code"], "AUTH_DENIED")
        self.assertEqual(sock.recv(1), b"")
        self.assertFalse(self.broker.adapter.jobs)
    def test_duplicate_keys_are_rejected_on_actual_socket(self):
        sock = self.connect()
        sock.sendall(b'{"op":"hello","op":"status"}\n')
        result = json.loads(sock.recv(4096))
        self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(sock.recv(1), b"")
    def test_lifecycle_lock_never_unlinks_live_endpoint(self):
        inode = self.server.socket_path.stat().st_ino
        other = BrokerServer(self.broker, self.server.runtime_dir)
        with self.assertRaises((OSError, BlockingIOError)):
            other.start()
        self.assertEqual(inode, self.server.socket_path.stat().st_ino)
        self.assertTrue(self.exchange(self.connect(), self.hello())["ok"])
    def test_foreign_symlink_credential_refused(self):
        self.server.stop()
        target = Path(self.temporary.name) / "do-not-touch"
        target.write_text("keep")
        self.server.credential_path.symlink_to(target)
        other = BrokerServer(self.broker, self.server.runtime_dir)
        with self.assertRaises(PermissionError):
            other.start()
        self.assertEqual(target.read_text(), "keep")
    def test_decoder_rejects_deep_nonfinite_duplicate_and_unsafe_integers(self):
        values = [b'{"x":NaN}\n', b'{"x":1,"x":2}\n', b'{"x":9007199254740992}\n', b'{"x":' + b'[' * 9 + b'0' + b']' * 9 + b'}\n', b'[]\n', b'{}']
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    decode_message(value)


if __name__ == "__main__":
    unittest.main()
