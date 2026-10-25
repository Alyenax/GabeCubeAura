"""Runtime bootstrap with real ownership flocks and Unix broker connections.

The temporary hierarchy uses this test process's real UID. It does not prove
root-to-Steam permissions, USB playback, or a Steam Machine's systemd setup.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock, patch

from signalbar.faceplate.transport import PhysicalOwnership
from signalbar.jsaux_broker import Broker, BrokerServer
from signalbar.jsaux_broker import server as server_module
from signalbar.faceplate import runtime as runtime_module
from test_cinema_integration import plugin_class
from test_jsaux_broker_core import Adapter


class Runtime139Tests(unittest.TestCase):
    def setUp(self):
        # Keep paths below Darwin's sockaddr_un bound and resolve /var aliases.
        self.temporary=tempfile.TemporaryDirectory(prefix='jr139-',dir='/private/tmp')
        self.root=Path(self.temporary.name).resolve()
        self.runtime=self.root/'run'/'decky'/'jsaux-broker'/'v1'
        (self.root/'run').mkdir(mode=0o755)
        self.owners=[];self.servers=[];self.brokers=[]
        self.patches=ExitStack()
        self.patches.enter_context(patch.object(runtime_module,'CANONICAL_RUNTIME',self.runtime))
        self.patches.enter_context(patch.object(server_module,'CANONICAL_RUNTIME',self.runtime))

    def tearDown(self):
        for server in reversed(self.servers):server.stop()
        for broker in reversed(self.brokers):
            broker.stop();broker.worker.shutdown(wait=True)
        for owner in reversed(self.owners):owner.close()
        self.patches.close();self.temporary.cleanup()

    def owner(self):
        value=PhysicalOwnership(self.runtime/'ownership');self.owners.append(value)
        return value

    def provision(self):
        return runtime_module.provision_runtime(self.runtime,expected_uid=os.geteuid())

    def legacy_claim(self):
        # Reproduce Lab138: mkdir(parents=True) made v1 0755 before broker
        # provisioning. Only the ownership leaf and actual lock were private.
        self.runtime.mkdir(parents=True,mode=0o755)
        self.runtime.chmod(0o755)
        owner=self.owner()
        self.assertTrue(owner.claim(str(self.root/'fake-usb-tty')))
        # Keep the old on-disk state while the real ownership flock is held;
        # the new claim implementation may already have secured the parent.
        self.runtime.chmod(0o755)
        lock=self.runtime/'ownership'/(owner.key(str(self.root/'fake-usb-tty'))+'.lock')
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(lock.parent.stat().st_mode),0o700)
        return owner,lock

    def start_server(self):
        broker=Broker(self.root/('content-'+uuid.uuid4().hex[:6]),Adapter())
        self.brokers.append(broker)
        server=BrokerServer(broker,self.runtime);self.servers.append(server)
        self.assertTrue(server.start())
        return broker,server

    def exchange(self,server,broker):
        credential=json.loads(server.credential_path.read_text())
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(2);client.connect(str(server.socket_path))
            stream=client.makefile('rwb',buffering=0)
            with stream:
                for op,args in (
                    ('hello',{'capability':credential['capability'],'client_instance_id':str(uuid.uuid4()),'supported_versions':['1.0']}),
                    ('status',{}),('goodbye',{})):
                    message={'protocol':'jsaux-broker','version':'1.0','request_id':op,'op':op,'args':args}
                    if op!='hello':message['boot_id']=broker.boot_id
                    stream.write(json.dumps(message,separators=(',',':')).encode()+b'\n')
                    response=json.loads(stream.readline())
                    self.assertTrue(response['ok'],response)

    def test_legacy_0755_runtime_migrates_with_live_ownership_then_real_client_connects(self):
        owner,lock=self.legacy_claim();inode=lock.stat().st_ino
        self.provision()
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode),0o700)
        self.assertEqual(lock.stat().st_ino,inode)
        self.assertTrue(owner.claim(str(self.root/'fake-usb-tty')))
        broker,server=self.start_server();self.exchange(server,broker)
        self.assertFalse(broker.adapter.jobs)
        self.assertFalse(broker.adapter.reservations)
        self.assertFalse(broker.adapter.restorations)

    def test_migration_is_idempotent_under_concurrency_and_preserves_held_lock(self):
        _,lock=self.legacy_claim();inode=lock.stat().st_ino
        barrier=threading.Barrier(4)
        def provision(_):barrier.wait(timeout=3);return self.provision()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(provision,range(4)))
        self.provision()
        self.assertEqual(lock.stat().st_ino,inode)
        contender=self.owner()
        self.assertFalse(contender.claim(str(self.root/'fake-usb-tty')))

    def test_restart_keeps_ownership_inode_and_never_unlinks_live_endpoint(self):
        _,lock=self.legacy_claim();self.provision();inode=lock.stat().st_ino
        broker,server=self.start_server();socket_inode=server.socket_path.stat().st_ino
        contender=BrokerServer(broker,self.runtime);self.servers.append(contender)
        with self.assertRaises(OSError):contender.start()
        self.assertEqual(server.socket_path.stat().st_ino,socket_inode)
        self.exchange(server,broker)
        server.stop()
        second,ready=self.start_server();self.exchange(ready,second)
        self.assertEqual(lock.stat().st_ino,inode)
        self.assertFalse(self.owner().claim(str(self.root/'fake-usb-tty')))

    def test_custom_0755_is_not_silently_repaired(self):
        custom=self.root/'custom';custom.mkdir(mode=0o755);custom.chmod(0o755)
        with self.assertRaises((PermissionError,runtime_module.RuntimeSecurityError)):
            runtime_module.provision_runtime(custom,expected_uid=os.geteuid())
        self.assertEqual(stat.S_IMODE(custom.stat().st_mode),0o755)

    def test_writable_or_symlink_canonical_runtime_is_never_repaired(self):
        self.runtime.mkdir(parents=True,mode=0o777);self.runtime.chmod(0o777)
        with self.assertRaises((PermissionError,runtime_module.RuntimeSecurityError)):self.provision()
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode),0o777)
        self.runtime.rmdir()
        target=self.root/'untouched';target.mkdir(mode=0o700)
        sentinel=target/'sentinel';sentinel.write_text('keep')
        self.runtime.symlink_to(target,target_is_directory=True)
        with self.assertRaises((PermissionError,runtime_module.RuntimeSecurityError)):self.provision()
        self.assertEqual(sentinel.read_text(),'keep');self.assertTrue(self.runtime.is_symlink())


class PluginRuntime139Tests(unittest.IsolatedAsyncioTestCase):
    async def bootstrap(self,root,*,deny=False):
        cls=plugin_class();namespace=cls._main.__globals__
        runtime=root/'run'/'decky'/'jsaux-broker'/'v1'
        (root/'run').mkdir(mode=0o755)
        decky=namespace['decky']
        decky.DECKY_PLUGIN_SETTINGS_DIR=str(root/'settings')
        decky.DECKY_PLUGIN_RUNTIME_DIR=str(root/'runtime')
        decky.DECKY_PLUGIN_DIR=str(root/'plugin')
        (root/'settings').mkdir(mode=0o700)
        engine=Mock();diagnostics=Mock()
        diagnostics.state_dir=root/'settings'
        engine.settings.all.return_value={'faceplate_lab_enabled':False}
        engine.assistant.diagnostic={};engine.faceplate_game_snapshot.return_value={'appid':0}
        diagnostics.status.return_value={'automatic_upload':False}
        diagnostics.automatic_upload_due.return_value=False
        events=[];owners=[];servers=[]
        adapter=Adapter()
        def provision(*args,**kwargs):
            events.append('provision')
            if deny:raise PermissionError('fixture unsafe hierarchy')
            return runtime_module.provision_runtime(runtime,expected_uid=os.geteuid())
        def make_adapter(engine,ownership_root):
            self.assertEqual(ownership_root,runtime/'ownership')
            owner=PhysicalOwnership(ownership_root);owners.append(owner)
            adapter.ownership=owner
            return adapter
        def make_server(broker,**kwargs):
            server=BrokerServer(broker,**kwargs);servers.append(server);return server
        def engine_start():
            events.append('engine-start')
            if not deny:
                self.assertTrue(servers[0].listener)
                self.assertTrue(owners[0].claim(str(root/'fake-usb-tty')))
                events.append('ownership-claim')
                self.assertLess(events.index('provision'),events.index('ownership-claim'))
        engine.start.side_effect=engine_start
        plugin=cls();plugin._configure_faceplate_power_events=Mock()
        with patch.object(runtime_module,'CANONICAL_RUNTIME',runtime),\
             patch.object(server_module,'CANONICAL_RUNTIME',runtime),\
             patch.dict(namespace,Engine=Mock(return_value=engine),DiagnosticJournal=Mock(return_value=diagnostics),
                        FaceplatePreferencesStore=Mock(),FaceplateBrokerAdapter=make_adapter,
                        CANONICAL_RUNTIME=runtime,PERSISTENT_JSAUX_CONTENT=root/'persistent-content',provision_runtime=provision,
                        BrokerServer=make_server,PowerEvents=Mock(),UpdateManager=Mock(),
                        PixelStudioManager=Mock(),ArtworkPreparationJobs=Mock()),\
             patch.dict(os.environ,{'DECKY_USER_HOME':str(root)}):
            try:
                await plugin._main()
                if not deny:
                    task=getattr(plugin,'_jsaux_recovery_task',None)
                    if task:await task
                    self.assertEqual(plugin._jsaux_broker_stage,'ready')
                    self.assertTrue(plugin.jsaux_broker_server.status()['available'])
                else:
                    self.assertIsNone(plugin.jsaux_broker_server)
                    self.assertNotEqual(plugin._jsaux_broker_stage,'ready')
                engine.start.assert_called_once()
                return events
            finally:
                automatic=getattr(plugin,'automatic_incidents',None)
                if automatic:await automatic.close()
                task=getattr(plugin,'_jsaux_recovery_task',None)
                if task:
                    task.cancel()
                    try:await task
                    except asyncio.CancelledError:pass
                plugin._stop_jsaux_broker(timeout=2)
                for server in servers:server.stop()
                if getattr(plugin,'jsaux_broker',None):plugin.jsaux_broker.worker.shutdown(wait=True)
                for owner in owners:owner.close()

    async def test_real_bootstrap_provisions_before_ownership_and_engine_start(self):
        with tempfile.TemporaryDirectory(prefix='jp139-',dir='/private/tmp') as directory:
            events=await self.bootstrap(Path(directory).resolve())
            self.assertIn('provision',events);self.assertIn('ownership-claim',events)

    async def test_permission_refusal_never_prevents_engine_start(self):
        with tempfile.TemporaryDirectory(prefix='jp139-',dir='/private/tmp') as directory:
            events=await self.bootstrap(Path(directory).resolve(),deny=True)
            self.assertIn('engine-start',events)


if __name__=='__main__':unittest.main()
