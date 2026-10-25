"""Exit control is volatile, serialized and independent of weather readiness."""
from unittest.mock import Mock
import unittest
from signalbar.backend import Engine
from signalbar.models import GameState
from signalbar.faceplate import protocol
from signalbar.faceplate.coordinator import encode_frame
import tempfile
import test_broker_adapter as fixtures
import test_native_clock


class Exit147Tests(unittest.TestCase):
    def fixture(self):
        f=fixtures.BrokerAdapterTests();f.setUp();self.addCleanup(f.tearDown);return f

    def test_exit_stops_autonomous_gif_before_waiting_for_normal_content(self):
        f=self.fixture();f.start();f.adapter.cancel('operation')
        f.adapter.restore('operation',f.report);f.wait()
        self.assertEqual(f.power_calls,[(False,'screensaver-exit')])
        self.assertFalse(f.adapter.holds_display())
        self.assertTrue(f.engine._faceplate_resume_requested)
        trace=f.adapter.diagnostic_snapshot()['normal_route_restoration']
        self.assertEqual(trace['exit_stop'],'confirmed');self.assertEqual(trace['state'],'pending')
        # ACK of volatile Off does not claim that the Dashboard is restored.
        f.adapter.normal_completed({'synchronized':True})
        self.assertEqual(f.adapter.diagnostic_snapshot()['normal_route_restoration']['state'],'confirmed')
        self.assertEqual(len(f.calls),1) # No extra GIF transfer to stop playback.

    def test_refused_unstarted_lease_never_turns_the_normal_picture_off(self):
        f=self.fixture();f.adapter.restore('operation',f.report);f.wait()
        self.assertEqual(f.power_calls,[])

    def test_manual_off_or_priority_does_not_get_overridden_by_exit(self):
        f=self.fixture();f.start();f.adapter.cancel('operation');f.priority=True
        f.adapter.restore('operation',f.report);f.wait()
        self.assertEqual(f.power_calls,[])
        self.assertEqual(f.receipts[-1]['restore_state'],'blocked')

    def test_stale_exit_control_cannot_darken_new_owner(self):
        f=self.fixture();f.adapter._exit_stop={'operation_id':'old','at':f.clock()}
        f.adapter._job=dict(operation_id='new')
        self.assertTrue(f.adapter.execute_exit({'payload':{'operation_id':'old'}})['superseded'])
        self.assertEqual(f.power_calls,[])

    def test_a_later_normal_receipt_clears_delegated_visibility_after_priority_handoff(self):
        f=self.fixture();f.adapter._display_operation='old-operation'
        self.assertTrue(f.adapter.requires_exit_blank())
        f.adapter.normal_completed({'synchronized':True})
        self.assertFalse(f.adapter.requires_exit_blank())

    def test_screensaver_extension_never_uses_home_weather_palette(self):
        engine=object.__new__(Engine);engine.faceplate_extension=Mock()
        engine._faceplate_suspended=False;engine._faceplate_extension_present=True
        engine.faceplate=Mock(powered=True)
        engine.faceplate_extension.adjusted=((200,80,5),)*17
        engine.jsaux_broker_adapter=Mock()
        for held in (True,False):
            engine.jsaux_broker_adapter.holds_display.return_value=held
            engine.jsaux_broker_adapter.extension_frame.return_value=None
            output=engine._faceplate_extension_output({'faceplate_lab_enabled':True,'faceplate_extension_mapping':'whole'},GameState(0,''),'faceplate_extension',0,screensaver=True)
            self.assertEqual(output.frame,((0,0,0),)*17)
        engine.jsaux_broker_adapter.extension_frame.return_value=((30,0,80),)*17
        output=engine._faceplate_extension_output({'faceplate_lab_enabled':True,'faceplate_extension_mapping':'whole'},GameState(0,''),'faceplate_extension',1,screensaver=True)
        self.assertEqual(output.frame,((30,0,80),)*17)
        engine.faceplate_extension.configure.assert_not_called()

    def test_normal_transfer_stays_dark_until_the_replacement_is_committed(self):
        with tempfile.TemporaryDirectory() as root:
            records=[]
            coordinator=fixtures.DelegatedCoordinatorTests().coordinator(root,records)
            coordinator.set_power(False,'screensaver-exit');records.clear()
            result=coordinator.synchronize_scene(encode_frame(bytes([8,0,0])*3456),'weather','home',peak_load=.1,reason='current-route-restore')
            self.assertTrue(result['synchronized'])
            off=records.index(('command',protocol.power(False)))
            body=next(n for n,row in enumerate(records) if row[0]=='gif')
            on=records.index(('command',protocol.power(True)))
            self.assertLess(off,body);self.assertLess(body,on)
            self.assertFalse(coordinator._screensaver_exit_blank)
            self.assertTrue(coordinator.powered)

    def test_system_resume_does_not_power_on_a_retained_screensaver(self):
        f=test_native_clock.NativeSceneTests();f.setUp();self.addCleanup(f.doCleanups)
        engine=f.engine;engine.jsaux_broker_adapter=Mock()
        engine.jsaux_broker_adapter.requires_exit_blank.return_value=True
        engine._reconcile_faceplate=Mock()
        result=engine.resume_faceplate()
        self.assertTrue(result['ok']);self.assertFalse(f.faceplate.powered)
        self.assertTrue(f.faceplate._screensaver_exit_blank)
        self.assertIn(protocol.power(False),f.calls);self.assertNotIn(protocol.power(True),f.calls)
        engine.jsaux_broker_adapter.observe_steam.assert_called_with(False,'waiting',source='resume')
        engine._reconcile_faceplate.assert_called_with('steam-machine-resume',force=True)
