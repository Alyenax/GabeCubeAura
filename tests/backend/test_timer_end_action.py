"""No real power commands: deterministic clock and mocked existing action path."""
import tempfile
import asyncio
import importlib.util
import sys
import types
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from signalbar.backend import Engine
from signalbar.providers.countdown import CountdownProvider
from signalbar.providers.timer_end_action import TimerEndAction
from signalbar.settings import SettingsStore


class TimerEndActionTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.
        self.timer = CountdownProvider(lambda: self.now)

    def test_default_and_preview_and_families_never_request_power(self):
        for source in ('free', 'preview', 'parental'):
            self.timer.start(source, 10)
            self.now += 11
            self.assertIsNone(self.timer.claim_end_action())
        for source in ('preview', 'parental'):
            with self.assertRaises(ValueError): self.timer.start(source, 10, end_action='shutdown')

    def test_natural_expiry_is_single_use_despite_status_polling(self):
        for action in ('sleep', 'shutdown'):
            self.timer.start('free', 10, end_action=action)
            self.now += 10
            for poll in (self.timer.status, self.timer.personal_status, self.timer.faceplate_snapshot): poll()
            request = self.timer.claim_end_action()
            self.assertEqual(request[1], action)
            self.assertFalse(request[2].is_set())
            for _ in range(10): self.assertIsNone(self.timer.claim_end_action())
            self.timer.end_action.finish(request[0], True)
            self.assertEqual(self.timer.end_action.status()['phase'], 'requested')

    def test_hidden_personal_timer_still_uses_its_own_deadline(self):
        self.timer.start('free', 10, end_action='sleep')
        self.timer.start('parental', 100)
        self.timer.start('preview', 50)
        self.now += 11
        self.assertEqual(self.timer.status()['source'], 'preview')
        self.assertEqual(self.timer.claim_end_action()[1], 'sleep')

    def test_stop_and_replacement_cancel_pending_or_inflight_requests(self):
        self.timer.start('free', 10, end_action='shutdown')
        self.now += 10
        request = self.timer.claim_end_action()
        self.timer.stop('free')
        self.assertTrue(request[2].is_set())
        self.timer.end_action.finish(request[0], True)
        self.assertEqual(self.timer.end_action.status()['phase'], 'cancelled')
        self.timer.start('free', 10, end_action='shutdown')
        self.now += 10
        self.timer.personal_status()  # expiry queued by a read, then replaced
        self.timer.start('free', 50)
        self.assertIsNone(self.timer.claim_end_action())

    def test_extension_updates_existing_deadline(self):
        self.timer.start('free', 10, end_action='sleep')
        self.now += 5
        self.assertTrue(self.timer.extend_personal(20))
        self.now += 5
        self.assertIsNone(self.timer.claim_end_action())
        self.now += 20
        self.assertEqual(self.timer.claim_end_action()[1], 'sleep')

    def test_late_expiry_and_suspend_cannot_fire_on_resume(self):
        self.timer.start('free', 10, end_action='shutdown')
        self.now += 41
        self.assertIsNone(self.timer.claim_end_action())
        self.assertEqual(self.timer.end_action.status()['phase'], 'skipped')
        self.timer.start('free', 10, end_action='sleep')
        self.timer.end_action.cancel('system-suspended')
        self.now += 10
        self.assertIsNone(self.timer.claim_end_action())

    def test_failed_request_never_retries_and_stale_finish_cannot_overwrite_new_arm(self):
        self.timer.start('free', 10, end_action='sleep')
        self.now += 10
        request = self.timer.claim_end_action()
        self.timer.end_action.finish(request[0], False)
        self.assertEqual(self.timer.end_action.status()['phase'], 'failed')
        self.assertIsNone(self.timer.claim_end_action())
        self.timer.start('free', 20, end_action='shutdown')
        self.timer.end_action.finish(request[0], True)
        self.assertEqual(self.timer.end_action.status(), {'action':'shutdown','phase':'armed','reason':''})

    def test_invalid_actions_and_new_process_are_unarmed(self):
        for action in ('reboot', '', [], None, True):
            with self.assertRaises(ValueError): self.timer.start('free', 10, end_action=action)
        self.assertEqual(TimerEndAction().status()['phase'], 'idle')

    def test_cancelling_a_preview_does_not_disarm_the_personal_timer(self):
        self.timer.start('free', 10, end_action='sleep')
        self.timer.start('preview', 15)
        self.timer.stop('preview')
        self.now += 10
        self.assertEqual(self.timer.claim_end_action()[1], 'sleep')


class EngineTimerPowerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.store = SettingsStore(str(Path(self.directory.name)/'settings.json'))
        self.engine = Engine(self.store, str(Path(self.directory.name)/'cache.json'))
        self.now = 100.
        self.engine.countdown = CountdownProvider(lambda: self.now)
        self.engine.assistant.actions.request = Mock()
        self.addCleanup(self.engine.stop)

    def expire(self, action='sleep'):
        self.engine.start_free_timer(1, action)
        self.now += 60

    def service(self):
        self.engine._service_timer_end_action()
        if self.engine._timer_power_thread: self.engine._timer_power_thread.join(1)

    def test_actions_work_without_open_panel_or_led_hardware(self):
        for action in ('sleep', 'shutdown'):
            self.expire(action); self.service(); self.service()
            self.assertEqual(self.engine.assistant.actions.request.call_args.args[:2], (action, 0))
        self.assertEqual(self.engine.assistant.actions.request.call_count, 2)

    def test_preference_does_not_arm_voice_or_existing_timer(self):
        self.store.update({'free_timer_end_action':'shutdown'})
        self.engine.start_free_timer(1)  # voice and old clients omit consent
        self.now += 60; self.service()
        self.engine.assistant.actions.request.assert_not_called()
        self.assertEqual(self.engine.status()['timer_end_action']['action'], 'none')

    def test_suspend_unload_cancellation_and_backend_errors(self):
        self.expire(); self.engine._assistant_system_suspended = True; self.service()
        self.engine._assistant_system_suspended = False; self.service()
        self.engine.assistant.actions.request.assert_not_called()
        self.expire(); self.engine.assistant.actions.request.side_effect = RuntimeError('not available')
        self.service(); self.service()
        self.assertEqual(self.engine.assistant.actions.request.call_count, 1)
        self.assertEqual(self.engine.countdown.end_action.status()['phase'], 'failed')
        self.expire(); self.engine._stop.set(); self.service()
        self.assertEqual(self.engine.assistant.actions.request.call_count, 1)

    def test_stop_while_request_is_pending_invalidates_cancel_token(self):
        entered, release = threading.Event(), threading.Event()
        def wait(action, appid, cancel):
            entered.set(); release.wait(1); self.assertTrue(cancel.is_set())
        self.engine.assistant.actions.request.side_effect = wait
        self.expire(); self.engine._service_timer_end_action()
        self.assertTrue(entered.wait(1)); self.engine.stop_free_timer(); release.set()
        self.engine._timer_power_thread.join(1)
        self.assertEqual(self.engine.countdown.end_action.status()['phase'], 'cancelled')

    def test_preference_does_not_reconfigure_hardware_and_defaults_are_safe(self):
        self.assertEqual(self.store.all()['free_timer_end_action'], 'none')
        with patch.object(self.engine, '_apply_settings') as apply, patch.object(self.engine.assistant, 'cancel') as voice_cancel:
            self.engine.update_settings({'free_timer_end_action':'sleep'})
            apply.assert_not_called()
            voice_cancel.assert_not_called()
        for value in ('reboot', 'force', [], None):
            self.store.update({'free_timer_end_action':value})
            self.assertEqual(self.store.all()['free_timer_end_action'], 'none')

    def test_choosing_none_disarms_current_power_without_stopping_timer(self):
        self.engine.start_free_timer(1, 'shutdown')
        self.engine.update_settings({'free_timer_end_action':'none'})
        self.assertTrue(self.engine.countdown.personal_status()['active'])
        self.now += 60; self.service()
        self.engine.assistant.actions.request.assert_not_called()

    def test_resume_recovery_disarms_even_if_the_suspend_observer_was_missed(self):
        self.engine.start_free_timer(1, 'shutdown')
        self.engine.resume_faceplate()
        self.now += 60; self.service()
        self.engine.assistant.actions.request.assert_not_called()

    def test_live_engine_services_expiry_without_led_hardware(self):
        called = threading.Event()
        self.engine.assistant.actions.request.side_effect = lambda *args: called.set()
        self.engine.hardware_factory = Mock(side_effect=RuntimeError('no LEDs'))
        self.store.update({'signalbar_enabled':False})
        self.expire('sleep'); self.engine.start()
        self.assertTrue(called.wait(2), 'power dispatch must not depend on LED ownership/hardware')

    def test_rpc_enables_shared_suspend_observer_without_voice_or_faceplate(self):
        root = Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules, {'decky':types.SimpleNamespace(logger=Mock())}):
            spec=importlib.util.spec_from_file_location('timer_power_main', root/'main.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        plugin=module.Plugin(); plugin.engine=self.engine; plugin.faceplate_power_events=Mock()
        self.store.update({'faceplate_lab_enabled':False})
        asyncio.run(plugin.start_free_timer(1, 'sleep'))
        plugin.faceplate_power_events.start.assert_called_once()
        plugin._handle_faceplate_power_event('sleep', True)
        self.now += 60; plugin._handle_faceplate_power_event('sleep', False); self.service()
        self.engine.assistant.actions.request.assert_not_called()

    def test_import_or_reset_never_rearms_an_existing_timer(self):
        for operation in ('import', 'reset'):
            self.engine.start_free_timer(1, 'shutdown')
            with patch.object(self.engine, '_apply_settings'):
                if operation == 'import': self.engine.import_configuration({'free_timer_end_action':'shutdown'}, {}, {})
                else: self.engine.reset_configuration()
            self.now += 60; self.service()
            self.engine.assistant.actions.request.assert_not_called()
