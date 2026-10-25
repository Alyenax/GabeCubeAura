# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Lease/content broker. Hardware effects are exclusively delegated to an adapter.

Lock order: broker state lock, then short adapter state methods. Adapter callbacks
must not hold its state lock when calling ``report``. No client read, decoder or
serial I/O is awaited while holding this lock. Content decoding is isolated in a
disposable child, serialized by one worker. USB completion is a separate receipt.
"""
from __future__ import annotations
import base64
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import threading
import time
import uuid

from .limits import CAPABILITIES, CONTRACT_REVISION, LIMITS, PROTOCOL, VERSION
from .validator import validate_isolated
from ..faceplate import timing

ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z", re.ASCII)
DIGEST = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
SAFE_INTEGER = (1 << 53) - 1
TERMINAL = {"released", "expired", "preempted", "rejected"}
TRANSFERS = {"not-started", "deferred", "queued", "transferring", "confirmed", "unconfirmed", "failed", "cancelled"}
RESTORES = {"not-needed", "pending", "deferred", "confirmed", "unconfirmed", "blocked"}
FIELDS = {
    "hello": {"capability", "client_instance_id", "supported_versions"},
    "status": set(), "goodbye": set(),
    "publish_player": {"content_id","collection_id","token","mode","alignment_ms"},
    "publish_player_batch": {"content_id","collection_id","token","alignment_ms","index","count"},
    "remove_player": {"token"},
    "calibrate_player": {"token","alignment_ms"},
    "player_status": {"token"},
    "register_content": {"sha256", "size_bytes", "collection_id"},
    "content_chunk": {"upload_id", "offset", "data_base64"},
    "commit_content": {"upload_id"}, "abort_content": {"upload_id"},
    "acquire_display": {"activation_id", "session_id", "content_id", "collection_id", "mode"},
    "renew_display": {"lease_id", "generation", "sequence"},
    "release_display": {"lease_id", "generation", "reason"},
    "player_ready": {"lease_id", "generation", "alignment_attempt_id", "ready_mono_ms", "deadline_mono_ms", "clock_uncertainty_ms"},
    "tv_started": {"lease_id", "generation", "alignment_attempt_id", "started_mono_ms", "outcome", "candidate_id"},
}


class BrokerError(Exception):
    def __init__(self, code, retry_after_ms=None):
        self.code, self.retry_after_ms = code, retry_after_ms
        super().__init__(code)


def opaque():
    return secrets.token_hex(16)


def integer(value, low=0, high=SAFE_INTEGER):
    return type(value) is int and low <= value <= high


def ident(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def digest(value):
    return isinstance(value, str) and DIGEST.fullmatch(value) is not None


def private_directory(path):
    """Reject existing foreign/symlink directories rather than chmodding them."""
    path = Path(path).absolute()
    for ancestor in [*reversed(path.parents), path]:
        if ancestor.is_symlink():
            raise PermissionError("unsafe private directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    value = path.lstat()
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o700:
        raise PermissionError("private directory ownership/permissions")
    return path


class Broker:
    def __init__(self, root, adapter, clock=time.monotonic, validator=validate_isolated):
        self.root = private_directory(root)
        self.contents_dir = private_directory(self.root / "contents")
        self.staging_dir = private_directory(self.root / "staging")
        self.adapter, self.clock, self.validator = adapter, clock, validator
        self.boot_id, self.capability = opaque(), secrets.token_hex(32)
        self.lock = threading.RLock()
        self.clients, self.connections = {}, {}
        self.receipts = OrderedDict()
        self.contents, self.uploads = OrderedDict(), {}
        self.validations = OrderedDict()
        self.registration = OrderedDict()
        self.operations = OrderedDict()
        self.diagnostic_events = []
        self.last_admission = None
        self.fenced = OrderedDict()
        self.lease = None
        self.generation = 0
        self.stopped = False
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jsaux-validate")
        from .player_runtime import PlayerRuntime
        self.player_runtime=PlayerRuntime(self)
        self._load_completed()
        # A boot invalidates all uploads; remove only broker-owned regular files.
        for path in self.staging_dir.iterdir():
            if path.name.endswith(".upload") and path.is_file() and not path.is_symlink() and path.stat().st_uid == os.geteuid():
                path.unlink()

    def now_ms(self):
        return max(0, int(self.clock() * 1000))

    def _load_completed(self):
        # Revalidate immutable bytes after restart rather than trusting metadata.
        # Startup schedules bounded children, never decodes in Decky's thread.
        for path in sorted(self.contents_dir.glob("*.gif")):
            if len(self.contents) >= LIMITS["max_contents"]:
                break
            key = path.stem
            if not digest(key) or path.is_symlink():
                continue
            info = path.stat()
            if info.st_uid == os.geteuid() and stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= LIMITS["max_content_bytes"]:
                self.contents[key] = dict(path=path, size=info.st_size, metadata=None, used=self.now_ms(), owner=None)
                self.worker.submit(self._revalidate_completed, key, path)

    def _revalidate_completed(self, content_id, path):
        try:
            result = self.validator(path, content_id)
        except Exception:
            result = dict(error="CONTENT_INVALID")
        with self.lock:
            value = self.contents.get(content_id)
            if value is None or self.stopped:
                return
            if "error" in result:
                del self.contents[content_id]
                path.unlink(missing_ok=True)
            else:
                value["metadata"] = result
                self._queue_extension(content_id,path)

    def _queue_extension(self,content_id,path):
        if not self.stopped and callable(getattr(self.adapter,'prepare_extension',None)):
            try:self.worker.submit(self._prepare_extension,content_id,path)
            except RuntimeError:pass # Shutdown cannot turn optional LED work into an admission failure.

    def _prepare_extension(self,content_id,path):
        # Optional derived LED data, queued after admission on this existing
        # bounded worker. It is never part of client metadata or a USB gate.
        prepare=getattr(self.adapter,'prepare_extension',None)
        if callable(prepare) and not self.stopped:
            try:prepare(content_id,path)
            except Exception:pass # TV and Faceplate remain independent of LED projection.

    def _client_busy(self, client):
        if any(value["client"] == client and value["state"] == "validating" for value in self.validations.values()):
            return True
        if any(value["client"] == client for value in self.uploads.values()):
            return True
        return any(value["client"] == client and (value["lease_state"] not in TERMINAL or not value["quiescent"] or value["restore_state"] == "pending") for value in self.operations.values())

    def _cleanup(self):
        now = self.now_ms()
        for upload_id, upload in list(self.uploads.items()):
            if not upload.get("committed") and now - upload["updated"] >= LIMITS["upload_idle_ms"]:
                self._discard_upload(upload_id)
        for client, value in list(self.clients.items()):
            if not value["connections"] and not self._client_busy(client) and now - value["seen"] >= LIMITS["client_gc_idle_ms"]:
                del self.clients[client]
        for key, value in list(self.receipts.items()):
            if now - value["at"] >= 600000:
                del self.receipts[key]
        while len(self.receipts) > 1024:
            self.receipts.popitem(last=False)
        while len(self.validations) > 64:
            key = next((key for key, value in self.validations.items() if value["state"] != "validating"), None)
            if key is None:
                break
            del self.validations[key]
        while len(self.operations) > 64:
            key = next((key for key, value in self.operations.items() if value is not self.lease and value["lease_state"] in TERMINAL and value["quiescent"] and value["restore_state"] != "pending"), None)
            if key is None:
                break
            del self.operations[key]

    def connect(self, peer_uid):
        with self.lock:
            if self.stopped or peer_uid != os.geteuid():
                raise BrokerError("AUTH_DENIED")
            if len(self.connections) >= LIMITS["max_connections"]:
                raise BrokerError("RATE_LIMITED", 1000)
            token = opaque()
            self.connections[token] = dict(client=None)
            return token

    def disconnect(self, token):
        with self.lock:
            connection = self.connections.pop(token, None)
            if connection and connection["client"] in self.clients:
                client = self.clients[connection["client"]]
                client["connections"].discard(token)
                client["seen"] = self.now_ms()

    def _response(self, request_id, result=None, error=None, version=VERSION):
        response = dict(protocol=PROTOCOL, version=version, request_id=request_id, boot_id=self.boot_id, ok=error is None)
        if error is None:
            response["result"] = result
        else:
            response["error"] = dict(code=error.code)
            if error.retry_after_ms is not None:
                response["error"]["retry_after_ms"] = max(0, int(error.retry_after_ms))
        return response

    def handle(self, token, request):
        """Handle one already parsed JSON object; bounded and never waits for USB."""
        with self.lock:
            request_id = request.get("request_id") if isinstance(request, dict) else None
            wire_version=request.get("version",VERSION) if isinstance(request,dict) else VERSION
            def response(*args,**kw):return self._response(*args,**kw,version=wire_version if wire_version in (VERSION,"1.1","1.2") else VERSION)
            try:
                self.tick()
                if not isinstance(request, dict) or not ident(request_id):
                    raise BrokerError("INVALID_REQUEST")
                op = request.get("op")
                if not isinstance(op, str) or not ident(op):
                    raise BrokerError("INVALID_REQUEST")
                keys = {"protocol", "version", "request_id", "op", "args"}
                if op != "hello":
                    keys.add("boot_id")
                if set(request) != keys or request["protocol"] != PROTOCOL:
                    raise BrokerError("INVALID_REQUEST")
                connection = self.connections.get(token)
                expected_version=VERSION if op=="hello" else (connection or {}).get("wire_version",VERSION)
                if request["version"] != expected_version:
                    raise BrokerError("VERSION_UNSUPPORTED")
                if op in ("publish_player","remove_player","calibrate_player","player_status") and expected_version not in ("1.1","1.2"):raise BrokerError("VERSION_UNSUPPORTED")
                if op=="publish_player_batch" and expected_version!="1.2":raise BrokerError("VERSION_UNSUPPORTED")
                connection = self.connections.get(token)
                if connection is None:
                    raise BrokerError("AUTH_DENIED")
                if op != "hello" and request["boot_id"] != self.boot_id:
                    raise BrokerError("STALE_BOOT")
                args = request["args"]
                expected = FIELDS.get(op)
                if op == "operation_status":
                    valid = isinstance(args, dict) and set(args) in ({"operation_id"}, {"validation_id"})
                else:
                    valid = expected is not None and isinstance(args, dict) and set(args) == expected
                if not valid:
                    raise BrokerError("INVALID_REQUEST")
                if op == "hello":
                    return response(request_id, self._hello(token, args))
                client = connection["client"]
                if client not in self.clients:
                    raise BrokerError("AUTH_DENIED")
                value = self.clients[client]
                value["seen"] = self.now_ms()
                self._rate_limit(value)
                fingerprint = hashlib.sha256(json.dumps([op, args], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                key = (client, request_id)
                previous = self.receipts.get(key)
                if previous:
                    self.receipts.move_to_end(key)
                    if previous["fingerprint"] != fingerprint:
                        raise BrokerError("REQUEST_CONFLICT")
                    return previous["response"]
                try:
                    result = getattr(self, "_" + op)(client, args)
                    reply = response(request_id, result)
                except BrokerError as error:
                    reply = response(request_id, error=error)
                if op in ('register_content','commit_content','acquire_display','player_ready','tv_started','release_display') or not reply['ok']:
                    self.diagnostic_events=(self.diagnostic_events+[dict(at=int(time.time()),op=op,
                        accepted=reply['ok'],reason=reply.get('error',{}).get('code'))])[-24:]
                self.receipts[key] = dict(at=self.now_ms(), fingerprint=fingerprint, response=reply)
                # Limit each client's replay memory independently of resident GC.
                owned = [item for item in self.receipts if item[0] == client]
                for old in owned[:-256]:
                    del self.receipts[old]
                self._cleanup()
                return reply
            except BrokerError as error:
                return response(request_id if ident(request_id) else "invalid", error=error)
            except Exception:
                # Keep credentials, paths and arbitrary adapter errors out of wire.
                return response(request_id if ident(request_id) else "invalid", error=BrokerError("INTERNAL_ERROR"))

    def _rate_limit(self, value):
        now = self.now_ms()
        value["tokens"] = min(40., value["tokens"] + max(0, now - value["refilled"]) * .02)
        value["refilled"] = now
        if value["tokens"] < 1:
            raise BrokerError("RATE_LIMITED", 50)
        value["tokens"] -= 1

    def _hello(self, token, args):
        if self.connections[token]["client"] is not None:
            raise BrokerError("INVALID_REQUEST")
        if not digest(args["capability"]) or not secrets.compare_digest(args["capability"], self.capability):
            raise BrokerError("AUTH_DENIED")
        try:
            client = str(uuid.UUID(args["client_instance_id"]))
            if not ident(args["client_instance_id"]):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise BrokerError("INVALID_REQUEST")
        versions = args["supported_versions"]
        if not isinstance(versions, list) or not 1 <= len(versions) <= 4 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}", v) for v in versions):
            raise BrokerError("INVALID_REQUEST")
        if VERSION not in versions:
            raise BrokerError("VERSION_UNSUPPORTED")
        self._cleanup()
        if client not in self.clients:
            if len(self.clients) >= 4:
                remaining = [max(1, 10000 - (self.now_ms() - value["seen"])) for key, value in self.clients.items() if not value["connections"] and not self._client_busy(key)]
                raise BrokerError("RATE_LIMITED", min(remaining) if remaining else 8000)
            self.clients[client] = dict(connections=set(), seen=self.now_ms(), tokens=40., refilled=self.now_ms())
        self.connections[token]["client"] = client
        self.clients[client]["connections"].add(token)
        self.clients[client]["seen"] = self.now_ms()
        extended=any(v in versions for v in ("1.1","1.2")) and self.player_runtime.server is not None
        batched=extended and "1.2" in versions
        negotiated="1.2" if batched else "1.1" if extended else VERSION
        self.connections[token]["wire_version"]=negotiated
        capabilities=dict(CAPABILITIES)
        if extended:capabilities={**capabilities,"operations":[*CAPABILITIES["operations"],"publish_player","remove_player","calibrate_player","player_status"],"autonomous_player":True}
        if batched:capabilities={**capabilities,"operations":[*capabilities["operations"],"publish_player_batch"],"autonomous_batches":True}
        return dict(negotiated_version=negotiated, contract_revision=6 if batched else 5 if extended else CONTRACT_REVISION,
                    connection_id=token, broker_mono_ms=self.now_ms(),
                    clock_domain="linux-host-clock-monotonic", capabilities=capabilities,
                    limits=dict(LIMITS), state=self._status(client, {}))

    def _snapshot(self):
        return self.adapter.snapshot()

    def _status(self, client, args):
        value = self._snapshot()
        return dict(hardware=value["hardware"], policy=dict(value["policy"]),
                    steam=dict(value["steam"]), ownership=dict(value["ownership"]),
                    flash=dict(value["flash"]),
                    lease=self._lease_public(self.lease) if self.lease and self.lease["client"] == client else None,
                    cache=dict(completed_count=len(self.contents),
                               completed_bytes=sum(c["size"] for c in self.contents.values()),
                               staging_bytes=sum(c["offset"] for c in self.uploads.values()),
                               evictable_count=sum(not self._pinned(key) for key in self.contents)))

    def _publish_player(self,client,args):return self.player_runtime.publish(client,args)

    def _publish_player_batch(self,client,args):return self.player_runtime.batches.publish(client,args)

    def _remove_player(self,client,args):return self.player_runtime.remove(args)

    def _calibrate_player(self,client,args):return self.player_runtime.calibrate(args)

    def _player_status(self,client,args):return self.player_runtime.state(args)

    def _goodbye(self, client, args):
        return {"closed": True}

    def _pinned(self, content_id):
        if self.player_runtime.pinned(content_id):return True
        return any(value["content_id"] == content_id and (value["lease_state"] not in TERMINAL or not value["quiescent"] or value["restore_state"] == "pending") for value in self.operations.values())

    def _disk(self, additional):
        if shutil.disk_usage(self.root).free < LIMITS["min_free_disk_bytes"] + additional:
            raise BrokerError("DISK_LOW")

    def _register_content(self, client, args):
        sha, size, collection = args["sha256"], args["size_bytes"], args["collection_id"]
        if not digest(sha) or not digest(collection) or not integer(size, 1):
            raise BrokerError("INVALID_REQUEST")
        if size > LIMITS["max_content_bytes"]:
            raise BrokerError("CONTENT_TOO_LARGE")
        self._disk(size)
        existing = self.contents.get(sha)
        if existing and existing["metadata"] is None:
            raise BrokerError("RATE_LIMITED", 100)
        if existing and existing["size"] == size and existing["metadata"] is not None:
            existing["used"] = self.now_ms()
            self.contents.move_to_end(sha)
            # Collection authorization is per instance, never borrowed by digest alone.
            self._registered(client, sha, collection)
            return dict(content_id=sha)
        if self.uploads:
            raise BrokerError("RATE_LIMITED", 1000)
        while len(self.contents) >= 4 or sum(v["size"] for v in self.contents.values()) + size > LIMITS["max_cached_content_bytes"]:
            evict = next((key for key in self.contents if not self._pinned(key)), None)
            if evict is None:
                raise BrokerError("CACHE_FULL")
            self.contents.pop(evict)["path"].unlink(missing_ok=True)
        upload_id = opaque()
        path = self.staging_dir / (upload_id + ".upload")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        self.uploads[upload_id] = dict(client=client, sha256=sha, collection_id=collection,
                                      size=size, path=path, offset=0, updated=self.now_ms(), committed=False)
        return dict(upload_id=upload_id, next_offset=0, limits=dict(LIMITS))

    def _upload(self, client, upload_id):
        if not ident(upload_id):
            raise BrokerError("INVALID_REQUEST")
        value = self.uploads.get(upload_id)
        if value is None or value["client"] != client:
            raise BrokerError("CONTENT_MISSING")
        return value

    def _content_chunk(self, client, args):
        upload = self._upload(client, args["upload_id"])
        encoded = args["data_base64"]
        if upload["committed"] or not integer(args["offset"]) or not isinstance(encoded, str) or len(encoded) > 32768:
            raise BrokerError("INVALID_REQUEST")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError):
            raise BrokerError("INVALID_REQUEST")
        if not data or len(data) > LIMITS["chunk_bytes"] or upload["offset"] + len(data) > upload["size"]:
            raise BrokerError("CONTENT_TOO_LARGE")
        if args["offset"] != upload["offset"]:
            raise BrokerError("REQUEST_CONFLICT")
        fd = os.open(upload["path"], os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "ab") as target:
            target.write(data)
        upload["offset"] += len(data)
        upload["updated"] = self.now_ms()
        return dict(upload_id=args["upload_id"], next_offset=upload["offset"])

    def _commit_content(self, client, args):
        upload = self._upload(client, args["upload_id"])
        if upload["offset"] != upload["size"]:
            raise BrokerError("CONTENT_INVALID")
        if upload["committed"]:
            return dict(validation_id=upload["validation_id"])
        validation_id = opaque()
        upload.update(committed=True, validation_id=validation_id)
        self.validations[validation_id] = dict(client=client, state="validating", at=self.now_ms())
        self.worker.submit(self._validate, args["upload_id"], validation_id, dict(upload))
        return dict(validation_id=validation_id)

    def _validate(self, upload_id, validation_id, upload):
        try:
            result = self.validator(upload["path"], upload["sha256"])
        except Exception:
            result = dict(error="CONTENT_INVALID")
        with self.lock:
            value = self.validations.get(validation_id)
            if not value or self.stopped:
                self._discard_upload(upload_id)
                return
            path = self.contents_dir / (upload["sha256"] + ".gif")
            created=False
            try:
                if "error" in result:
                    value.update(state="rejected", reason=result["error"])
                else:
                    if upload["sha256"] not in self.contents:
                        # chmod staging first: failure cannot damage a shared
                        # already-published content file.
                        os.chmod(upload["path"], 0o400)
                        os.replace(upload["path"], path);created=True
                        self.contents[upload["sha256"]] = dict(path=path, size=upload["size"], metadata=result,
                                                               used=self.now_ms(), owner=None)
                    if upload["client"] in self.clients:
                        self._registered(upload["client"], upload["sha256"], upload["collection_id"])
                    value.update(state="ready", content_id=upload["sha256"], metadata=result)
                    self._queue_extension(upload['sha256'],path)
            except Exception:
                value.update(state="rejected",reason="CONTENT_INVALID")
                if created:
                    self.contents.pop(upload["sha256"],None)
                    try:path.unlink(missing_ok=True)
                    except OSError:pass
            finally:
                self._discard_upload(upload_id)

    def _discard_upload(self, upload_id):
        upload = self.uploads.pop(upload_id, None)
        if upload:
            try:upload["path"].unlink(missing_ok=True)
            except OSError:
                # Memory finalization is authoritative; retain this path for a
                # bounded later cleanup, never keep the upload slot occupied.
                self._cleanup_upload_paths=getattr(self,'_cleanup_upload_paths',set())
                self._cleanup_upload_paths.add(upload['path'])

    def _registered(self, client, content_id, collection_id):
        key = (client, content_id, collection_id)
        self.registration[key] = self.now_ms()
        self.registration.move_to_end(key)
        while len(self.registration) > 1024:
            removable = next((value for value in self.registration if not any(
                (lease["client"], lease["content_id"], lease["collection_id"]) == value
                and (lease["lease_state"] not in TERMINAL or not lease["quiescent"])
                for lease in self.operations.values())), None)
            if removable is None:
                break
            del self.registration[removable]

    def _abort_content(self, client, args):
        if not ident(args["upload_id"]):
            raise BrokerError("INVALID_REQUEST")
        value = self.uploads.get(args["upload_id"])
        if value and value["client"] != client:
            raise BrokerError("CONTENT_MISSING")
        if value and not value["committed"]:
            self._discard_upload(args["upload_id"])
        return dict(aborted=not bool(value and value["committed"]))

    def _policy(self, activation_id=None, flash=True, continuity=False):
        value = self._snapshot()
        hardware = value["hardware"]
        if hardware != "available":
            raise BrokerError({"absent": "DEVICE_ABSENT", "busy": "DEVICE_BUSY", "ownership-unavailable": "OWNERSHIP_UNAVAILABLE"}.get(hardware, "OWNERSHIP_UNAVAILABLE"))
        policy = value["policy"]
        for blocked, code in ((not policy["faceplate_enabled"], "FACEPLATE_DISABLED"),
                              (not policy["display_on"], "DISPLAY_OFF"),
                              (policy["suspended"], "SUSPENDED"),
                              (policy["thermal_blocked"], "PRIORITY_ACTIVE"),
                              (policy["priority_active"], "PRIORITY_ACTIVE")):
            if blocked:
                raise BrokerError(code)
        steam = value["steam"]
        age = steam["observation_age_ms"]
        # Existing leases may bridge one missed observation, bounded by the
        # lease-sized evidence window. Admission retains the strict 5s limit.
        freshness = LIMITS["lease_ms"] if continuity else LIMITS["steam_freshness_ms"]
        if steam["observed"] == "unknown" or age is None or age > freshness:
            raise BrokerError("STEAM_STATE_STALE")
        if steam["observed"] != "active":
            raise BrokerError("STEAM_INACTIVE")
        if steam["activation_closed"] or not steam["activation_id"] or steam["activation_id"] in self.fenced:
            raise BrokerError("ACTIVATION_CLOSED")
        if activation_id is not None and activation_id != steam["activation_id"]:
            raise BrokerError("ACTIVATION_CLOSED")
        if flash and not value["flash"]["allowed"]:
            raise BrokerError("FLASH_DEFERRED", value["flash"]["retry_after_ms"])
        return value

    def _acquire_display(self, client, args):
        if any(not ident(args[key]) for key in ("activation_id", "session_id")) or not digest(args["content_id"]) or not digest(args["collection_id"]) or args["mode"] not in ("sync", "async"):
            raise BrokerError("INVALID_REQUEST")
        if self.lease and (self.lease["lease_state"] not in TERMINAL or not self.lease["quiescent"] or self.lease["restore_state"] == "pending"):
            raise BrokerError("LEASE_CONFLICT")
        try:
            self._policy(args["activation_id"])
        except BrokerError as error:
            if error.code in ("FLASH_DEFERRED", "MIN_HOLD"):
                self._fence(args["activation_id"])
            raise
        content = self.contents.get(args["content_id"])
        if not content or content["metadata"] is None or (client, args["content_id"], args["collection_id"]) not in self.registration:
            raise BrokerError("CONTENT_MISSING")
        if args["mode"] == "sync" and content["metadata"]["static"]:
            raise BrokerError("CONTENT_PROFILE_UNSUPPORTED")
        if args["mode"] == "sync":
            from signalbar.faceplate.transport import timing_admission
            size=content["path"].stat().st_size
            admitted=timing_admission(size,LIMITS['sync_wait_ms'])
            self.last_admission=dict(stage='acquire',bytes=size,estimate_ms=timing.transfer_ms(size),
                remaining_ms=LIMITS['sync_wait_ms'],admitted=admitted,model=timing.MODEL)
            if not admitted:
                raise BrokerError("ALIGNMENT_EXPIRED")
        self.generation += 1
        lease = dict(args, client=client, lease_id=opaque(), generation=self.generation,
                     operation_id=opaque(), alignment_attempt_id=opaque() if args["mode"] == "sync" else None,
                     lease_state="pending", transfer_state="not-started",
                     alignment_state="waiting" if args["mode"] == "sync" else "not-requested",
                     restore_state="not-needed", reason=None, retry_after_ms=0,
                     revocation_reason=None, transfer_reason=None,
                     expires=self.now_ms() + 8000, deadline_mono_ms=None, candidate=None,
                     gate=None, tv=None, fresh_commit_ack=False, sequence=0, quiescent=True, events={"acquired": self.now_ms()})
        self.lease = lease
        self.operations[lease["operation_id"]] = lease
        # A valid stored collection can outlive the optional four-entry LED
        # cache. Rebuild its projection asynchronously if it was evicted.
        self._queue_extension(args['content_id'],content['path'])
        try:
            result = self.adapter.reserve(self._job(lease))
            if result is False or isinstance(result, dict) and result.get("error"):
                raise BrokerError(result.get("error", "DEVICE_BUSY") if isinstance(result, dict) else "DEVICE_BUSY")
        except Exception:
            self._revoke(lease, "PRIORITY_ACTIVE", "rejected",source='reservation-failed')
            raise BrokerError("DEVICE_BUSY")
        content["used"] = self.now_ms()
        return dict(lease_id=lease["lease_id"], generation=lease["generation"],
                    operation_id=lease["operation_id"], expires_in_ms=8000,
                    **(dict(alignment_attempt_id=lease["alignment_attempt_id"]) if args["mode"] == "sync" else {}))

    def _reporter(self,lease):
        operation=lease["operation_id"];serial=lease.get("transfer_serial",0)
        def report(operation_id,**receipt):
            with self.lock:
                current=self.operations.get(operation)
                if operation_id==operation and current and current.get("transfer_serial",0)==serial:self.report(operation_id,**receipt)
        return report

    def _job(self, lease):
        operation=lease["operation_id"];serial=lease.get("transfer_serial",0)
        return dict(operation_id=lease["operation_id"], lease_id=lease["lease_id"], generation=lease["generation"],
                    activation_id=lease["activation_id"], content_path=str(self.contents[lease["content_id"]]["path"]),
                    content_id=lease["content_id"], sha256=lease["content_id"], collection_id=lease["collection_id"],
                    peak_load=self.contents[lease["content_id"]]["metadata"].get("peak_load", 1.),
                    mode=lease["mode"], deadline_mono_ms=lease["deadline_mono_ms"],
                    valid=lambda: self.is_valid(operation) and self.operations.get(operation,{}).get("transfer_serial",0)==serial)

    def _owned(self, client, args):
        if not ident(args["lease_id"]) or not integer(args["generation"], 1):
            raise BrokerError("INVALID_REQUEST")
        lease = next((value for value in self.operations.values() if value["lease_id"] == args["lease_id"] and value["client"] == client), None)
        if lease is None:
            raise BrokerError("LEASE_EXPIRED")
        if lease["generation"] != args["generation"]:
            raise BrokerError("STALE_GENERATION")
        return lease

    def _renew_display(self, client, args):
        lease = self._owned(client, args)
        if not integer(args["sequence"], 1):
            raise BrokerError("INVALID_REQUEST")
        if lease["lease_state"] in TERMINAL | {"revoking"}:
            raise BrokerError("LEASE_EXPIRED")
        self._policy(lease["activation_id"], flash=False, continuity=True)
        if args["sequence"] <= lease["sequence"]:
            raise BrokerError("STALE_GENERATION")
        lease["sequence"], lease["expires"] = args["sequence"], self.now_ms() + 8000
        return self._lease_public(lease)

    def _player_ready(self, client, args):
        lease = self._owned(client, args)
        if lease["gate"] is not None:
            if lease["gate"] != args:
                raise BrokerError("GATE_CONFLICT")
            return self._gate_public(lease)
        if lease["lease_state"] in TERMINAL | {"revoking"}:
            raise BrokerError("LEASE_EXPIRED")
        if args["alignment_attempt_id"] != lease["alignment_attempt_id"]:
            raise BrokerError("STALE_GENERATION")
        if lease["mode"] == "sync":
            ready, deadline, uncertainty = args["ready_mono_ms"], args["deadline_mono_ms"], args["clock_uncertainty_ms"]
            if (not integer(ready) or not integer(deadline) or not integer(uncertainty, 0, 50)
                    or not 2500 <= deadline-ready <= LIMITS['sync_wait_ms'] or ready > self.now_ms()):
                raise BrokerError("CLOCK_UNAVAILABLE")
            if self.now_ms() >= deadline:
                self._revoke(lease, "ALIGNMENT_EXPIRED", "expired")
                raise BrokerError("ALIGNMENT_EXPIRED")
            lease["deadline_mono_ms"] = deadline
            from signalbar.faceplate.transport import timing_admission
            size = self.contents[lease["content_id"]]["path"].stat().st_size
            remaining=deadline-self.now_ms()
            admitted=timing_admission(size,remaining)
            self.last_admission=dict(stage='ready',bytes=size,estimate_ms=timing.transfer_ms(size),
                remaining_ms=remaining,admitted=admitted,model=timing.MODEL)
            if not admitted:
                self._revoke(lease, "ALIGNMENT_EXPIRED", "expired")
                raise BrokerError("ALIGNMENT_EXPIRED")
        elif any(args[key] is not None for key in ("alignment_attempt_id", "ready_mono_ms", "deadline_mono_ms", "clock_uncertainty_ms")):
            raise BrokerError("CLOCK_UNAVAILABLE")
        try:
            self._policy(lease["activation_id"], continuity=True)
        except BrokerError as error:
            self._revoke(lease, error.code, "rejected")
            raise
        lease.update(gate=dict(args), lease_state="active", transfer_state="queued", quiescent=False)
        lease["events"]["ready"] = self.now_ms()
        try:
            accepted = self.adapter.submit(self._job(lease), self._reporter(lease))
            if accepted is False:
                raise BrokerError("USB_FAILED")
        except Exception:
            self._revoke(lease, "USB_FAILED", "rejected")
            raise BrokerError("USB_FAILED")
        return self._gate_public(lease)

    def _gate_public(self, lease):
        return dict(operation_id=lease["operation_id"], gate_accepted=True,
                    deadline_mono_ms=lease["deadline_mono_ms"], transfer_state=lease["transfer_state"],
                    alignment_state=lease["alignment_state"],
                    remaining_ms=max(0, lease["deadline_mono_ms"] - self.now_ms()) if lease["deadline_mono_ms"] is not None else None)

    def _tv_started(self, client, args):
        lease = self._owned(client, args)
        if lease["tv"] is not None:
            if lease["tv"] != args:
                raise BrokerError("GATE_CONFLICT")
            return self._tv_public(lease)
        if args["alignment_attempt_id"] != lease["alignment_attempt_id"] or args["outcome"] not in ("software-coordinated", "tv-only", "independent"):
            raise BrokerError("INVALID_REQUEST")
        if args["outcome"] == "software-coordinated":
            candidate = lease["candidate"]
            deadline = lease["deadline_mono_ms"]
            if not integer(args["started_mono_ms"]) or deadline is None or self.now_ms() >= deadline or args["started_mono_ms"] >= deadline or lease["lease_state"] in TERMINAL | {"revoking"}:
                raise BrokerError("ALIGNMENT_EXPIRED")
            if lease["mode"] != "sync" or candidate is None or args["candidate_id"] != candidate["candidate_id"] or args["started_mono_ms"] > self.now_ms():
                raise BrokerError("GATE_CONFLICT")
            if args["started_mono_ms"] < lease["events"].get("candidate", self.now_ms()):
                raise BrokerError("GATE_CONFLICT")
            self._policy(lease["activation_id"], flash=False, continuity=True)
            lease["alignment_state"] = "software-coordinated"
        elif args["candidate_id"] is not None or args["outcome"] == "independent" and (lease["mode"] != "async" or args["started_mono_ms"] is not None):
            raise BrokerError("INVALID_REQUEST")
        elif args["outcome"] == "tv-only" and lease["mode"] == "sync":
            if args["started_mono_ms"] is not None and not integer(args["started_mono_ms"]):
                raise BrokerError("INVALID_REQUEST")
            self._revoke(lease, "ALIGNMENT_EXPIRED", "released")
        lease["tv"] = dict(args)
        lease["events"]["tv_started"] = self.now_ms()
        return self._tv_public(lease)

    def _tv_public(self, lease):
        return dict(recorded=True, lease_state=lease["lease_state"], alignment_state=lease["alignment_state"], restore_state=lease["restore_state"])

    def _release_display(self, client, args):
        lease = self._owned(client, args)
        if args["reason"] not in ("player-ended", "tv-timeout", "user-disabled", "client-stopping"):
            raise BrokerError("INVALID_REQUEST")
        if lease["lease_state"] not in TERMINAL | {"revoking"}:
            # Request reasons use kebab-case; public status reasons are codes.
            # Leaking the request spelling makes the next discovery invalid
            # while this terminal lease is still retained for diagnostics.
            self._revoke(lease, args["reason"].replace("-", "_").upper(), "released")
        return dict(state="released" if lease["quiescent"] else "release-pending",
                    lease_state=lease["lease_state"], restore_state=lease["restore_state"])

    def _lease_public(self, lease):
        keys = ("lease_id", "generation", "session_id", "activation_id", "content_id", "operation_id", "mode",
                "lease_state", "transfer_state", "alignment_state", "restore_state", "deadline_mono_ms", "candidate", "reason", "retry_after_ms")
        return {**{key: lease[key] for key in keys}, "expires_in_ms": max(0, lease["expires"] - self.now_ms()) if lease["lease_state"] not in TERMINAL | {"revoking"} else 0}

    def _operation_status(self, client, args):
        key = next(iter(args))
        if not ident(args[key]):
            raise BrokerError("INVALID_REQUEST")
        if key == "validation_id":
            value = self.validations.get(args[key])
            if not value or value["client"] != client:
                raise BrokerError("CONTENT_MISSING")
            return {key: item for key, item in value.items() if key not in ("client", "at")}
        lease = self.operations.get(args[key])
        if lease is None or lease["client"] != client:
            raise BrokerError("LEASE_EXPIRED")
        return {**self._lease_public(lease), "event_ages_ms": {key: max(0, self.now_ms() - value) for key, value in list(lease["events"].items())[-8:]}}

    def _fence(self, activation):
        self.fenced[activation] = self.now_ms()
        self.fenced.move_to_end(activation)
        while len(self.fenced) > 64:
            self.fenced.popitem(last=False)

    def _revoke(self, lease, reason, state,source='lease-revocation'):
        if lease["lease_state"] in TERMINAL | {"revoking"}:
            return
        try:
            capture=getattr(self.adapter,'record_revocation',None)
            if callable(capture):capture(lease['operation_id'],reason,state,source=source)
        except Exception:pass # Diagnostic failure cannot suppress a safety revocation.
        prepare_return=getattr(self.adapter,'prepare_return',None)
        if callable(prepare_return):
            try:prepare_return(lease['operation_id'],reason,
                lease['transfer_state']=='confirmed' and bool(lease.get('tv'))
                and lease['tv'].get('outcome') in ('software-coordinated','independent'))
            except Exception:pass
        self._fence(lease["activation_id"])
        lease["terminal"] = state
        lease["revocation_reason"] = reason
        lease["lease_state"], lease["reason"] = "revoking", reason
        lease["events"]["revoked"] = self.now_ms()
        if lease["mode"] == "sync" and lease["alignment_state"] != "software-coordinated":
            lease["alignment_state"] = "abandoned"
        lease["restore_state"] = "pending"
        try:
            quiescent = bool(self.adapter.cancel(lease["operation_id"]))
        except Exception:
            quiescent = False
        lease["quiescent"] = quiescent
        if quiescent:
            self._finish_release(lease)

    def _finish_release(self, lease):
        lease["quiescent"] = True
        lease["lease_state"] = lease.get("terminal", "released")
        if lease["transfer_state"] in ("not-started", "queued"):
            lease["transfer_state"] = "cancelled"
        try:
            self.adapter.restore(lease["operation_id"], self.report)
        except Exception:
            lease["restore_state"] = "blocked"

    def report(self, operation_id, transfer_state=None, reason=None, fresh_ack=False, restore_state=None, retry_after_ms=0):
        """Adapter completion hook. Late receipts cannot reacquire display authority."""
        with self.lock:
            lease = self.operations.get(operation_id)
            if lease is None:
                return
            if transfer_state in TRANSFERS:
                lease["transfer_state"] = transfer_state
                lease["events"]["transfer"] = self.now_ms()
                if transfer_state in ("confirmed", "unconfirmed", "failed", "cancelled", "deferred"):
                    lease["quiescent"] = True
            if restore_state in RESTORES:
                lease["restore_state"] = restore_state
            if reason:
                safe_reason = reason if isinstance(reason, str) and ident(reason) else "INTERNAL_ERROR"
                lease["transfer_reason"] = safe_reason
                # Late USB evidence cannot overwrite the original expiry,
                # inactive-Steam edge or explicit release that caused exit.
                if lease["lease_state"] not in TERMINAL | {"revoking"}:
                    lease["reason"] = safe_reason
            lease["retry_after_ms"] = retry_after_ms if integer(retry_after_ms) else 0
            if lease["lease_state"] == "revoking" and lease["quiescent"]:
                self._finish_release(lease)
                return
            if lease["lease_state"] in TERMINAL:
                return
            if transfer_state=='deferred' and reason=='FLASH_DEFERRED' and lease.get('gca_owned'):
                if self.player_runtime.batches.deferred(lease,lease['retry_after_ms']):return
            if transfer_state == "confirmed":self.player_runtime.batches.confirmed(lease)
            if transfer_state == "confirmed" and lease["mode"] == "sync":
                lease['fresh_commit_ack'] = bool(fresh_ack)
                if fresh_ack and lease["candidate"] is None and self.is_valid(operation_id) and lease["deadline_mono_ms"] is not None and self.now_ms() < lease["deadline_mono_ms"]:
                    lease["candidate"] = dict(candidate_id=opaque(), deadline_mono_ms=lease["deadline_mono_ms"],
                                              phase_basis="gif-end-ack-assumption", optical_alignment="unknown")
                    lease["events"]["candidate"] = self.now_ms()
                    lease["alignment_state"] = "candidate"
                elif lease["candidate"] is None:
                    lease["alignment_state"] = "unconfirmed"
            if transfer_state in ("unconfirmed", "failed", "deferred"):
                self._revoke(lease, reason or {"unconfirmed": "USB_UNCONFIRMED", "failed": "USB_FAILED", "deferred": "FLASH_DEFERRED"}[transfer_state], "rejected")

    def is_valid(self, operation_id):
        with self.lock:
            lease = self.operations.get(operation_id)
            if lease is None or lease["lease_state"] in TERMINAL | {"revoking"} or self.stopped or (not lease.get("gca_owned") and self.now_ms() >= lease["expires"]):
                return False
            if lease["deadline_mono_ms"] is not None and lease["alignment_state"] != "software-coordinated" and self.now_ms() >= lease["deadline_mono_ms"]:
                return False
            try:
                self._policy(lease["activation_id"], flash=False, continuity=True)
            except BrokerError:
                return False
            return True

    def tick(self):
        with self.lock:
            for path in tuple(getattr(self,'_cleanup_upload_paths',())):
                try:path.unlink(missing_ok=True)
                except OSError:continue
                self._cleanup_upload_paths.discard(path)
            lease = self.lease
            if lease and lease["lease_state"] not in TERMINAL | {"revoking"}:
                reason = None
                if not lease.get("gca_owned") and self.now_ms() >= lease["expires"]:
                    reason = "LEASE_EXPIRED"
                elif lease["deadline_mono_ms"] is not None and lease["alignment_state"] != "software-coordinated" and self.now_ms() >= lease["deadline_mono_ms"]:
                    reason = "ALIGNMENT_EXPIRED"
                else:
                    try:
                        self._policy(lease["activation_id"], flash=False, continuity=True)
                    except BrokerError as error:
                        reason = error.code
                if reason:
                    self._revoke(lease, reason, "expired" if reason in ("LEASE_EXPIRED", "ALIGNMENT_EXPIRED") else "preempted")
            self.player_runtime.batches.tick()
            self._cleanup()

    def stop(self, timeout=2.0):
        self.player_runtime.close()
        with self.lock:
            if self.stopped:
                return
            if self.lease and self.lease["lease_state"] not in TERMINAL | {"revoking"}:
                self._revoke(self.lease, "SUSPENDED", "preempted")
            self.stopped = True
            for upload_id, upload in list(self.uploads.items()):
                if not upload["committed"]:
                    self._discard_upload(upload_id)
        # Validators are hard limited to 10 seconds and own no serial descriptor.
        self.worker.shutdown(wait=False, cancel_futures=True)

    def diagnostic_snapshot(self):
        """Bounded transport evidence, no credentials, paths or raw identities."""
        with self.lock:
            lease = self.lease
            return dict(protocol=PROTOCOL, version=VERSION, contract_revision=CONTRACT_REVISION,
                        timing_policy=dict(model=timing.MODEL,sync_max_bytes=timing.SYNC_MAX_BYTES,
                            last_admission=dict(self.last_admission) if self.last_admission else None),
                        clients=len(self.clients), connections=len(self.connections),
                        cached_contents=len(self.contents), uploads=len(self.uploads),
                        pending_validations=sum(value["state"] == "validating" for value in self.validations.values()),
                        phase={key: lease[key] for key in ("lease_state", "transfer_state", "alignment_state", "restore_state", "reason")} if lease else None,
                        events=list(self.diagnostic_events),
                        attempts=[dict(correlation_id=hashlib.sha256(value['operation_id'].encode()).hexdigest()[:16],
                            **{key:value[key] for key in ('mode','lease_state','transfer_state','alignment_state','restore_state','reason','retry_after_ms','fresh_commit_ack','revocation_reason','transfer_reason')},
                            content_bytes=self.contents.get(value['content_id'],{}).get('size',0),
                            event_ages_ms={key:max(0,self.now_ms()-at) for key,at in value['events'].items()},
                            optical_playback='not-measured') for value in list(self.operations.values())[-12:]])
