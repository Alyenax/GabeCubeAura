"""Full Plugin startup bodies with explicit provider/Decky doubles, no devices.

Unlike the small AST startup test, failures are injected after the engine has
started as well. Claim files and the production shutdown methods execute.
"""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_cinema_integration import plugin_class
from signalbar import faceplate_claim


class StartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.plugin = plugin_class()()
        self.engine = SimpleNamespace(
            settings=SimpleNamespace(all=lambda: {'faceplate_lab_enabled': True}),
            _stop=threading.Event(),
            countdown=SimpleNamespace(end_action=Mock()),
            assistant=Mock(), faceplate=SimpleNamespace(steamgriddb=Mock()),
            faceplate_game_snapshot=Mock(return_value={}),
            start=Mock(), stop=Mock(),
        )
        self.broker, self.server = Mock(), Mock()
        def start_broker():
            self.plugin.jsaux_broker = self.broker
            self.plugin.jsaux_broker_server = self.server
        self.plugin._start_jsaux_broker = Mock(side_effect=start_broker)
        self.plugin._migrate_legacy_settings = Mock(return_value='')
        self.plugin._configure_faceplate_power_events = Mock()
        ns = self.plugin._main.__globals__
        self.dependencies = {name: Mock() for name in (
            'DiagnosticJournal', 'SettingsStore', 'FaceplatePreferencesStore',
            'OnboardingDraft', 'OnboardingTransaction', 'ScreenSyncTrace',
            'FaceplateBrokerAdapter', 'PowerEvents', 'UpdateManager',
            'PixelStudioManager', 'ArtworkPreparationJobs',
        )}
        self.dependencies['OnboardingTransaction'].return_value.recover.return_value = None
        self.dependencies.update(
            Engine=Mock(return_value=self.engine),
            configuration_export_path=Mock(return_value=str(self.directory/'config.json')),
            CANONICAL_RUNTIME=self.directory/'runtime',
            decky=SimpleNamespace(
                DECKY_PLUGIN_SETTINGS_DIR=str(self.directory),
                DECKY_PLUGIN_RUNTIME_DIR=str(self.directory),
                DECKY_PLUGIN_DIR=str(self.directory), logger=Mock()),
        )
        self.patch = patch.dict(ns, self.dependencies)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def assert_released(self):
        self.assertFalse((self.directory/faceplate_claim.CLAIM_FILENAME).exists())
        self.engine.stop.assert_called()
        self.assertTrue(self.engine._stop.is_set())
        self.broker.stop.assert_called()
        self.server.stop.assert_called()
        # A later saved-setting callback must not reclaim after failed startup.
        self.plugin._sync_faceplate_claim()
        self.assertFalse((self.directory/faceplate_claim.CLAIM_FILENAME).exists())

    async def test_engine_partial_start_failure_stops_and_releases(self):
        self.engine.start.side_effect = RuntimeError('engine partially started')
        with self.assertRaisesRegex(RuntimeError, 'engine partially started'):
            await self.plugin._main()
        self.assert_released()

    async def test_update_manager_constructor_failure_stops_and_releases(self):
        self.dependencies['UpdateManager'].side_effect = OSError('runtime storage unavailable')
        with self.assertRaisesRegex(OSError, 'runtime storage unavailable'):
            await self.plugin._main()
        self.assert_released()
        # Decky can call unload again after a failed startup.
        await self.plugin._unload()
        self.assert_released()

    async def test_pixel_studio_cleanup_failure_stops_and_releases(self):
        self.dependencies['PixelStudioManager'].return_value.disable_standalone.side_effect = OSError('desktop cleanup failed')
        with self.assertRaisesRegex(OSError, 'desktop cleanup failed'):
            await self.plugin._main()
        self.assert_released()
        self.dependencies['UpdateManager'].return_value.stop.assert_called()

    async def test_final_update_start_failure_stops_and_releases(self):
        self.dependencies['UpdateManager'].return_value.start.side_effect = RuntimeError('update worker failed')
        with self.assertRaisesRegex(RuntimeError, 'update worker failed'):
            await self.plugin._main()
        self.assert_released()
        self.dependencies['ArtworkPreparationJobs'].return_value.cancel.assert_called()

    async def test_startup_cancellation_stops_and_releases(self):
        self.engine.start.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.plugin._main()
        self.assert_released()

    async def test_successful_start_claims_before_engine_and_unload_releases(self):
        def observe_claim():
            self.assertTrue((self.directory/faceplate_claim.CLAIM_FILENAME).exists())
        self.engine.start.side_effect = observe_claim
        await self.plugin._main()
        self.assertTrue((self.directory/faceplate_claim.CLAIM_FILENAME).exists())
        self.engine.stop.assert_not_called()
        await self.plugin._unload()
        self.assert_released()

    async def test_unload_before_engine_construction_is_safe(self):
        await self.plugin._unload()
        self.assertFalse((self.directory/faceplate_claim.CLAIM_FILENAME).exists())
        self.engine.stop.assert_not_called()
