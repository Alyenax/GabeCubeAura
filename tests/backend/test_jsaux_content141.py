"""Real plugin broker startup independent of Decky's legacy settings permissions.

Real Unix authentication, no root or USB. The existing library is never touched.
"""
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from signalbar.faceplate.runtime import provision_runtime
from test_cinema_integration import plugin_class
from test_jsaux_broker_core import Adapter


class ContentStorage141Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jc141-', dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.runtime = self.root / 'runtime'
        self.settings = self.root / 'settings'
        self.settings.mkdir(mode=0o755)
        self.legacy = self.settings / 'jsaux-broker'
        self.legacy.mkdir(mode=0o755)
        self.legacy.chmod(0o755)
        self.marker = self.legacy / 'preserve.gif'
        self.marker.write_bytes(b'legacy-cache-preserved')
        cls = plugin_class()
        self.namespace = cls._main.__globals__
        self.plugin = cls()
        self.plugin.engine = SimpleNamespace(jsaux_broker_adapter=Adapter())
        self.plugin._jsaux_broker_start_lock = threading.Lock()
        self.plugin.jsaux_broker_server = self.plugin.jsaux_broker = None
        self.namespace['decky'].DECKY_PLUGIN_SETTINGS_DIR = str(self.settings)
        self.patches = patch.dict(self.namespace, CANONICAL_RUNTIME=self.runtime, PERSISTENT_JSAUX_CONTENT=self.root / "persistent-content",
                                  provision_runtime=provision_runtime)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.addCleanup(self.stop)

    def stop(self):
        broker = self.plugin.jsaux_broker
        self.plugin._stop_jsaux_broker(timeout=2)
        if broker:
            broker.worker.shutdown(wait=True)
        self.plugin.jsaux_broker = self.plugin.jsaux_broker_server = None

    def exchange(self):
        server, broker = self.plugin.jsaux_broker_server, self.plugin.jsaux_broker
        credential = json.loads(server.credential_path.read_text())
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(server.socket_path))
            with client.makefile('rwb', buffering=0) as stream:
                for op, args in (
                    ('hello', dict(capability=credential['capability'],
                                   client_instance_id=str(uuid.uuid4()), supported_versions=['1.0'])),
                    ('status', {}), ('goodbye', {})):
                    message = dict(protocol='jsaux-broker', version='1.0',
                                   request_id=op, op=op, args=args)
                    if op != 'hello':
                        message['boot_id'] = broker.boot_id
                    stream.write(json.dumps(message).encode() + b'\n')
                    response = json.loads(stream.readline())
                    self.assertTrue(response['ok'], response)

    def test_legacy_nonprivate_settings_cache_is_preserved_and_real_socket_works_after_restart(self):
        inode = self.legacy.stat().st_ino
        for _ in range(2):
            self.assertTrue(self.plugin._start_jsaux_broker())
            broker = self.plugin.jsaux_broker
            self.assertEqual(broker.root, self.root / 'persistent-content')
            for directory in (broker.root, broker.contents_dir, broker.staging_dir):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                self.assertEqual(directory.stat().st_uid, os.geteuid())
            self.exchange()
            self.assertEqual(self.plugin._broker_diagnostic_snapshot()['startup_stage'], 'ready')
            self.assertEqual(broker.adapter.jobs, [])
            self.stop()
        self.assertEqual(self.legacy.stat().st_ino, inode)
        self.assertEqual(stat.S_IMODE(self.legacy.stat().st_mode), 0o755)
        self.assertEqual(self.marker.read_bytes(), b'legacy-cache-preserved')

    def test_legacy_settings_symlink_is_not_followed_or_repaired(self):
        real = self.legacy.with_name('old-cache')
        self.legacy.rename(real)
        self.legacy.symlink_to(real, target_is_directory=True)
        self.assertTrue(self.plugin._start_jsaux_broker())
        self.exchange()
        self.assertTrue(self.legacy.is_symlink())
        self.assertEqual((real / 'preserve.gif').read_bytes(), b'legacy-cache-preserved')
        self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o755)

    def test_unsafe_runtime_content_cache_still_refused_without_repair(self):
        provision_runtime(self.runtime)
        cache = self.root / 'persistent-content'
        cache.mkdir(mode=0o755)
        cache.chmod(0o755)
        self.assertFalse(self.plugin._start_jsaux_broker())
        self.assertEqual(self.plugin._jsaux_broker_stage, 'content-storage')
        self.assertIsNone(self.plugin.jsaux_broker_server)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o755)
        self.assertFalse((self.runtime / 'control.sock').exists())

    @unittest.skipUnless(os.environ.get('GCA_TEST_DAS_ROOT'), 'explicit real DAS checkout required')
    def test_actual_das_client_after_real_plugin_start_registers_acquires_and_restores(self):
        # Optional source-only interop gate, never a runtime dependency/import.
        source = Path(os.environ['GCA_TEST_DAS_ROOT']).resolve() / 'py_modules'
        with patch.object(sys, 'path', [str(source), *sys.path]):
            from das.jsaux.client import BrokerClient
            from das.jsaux.collection import compile_pages
        self.assertTrue(self.plugin._start_jsaux_broker())
        client = BrokerClient(self.runtime)
        self.addCleanup(client.close)
        self.assertEqual(client.discover()['hardware'], 'available')
        self.assertEqual(client.diagnostic_snapshot(), {'state': 'connected'})
        data, _ = compile_pages([bytes(3456), bytes([0xe0]) * 3456], 8, 'fade')
        asset = self.root / 'fixture.gif'
        asset.write_bytes(data)
        result = client.register(asset, 'c' * 64)
        deadline = time.monotonic() + 12
        while 'content_id' not in result and time.monotonic() < deadline:
            receipt = client.operation(validation_id=result['validation_id'])
            self.assertNotEqual(receipt['state'], 'rejected', receipt)
            if receipt['state'] == 'ready':
                result = receipt
            else:
                time.sleep(.02)
        self.assertIn('content_id', result)
        adapter = self.plugin.engine.jsaux_broker_adapter
        self.assertEqual(adapter.jobs, [])  # Preparation never touches USB.
        lease = client.acquire(activation_id='activation-1', session_id='session141',
                               content_id=result['content_id'], collection_id='c' * 64, mode='sync')
        common = dict(lease_id=lease['lease_id'], generation=lease['generation'])
        now = time.monotonic_ns() // 1000000
        # Use the actually negotiated envelope, not the retired 2.5s fixture:
        # current DAS fade collections can exceed that old transfer budget.
        wait = client.hello['limits']['sync_wait_ms']
        client.ready(**common, alignment_attempt_id=lease['alignment_attempt_id'],
                     ready_mono_ms=now, deadline_mono_ms=now + wait, clock_uncertainty_ms=2)
        self.assertEqual(len(adapter.jobs), 1)
        adapter.report(lease['operation_id'], transfer_state='confirmed', fresh_ack=True)
        receipt = client.operation(operation_id=lease['operation_id'])
        self.assertEqual(receipt['transfer_state'], 'confirmed')
        client.release(**common, reason='player-ended')
        self.assertEqual(adapter.restorations, [lease['operation_id']])
        # Adapter reports unconfirmed restore deliberately: never invent an ACK.
        self.assertEqual(client.operation(operation_id=lease['operation_id'])['restore_state'], 'unconfirmed')
        self.assertEqual(self.marker.read_bytes(), b'legacy-cache-preserved')
