"""Retired Studio RPCs preserve user data; independent Steam activation remains."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from signalbar.settings import SettingsStore
from signalbar.activation import ScreenSyncActivation


def plugin_class():
    path = Path(__file__).resolve().parents[2] / "main.py"
    spec = importlib.util.spec_from_file_location("cinema_rpc_integration_subject", path)
    module = importlib.util.module_from_spec(spec)
    decky = types.ModuleType("decky")
    decky.logger = Mock()
    with patch.dict(sys.modules, {"decky": decky}), patch.object(sys, "path", list(sys.path)):
        spec.loader.exec_module(module)
    return module.Plugin


class SeparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_retired_rpc_cannot_mutate_or_prepare_existing_library(self):
        plugin = plugin_class()()
        plugin._cinema_error = "Moved to Decky-Animated-Screensaver"
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); catalog=root/'studio.json'
            catalog.write_text('{"preserved":true}')
            before=catalog.read_bytes()
            for action in ('scan','prepare','resume','configure','install','repair','purge','preview','state'):
                result=await plugin.animated_screensaver_studio(action,{'confirm':True})
                self.assertTrue(result['retired'])
                self.assertTrue(result['preserved_existing_files'])
                self.assertEqual(catalog.read_bytes(),before)
            self.assertEqual([p.name for p in root.iterdir()],['studio.json'])
            self.assertFalse(await plugin.set_cinema_context({'active':True,'token':'old-export'}))

    async def test_saved_screen_sync_value_survives_without_studio(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'config.json'))
            for value in (True,False):
                store.update({'screen_sync_screensaver_enabled':value})
                reloaded=SettingsStore(str(Path(folder)/'config.json'))
                self.assertEqual(reloaded.all()['screen_sync_screensaver_enabled'],value)
                activation=ScreenSyncActivation()
                activation.set_screensaver(True)
                self.assertEqual(activation.resolve(screensaver_enabled=value),
                                 'steam-screensaver' if value else '')

    async def test_broker_diagnostics_use_metadata_not_secrets(self):
        plugin=plugin_class()(); plugin._jsaux_broker_error=''
        plugin.jsaux_broker=object()
        plugin.engine=types.SimpleNamespace(jsaux_broker_adapter=types.SimpleNamespace(
            snapshot=lambda:dict(hardware='available',steam=dict(observed='inactive'))))
        result=await plugin.get_jsaux_broker_status()
        self.assertTrue(result['available']); self.assertTrue(result['studio_retired'])
        self.assertNotIn('capability',json.dumps(result))
        self.assertEqual(plugin._cinema_diagnostic_snapshot(),result)

    async def test_runtime_entry_does_not_import_or_initialize_studio(self):
        source=(Path(__file__).resolve().parents[2]/'main.py').read_text()
        self.assertNotIn('from signalbar.studio',source)
        self.assertNotIn('from signalbar.cinema',source)
        self.assertNotIn('StudioService(',source)
        self.assertNotIn('CinemaResources(',source)
