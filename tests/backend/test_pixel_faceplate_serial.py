"""Linux PTY integration against the pinned, unchanged Pixel Faceplate 0.3.1.

Real processes, UIDs, /proc, tty opens, termios and flock; a virtual device ACKs
wire packets. Rendering, USB discovery, the GCA ownership broker and elapsed
poll time are explicit substitutes. No physical USB/firmware claim is made.
"""
from __future__ import annotations
import ast
import base64
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import threading
import time
from types import ModuleType, SimpleNamespace
import tty
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('GCA_HANDOFF_SOURCE', ROOT))
FIXTURE = ROOT / 'tests/fixtures/pixel_faceplate_031'
TRANSPORT = Path(os.environ.get('GCA_TRANSPORT_SOURCE', SOURCE / 'py_modules/signalbar/faceplate/transport.py'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def pixel_modules():
    package = ModuleType('_pixel_fixture')
    package.__path__ = [str(FIXTURE)]
    sys.modules[package.__name__] = package
    protocol = load('_pixel_fixture.protocol', FIXTURE / 'protocol.py')
    transport = load('_pixel_fixture.transport', FIXTURE / 'transport.py')
    handoff = load('_pixel_fixture.handoff', FIXTURE / 'handoff.py')
    return protocol, transport, handoff


def gca_link():
    """Use the production arbitration methods, not a rewritten flock facsimile."""
    tree = ast.parse(TRANSPORT.read_text())
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {
                'port_owners', 'port_owner_details', 'LinkError', 'LinkBusy', 'Link'}:
            if node.name == 'Link':
                node.body = [n for n in node.body if isinstance(n, ast.FunctionDef)
                             and n.name in {'__init__', 'open', 'close'}]
            selected.append(node)
    ns = dict(os=os, Path=Path, errno=errno, fcntl=fcntl, termios=termios,
              PROFILE_BASELINE='baseline', TRANSPORT_PROFILES=('baseline', 'vendor', 'auto'),
              _ownership_manager=None)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(TRANSPORT), 'exec'), ns)
    return ns['Link']


def actor(role, home, port):
    protocol, transport, handoff = pixel_modules()
    claim = load('_claim', SOURCE / 'py_modules/signalbar/faceplate_claim.py')
    home = Path(home)
    settings = home / 'settings/GabeCubeAura'
    os.umask(0o077)
    link = gca_link()(port=port) if role == 'gca' else None
    if role == 'pixel':
        # Keep service control, handoff, uploads and transport intact; replace
        # only artwork providers / encoder and USB discovery in its imports.
        clock = SimpleNamespace(now=120., wall=120.)
        clock.monotonic = lambda: clock.now
        clock.time = lambda: clock.wall
        clock.sleep = lambda delay: None
        ns = dict(hashlib=hashlib, json=json, os=os, threading=threading, time=clock,
                  protocol=protocol, Link=transport.Link, LinkBusy=transport.LinkBusy,
                  LinkError=transport.LinkError, find_port=lambda: port,
                  gif=SimpleNamespace(PixelAnimation=type('UnusedAnimation', (), {})),
                  pictures=SimpleNamespace(PictureFeed=lambda **kwargs: None),
                  render=SimpleNamespace(clock=lambda **kwargs: b'\x00' * (64 * 54 * 3)),
                  parse_color=lambda color: (0, 0, 0), for_game=lambda cfg, appid: cfg)
        tree = ast.parse((FIXTURE / 'service.py').read_text())
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        exec(compile(tree, str(FIXTURE / 'service.py'), 'exec'), ns)
        # A deterministic valid 64x54 GIF is supplied in place of image encoding.
        data = base64.b64decode(TEST_GIF)
        ns['encode_frame'] = lambda rgb: data
        ns['MIN_UPLOAD_GAP'] = 0.
        service = ns['FaceplateService'](
            {'mode': 'clock', 'brightness': 30, 'rotate': False, 'clock_color': '#ffffff',
             'clock_24h': True, 'sleep_action': 'off', 'shutdown_action': 'off'},
            link_factory=lambda **kw: transport.Link(port=port, **kw),
            owner_check=lambda: handoff.faceplate_owner(str(home / 'plugins')))
    print(json.dumps({'ready': True, 'pid': os.getpid(), 'uid': os.geteuid()}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        op = request['op']
        try:
            if role == 'gca':
                if op == 'claim':
                    result = {'claimed': claim.claim(str(settings))}
                elif op == 'release':
                    link.close()
                    claim.release(str(settings))
                    result = {'released': True}
                elif op == 'open':
                    if link.fd is None:
                        link.open()
                    result = {'open': link.fd is not None}
                elif op == 'close':
                    link.close()
                    result = {'closed': True}
                elif op == 'power':
                    # Direct write only AFTER the real GCA open acquired its
                    # lock. Packet bytes/ACKs use the peer's unchanged protocol.
                    os.write(link.fd, protocol.power(request['enabled']))
                    termios.tcdrain(link.fd)
                    result = {'sent': True}
                else:
                    raise ValueError(op)
            else:
                if op == 'step':
                    clock.now += request.get('advance', 0.)
                    clock.wall += request.get('advance', 0.)
                    delay = service.step()
                    result = dict(service.status(), delay=delay)
                elif op == 'sleep':
                    service.power_event('sleep', request['starting'])
                    result = service.status()
                elif op == 'raw_open':
                    if link is None:
                        link = transport.Link(port=port)
                    link.open()
                    result = {'open': True}
                else:
                    raise ValueError(op)
            result['ok'] = True
        except Exception as error:
            result = {'ok': False, 'error': type(error).__name__, 'detail': str(error)}
        print(json.dumps(result), flush=True)


TEST_GIF = 'R0lGODdhQAA2AIAAAAAAAAAAACwAAAAAQAA2AEAIYAABCBxIsKDBgwgTKlzIsKHDhxAjSpxIsaLFixgzatzIsaPHjyBDihxJsqTJkyhTqlzJsqXLlzBjypxJs6bNmzhz6tzJs6fPn0CDCh1KtKjRo0iTKl3KtKnTp1CjSq0ZEAA7'


class Process:
    def __init__(self, script, role, home, port, uid=None):
        def drop():
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
        self.p = subprocess.Popen([sys.executable, str(script), role, str(home), port],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True,
                                  preexec_fn=drop if uid is not None else None)
        self.ready = self.read()

    def read(self):
        if not select.select([self.p.stdout], [], [], 6)[0]:
            raise TimeoutError('test actor did not reply')
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(self.p.stderr.read())
        return json.loads(line)

    def call(self, op, **values):
        self.p.stdin.write(json.dumps(dict(op=op, **values)) + '\n')
        self.p.stdin.flush()
        return self.read()

    def kill(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.communicate(timeout=5)


@unittest.skipUnless(sys.platform.startswith('linux'), 'requires Linux PTY/flock/proc')
class SerialCoexistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gca-serial-')
        self.home = Path(self.tmp.name)
        self.home.chmod(0o755)
        self.addCleanup(self.tmp.cleanup)
        self.settings = self.home / 'settings/GabeCubeAura'
        self.settings.mkdir(parents=True)
        self.settings.chmod(0o700)
        self.split_uids = os.geteuid() == 0
        if self.split_uids:
            os.chown(self.settings, 65534, 65534)
        self.script = self.home / 'plugins/GabeCubeAura/main.py'
        self.script.parent.mkdir(parents=True)
        self.script.write_text(
            'import runpy,sys\n'
            f'm=runpy.run_path({str(Path(__file__).resolve())!r})\n'
            "m['actor'](*sys.argv[1:])\n")
        self.master, slave = pty.openpty()
        tty.setraw(slave)
        self.port = os.ttyname(slave)
        os.chmod(self.port, 0o666)
        os.close(slave)
        self.stop = threading.Event()
        self.frames = []
        self.junk = bytearray()
        self.frame_lock = threading.Lock()
        self.protocol = pixel_modules()[0]
        self.device = threading.Thread(target=self.firmware, daemon=True)
        self.device.start()
        self.addCleanup(self.close_device)
        self.gca = self.spawn('gca')
        self.pixel = self.spawn('pixel')

    def spawn(self, role):
        proc = Process(self.script, role, self.home, self.port,
                       uid=65534 if role == 'pixel' and self.split_uids else None)
        self.addCleanup(proc.kill)
        return proc

    def close_device(self):
        self.stop.set()
        self.device.join(timeout=2)
        os.close(self.master)

    def firmware(self):
        rx = bytearray()
        while not self.stop.is_set():
            if not select.select([self.master], [], [], .02)[0]:
                continue
            try:
                data = os.read(self.master, 4096)
            except OSError as error:
                if error.errno == errno.EIO:
                    self.stop.wait(.01)
                    continue
                raise
            rx.extend(data)
            replies, junk = self.protocol.parse(rx)
            with self.frame_lock:
                self.junk.extend(junk)
                for reply in replies:
                    self.frames.append((reply.kind, reply.cmd, bytes(reply.payload)))
            for reply in replies:
                if (reply.kind, reply.cmd) != (1, 2):  # brightness has no ACK
                    os.write(self.master, self.protocol.frame(reply.kind, reply.cmd, b'\x01'))

    def frame_count(self):
        # Drain any writes already returned by the actors, without polling USB.
        time.sleep(.04)
        with self.frame_lock:
            return len(self.frames)

    def test_pixel_first_claim_yield_gca_then_pixel_resume(self):
        initial = self.pixel.call('step')
        self.assertTrue(initial['connected'], initial)
        self.assertEqual(initial['uploads'], 1)
        self.assertTrue(self.gca.call('claim')['claimed'])
        self.assertFalse(self.gca.call('open')['ok'])  # no writer interleaving
        waiting = self.pixel.call('step', advance=29)
        self.assertEqual(waiting['handed_to'], '')
        self.assertFalse(self.gca.call('open')['ok'])
        yielded = self.pixel.call('step', advance=1)
        self.assertEqual(yielded['handed_to'], 'GabeCubeAura')
        self.assertFalse(yielded['connected'])
        self.assertTrue(self.gca.call('open')['ok'])
        self.assertTrue(self.gca.call('power', enabled=False)['ok'])
        before = self.frame_count()
        self.pixel.call('sleep', starting=True)
        self.pixel.call('sleep', starting=False)
        self.pixel.call('step', advance=60)
        self.assertEqual(self.frame_count(), before)  # no wake or image from peer
        self.gca.call('release')
        resumed = self.pixel.call('step', advance=30)
        self.assertEqual(resumed['handed_to'], '')
        self.assertTrue(resumed['connected'])
        self.assertEqual(resumed['uploads'], 2)
        self.assertEqual(self.junk, b'')

    def test_gca_first_pixel_does_not_open_or_write(self):
        self.assertTrue(self.gca.call('claim')['claimed'])
        self.assertTrue(self.gca.call('open')['ok'])
        state = self.pixel.call('step')
        self.assertEqual(state['phase'], 'handed over')
        self.assertFalse(state['connected'])
        self.assertEqual(self.frame_count(), 0)
        self.assertFalse(self.pixel.call('raw_open')['ok'])
        self.gca.call('release')
        self.assertTrue(self.pixel.call('step', advance=30)['connected'])

    def test_crash_releases_kernel_lock_and_dead_claim_is_ignored(self):
        self.gca.call('claim')
        self.gca.call('open')
        self.assertEqual(self.pixel.call('step')['phase'], 'handed over')
        self.gca.kill()
        self.assertTrue((self.settings / 'faceplate-claim.json').exists())
        self.assertTrue(self.pixel.call('step', advance=30)['connected'])

    def test_old_process_cannot_remove_new_process_claim(self):
        self.gca.call('claim')
        replacement = self.spawn('gca')
        self.assertTrue(replacement.call('claim')['claimed'])
        self.gca.call('release')
        self.assertEqual(json.loads((self.settings / 'faceplate-claim.json').read_text())['pid'],
                         replacement.ready['pid'])
        self.assertEqual(self.pixel.call('step')['phase'], 'handed over')
        replacement.call('release')
        self.assertTrue(self.pixel.call('step', advance=30)['connected'])

    def test_clock_mode_does_not_promise_a_thirty_second_upper_bound(self):
        state = self.pixel.call('step')
        self.assertEqual(state['delay'], 60.5)
        self.gca.call('claim')
        self.assertFalse(self.gca.call('open')['ok'])
        self.assertEqual(self.pixel.call('step', advance=state['delay'])['phase'], 'handed over')
        self.assertTrue(self.gca.call('open')['ok'])

    def test_twenty_round_trips_no_interleaved_frames(self):
        self.assertTrue(self.pixel.call('step')['connected'])
        for cycle in range(20):
            self.assertTrue(self.gca.call('claim')['claimed'])
            self.assertEqual(self.pixel.call('step', advance=31)['phase'], 'handed over')
            self.assertTrue(self.gca.call('open')['ok'])
            self.assertFalse(self.pixel.call('raw_open')['ok'])
            self.assertTrue(self.gca.call('power', enabled=False)['ok'])
            self.gca.call('release')
            self.assertTrue(self.pixel.call('step', advance=31)['connected'])
        self.assertEqual(self.junk, b'')


class FixtureIntegrityTests(unittest.TestCase):
    def test_peer_sources_are_byte_identical_to_pinned_upstream(self):
        for name, expected in {
            'handoff.py': 'd741d497a566edfbbbdbf30a033d8a3e08a89045',
            'protocol.py': '14103953759977f2b29298fe7dc95d08d67c52db',
            'transport.py': 'e7cb91171bd37193e12b087fa72bc3b07fe703ca',
            'service.py': 'e31dd2b05566ce59c67d4ba6e76a92894659e3c4',
        }.items():
            with self.subTest(file=name):
                data = (FIXTURE / name).read_bytes()
                self.assertEqual(hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
