import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.models import normalize_frame, GameState, ProviderOutput
from signalbar.faceplate.transport import Link, ReplyTimeout, GifCommitUnconfirmed, LinkError
from signalbar.faceplate import protocol
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.routing import FaceplateSceneRouter
from signalbar.faceplate.service import FaceplateWorker


class FakeHardware:
    device_path='/test/lab101'; reverse=False
    def __init__(self): self.frame=normalize_frame([(1,2,3)]*17)
    def set_reverse(self,value): self.reverse=value
    def read_frame(self): return self.frame
    def read_signature(self): return self.frame
    def write_frame(self,value): self.frame=value
    def try_restore(self,value): self.frame=value


class RuntimeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.settings=SettingsStore(str(Path(self.directory.name)/'settings.json'))
        self.settings.update({'home_display':'customization','game_display':'customization',
                              'faceplate_lab_enabled':True,'valve_ownership_policy':'critical'})
        self.hardware=FakeHardware()
        self.engine=Engine(self.settings,str(Path(self.directory.name)/'cache'),hardware_factory=lambda:self.hardware)
        self.engine.assistant=Mock(active=False,holds_bar=False,output=Mock(return_value=None))
        self.engine.faceplate_worker=Mock(); self.engine.faceplate_worker.status.return_value={}
        self.engine.faceplate.set_power=Mock(return_value={'ok':True,'powered':True,'error':''})
        self.engine.faceplate.device_status=Mock(return_value={'available':True,'port':'/test','busy':False})
        self.engine._write_faceplate_runtime_status=Mock()
        self.engine._reconcile_faceplate=Mock(return_value=0)
        self.addCleanup(self.engine.stop)

    def wait_for(self, predicate, seconds=3):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue(predicate())

    def test_reconcile_failure_preserves_bar_and_is_bounded_and_traceable(self):
        self.engine._reconcile_faceplate.side_effect=ValueError('route snapshot failure')
        self.engine.start()
        self.wait_for(lambda:self.engine._owner=='GabeCubeAura')
        self.assertTrue(self.engine._thread.is_alive())
        self.assertTrue(any(any(rgb) for rgb in self.hardware.frame))
        self.assertEqual(self.engine._reconcile_faceplate.call_count,1)
        failure=self.engine.display_control_snapshot()['runtime_failures'][-1]
        self.assertEqual(failure['stage'],'faceplate-maintenance')
        self.assertIn('ValueError: route snapshot failure',failure['error'])
        self.assertIn('_run_loop',failure['traceback'])
        self.assertTrue(failure['stack'])

    def test_fault_before_renderer_try_recovers_on_same_thread(self):
        refresh=self.engine.performance.refresh
        calls=[0]
        def fail_once(*args,**kwargs):
            calls[0]+=1
            if calls[0]==1: raise RuntimeError('early engine failure')
            return refresh(*args,**kwargs)
        self.engine.performance.refresh=fail_once
        self.engine.start(); thread=self.engine._thread
        self.wait_for(lambda:self.engine._owner=='GabeCubeAura')
        self.assertIs(self.engine._thread,thread); self.assertTrue(thread.is_alive())
        self.assertIn('early engine failure',self.engine._last_runtime_error)

    def test_engine_keeps_unconfirmed_weather_ticket_without_claiming_or_repeating_it(self):
        self.engine.faceplate_preferences.update(home_scene='weather')
        self.engine._faceplate_weather_payload=Mock(return_value=({'signature':'same',
            'condition':'rain','variant':0,'temperature_c':12,'unit':'celsius','phase':'night'}, {}, ''))
        self.engine.faceplate_worker.status.return_value={'busy':False,'queued':False}
        self.engine.faceplate_worker.submit.return_value=1
        self.engine._reconcile_faceplate=Engine._reconcile_faceplate.__get__(self.engine)
        self.assertEqual(self.engine._reconcile_faceplate(),1)
        call=self.engine.faceplate_worker.submit.call_args
        request={'payload':call.args[1],'metadata':call.args[2]}
        self.engine._render_faceplate_scene=Mock(return_value=(b'data',{'signature':'new'}))
        self.engine.faceplate.synchronize_scene=Mock(return_value={'sent_unconfirmed':True,
            'synchronized':False,'error':'no reply to type=0x01 cmd=0x0b'})
        self.engine._handle_faceplate_scene(request)
        route=self.engine.faceplate_router.status()
        self.assertEqual(route['preparation']['state'],'unconfirmed')
        self.assertEqual(route['effective_content_key'],'')
        self.assertEqual(self.engine._reconcile_faceplate(),0)
        self.assertEqual(self.engine.faceplate_worker.submit.call_count,1)

    def test_cleanup_failure_is_isolated_from_engine_recovery(self):
        self.engine._run_loop=Mock(side_effect=[RuntimeError('primary fault'), None])
        self.engine.assistant.cancel.side_effect=RuntimeError('secondary cleanup failure')
        self.engine.start()
        self.wait_for(lambda:self.engine._run_loop.call_count==2)
        failures=self.engine.display_control_snapshot()['runtime_failures']
        self.assertTrue(any(item['stage']=='engine' for item in failures))
        self.assertTrue(any(item['stage']=='assistant-cancel' for item in failures))

    # Voice-specific test transferred to DVA migration archive.


class DeliveryTests(unittest.TestCase):
    # Voice-specific test transferred to DVA migration archive.

    def test_only_final_reply_timeout_is_unconfirmed_and_never_reuploads_via_fallback(self):
        link=Link('/test',transport_profile='auto')
        reply=protocol.Reply(1,1,b'\x01')
        def command(data,**kwargs):
            if data==protocol.gif_end(): raise ReplyTimeout('no reply to type=0x01 cmd=0x0b')
            return reply
        with patch.object(link,'command',side_effect=command) as commands, patch('signalbar.faceplate.transport.time.sleep'):
            with self.assertRaises(GifCommitUnconfirmed): link.send_gif(b'payload')
        self.assertEqual(link.last_transfer_timings['attempt_profiles'],['baseline'])
        self.assertTrue(link.last_transfer_timings['payload_complete'])
        self.assertTrue(link.last_transfer_timings['end_sent'])
        self.assertTrue(link.last_transfer_timings['sent_unconfirmed'])
        self.assertEqual(commands.call_count,3)

    def test_missing_chunk_reply_or_refused_final_reply_remains_failed(self):
        for kind in ('chunk','refused'):
            link=Link('/test')
            def command(data,**kwargs):
                if kind=='chunk' and data[2]==protocol.TYPE_DATA: raise ReplyTimeout('chunk missing')
                return protocol.Reply(1,1,b'\xff' if kind=='refused' and data==protocol.gif_end() else b'\x01')
            with patch.object(link,'command',side_effect=command),patch('signalbar.faceplate.transport.time.sleep'):
                with self.assertRaises(LinkError) as caught: link.send_gif(b'payload')
            self.assertNotIsInstance(caught.exception,GifCommitUnconfirmed)
            self.assertFalse(link.last_transfer_timings['sent_unconfirmed'])

    def test_unconfirmed_delivery_does_not_claim_flash_write_or_effective_route(self):
        class FakeLink:
            last_transfer_timings={'payload_complete':True,'end_sent':True,'sent_unconfirmed':True}
            def __init__(self,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def command(self,*args,**kwargs): return protocol.Reply(1,1,b'\x01')
            def write(self,*args): pass
            def send_gif(self,*args,**kwargs): raise GifCommitUnconfirmed('final reply missing')
        with tempfile.TemporaryDirectory() as directory:
            coordinator=FaceplateCoordinator(directory,Path(directory)/'state.json',link_factory=FakeLink,
                port_finder=lambda:'/test',identity_reader=lambda port:1)
            coordinator.configure(True,100)
            data=encode_frame(bytes([20,30,40])*(64*54))
            result=coordinator.synchronize_scene(data,'weather','key')
            self.assertTrue(result['sent_unconfirmed']); self.assertFalse(result['synchronized'])
            self.assertIsNone(result['wrote']); self.assertEqual(coordinator.writes_session,0)
            self.assertEqual(coordinator.failed_session,0); self.assertEqual(coordinator.unconfirmed_session,1)
            self.assertFalse(coordinator.last_synchronized)
            self.assertEqual(coordinator.status()['delivery']['state'],'unconfirmed')
            self.assertEqual(coordinator.state['observability']['journal'][-1]['outcome'],'unconfirmed')
            self.assertIsNone(coordinator.state['observability']['journal'][-1]['wrote'])
        router=FaceplateSceneRouter()
        ticket=router.reconcile(game_running=False,content_key='key')
        router.sent_unconfirmed(ticket,'final reply missing')
        self.assertEqual(router.status()['effective_content_key'],'')
        self.assertEqual(router.status()['preparation']['state'],'unconfirmed')
        self.assertEqual(router.reconcile(game_running=False,content_key='key'),ticket)
        newer=router.reconcile(game_running=False,content_key='new')
        self.assertNotEqual(newer,ticket); self.assertFalse(router.sent_unconfirmed(ticket,'stale'))

    def test_worker_completion_snapshot_runs_after_busy_is_cleared_and_callback_fault_is_isolated(self):
        observations=[]; finished=threading.Event()
        worker=FaceplateWorker(lambda request:{'sent_unconfirmed':True,'ack_ms':999},enabled=True)
        def callback():
            observations.append(worker.status()); finished.set(); raise RuntimeError('snapshot failure')
        worker.on_complete=callback
        try:
            worker.submit('weather',{})
            self.assertTrue(finished.wait(2))
            self.assertFalse(observations[0]['busy'])
            self.assertTrue(observations[0]['last_result']['sent_unconfirmed'])
            self.assertEqual(observations[0]['ack_ema_ms'],0)
            self.assertTrue(worker.thread.is_alive())
        finally: worker.stop()
