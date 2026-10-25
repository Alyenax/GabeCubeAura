"""Real Engine policy + adapter mapping + broker lifecycle; no physical USB."""
from types import SimpleNamespace
import unittest

import test_jsaux_broker_core as core_tests
import test_broker_priority_evidence as policy_tests
from signalbar.activation import ScreenSyncActivation
from signalbar.faceplate.broker_adapter import FaceplateBrokerAdapter


class ScreensaverBriefAlerts172Tests(unittest.TestCase):
    def setUp(self):
        self.core = core_tests.CoreTests()
        self.core.setUp()
        self.addCleanup(self.core.tearDown)
        self.engine,self.values,self.dynamic,_ = policy_tests.PriorityEvidenceTests().fixture()
        self.engine.settings=SimpleNamespace(all=lambda:self.values)
        self.engine.screen_sync_activation=ScreenSyncActivation(clock=self.core.clock)
        self.engine.screen_sync_activation.set_screensaver(True)
        self.event=None
        self.engine.events.status=lambda:dict(active=self.event is not None,kind=self.event)
        # Use the production policy mapper without creating a physical owner.
        self.policy=FaceplateBrokerAdapter.__new__(FaceplateBrokerAdapter)
        self.policy.engine=self.engine
        self.policy._stopped=False
        snapshot=self.core.adapter.snapshot
        def state():
            value=snapshot()
            value['policy']=self.policy._policy()
            return value
        self.core.adapter.snapshot=state

    def start(self):
        lease=self.core.acquire()
        self.core.ok('player_ready',self.core.ready(lease))
        self.assertEqual(len(self.core.adapter.jobs),1)
        self.core.adapter.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        self.assertEqual(self.core.broker.lease['transfer_state'],'confirmed')
        return lease

    def test_brief_alerts_do_not_revoke_fence_restore_or_resend_the_running_gif(self):
        for economy in (False,True):
            self.values['faceplate_flash_protection_enabled']=economy
            # Exercise both legacy/economy settings on the same live session.
            if not self.core.broker.lease:lease=self.start()
            for kind in ('notification','achievement','screenshot'):
                for event in (kind,None,kind,None):
                    self.event=event
                    self.core.clock.now+=.05
                    self.core.broker.tick()
                    status=self.core.ok('operation_status',dict(operation_id=lease['operation_id']))
                    self.assertNotIn(status['lease_state'],('revoking','released','preempted','rejected','expired'))
                    self.assertEqual(status['transfer_state'],'confirmed')
                    self.assertEqual(self.engine.events.status()['active'],event is not None)
                    self.assertFalse(self.policy._policy()['priority_active'])
        self.assertEqual(self.core.adapter.cancellations,[])
        self.assertEqual(self.core.adapter.restorations,[])
        self.assertEqual(len(self.core.adapter.jobs),1)
        self.assertNotIn('activation-1',self.core.broker.fenced)

    def recording_preempts(self,kind):
        lease=self.start();self.event=kind
        self.assertTrue(self.policy._policy()['priority_active'])
        self.core.broker.tick()
        self.assertEqual(self.core.broker.lease['reason'],'PRIORITY_ACTIVE')
        self.assertEqual(self.core.adapter.cancellations,[lease['operation_id']])
        self.assertIn('activation-1',self.core.broker.fenced)

    def test_record_start_keeps_priority(self):
        self.recording_preempts('record-start')

    def test_record_stop_keeps_priority(self):
        self.recording_preempts('record-stop')

    def test_assistant_preempts_even_while_notification_is_active(self):
        lease=self.start();self.event='notification';self.dynamic['assistant']=True
        self.core.broker.tick()
        self.assertEqual(self.core.broker.lease['reason'],'PRIORITY_ACTIVE')
        self.assertEqual(self.core.adapter.cancellations,[lease['operation_id']])

    def test_thermal_preempts_even_while_notification_is_active(self):
        lease=self.start();self.event='notification';self.engine.thermal_protection.active=True
        self.core.broker.tick()
        self.assertEqual(self.core.broker.lease['reason'],'PRIORITY_ACTIVE')
        self.assertEqual(self.core.adapter.cancellations,[lease['operation_id']])

    def test_real_steam_inactive_still_ends_a_brief_alert_session(self):
        lease=self.start();self.event='screenshot'
        self.core.adapter.state['steam']['observed']='inactive'
        self.core.broker.tick()
        self.assertEqual(self.core.broker.lease['reason'],'STEAM_INACTIVE')
        self.assertEqual(self.core.adapter.cancellations,[lease['operation_id']])
