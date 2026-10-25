# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Bounded Unix-stream control endpoint, backend credentials only, no TCP.

Lifecycle uses a private nonblocking lock. A stale socket is removable only
after this lock is acquired, its owner/type checked and a live-connect probe
refused. Never unlink a live/foreign/symlink endpoint. Peer UID checking is a
same-backend trust boundary, not isolation between root/UID-sharing plugins.
"""
from __future__ import annotations
import fcntl
import json
import math
import os
from pathlib import Path
import socket
import stat
import struct
import threading
import time

from .core import BrokerError
from .limits import LIMITS, PROTOCOL
from ..faceplate.runtime import CANONICAL_RUNTIME, provision_runtime


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def decode_message(raw):
    if not raw.endswith(b"\n") or len(raw) > LIMITS["message_bytes"]:
        raise ValueError("invalid framing")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    def check(item, depth=0):
        if depth > 8:
            raise ValueError("nesting")
        if isinstance(item, dict):
            for child in item.values():
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        elif type(item) is int and abs(item) > (1 << 53) - 1:
            raise ValueError("unsafe integer")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("nonfinite")
    check(value)
    if not isinstance(value, dict):
        raise ValueError("object required")
    return value


def peer_uid(sock):
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if hasattr(sock, "getpeereid"):
        return sock.getpeereid()[0]
    # macOS Python may not expose getpeereid even though LOCAL_PEERCRED exists.
    if os.uname().sysname == "Darwin":
        credentials = sock.getsockopt(0, 1, 80)  # SOL_LOCAL / LOCAL_PEERCRED
        return struct.unpack_from("I", credentials, 4)[0]
    raise PermissionError("peer credentials unavailable")


class BrokerServer:
    def __init__(self, broker, runtime_dir=Path("/run/decky/jsaux-broker/v1"), expected_uid=None):
        self.broker = broker
        self.runtime_dir = Path(runtime_dir).absolute()
        self.expected_uid = os.geteuid() if expected_uid is None else expected_uid
        self.socket_path = self.runtime_dir / "control.sock"
        self.credential_path = self.runtime_dir / "credential.json"
        self.listener = None
        self.lifecycle_fd = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.sockets = set()
        self.threads = []
        self.thread = None
        self.socket_inode = None
        self.start_state = "stopped"
        self.start_error = ""

    def status(self):
        # Deliberately omit credentials, paths, capability and peer payloads.
        return {"state": self.start_state, "available": self.listener is not None,
                "error": self.start_error, "wire_version": "1.0", "contract_revision": 4, "player_runtime": self.broker.player_runtime.snapshot()}

    def _safe_file(self, path, mode, kind="regular"):
        value = path.lstat()
        valid_type = stat.S_ISSOCK(value.st_mode) if kind == "socket" else stat.S_ISREG(value.st_mode)
        if not valid_type or value.st_uid != self.expected_uid or stat.S_IMODE(value.st_mode) != mode or value.st_nlink != 1:
            raise PermissionError("unsafe broker runtime file")
        return value

    def start(self):
        if self.listener is not None:
            return True
        if self.expected_uid != os.geteuid():
            raise PermissionError("broker identity mismatch")
        self.start_state, self.start_error = "starting", ""
        try:
            provision_runtime(self.runtime_dir, self.expected_uid)
        except (OSError, ValueError):
            self.start_state, self.start_error = "unavailable", "RUNTIME_PERMISSIONS"
            raise
        lock_path = self.runtime_dir / "lifecycle.lock"
        if lock_path.exists() or lock_path.is_symlink():
            self._safe_file(lock_path, 0o600)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lifecycle_fd = descriptor
            if self.socket_path.exists() or self.socket_path.is_symlink():
                self._safe_file(self.socket_path, 0o600, "socket")
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.settimeout(.2)
                try:
                    probe.connect(str(self.socket_path))
                except ConnectionRefusedError:
                    self.socket_path.unlink()
                else:
                    raise FileExistsError("broker endpoint is live")
                finally:
                    probe.close()
            if self.credential_path.exists() or self.credential_path.is_symlink():
                self._safe_file(self.credential_path, 0o600)
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            old_umask = os.umask(0o177)
            try:
                listener.bind(str(self.socket_path))
            finally:
                os.umask(old_umask)
            os.chmod(self.socket_path, 0o600)
            self.socket_inode = self.socket_path.lstat().st_ino
            listener.listen(2)
            listener.settimeout(.1)
            self.listener = listener
            credential = dict(protocol=PROTOCOL, major=1, boot_id=self.broker.boot_id,
                              socket_path=str(self.socket_path), capability=self.broker.capability)
            temporary = self.runtime_dir / ("credential-" + self.broker.boot_id + ".tmp")
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as target:
                    json.dump(credential, target, separators=(",", ":"))
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, self.credential_path)
            finally:
                temporary.unlink(missing_ok=True)
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._serve, name="jsaux-broker", daemon=True)
            self.thread.start()
            try:self.broker.player_runtime.start()
            except OSError:self.broker.player_runtime._event("listener-unavailable","ENDPOINT_UNAVAILABLE")
            self.start_state = "available"
            return True
        except Exception:
            self.start_state, self.start_error = "unavailable", "ENDPOINT_UNAVAILABLE"
            if self.listener:
                self.listener.close()
                self.listener = None
            if self.socket_inode and self.socket_path.exists() and self.socket_path.lstat().st_ino == self.socket_inode:
                self.socket_path.unlink()
            self.socket_inode = None
            os.close(descriptor)
            self.lifecycle_fd = None
            raise

    def _serve(self):
        while not self.stop_event.is_set():
            try:
                self.broker.tick()
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except (OSError, AttributeError):
                break
            try:
                uid = peer_uid(client)
                if uid != self.expected_uid:
                    raise PermissionError()
                token = self.broker.connect(uid)
            except (BrokerError, OSError, PermissionError):
                client.close()
                continue
            with self.lock:
                self.sockets.add(client)
                # Prune completed references; connection count stays <= 2.
                self.threads = [thread for thread in self.threads if thread.is_alive()]
                thread = threading.Thread(target=self._connection, args=(client, token), name="jsaux-client", daemon=True)
                self.threads.append(thread)
            thread.start()

    def _connection(self, client, token):
        try:
            client.settimeout(LIMITS["idle_read_ms"] / 1000)
            buffer = bytearray()
            while not self.stop_event.is_set():
                newline = buffer.find(b"\n")
                if newline < 0:
                    if len(buffer) >= LIMITS["message_bytes"]:
                        break
                    data = client.recv(min(4096, LIMITS["message_bytes"] - len(buffer)))
                    if not data:
                        break
                    buffer.extend(data)
                    continue
                raw = bytes(buffer[:newline + 1])
                del buffer[:newline + 1]
                try:
                    message = decode_message(raw)
                except (ValueError, UnicodeError, RecursionError):
                    response = self.broker._response("invalid", error=BrokerError("INVALID_REQUEST"))
                    client.settimeout(2)
                    client.sendall(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                    break
                response = self.broker.handle(token, message)
                client.settimeout(2)
                client.sendall(json.dumps(response, separators=(",", ":"), allow_nan=False).encode() + b"\n")
                if message.get("op") == "goodbye" and response["ok"]:
                    break
                if not response["ok"] and response["error"]["code"] in ("AUTH_DENIED", "VERSION_UNSUPPORTED", "STALE_BOOT"):
                    break
                client.settimeout(LIMITS["idle_read_ms"] / 1000)
        except (OSError, ValueError):
            pass
        finally:
            self.broker.disconnect(token)
            client.close()
            with self.lock:
                self.sockets.discard(client)

    def stop(self, timeout=2.0):
        self.broker.player_runtime.close()
        self.stop_event.set()
        deadline = time.monotonic() + max(0., timeout)
        if self.listener:
            self.listener.close()
            self.listener = None
        with self.lock:
            for client in tuple(self.sockets):
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread:
            self.thread.join(max(0., deadline - time.monotonic()))
        for thread in self.threads:
            thread.join(max(0., deadline - time.monotonic()))
        if self.socket_inode and self.socket_path.exists() and self.socket_path.lstat().st_ino == self.socket_inode:
            self.socket_path.unlink()
        if self.credential_path.exists() and not self.credential_path.is_symlink():
            try:
                self._safe_file(self.credential_path, 0o600)
                value = json.loads(self.credential_path.read_text())
                if value.get("boot_id") == self.broker.boot_id:
                    self.credential_path.unlink()
            except (ValueError, OSError):
                pass
        self.socket_inode = None
        if self.lifecycle_fd is not None:
            os.close(self.lifecycle_fd)
            self.lifecycle_fd = None


UnixBrokerServer = BrokerServer
