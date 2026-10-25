"""Lost END receipt: one delayed retry, real reconnect and explicit recovery."""
from unittest.mock import patch
import unittest
from signalbar.backend import Engine
import test_faceplate_recovery244 as fixture

class Recovery250Tests(unittest.TestCase):
    setUp=fixture.Recovery244Tests.setUp

    def start_unconfirmed(self, now):
        self.f.exit();self.f.panel.lose_end=True
        self.assertGreater(self.engine._reconcile_faceplate(),0)
        self.assertTrue(self.result['sent_unconfirmed'])
        self.assertEqual(self.f.panel.commits,1)
        self.assertFalse(self.f.coordinator.powered)
        self.assertEqual(self.engine._faceplate_scene_retry_at,now[0]+30)
        self.f.panel.events.clear()

    def test_first_missing_receipt_waits_then_retries_once_and_relights_after_ack(self):
        now=[100.0]
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            self.start_unconfirmed(now)
            for _ in range(20):self.assertEqual(self.engine._reconcile_faceplate(),0)
            self.assertEqual(self.engine._faceplate_route_recovery['state'],'retry-waiting')
            self.assertEqual(self.f.panel.events,[])
            now[0]=129.9;self.assertEqual(self.engine._reconcile_faceplate(),0)
            self.f.panel.lose_end=False;now[0]=130.0
            self.assertGreater(self.engine._reconcile_faceplate(),0)
            self.assertTrue(self.result['synchronized'],self.result)
        self.assertEqual(self.f.panel.commits,2)
        self.assertTrue(self.f.coordinator.powered)
        self.assertFalse(self.f.coordinator.restoration_status()['pending'])
        end=next(i for i,e in enumerate(self.f.panel.events) if e[:2]==(1,11))
        on=self.f.panel.events.index((1,1,b'\x01'))
        self.assertLess(end,on)
        self.assertEqual(self.f.panel.empty_ends,0)
        self.assertEqual(self.f.coordinator.flash.session['uncertain'],1)
        self.assertEqual(self.f.coordinator.flash.session['confirmed'],1)

    def test_second_missing_receipt_stops_without_a_third_body_or_power_on(self):
        now=[100.0]
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            self.start_unconfirmed(now);now[0]=130
            self.assertGreater(self.engine._reconcile_faceplate(),0)
            self.assertTrue(self.result['sent_unconfirmed'])
            self.f.panel.events.clear();now[0]=1000
            for _ in range(60):self.assertEqual(self.engine._reconcile_faceplate(),0)
        self.assertEqual(self.f.panel.commits,2)
        self.assertEqual(self.f.panel.events,[])
        self.assertEqual(self.engine._faceplate_route_recovery['state'],'unconfirmed')
        self.f.assert_no_on()

    def test_real_usb_reconnect_is_observed_before_the_uncertain_gate(self):
        self.engine._faceplate_continuity=Engine._faceplate_continuity.__get__(self.engine,Engine)
        now=[100.0]
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            self.start_unconfirmed(now)
            self.f.panel.token='new-usb-session';self.f.panel.lose_end=False
            self.assertGreater(self.engine._reconcile_faceplate(hardware={
                'available':True,'busy':False,'port':'/test','device_identity':self.f.panel.token}),0)
        self.assertTrue(self.result['synchronized']);self.assertEqual(self.f.panel.commits,2)
        self.assertTrue(self.f.coordinator.powered)

    def test_explicit_power_on_can_retry_the_same_uncertain_image_without_reconnect(self):
        now=[100.0]
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            self.start_unconfirmed(now);self.f.panel.lose_end=False
            result=self.engine.set_faceplate_power(True)
        self.assertTrue(result['deferred_to_route'])
        self.assertTrue(self.result['synchronized']);self.assertEqual(self.f.panel.commits,2)
        self.assertTrue(self.f.coordinator.powered)

    def test_no_retry_while_off_unplugged_or_busy_and_incomplete_transfer_is_not_eligible(self):
        now=[100.0]
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            self.start_unconfirmed(now);now[0]=200
            for presence in [{'available':False},{'available':True,'busy':True}]:
                self.assertEqual(self.engine._reconcile_faceplate(hardware=presence),0)
            self.assertEqual(self.f.panel.events,[])
            self.f.coordinator._restore_uncertain['transfer']['payload_complete']=False
            self.assertFalse(self.f.coordinator.retry_uncertain_restore())
            self.engine.set_faceplate_power(False);self.f.panel.events.clear()
            for _ in range(10):self.assertEqual(self.engine._reconcile_faceplate(),0)
        self.assertEqual(self.f.panel.events,[])
        self.assertEqual(self.f.panel.commits,1)

    def test_real_setup_without_device_then_connected_setup_recovers_the_first_failed_transfer(self):
        import asyncio
        import threading
        from unittest.mock import Mock
        from signalbar.onboarding import OnboardingDraft, OnboardingTransaction
        from test_cinema_integration import plugin_class
        plugin=plugin_class()();plugin.engine=self.engine
        plugin._onboarding_commit_lock=threading.RLock()
        plugin._onboarding_recovery_error=''
        plugin.onboarding_draft=OnboardingDraft(self.f.root/'draft.json')
        plugin.onboarding_transaction=OnboardingTransaction(self.f.root/'transaction.json')
        plugin._configure_faceplate_power_events=Mock()
        self.store.update({'onboarding_completed':False,'faceplate_setup_completed':False})
        with patch.object(self.f.coordinator,'device_status',return_value={'available':False,'busy':False}):
            asyncio.run(plugin.complete_onboarding({}))
        self.assertTrue(self.store.all()['onboarding_completed'])
        self.assertFalse(self.store.all()['faceplate_setup_completed'])
        now=[100.0]
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            self.f.panel.lose_end=True
            asyncio.run(plugin.complete_onboarding({'faceplate_requested':True,'home':'weather','game':'keep'}))
            self.assertTrue(self.store.all()['faceplate_setup_completed'])
            self.assertTrue(self.f.coordinator.restoration_status()['pending'])
            self.assertTrue(self.result['sent_unconfirmed'])
            self.f.panel.lose_end=False;now[0]=130
            self.assertGreater(self.engine._reconcile_faceplate(),0)
        self.assertTrue(self.result['synchronized']);self.assertTrue(self.f.coordinator.powered)
        self.assertTrue(self.store.all()['onboarding_completed'])
        self.assertTrue(self.store.all()['faceplate_setup_completed'])
