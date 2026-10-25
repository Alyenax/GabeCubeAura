"""Actual Plugin startup/shutdown orchestration, injected services, no USB."""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_cinema_integration import plugin_class


class PluginBrokerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_start_attaches_broker_before_engine_without_loading_studio(self):
        cls = plugin_class()
        namespace = cls._main.__globals__
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            decky = namespace['decky']
            decky.DECKY_PLUGIN_SETTINGS_DIR = str(root/'settings')
            decky.DECKY_PLUGIN_RUNTIME_DIR = str(root/'runtime')
            decky.DECKY_PLUGIN_DIR = str(root/'plugin')
            (root/'settings').mkdir(mode=0o700)
            engine, diagnostics, server, broker, adapter = (Mock() for _ in range(5))
            diagnostics.state_dir = root/'settings'
            diagnostics.automatic_upload_due.return_value = False
            diagnostics.status.return_value = {'automatic_upload': False}
            engine.settings.all.return_value = {'faceplate_lab_enabled': False}
            engine.assistant.diagnostic = {}
            engine.faceplate_game_snapshot.return_value = {'appid': 0}
            events = []
            server.start.side_effect = lambda: events.append('broker-start')
            engine.start.side_effect = lambda: events.append('engine-start')
            plugin = cls()
            plugin._configure_faceplate_power_events = Mock()
            with patch.dict(namespace, Engine=Mock(return_value=engine),
                            DiagnosticJournal=Mock(return_value=diagnostics),
                            FaceplatePreferencesStore=Mock(),
                            FaceplateBrokerAdapter=Mock(return_value=adapter),
                            provision_runtime=Mock(), CANONICAL_RUNTIME=root/'broker',
                            Broker=Mock(return_value=broker),
                            BrokerServer=Mock(return_value=server), PowerEvents=Mock(),
                            UpdateManager=Mock(), PixelStudioManager=Mock(),
                            ArtworkPreparationJobs=Mock()), \
                 patch.dict('os.environ', {'DECKY_USER_HOME': str(root)}):
                await plugin._main()
                self.assertIsNone(plugin.automatic_incidents)
                await plugin._jsaux_recovery_task
            self.assertEqual(events, ['broker-start', 'engine-start'])
            self.assertIs(engine.jsaux_broker_adapter, adapter)
            self.assertIsNone(plugin.studio)
            self.assertIsNone(plugin.cinema)
            self.assertFalse((root/'.local/share/gabecubeaura/animated-screensaver-studio').exists())
            self.assertTrue((await plugin.animated_screensaver_studio('prepare'))['retired'])
            self.assertFalse(await plugin.set_cinema_context({'active': True}))
            plugin._stop_jsaux_broker(timeout=0)
            server.stop.assert_called_once()
            broker.stop.assert_called_once()

    async def test_broker_start_failure_does_not_stop_normal_engine_start(self):
        cls = plugin_class()
        namespace = cls._main.__globals__
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            decky = namespace['decky']
            for key in ('SETTINGS', 'RUNTIME', ''):
                name = 'DECKY_PLUGIN_'+(key+'_' if key else '')+'DIR'
                setattr(decky, name, str(root/(key.lower() or 'plugin')))
            engine, diagnostics, server = Mock(), Mock(), Mock()
            diagnostics.state_dir = root/'settings'
            diagnostics.automatic_upload_due.return_value = False
            diagnostics.status.return_value = {'automatic_upload': False}
            engine.settings.all.return_value = {'faceplate_lab_enabled': False}
            engine.assistant.diagnostic = {}
            server.start.side_effect = PermissionError('fixture endpoint unavailable')
            plugin = cls(); plugin._configure_faceplate_power_events = Mock()
            (root/'settings').mkdir(mode=0o700)
            with patch.dict(namespace, Engine=Mock(return_value=engine),
                            DiagnosticJournal=Mock(return_value=diagnostics),
                            FaceplatePreferencesStore=Mock(),
                            FaceplateBrokerAdapter=Mock(), Broker=Mock(),
                            provision_runtime=Mock(), CANONICAL_RUNTIME=root/'broker',
                            BrokerServer=Mock(return_value=server), PowerEvents=Mock(),
                            UpdateManager=Mock(), PixelStudioManager=Mock(),
                            ArtworkPreparationJobs=Mock()), \
                 patch.dict('os.environ', {'DECKY_USER_HOME': str(root)}):
                await plugin._main()
                self.assertIsNone(plugin.automatic_incidents)
                plugin._jsaux_recovery_task.cancel()
            engine.start.assert_called_once()
            self.assertIsNone(plugin.jsaux_broker_server)
            self.assertEqual(plugin._jsaux_broker_error, 'PermissionError')
            self.assertFalse((root/'.local/share/gabecubeaura/animated-screensaver-studio').exists())
