"""GH-06: run the actual RPCs with the two historical lock paths aligned."""
import asyncio
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.onboarding import OnboardingDraft, OnboardingTransaction
from test_cinema_integration import plugin_class


def concurrent_rpcs():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = SettingsStore(str(root/'config.json'))
        engine = Engine(store, str(root/'cache'))
        engine.assistant = Mock(active=False)
        engine.assistant.status.return_value = {'voice_ready': False}
        engine.faceplate.device_status = lambda: {'available': False}
        engine.faceplate_worker = Mock()
        engine.faceplate_worker.status.return_value = {}
        engine._apply_settings = Mock(wraps=engine._apply_settings)
        plugin = plugin_class()()
        plugin.engine = engine
        plugin._onboarding_commit_lock = threading.RLock()
        plugin._onboarding_recovery_error = ''
        plugin._configure_faceplate_power_events = Mock()
        plugin.onboarding_draft = OnboardingDraft(root/'draft.json')
        plugin.onboarding_transaction = OnboardingTransaction(root/'transaction.json')
        engine_held, settings_held, display_waiting = (threading.Event() for _ in range(3))
        original_launch, original_display, original_plan = engine.launch_artwork.status, store.display_for, store.plan_update
        def launch(*args):
            if threading.current_thread().name.startswith('asyncio') and not engine_held.is_set():
                engine_held.set()
                assert settings_held.wait(2)
            return original_launch(*args)
        def display(*args):
            if settings_held.is_set(): display_waiting.set()
            return original_display(*args)
        def plan(changes):
            settings_held.set()
            assert display_waiting.wait(2)
            return original_plan(changes)
        engine.launch_artwork.status, store.display_for, store.plan_update = launch, display, plan
        async def scenario():
            status = asyncio.create_task(plugin.get_status())
            assert await asyncio.to_thread(engine_held.wait, 2)
            setup = asyncio.create_task(plugin.complete_onboarding({'assistant_requested': False}))
            await asyncio.wait_for(asyncio.gather(status, setup), 3)
            assert store.base_all()['onboarding_completed']
            # A delayed application always uses the latest committed values.
            store.update({'light_bar_day_brightness': 23})
            engine.refresh_settings({'light_bar_day_brightness': 5})
            assert engine._apply_settings.call_args.args[0]['light_bar_day_brightness'] == 23
        asyncio.run(scenario())


class OnboardingLockTests(unittest.TestCase):
    def test_complete_and_status_terminate_without_losing_newer_settings(self):
        process = multiprocessing.get_context('spawn').Process(target=concurrent_rpcs)
        process.start()
        process.join(6)
        if process.is_alive():
            process.terminate(); process.join()
            self.fail('The real complete_onboarding/get_status RPCs deadlocked')
        self.assertEqual(0, process.exitcode)
