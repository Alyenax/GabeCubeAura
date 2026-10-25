"""Real GCA transport with explicit simulated MCU display variants, no USB."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_screensaver_restore148 as fixture
import test_broker_adapter as adapter_fixture
from signalbar.faceplate import gif,protocol
from signalbar.faceplate.transport import Link,TransferCancelled
from signalbar.settings import SettingsStore

GAMES=gif.encode(64,54,[(0,0,0),(0,15,0)],[bytes([1])*3456,bytes([0])*3456],[45,45])

class Continuous193(unittest.TestCase):
    setUp=fixture.Restore148Tests.setUp
    new_coordinator=fixture.Restore148Tests.new_coordinator
    def prepare(self,variant='continuous'):
        if getattr(self,'prepared_once',False):self.setUp()
        self.prepared_once=True
        panel=self.panel;original=panel.command;self.phase=7;self.commit_visibility=[]
        def command(packet,**kw):
            if packet[2:4]==bytes([1,1]) and packet[6:-2]==b'\x01':self.phase=0
            if packet[2:4]==bytes([1,4]) and variant=='restart-on-begin':self.phase=0
            result=original(packet,**kw)
            if packet[2:4]==bytes([1,11]) and result.status==1:
                panel.visible=panel.stored
                if variant=='black-at-end':self.phase=-1
            return result
        panel.command=command
        c=self.coordinator
        self.assertTrue(c.synchronize_scene(GAMES,'screensaver','games',delegated=True,peak_load=.1)['synchronized'])
        self.phase=7;panel.events.clear();self.clock=100.;self.allowed=True
        c.monotonic=lambda:self.clock
        self.assertTrue(c.arm_continuous_return('operation',lambda:self.allowed))
        return c
    def restore(self):return self.coordinator.synchronize_scene(fixture.HOME,'weather','home',reason='current-route-restore')
    def powers(self):return [p for k,cmd,p in self.panel.events if (k,cmd)==(1,1)]
    def test_success_one_body_no_power_or_brightness_and_old_display_until_commit(self):
        c=self.prepare()
        def inspect():self.assertEqual(self.panel.visible,GAMES);self.assertEqual(self.phase,7)
        self.panel.after_chunk=inspect
        result=self.restore();self.assertTrue(result['synchronized'])
        self.assertEqual(self.powers(),[]);self.assertEqual(self.panel.visible,fixture.HOME)
        self.assertFalse(any((k,cmd) in ((1,2),(1,240)) for k,cmd,p in self.panel.events))
        self.assertEqual(sum((k,cmd)==(1,11) for k,cmd,p in self.panel.events),1)
        self.assertEqual(c.continuous_return_status()['state'],'confirmed')
        self.assertFalse(c.state['delegated_display_pending']);self.assertIsNone(c._continuous_return)
    def test_models_do_not_masquerade_as_physical_continuity(self):
        for variant,expected in [('restart-on-begin',0),('black-at-end',-1)]:
            with self.subTest(variant=variant):
                self.prepare(variant);self.assertTrue(self.restore()['synchronized']);self.assertEqual(self.powers(),[])
                self.assertEqual(self.phase,expected)
                self.assertEqual(self.coordinator.continuous_return_status()['physical_playback'],'not-measured')
    def test_same_stored_crc_still_gets_one_confirmed_body_without_power_cycle(self):
        c=self.prepare()
        result=c.synchronize_scene(GAMES,'dashboard','same-pixels',reason='current-route-restore')
        self.assertTrue(result['synchronized']);self.assertEqual(self.powers(),[])
        self.assertEqual(sum((k,cmd)==(1,11) for k,cmd,p in self.panel.events),1)
        self.assertTrue(any((k,cmd)==(2,2) for k,cmd,p in self.panel.events))
        self.assertFalse(c.state['delegated_display_pending'])
    def test_arm_requires_known_confirmed_baseline_display(self):
        c=self.prepare();c._continuous_return=None
        for field,value in [('powered',None),('enabled',False),('_screensaver_exit_blank',True),('last_synchronized',False),('last_asset','weather:home')]:
            old=getattr(c,field);setattr(c,field,value)
            self.assertFalse(c.arm_continuous_return('other',lambda:True));setattr(c,field,old)
        c.last_transfer['active_profile']='vendor';self.assertFalse(c.arm_continuous_return('other',lambda:True))
    def test_native_replacement_uses_real_clock_ack_without_power_cycle(self):
        c=self.prepare();r=c.synchronize_native_clock(sync_key='native',reason='current-route-restore')
        self.assertTrue(r['synchronized']);self.assertEqual(self.powers(),[])
        self.assertTrue(any((k,cmd)==(1,5) for k,cmd,p in self.panel.events));self.assertFalse(c.state['delegated_display_pending'])
    def test_native_late_ack_cannot_confirm_a_superseded_route(self):
        c=self.prepare();cancel=threading.Event();original=self.panel.command
        def command(packet,**kwargs):
            result=original(packet,**kwargs)
            if packet[2:4]==bytes([1,5]):cancel.set()
            return result
        self.panel.command=command
        result=c.synchronize_native_clock(sync_key='native',cancelled=cancel.is_set)
        self.assertFalse(result.get('synchronized'));self.assertEqual(self.powers(),[b'\x00'])
        self.assertTrue(c._screensaver_exit_blank);self.assertTrue(c.state['delegated_display_pending'])
    def test_manual_off_and_old_on_do_not_revive_games(self):
        c=self.prepare();self.assertTrue(c.set_power(False,'manual')['ok']);count=len(self.panel.events)
        r=c.set_power(True,'automatic power recovery');self.assertTrue(r['deferred_to_route'])
        self.assertEqual(len(self.panel.events),count);self.assertTrue(c._screensaver_exit_blank)
    def test_real_brightness_change_during_return_has_no_replay_command(self):
        c=self.prepare();self.assertTrue(c.set_brightness(65)['ok'])
        self.assertEqual(c.effective_brightness,65);self.assertEqual(self.powers(),[])
        self.assertEqual(self.panel.visible,GAMES);self.assertIsNotNone(c._continuous_return)
        self.assertEqual(sum((k,cmd)==(1,2) for k,cmd,p in self.panel.events),1)
    def test_brightness_after_identity_change_cannot_power_on_stale_content(self):
        c=self.prepare();self.panel.token='usb-new';self.assertTrue(c.set_brightness(65)['ok'])
        self.assertNotIn(b'\x01',self.powers());self.assertFalse(c.powered)
        self.assertTrue(c._screensaver_exit_blank);self.assertIsNone(c._continuous_return)
    def test_deadline_before_transfer_uses_dark_path_without_new_authority(self):
        c=self.prepare();self.clock+=21;self.assertTrue(c.continuous_return_needs_stop())
        self.assertTrue(c.stop_continuous_return()['ok']);self.assertEqual(self.powers(),[b'\x00'])
        self.assertTrue(c._screensaver_exit_blank);self.assertTrue(c.state['delegated_display_pending'])
    def test_policy_or_timeout_during_blocks_aborts_and_darkens(self):
        for why in ('policy','timeout'):
            self.prepare()
            def interrupt():
                if why=='policy':self.allowed=False
                else:self.clock+=21
            self.panel.after_chunk=interrupt
            r=self.restore();self.assertFalse(r.get('synchronized'));self.assertNotIn(b'\x01',self.powers())
            self.assertIn(b'\x00',self.powers());self.assertIsNone(self.coordinator._continuous_return)
            self.panel.after_chunk=None
            count=len(self.panel.events)
            self.assertTrue(self.restore()['retry_suppressed']);self.assertEqual(len(self.panel.events),count)
    def test_changed_device_or_vendor_profile_falls_back_before_body(self):
        for change in ('device','vendor'):
            c=self.prepare()
            if change=='device':self.panel.token='usb-new'
            else:
                original=c.link_factory
                def vendor(**kw):
                    link=original(**kw);link.transport_profile='vendor';return link
                c.link_factory=vendor
            self.assertTrue(self.restore()['synchronized'])
            self.assertEqual(self.powers()[0],b'\x00')
            begin=next(i for i,(k,cmd,p) in enumerate(self.panel.events) if (k,cmd)==(1,4))
            off=next(i for i,(k,cmd,p) in enumerate(self.panel.events) if (k,cmd,p)==(1,1,b'\x00'))
            self.assertLess(off,begin)
    def test_policy_change_before_begin_cannot_send_a_body_or_on(self):
        c=self.prepare();self.allowed=False;r=self.restore()
        self.assertFalse(r.get('synchronized'));self.assertEqual(self.powers(),[b'\x00'])
        self.assertFalse(any((k,cmd)==(1,4) for k,cmd,p in self.panel.events))
    def test_larger_content_uses_dark_path_instead_of_exceeding_budget(self):
        c=self.prepare()
        with patch('signalbar.faceplate.continuous_return.timing.transfer_ms',return_value=21000):
            self.assertTrue(self.restore()['synchronized'])
        self.assertEqual(self.powers()[0],b'\x00');self.assertEqual(c.continuous_return_status()['state'],'fallback-dark')
    def test_negative_or_lost_end_is_not_retried_and_retains_durable_uncertainty(self):
        for field in ('refuse_end','lose_end'):
            self.prepare();setattr(self.panel,field,True)
            self.assertFalse(self.restore().get('synchronized'));count=len(self.panel.events)
            self.assertIsNotNone(self.coordinator._restore_uncertain)
            self.assertTrue(self.restore()['retry_suppressed']);self.assertEqual(len(self.panel.events),count)
            self.assertNotIn(b'\x01',self.powers());self.assertTrue(self.coordinator.state['delegated_display_pending'])
            setattr(self.panel,field,False)
    def test_late_successful_end_after_deadline_never_relights(self):
        c=self.prepare();self.panel.after_end=lambda:setattr(self,'clock',self.clock+21)
        self.assertFalse(self.restore().get('synchronized'));self.assertNotIn(b'\x01',self.powers())
        self.assertTrue(c._screensaver_exit_blank);self.assertTrue(c.state['delegated_display_pending'])
    def test_reboot_never_restores_continuous_permission(self):
        self.prepare();c=self.new_coordinator();self.assertIsNone(c._continuous_return)
        self.assertTrue(c._screensaver_exit_blank);self.assertTrue(c.state['delegated_display_pending'])
    def test_diagnostics_never_include_identity_or_operation(self):
        c=self.prepare();self.restore();s=json.dumps(c.continuous_return_status())
        self.assertNotIn('operation',s);self.assertNotIn(self.panel.token,s)
    def test_plugin_shutdown_stops_pending_return_on_the_existing_worker(self):
        from signalbar.backend.engine import Engine
        from signalbar.faceplate.service import FaceplateWorker
        from signalbar.providers.countdown import CountdownProvider
        c=self.prepare();e=Engine.__new__(Engine)
        e.faceplate=c;e._stop=threading.Event();e._lock=threading.RLock()
        e.countdown=CountdownProvider();e.faceplate_router=Mock()
        e._timer_power_thread=None;e._thread=None;e._renderer=None
        e._write_faceplate_runtime_status=Mock();e.screen_sync_activation=Mock()
        e.screen_sync_trace=Mock()
        # return-stop must bypass these guards, even during an Off/setup change.
        e._display_panel_off=Mock(side_effect=AssertionError('guard before safety stop'))
        e._onboarding_recovery_blocked=True
        for name in ('assistant','weather','faceplate_extension','screen_sync','audio_sync','dashboard_stats'):
            setattr(e,name,SimpleNamespace(stop=lambda timeout=None:None))
        for name in ('events','launch_artwork','faceplate_steam_state','controllers','event_lease','stripmine_claim'):
            setattr(e,name,Mock())
        e.faceplate_worker=FaceplateWorker(e._handle_faceplate_scene,enabled=True)
        self.addCleanup(e.faceplate_worker.stop,1)
        e.stop(timeout=2)
        self.assertEqual(self.powers(),[b'\x00']);self.assertIsNone(c._continuous_return)
        self.assertTrue(c.state['delegated_display_pending']);e._display_panel_off.assert_not_called()

class Adapter193(unittest.TestCase):
    setUp=adapter_fixture.BrokerAdapterTests.setUp
    tearDown=adapter_fixture.BrokerAdapterTests.tearDown
    start=adapter_fixture.BrokerAdapterTests.start
    wait=adapter_fixture.BrokerAdapterTests.wait
    report=adapter_fixture.BrokerAdapterTests.report
    def test_only_opted_in_confirmed_normal_exit_can_arm(self):
        self.start();panel=self.engine.faceplate;panel.arm_continuous_return=Mock(return_value=True)
        self.engine.settings.all=lambda:{'faceplate_lab_enabled':True,'faceplate_continuous_home_return':True}
        self.adapter.prepare_return('operation','STEAM_INACTIVE',False);self.assertIsNone(self.adapter._return_candidate)
        self.adapter.prepare_return(self.job['operation_id'],'STEAM_STATE_STALE',True);self.assertIsNone(self.adapter._return_candidate)
        self.adapter.prepare_return(self.job['operation_id'],'STEAM_INACTIVE',True)
        self.adapter.cancel(self.job['operation_id']);self.adapter.restore(self.job['operation_id'],self.report)
        self.wait();panel.arm_continuous_return.assert_called_once();self.assertEqual(self.power_calls,[])
        self.assertEqual(self.adapter._restore_trace['exit_stop'],'continuous')
    def test_expired_transition_stop_runs_on_existing_worker(self):
        from signalbar.backend.engine import Engine
        self.engine.faceplate._continuous_return={}
        self.engine.faceplate.continuous_return_needs_stop=lambda:True
        self.engine.faceplate.stop_continuous_return=Mock(return_value={'ok':True})
        self.engine.faceplate_worker.handler=lambda request:Engine._handle_faceplate_scene(self.engine,request)
        self.adapter.service_continuous_return()
        self.wait();self.assertEqual(self.engine.faceplate_worker.status()['last_scene'],'return-stop')
        self.engine.faceplate.stop_continuous_return.assert_called_once_with()

class Settings193(unittest.TestCase):
    def test_experiment_is_disabled_on_fresh_install_and_legacy_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';store=SettingsStore(path)
            self.assertFalse(store.all()['faceplate_continuous_home_return'])
            store.update({'faceplate_continuous_home_return':True});self.assertTrue(store.all()['faceplate_continuous_home_return'])
            self.assertTrue(SettingsStore(path).all()['faceplate_continuous_home_return'])

class BrokerPair193(unittest.TestCase):
    def test_actual_broker_revokes_then_adapter_arms_and_current_receipt_completes(self):
        import test_jsaux_broker_core as core
        f=core.CoreTests();f.setUp();self.addCleanup(f.tearDown)
        content,collection=f.content()
        serial=fixture.Restore148Tests();serial.setUp();self.addCleanup(serial.doCleanups)
        adapter=adapter_fixture.BrokerAdapterTests();adapter.setUp();self.addCleanup(adapter.tearDown)
        panel=serial.coordinator
        panel.device_status=lambda:{'available':True,'port':'/test','busy':False}
        adapter.engine.faceplate=panel
        adapter.engine.settings.all=lambda:{'faceplate_lab_enabled':True,'faceplate_continuous_home_return':True}
        f.broker.adapter=adapter.adapter
        activation=adapter.adapter._steam()['activation_id']
        lease=f.ok('acquire_display',dict(content_id=content,collection_id=collection,activation_id=activation,session_id='paired',mode='async'))
        common=dict(lease_id=lease['lease_id'],generation=lease['generation'])
        f.ok('player_ready',dict(**common,alignment_attempt_id=None,ready_mono_ms=None,deadline_mono_ms=None,clock_uncertainty_ms=None))
        adapter.wait()
        f.ok('tv_started',dict(**common,alignment_attempt_id=None,started_mono_ms=None,outcome='independent',candidate_id=None))
        serial.panel.events.clear();adapter.adapter.observe_steam(False);f.broker.tick()
        self.assertEqual(f.broker.lease['reason'],'STEAM_INACTIVE')
        self.assertFalse(f.broker.is_valid(lease['operation_id']))
        self.assertIsNotNone(panel._continuous_return)
        # Serial callbacks may not acquire engine/settings locks.
        with patch.object(adapter.engine.settings,'all',side_effect=AssertionError('settings under serial')):
            result=panel.synchronize_scene(fixture.HOME,'weather','current',reason='current-route-restore')
        adapter.adapter.normal_completed(result)
        self.assertTrue(result['synchronized']);self.assertEqual(f.broker.lease['restore_state'],'confirmed')
        self.assertFalse(any((kind,cmd)==(1,1) for kind,cmd,p in serial.panel.events))
