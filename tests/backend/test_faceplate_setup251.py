"""A confirmed setup must activate its saved route without another Decky action.

Real setup RPC, Engine, coordinator and serial protocol; simulated MCU only.
"""
import asyncio
import threading
import unittest
from unittest.mock import Mock, patch
from signalbar.onboarding import OnboardingDraft, OnboardingTransaction
from test_cinema_integration import plugin_class
import test_faceplate_recovery244 as fixture

class Setup251Tests(unittest.TestCase):
    def setUp(self):
        fixture.Recovery244Tests.setUp(self)
        self.plugin = plugin_class()()
        self.plugin.engine = self.engine
        self.plugin._onboarding_commit_lock = threading.RLock()
        self.plugin._onboarding_recovery_error = ''
        self.plugin.onboarding_draft = OnboardingDraft(self.f.root/'draft.json')
        self.plugin.onboarding_transaction = OnboardingTransaction(self.f.root/'transaction.json')
        self.plugin._configure_faceplate_power_events = Mock()
        self.engine.set_faceplate_power(False)
        self.f.panel.events.clear()
        self.store.update({'onboarding_completed': False, 'faceplate_setup_completed': False})

    def finish(self, home='weather', requested=True):
        return asyncio.run(self.plugin.complete_onboarding({
            'faceplate_requested': requested, 'home': home, 'game': 'keep'}))

    def tick(self):
        self.engine._service_faceplate_power_retry()
        return self.engine._reconcile_faceplate()

    def assert_activates(self, home):
        self.finish(home)
        self.assertEqual(self.prefs.read().home_scene, 'dashboard')
        self.assertTrue(self.store.all()['faceplate_setup_completed'])
        self.assertFalse(self.engine._faceplate_suspended)
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertTrue(self.result['synchronized'], self.result)
        self.assertTrue(self.f.coordinator.powered)
        self.assertEqual(self.f.panel.commits, 1)
        end = next(i for i,e in enumerate(self.f.panel.events) if e[:2] == (1,11))
        self.assertLess(end, self.f.panel.events.index((1,1,b'\x01')))
        for _ in range(3): self.tick()
        self.assertEqual(self.f.panel.commits, 1)

    def test_legacy_weather_setup_starts_dashboard_without_a_second_decky_choice(self):
        self.assert_activates('weather')

    def test_dashboard_weather_setup_replaces_off_without_a_second_decky_choice(self):
        self.assert_activates('dashboard')
        self.assertEqual(self.store.all()['faceplate_dashboard_home_source'], 'weather')

    def test_general_setup_unplugged_then_connected_faceplate_setup(self):
        with patch.object(self.f.coordinator, 'device_status', return_value={'available':False,'busy':False}):
            asyncio.run(self.plugin.complete_onboarding({}))
        self.assertTrue(self.store.all()['onboarding_completed'])
        self.assertFalse(self.store.all()['faceplate_setup_completed'])
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertEqual(self.f.panel.events, [])
        self.assert_activates('weather')

    def test_power_failure_is_retried_by_the_existing_service(self):
        now = [100.0]
        actual = self.f.coordinator.set_power
        attempts = []
        def power(enabled, reason, **kwargs):
            attempts.append(reason)
            if len(attempts) == 1:
                return {'ok':False,'powered':False,'error':'simulated USB busy'}
            return actual(enabled, reason, **kwargs)
        with patch('signalbar.backend.engine.time.monotonic', side_effect=lambda:now[0]), patch.object(
                self.f.coordinator, 'set_power', side_effect=power):
            self.finish()
            self.assertEqual(self.tick(), 0)
            self.assertTrue(self.engine._faceplate_power_target)
            self.assertEqual(self.f.panel.commits, 0)
            now[0] = 102.1
            self.assertGreater(self.tick(), 0)
        self.assertTrue(self.result['synchronized'])
        self.assertTrue(self.f.coordinator.powered)

    def test_explicit_off_after_setup_cancels_the_queued_activation(self):
        self.finish()
        self.engine.set_faceplate_power(False)
        self.f.panel.events.clear()
        for _ in range(3): self.tick()
        self.assertEqual(self.f.panel.events, [])
        self.assertFalse(self.f.coordinator.powered)

    def test_not_now_does_not_queue_activation(self):
        self.finish(requested=False)
        self.assertTrue(self.store.all()['faceplate_setup_completed'])
        self.assertFalse(self.store.all()['faceplate_lab_enabled'])
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertEqual(self.f.panel.events, [])

    def test_global_off_and_real_system_sleep_remain_authoritative(self):
        self.store.update({'signalbar_enabled':False})
        self.finish()
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertEqual(self.f.panel.events, [])
        self.store.update({'signalbar_enabled':True})
        self.engine._assistant_system_suspended = True
        self.finish()
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertTrue(self.engine._faceplate_suspended)
        self.assertEqual(self.f.panel.events, [])

    def test_failed_setup_rolls_back_without_queuing_power(self):
        before = self.store.base_all()
        self.plugin.onboarding_draft.save({'step':'review','home':'weather'})
        with patch.object(self.engine, 'refresh_settings', side_effect=RuntimeError('provider failure')):
            with self.assertRaises(RuntimeError): self.finish('dashboard')
        self.assertEqual(self.store.base_all(), before)
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertEqual(self.f.panel.events, [])
