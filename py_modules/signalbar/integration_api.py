"""Versioned generic GCA context, utility and external-presentation API.

Only same-user clients can connect, with a per-start bearer in a 0700 runtime.
Each visual session expires; delayed work is cancellation-bound to that session.
No recorder, recognizer or keyboard/input reader is constructed in this module.
"""
from __future__ import annotations

import hashlib
import math
import re

import base64
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import socketserver
import stat
import struct
import threading
import time

from signalbar.models import ProviderOutput, normalize_frame

PROTOCOL = 1
RUNTIME = Path('/run/decky/gca-integrations-v1')
MAX_MESSAGE = 384 * 1024
LEASE_SECONDS = 4.0


def request(operation, payload=None, *, runtime=RUNTIME, timeout=2.0):
    root = Path(runtime)
    token_path = root / 'auth'
    info = token_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise PermissionError('Unsafe integration credential')
    message = {'protocol': PROTOCOL, 'auth': token_path.read_text().strip(),
               'operation': operation, 'payload': payload or {}}
    data = json.dumps(message, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(data) > MAX_MESSAGE:
        raise ValueError('Integration request too large')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(timeout)
        client.connect(str(root / 'bridge.sock'))
        client.sendall(data)
        with client.makefile('rb') as stream:
            result = stream.readline(MAX_MESSAGE + 1)
    if not result.endswith(b'\n') or len(result) > MAX_MESSAGE:
        raise ValueError('Invalid integration response')
    reply = json.loads(result)
    if not reply.get('ok'):
        raise RuntimeError(reply.get('error', 'Integration refused'))
    return reply['result']


class _PowerCommand:
    def run(self, args, cancel, timeout):
        from signalbar.core.cancellation import Cancelled
        from signalbar.updates import _clean_system_command_environment
        with subprocess.Popen(args, env=_clean_system_command_environment(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if cancel.is_set(): raise Cancelled()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TimeoutError('Power command timed out')
                    try:
                        output, _ = process.communicate(timeout=min(.05, remaining))
                        if process.returncode: raise RuntimeError('Power command refused')
                        if len(output) > 4096: raise ValueError('Invalid power response')
                        return output.decode('utf-8')
                    except subprocess.TimeoutExpired: pass
            finally:
                if process.poll() is None: process.kill(); process.wait()


class ExternalPresentation:
    """Bounded external visual provider. Hardware ownership stays with GCA."""
    def __init__(self, directory, asset_root, get_config, get_game, acquire, release, preflight,
                 get_facts=lambda: {}, get_face_state=lambda: None, execute_utility=None,
                 visual_capabilities=None, runtime=RUNTIME, clock=time.monotonic, **_unused):
        from signalbar.core.actions import SteamActions
        self.get_config, self.get_game = get_config, get_game
        self.acquire, self.release, self.preflight = acquire, release, preflight
        self.get_facts, self.get_face_state = get_facts, get_face_state
        self.execute_utility, self.visual_capabilities = execute_utility, visual_capabilities
        self.runtime, self.clock = Path(runtime), clock
        self.lock = threading.RLock()
        self.active = self.leased = self.visual_available = self.bar_available = False
        self.frame = None
        self.config = dict(get_config())
        self.restore_origin = {}
        self.event_callback = lambda *_args: None
        self.diagnostic = {'automatic': False, 'state': 'moved', 'error': '', 'url': ''}
        from signalbar.core.power import poweroff
        self.actions = SteamActions(get_game, shutdown=lambda cancel:poweroff(_PowerCommand(), cancel))
        self.session = ''
        self.deadline = 0.0
        self.cancelled = threading.Event()
        self.stop_event = threading.Event()
        self.server = self.thread = self.watchdog = None
        self.error = ''
        self.phase = 'moved'
        self.resetting = False
        self.last_contact = 0.0
        self.owner_file = None
        self.releasing = False

    @property
    def holds_bar(self):
        with self.lock:
            return bool(self.bar_available and self.frame is not None and self.clock() < self.deadline)

    def _event(self, *_args, **_kwargs):
        pass

    def configure(self, _config):
        # Presentation sessions have no access to plugin preference mutation.
        pass

    def remember_game(self, _appid):
        pass

    def start(self):
        # The Decky entry point owns IPC startup. Engine-only consumers/tests
        # must not create a system runtime, open a socket or start any capture.
        pass

    def start_server(self):
        if self.server is not None:
            return
        self.runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = self.runtime.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('Unsafe integration runtime')
        fd = os.open(self.runtime / 'owner.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        owner_file = os.fdopen(fd, 'a+')
        try: fcntl.flock(owner_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            owner_file.close()
            raise RuntimeError('Integration owner already running')
        self.owner_file = owner_file
        self.auth = secrets.token_hex(32)
        path = self.runtime / 'auth'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(self.auth)
        socket_path = self.runtime / 'bridge.sock'
        if socket_path.exists():
            with socket.socket(socket.AF_UNIX) as probe:
                try:
                    probe.settimeout(.2); probe.connect(str(socket_path))
                except (OSError, TimeoutError):
                    socket_path.unlink()
                else:
                    raise RuntimeError('Integration owner already running')
        owner = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(2)
                try:
                    if hasattr(socket, 'SO_PEERCRED'):
                        _pid, uid, _gid = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.getuid(): raise PermissionError('Client identity refused')
                    raw = self.rfile.readline(MAX_MESSAGE + 1)
                    if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'): raise ValueError('Invalid message')
                    message = json.loads(raw)
                    if (message.get('protocol') != PROTOCOL or not isinstance(message.get('auth'), str)
                            or not hmac.compare_digest(message['auth'], owner.auth)):
                        raise PermissionError('Integration authentication refused')
                    result = owner.dispatch(message.get('operation'), message.get('payload', {}))
                    reply = {'ok': True, 'result': result}
                except Exception as error:
                    reply = {'ok': False, 'error': type(error).__name__}
                self.wfile.write(json.dumps(reply, allow_nan=False).encode() + b'\n')
        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
        self.server = Server(str(socket_path), Handler)
        socket_path.chmod(0o600)
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()
        def sweep():
            while not self.stop_event.wait(.2):
                with self.lock:
                    expired = self.session if self.session and self.clock() >= self.deadline else ''
                if expired: self.cancel('lease-expired', expected=expired)
        self.watchdog = threading.Thread(target=sweep, daemon=True)
        self.watchdog.start()

    def stop(self, timeout=1):
        self.stop_event.set()
        self.cancel('stopped')
        if self.server:
            self.server.shutdown(); self.server.server_close(); self.server = None
        for thread in (self.thread, self.watchdog):
            if thread and thread is not threading.current_thread(): thread.join(timeout or 1)
        if self.owner_file is None: return
        for name in ('bridge.sock', 'auth'):
            try: (self.runtime / name).unlink(missing_ok=True)
            except OSError: pass
        self.owner_file.close(); self.owner_file = None

    def _detach_locked(self, matrix, bar):
        release = matrix and self.leased
        if matrix:
            self.cancelled.set(); self.visual_available = self.leased = False
        if bar:
            self.bar_available = False; self.frame = None
        if release: self.releasing = True
        return release

    def _restore(self, release):
        if release:
            try: self.release()
            finally:
                with self.lock: self.releasing = False

    def detach_visuals(self, reason='', *, matrix=True, bar=True):
        with self.lock: release = self._detach_locked(matrix, bar)
        self._restore(release)

    def cancel(self, _reason='', *, expected=None):
        with self.lock:
            if expected is not None and expected != self.session: return False
            release = self._detach_locked(True, True)
            self.active = False; self.session = ''; self.deadline = 0
        self._restore(release)
        return True

    def output(self, _now=None):
        with self.lock:
            return ProviderOutput('external:presentation', normalize_frame(self.frame), 'External presentation') if self.holds_bar else None

    def ui_status(self):
        return {'protocol': PROTOCOL, 'service': 'gca.integrations',
                'connected': bool(self.last_contact and self.clock()-self.last_contact < 3),
                'phase': 'active' if self.active else 'idle', 'active': self.active,
                'capabilities': self.visual_capabilities()}

    status = ui_status

    def dispatch(self, operation, payload):
        if not isinstance(payload, dict): raise ValueError('Invalid payload')
        self.last_contact = self.clock()
        if operation == 'hello':
            return {'protocol': PROTOCOL, 'service': 'gca.integrations',
                    'capabilities': self.visual_capabilities()}
        if operation == 'context':
            return {'facts': self.get_facts(), 'face': self.get_face_state(), 'capabilities': self.visual_capabilities()}
        if operation == 'utility':
            if payload.get('action') not in ('timer_start','timer_add','timer_cancel','profile_auto','profile_apply'):
                raise ValueError('Unsupported utility')
            action, argument = payload['action'], payload.get('argument')
            if action in ('timer_start','timer_add') and (type(argument) is not int or not 1 <= argument <= 1440):
                raise ValueError('Invalid timer duration')
            if action == 'profile_apply' and (not isinstance(argument, str) or not 1 <= len(argument) <= 128):
                raise ValueError('Invalid profile')
            return self.execute_utility(action, argument)
        if operation == 'begin':
            self.cancel('new-session')
            with self.lock:
                if self.releasing or self.session: raise RuntimeError('Visual transition in progress')
                self.preflight()
                self.session = secrets.token_hex(16)
                self.cancelled = threading.Event()
                self.active = True
                self.deadline = self.clock() + LEASE_SECONDS
                capabilities = self.visual_capabilities()
                self.bar_available = capabilities['bar_available']
                self.visual_available = capabilities['matrix_available']
                return {'session': self.session, 'capabilities': capabilities}
        with self.lock:
            if not self.session or payload.get('session') != self.session or self.clock() >= self.deadline:
                raise ValueError('Expired visual session')
            session, cancel = self.session, self.cancelled
        if operation == 'renew':
            frame = payload.get('frame')
            if frame is not None and (not isinstance(frame, list) or len(frame) != 17 or any(
                    not isinstance(pixel, list) or len(pixel) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in pixel) for pixel in frame)):
                raise ValueError('Invalid LED frame')
            with self.lock:
                if self.session != session or self.clock() >= self.deadline:
                    raise ValueError('Expired visual session')
                self.deadline = self.clock() + LEASE_SECONDS
                self.frame = frame if self.bar_available else None
            return {'capabilities': {'bar_available': self.bar_available, 'matrix_available': self.visual_available}}
        if operation == 'release':
            self.cancel('released', expected=session); return {}
        if operation == 'face':
            if not self.visual_available or not self.visual_capabilities()['matrix_available']:
                return {'accepted': False}
            data = base64.b64decode(payload.get('data', ''), validate=True)
            if len(data) > 196608 or not data.startswith((b'GIF87a', b'GIF89a')):
                raise ValueError('Invalid prepared scene')
            if len(data) < 10 or struct.unpack('<HH', data[6:10]) != (64,54):
                raise ValueError('Invalid scene dimensions')
            manifest = payload.get('manifest')
            if not isinstance(manifest, dict): raise ValueError('Invalid scene manifest')
            scene_id = manifest.get('scene_id', 'presentation')
            peak = manifest.get('peak_load')
            if (not isinstance(scene_id,str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',scene_id)
                    or type(peak) not in (int,float) or not math.isfinite(peak) or not 0 <= peak <= 1
                    or manifest.get('signature') != hashlib.sha256(data).hexdigest()):
                raise ValueError('Invalid scene integrity')
            with self.lock:
                if self.session != session or cancel.is_set() or not self.visual_available:
                    raise ValueError('Cancelled scene')
                # Reserve restitution before a transfer can touch hardware.
                self.leased = True
            try: self.acquire(data, manifest, cancel)
            except Exception:
                self.cancel('scene-failed', expected=session)
                raise
            with self.lock:
                if cancel.is_set() or session != self.session: raise ValueError('Cancelled scene')
                self.leased = True
            return {'accepted': True}
        raise ValueError('Unsupported operation')
