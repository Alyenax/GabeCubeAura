"""Admission parity and bounded metadata only. No actual device is opened."""
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from signalbar.backend.engine import Engine
from signalbar.faceplate.priority_evidence import BLOCKERS,clean
from signalbar.activation import ScreenSyncActivation


class PriorityEvidenceTests(unittest.TestCase):
    def fixture(self):
        engine=Engine.__new__(Engine);calls=[]
        values=dict(signalbar_enabled=True,faceplate_lab_enabled=True,mode='events',parental_countdown_enabled=True)
        dynamic=dict(timer=False,event=False,launch=False,pending=False,assistant=False,panel_off=False)
        engine.countdown=SimpleNamespace(status=lambda **kw:calls.append('timer') or dict(active=dynamic['timer'],remaining_seconds=300))
        engine.events=SimpleNamespace(status=lambda:calls.append('event') or dict(active=dynamic['event']))
        engine.launch_artwork=SimpleNamespace(status=lambda appid:calls.append('launch') or dict(active=dynamic['launch'],pending=dynamic['pending']))
        engine._game=SimpleNamespace(running=False,appid=0);engine._stop=threading.Event()
        engine._display_panel_off=lambda values:dynamic['panel_off']
        engine._assistant_holds_matrix=lambda:dynamic['assistant']
        engine._faceplate_suspended=False;engine._faceplate_power_target=None
        engine.faceplate=SimpleNamespace(powered=True);engine.thermal_protection=SimpleNamespace(active=False)
        engine._steam_active_until=0;engine._effective_steam_priority=False
        return engine,values,dynamic,calls

    def test_every_ordered_gate_identifies_its_first_blocker(self):
        for name in BLOCKERS:
            with self.subTest(name=name):
                e,v,d,calls=self.fixture()
                if name=='plugin-disabled':v['signalbar_enabled']=False
                elif name=='faceplate-disabled':v['faceplate_lab_enabled']=False
                elif name=='onboarding-recovery':e._onboarding_recovery_blocked=True
                elif name=='onboarding-applying':e._onboarding_applying=True
                elif name=='mode-disabled':v['mode']='disabled'
                elif name=='panel-route-off':d['panel_off']=True
                elif name=='faceplate-suspended':e._faceplate_suspended=True
                elif name=='power-target-off':e._faceplate_power_target=False
                elif name=='panel-powered-off':e.faceplate.powered=False
                elif name=='engine-stopping':e._stop.set()
                elif name=='thermal-protection':e.thermal_protection.active=True
                elif name=='steam-explicit-lease':e._steam_active_until=1001
                elif name=='steam-effective-priority':e._effective_steam_priority=True
                elif name=='countdown-last-5-min':d['timer']=True
                elif name=='external-matrix-hold':d['assistant']=True
                elif name=='light-event-active':d['event']=True
                elif name=='launch-artwork-active':d['launch']=True
                elif name=='launch-artwork-pending':d['pending']=True
                with patch('signalbar.backend.engine.time.monotonic',return_value=1000):allowed,evidence=e._broker_decision(v)
                self.assertFalse(allowed);self.assertEqual(evidence['first_blocker'],name)
                self.assertEqual(list(evidence['evaluated']),list(BLOCKERS[:BLOCKERS.index(name)+1]))
                self.assertEqual(sum(evidence['evaluated'].values()),1)
                self.assertEqual(calls.count('timer'),1)
                self.assertEqual(calls.count('event'),int(BLOCKERS.index(name)>=15))
                self.assertEqual(calls.count('launch'),max(0,BLOCKERS.index(name)-15))

    def test_economy_toggle_and_continuity_cannot_manufacture_a_priority(self):
        for economy in (True,False):
            for refresh in ('economy','minute'):
                e,v,d,calls=self.fixture();v.update(faceplate_flash_protection_enabled=economy,faceplate_artwork_dashboard_refresh=refresh)
                e.faceplate.flash=SimpleNamespace(screensaver_delay=lambda:5)
                allowed,proof=e._broker_decision(v)
                self.assertTrue(allowed);self.assertEqual(proof['first_blocker'],'none')
                self.assertEqual(calls,['timer','event','launch','launch'])

    def test_early_denial_does_not_advance_event_or_launch_providers(self):
        e,v,d,calls=self.fixture();e._effective_steam_priority=True;d['event']=True;d['launch']=True
        allowed,proof=e._broker_decision(v)
        self.assertFalse(allowed);self.assertEqual(calls,['timer'])
        self.assertNotIn('light-event-active',proof['evaluated'])
        self.assertEqual(proof['first_blocker'],'steam-effective-priority')

    def test_only_three_brief_events_are_matrix_neutral_during_a_fresh_screensaver(self):
        for kind in ('notification','achievement','screenshot','record-start','record-stop','unknown',None):
            for active in (False,True):
                with self.subTest(kind=kind,screensaver=active):
                    e,v,d,calls=self.fixture()
                    e.screen_sync_activation=ScreenSyncActivation(clock=lambda:1000)
                    e.screen_sync_activation.set_screensaver(active)
                    def event():calls.append('event');return dict(active=True,kind=kind)
                    e.events.status=event
                    allowed,proof=e._broker_decision(v)
                    neutral=active and kind in ('notification','achievement','screenshot')
                    self.assertEqual(allowed,neutral)
                    self.assertEqual(proof['first_blocker'],'none' if neutral else 'light-event-active')
                    self.assertEqual(calls.count('event'),1)
                    if kind in ('notification','achievement','screenshot'):
                        self.assertEqual(clean(proof)['light_event'],dict(kind=kind))

    def test_expired_or_explicitly_stopped_screensaver_does_not_keep_exception(self):
        e,v,d,calls=self.fixture();now=[1000.0]
        e.screen_sync_activation=ScreenSyncActivation(clock=lambda:now[0])
        e.events.status=lambda:dict(active=True,kind='notification')
        e.screen_sync_activation.set_screensaver(True)
        self.assertTrue(e._broker_allowed(v))
        now[0]+=5.01
        self.assertEqual(e._broker_decision(v)[1]['first_blocker'],'light-event-active')
        e.screen_sync_activation.set_screensaver(True)
        self.assertTrue(e._broker_allowed(v))
        e.screen_sync_activation.set_screensaver(False)
        self.assertFalse(e._broker_allowed(v))

    def test_brief_event_never_bypasses_other_matrix_priorities(self):
        for blocker in ('thermal','assistant','steam','explicit-steam','timer','launch','pending','off','suspended'):
            with self.subTest(blocker=blocker):
                e,v,d,calls=self.fixture()
                e.screen_sync_activation=ScreenSyncActivation(clock=lambda:1000)
                e.screen_sync_activation.set_screensaver(True)
                e.events.status=lambda:dict(active=True,kind='notification')
                if blocker=='thermal':e.thermal_protection.active=True
                elif blocker=='assistant':d['assistant']=True
                elif blocker=='steam':e._effective_steam_priority=True
                elif blocker=='explicit-steam':e._steam_active_until=float('inf')
                elif blocker=='timer':d['timer']=True
                elif blocker=='launch':d['launch']=True
                elif blocker=='pending':d['pending']=True
                elif blocker=='off':d['panel_off']=True
                elif blocker=='suspended':e._faceplate_suspended=True
                allowed,proof=e._broker_decision(v)
                self.assertFalse(allowed)
                self.assertNotEqual(proof['first_blocker'],'light-event-active')

    def test_same_event_read_supplies_its_kind_without_advancing_queue_twice(self):
        e,v,d,calls=self.fixture()
        def event():calls.append('event');return dict(active=True,kind='screenshot',text='PRIVATE')
        e.events.status=event
        allowed,proof=e._broker_decision(v)
        self.assertFalse(allowed);self.assertEqual(calls,['timer','event'])
        safe=clean(proof);self.assertEqual(safe['light_event'],dict(kind='screenshot'))
        self.assertNotIn('PRIVATE',json.dumps(safe))

    def test_economy_refresh_cannot_reconcile_over_a_leased_display(self):
        e,v,d,calls=self.fixture();e.settings=SimpleNamespace(all=lambda:v)
        e.jsaux_broker_adapter=SimpleNamespace(holds_display=lambda:True)
        e._faceplate_preview_until=0
        for economy in (True,False):
            for refresh in ('economy','minute'):
                v.update(faceplate_flash_protection_enabled=economy,faceplate_artwork_dashboard_refresh=refresh)
                self.assertEqual(e._reconcile_faceplate('periodic',force=True),0)
        self.assertEqual(calls,[])

    def test_steam_inputs_remain_fixed_and_no_arbitrary_payload_is_exported(self):
        e,v,d,calls=self.fixture();e._effective_steam_priority=True
        e._broker_steam_inputs=dict(policy='cooperative',download_lease=False,native_effect=True,guard_hard_priority=True,raw='PRIVATE')
        e._broker_steam_inputs_at=999
        with patch('signalbar.backend.engine.time.monotonic',return_value=1000):_,proof=e._broker_decision(v)
        safe=clean(proof);self.assertEqual(safe['steam_inputs_age_ms'],1000)
        self.assertNotIn('PRIVATE',json.dumps(safe));self.assertTrue(safe['steam_inputs']['native_effect'])
        for invalid in ({'first_blocker':'PRIVATE','steam_inputs':{'policy':'PRIVATE'}},None,[]):
            self.assertNotIn('PRIVATE',json.dumps(clean(invalid)))

    def test_all_fixed_labels_survive_the_real_gca_report_sanitizer(self):
        from signalbar.diagnostics import DiagnosticJournal
        with tempfile.TemporaryDirectory() as root:
            journal=DiagnosticJournal(root,'1.4.1-lab.152')
            for blocker in BLOCKERS:
                proof=clean(dict(first_blocker=blocker,evaluated={blocker:True},
                    steam_inputs=dict(guard_reason='repeated-led-activity',policy='cooperative')))
                snapshot=dict(usb=dict(priority_evidence=dict(revocations=[dict(decision=proof,
                    flash_continuity_ms=0,economy_refresh=True)])))
                report=journal.build_report(cinema=snapshot)['report']['cinema']
                self.assertEqual(report,snapshot)

