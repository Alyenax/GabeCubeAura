"""BEGIN refusal is not a successful display; recovery is a user power action."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from signalbar.faceplate import protocol
from signalbar.faceplate.transport import Link, LinkError, ReplyTimeout, TransferCancelled
from signalbar.faceplate.flash import FlashWearProtection
from signalbar.faceplate.coordinator import encode_frame
from signalbar.backend import Engine
from signalbar.models import GameState
from signalbar.settings.store import DEFAULTS
from signalbar.diagnostics import DiagnosticJournal
import test_screensaver_restore148 as restore_fixtures
HOME = restore_fixtures.HOME
import test_native_clock as native_fixtures
from test_cinema_integration import plugin_class

class RestoreFailureTests(unittest.TestCase):
    def setUp(self):
        self.f=restore_fixtures.Restore148Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.coordinator;self.panel=self.f.panel
    def failed_begin(self):
        self.f.exit();self.panel.refuse_begin=True
        result=self.f.restore();self.assertFalse(result['synchronized']);return result

    def test_rejected_begin_stops_same_restore_without_blocks_end_or_automatic_on(self):
        self.failed_begin();r=self.c.restoration_status()
        self.assertTrue(r['failed']);self.assertTrue(r['held_dark']);self.assertTrue(r['recovery_available'])
        self.assertEqual(r['failure_stage'],'begin');self.assertTrue(r['automatic_retry_stopped'])
        self.assertEqual(self.c.last_transfer['begin_status'],0)
        self.assertEqual(self.c.last_transfer['chunks'],0);self.assertFalse(self.c.last_transfer['end_sent'])
        before=list(self.panel.events);self.assertTrue(self.f.restore()['retry_suppressed'])
        self.assertEqual(self.panel.events,before)
        self.assertTrue(self.c.set_power(True,'automatic resume')['deferred_to_route'])
        self.f.assert_no_on()

    def test_explicit_user_recovery_only_restores_power_never_claims_current_image(self):
        self.failed_begin();self.panel.events.clear();writes=self.c.writes_session
        r=self.c.set_power(True,'Decky control')
        self.assertTrue(r['ok']);self.assertTrue(r['stored_picture_resumed'])
        self.assertEqual(sum(e[:2]==(1,1) and e[2]==b'\x01' for e in self.panel.events),1)
        self.assertFalse(any(e[:2] in ((1,4),(2,2),(1,11),(1,0xf0)) for e in self.panel.events))
        self.assertFalse(self.c.restoration_status()['held_dark']);self.assertFalse(self.c.restoration_status()['pending'])
        self.assertFalse(self.c.last_synchronized);self.assertEqual(self.c.delivery['state'],'failed')
        self.assertEqual(self.c.writes_session,writes);self.assertTrue(self.c.error)
        self.assertFalse(self.f.new_coordinator().restoration_status()['held_dark'])

    def test_failed_power_recovery_keeps_guard_and_can_be_retried_only_explicitly(self):
        self.failed_begin();original=self.panel.command
        def no_on(packet,**kwargs):
            if packet==protocol.power(True):raise ReplyTimeout('missing power ACK')
            return original(packet,**kwargs)
        self.panel.command=no_on
        self.assertFalse(self.c.set_power(True,'Decky control')['ok'])
        self.assertTrue(self.c.restoration_status()['held_dark']);self.assertFalse(self.c.last_synchronized)
        self.panel.command=original;self.assertTrue(self.c.set_power(True,'Decky control')['ok'])

    def test_empty_power_reply_never_releases_recovery_guard(self):
        self.failed_begin();original=self.panel.command
        self.panel.command=lambda p,**kw:None if p==protocol.power(True) else original(p,**kw)
        self.assertFalse(self.c.set_power(True,'Decky control')['ok'])
        self.assertTrue(self.c.restoration_status()['held_dark'])

    def test_reconnect_cannot_reuse_the_previous_devices_manual_recovery_receipt(self):
        self.failed_begin();self.panel.token='usb-2';self.panel.events.clear()
        r=self.c.set_power(True,'Decky control')
        self.assertFalse(r['ok']);self.assertTrue(r['deferred_to_route']);self.f.assert_no_on()

    def test_disabled_coordinator_never_uses_the_manual_recovery_escape(self):
        self.failed_begin();self.c.configure(False,20);self.panel.events.clear()
        self.assertFalse(self.c.set_power(True,'Decky control')['ok']);self.f.assert_no_on()

    def test_timeout_and_interruption_keep_a_truthful_failed_restore(self):
        for kind in ('timeout','cancelled'):
            with self.subTest(kind=kind):
                f=restore_fixtures.Restore148Tests();f.setUp();self.addCleanup(f.doCleanups);f.exit();original=f.panel.command
                def fail(packet,**kwargs):
                    if packet[2:4]==b'\x01\x04':
                        if kind=='timeout':raise ReplyTimeout('no reply')
                        raise TransferCancelled('superseded')
                    return original(packet,**kwargs)
                f.panel.command=fail;result=f.restore()
                self.assertFalse(result['synchronized']);self.assertTrue(f.coordinator.restoration_status()['recovery_available'])
                self.assertFalse(f.coordinator.last_transfer['end_sent']);self.assertEqual(f.coordinator.last_transfer['chunks'],0)
                f.assert_no_on()

    def test_mid_body_cancellation_never_sends_end_or_claims_a_new_picture(self):
        self.f.exit();cancelled=[False]
        self.panel.after_chunk=lambda:cancelled.__setitem__(0,True)
        result=self.c.synchronize_scene(encode_frame(bytes((13,21,34))*3456),'dashboard','new',
            reason='current-route-restore',cancelled=lambda:cancelled[0])
        self.assertTrue(result['cancelled']);self.assertFalse(result['synchronized'])
        self.assertTrue(self.c.last_transfer['body_reserved']);self.assertFalse(self.c.last_transfer['end_sent'])
        self.assertEqual(self.panel.commits,0);self.f.assert_no_on()
        self.panel.events.clear();self.assertTrue(self.c.set_power(True,'Decky control')['ok'])
        self.assertFalse(any(e[:2] in ((1,4),(2,2),(1,11)) for e in self.panel.events))
        self.assertFalse(self.c.last_synchronized)

    def test_new_content_can_recover_after_begin_failure_with_real_success_receipt(self):
        self.failed_begin();self.panel.refuse_begin=False
        result=self.f.restore(encode_frame(bytes((7,12,32))*3456),'dashboard')
        self.assertTrue(result['synchronized']);self.assertFalse(self.c.restoration_status()['failed'])
        self.assertFalse(self.c.restoration_status()['held_dark']);self.assertEqual(self.panel.commits,1)

    def test_engine_user_recovery_does_not_enqueue_another_image_and_holds_periodic_route(self):
        f=native_fixtures.NativeSceneTests();f.setUp();self.addCleanup(f.doCleanups);e=f.engine;e.faceplate=self.c
        self.failed_begin();e._reconcile_faceplate=Mock();e.faceplate_worker=Mock();e.faceplate_worker.status.return_value={'busy':False,'queued':False}
        e.jsaux_broker_adapter=Mock();e.jsaux_broker_adapter.holds_display.return_value=False
        r=e.set_faceplate_power(True)
        self.assertTrue(r['stored_picture_resumed']);e._reconcile_faceplate.assert_not_called()
        self.assertFalse(e._admit_faceplate_route_recovery('periodic'))
        e.settings.update({'faceplate_brightness':30})
        self.assertTrue(e._admit_faceplate_route_recovery('settings'))

    def test_stopped_recovery_does_not_block_a_new_route_or_usb_session(self):
        f=native_fixtures.NativeSceneTests();f.setUp();self.addCleanup(f.doCleanups);e=f.engine;e.faceplate=self.c
        self.failed_begin();e.faceplate_worker=Mock();e.faceplate_worker.status.return_value={'busy':False,'queued':False}
        hardware={'available':True,'busy':False,'device_identity':self.c.device_token}
        self.assertTrue(e._admit_faceplate_route_recovery('periodic',hardware))
        self.assertFalse(e._admit_faceplate_route_recovery('periodic',hardware))
        e.faceplate_preferences.update(home_scene='weather')
        self.assertTrue(e._admit_faceplate_route_recovery('route-change',hardware))
        self.assertTrue(e._admit_faceplate_route_recovery('reconnect',{**hardware,'device_identity':'new-usb'}))

    def test_engine_respects_explicit_off_other_owner_and_busy_worker(self):
        for block in ('master-off','power-off','other-app','lease','busy'):
            with self.subTest(block=block):
                f=native_fixtures.NativeSceneTests();f.setUp();self.addCleanup(f.doCleanups);e=f.engine;e.faceplate=self.c
                if not self.c.restoration_status()['recovery_available']:self.failed_begin()
                if block=='master-off':e.settings.update({'signalbar_enabled':False})
                if block=='power-off':
                    e._game=GameState(42,'Test');e.settings.update_display(42,'displays_off')
                if block=='other-app':e.settings.update({'faceplate_control_mode':'other-app'})
                e.faceplate_worker=Mock();e.faceplate_worker.status.return_value={'busy':block=='busy','queued':False}
                e.jsaux_broker_adapter=Mock();e.jsaux_broker_adapter.holds_display.return_value=block=='lease'
                self.panel.events.clear();self.assertFalse(e.set_faceplate_power(True)['ok']);self.f.assert_no_on()

class TransportFailureTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.events=[];self.ticks=1000.;self.status=0;self.profile='baseline'
        self.link=Link(port='/test');self.link.flash_manager=FlashWearProtection(self.root/'flash.json')
        self.link.write=self.events.append
        self.link.read_replies=lambda timeout:[protocol.Reply(self.events[-1][2],self.events[-1][3],bytes((self.status,)))]
        p=patch('signalbar.faceplate.transport.time.sleep');p.start();self.addCleanup(p.stop)
    def tick(self):self.ticks+=.02;return self.ticks

    def test_begin_refusal_is_one_command_and_never_reserves_or_sends_the_body(self):
        with self.assertRaisesRegex(LinkError,'refused GIF begin'):self.link.send_gif(HOME)
        r=self.link.last_transfer_timings
        self.assertEqual(r['begin_status'],0);self.assertEqual(r['begin_attempts'],1)
        self.assertEqual(r['failure_stage'],'begin');self.assertEqual(r['failure_kind'],'rejected')
        self.assertFalse(r['body_reserved']);self.assertFalse(r['payload_complete']);self.assertFalse(r['end_sent'])
        self.assertEqual([p[2:4] for p in self.events],[b'\x01\x04'])
        self.assertEqual(len(self.events[0][6:-2]),8)

    def test_no_begin_reply_has_three_bounded_attempts_and_no_end(self):
        self.link.read_replies=lambda timeout:[]
        with patch('signalbar.faceplate.transport.time.monotonic',side_effect=self.tick):
            with self.assertRaises(ReplyTimeout):self.link.send_gif(HOME)
        r=self.link.last_transfer_timings
        self.assertIsNone(r.get('begin_status'));self.assertEqual(r['begin_attempts'],3)
        self.assertEqual(r['failure_kind'],'timeout');self.assertFalse(r['body_reserved'])
        self.assertEqual([p[3] for p in self.events],[4,4,4])

    def test_already_stored_is_not_evidence_of_a_new_write(self):
        self.status=2;self.assertFalse(self.link.send_gif(HOME));r=self.link.last_transfer_timings
        self.assertTrue(r['already_stored']);self.assertEqual(r['chunks'],0);self.assertFalse(r['end_sent'])
        self.assertFalse(r['body_reserved']);self.assertEqual(len(self.events),1)

    def test_profiles_remain_opt_in_and_auto_fallback_has_at_most_two_transactions(self):
        self.link.transport_profile='auto'
        def replies(timeout):
            packet=self.events[-1];vendor=any(p[3]==0xf0 for p in self.events)
            status=1 if vendor else 0
            return [protocol.Reply(packet[2],packet[3],bytes((status,)))]
        self.link.read_replies=replies;self.assertTrue(self.link.send_gif(HOME));r=self.link.last_transfer_timings
        self.assertEqual(r['attempt_profiles'],['baseline','vendor']);self.assertEqual(r['transfer_retries'],1)
        self.assertEqual(sum(p[3]==4 for p in self.events),2);self.assertEqual(sum(p[3]==11 for p in self.events),1)

class CallbackAndExportTests(unittest.TestCase):
    def test_logind_resume_refreshes_weather_without_touching_a_nonautomatic_panel(self):
        for enabled,mode in ((False,'auto'),(True,'manual')):
            p=plugin_class()();p.engine=Mock();p.engine.settings.all.return_value=dict(DEFAULTS,faceplate_lab_enabled=enabled,faceplate_power_mode=mode)
            p._handle_faceplate_power_event('sleep',False)
            p.engine.weather.request_refresh.assert_called_once_with("logind-resume");p.engine.resume_faceplate.assert_not_called()
            p.engine.suspend_faceplate.assert_not_called()

    def test_power_rpc_surfaces_a_real_failure_and_preserves_normal_deferred_routing(self):
        import asyncio
        p=plugin_class()();p.engine=Mock();p.engine.status.return_value={'state':'unchanged'}
        p.engine.set_faceplate_power.return_value={'ok':False,'error':'Power reply missing'}
        with self.assertRaisesRegex(RuntimeError,'Power reply missing'):
            asyncio.run(p.set_faceplate_power(True))
        p.engine.set_faceplate_power.return_value={'ok':False,'deferred_to_route':True,'error':''}
        self.assertEqual(asyncio.run(p.set_faceplate_power(True)),{'state':'unchanged'})

    def test_local_export_preserves_zero_begin_status_and_recovery_without_paths(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            j=DiagnosticJournal(tmp,'1.6.0')
            j.faceplate_runtime_path.parent.mkdir(parents=True,exist_ok=True)
            j.faceplate_runtime_path.write_text(json.dumps({'device':{'restoration':{'held_dark':True,'failed':True,'recovery_available':True,'failure_stage':'begin'},
                'last_transfer':{'begin_status':0,'begin_attempts':1,'chunks':0,'failure_stage':'begin','failure_kind':'rejected','configured_profile':'baseline',
                                 'private_path':'/private/not-exported'}}}))
            r=j._faceplate_runtime_snapshot()['device']
            self.assertEqual(r['last_transfer']['begin_status'],0);self.assertTrue(r['restoration']['recovery_available'])
            self.assertNotIn('private_path',r['last_transfer'])

if __name__=='__main__':unittest.main()
