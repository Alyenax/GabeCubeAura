"""A saved slider choice emits gain, never another persistent GIF."""
from pathlib import Path
import unittest
from unittest.mock import patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
import test_screensaver_restore148 as fixture


class LiveBrightness186Tests(unittest.TestCase):
    def test_legacy_slider_applies_usb_off_the_decky_loop_without_starting_companion(self):
        import asyncio
        import importlib.util
        import sys
        import threading
        import types
        from unittest.mock import Mock
        root = Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules, {'decky': types.ModuleType('decky')}):
            spec = importlib.util.spec_from_file_location('brightness186_rpc', root/'main.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            caller = threading.get_ident()
            workers = []
            plugin.engine = types.SimpleNamespace(update_settings=lambda values: workers.append((threading.get_ident(), values)))
            plugin.pixel_studio = Mock()
            plugin.pixel_studio.status.return_value = {'brightness': 85}
            plugin.diagnostics = Mock()
            self.assertEqual(asyncio.run(plugin.set_pixel_studio_brightness(85)), {'brightness': 85})
            self.assertEqual(len(workers), 1)
            self.assertNotEqual(workers[0][0], caller)
            self.assertEqual(workers[0][1], {'faceplate_brightness': 85})
            plugin.pixel_studio.status.assert_called_once_with(probe=False)
            plugin.pixel_studio.start.assert_not_called()

    def setup_engine(self):
        f=fixture.Restore148Tests();f.setUp();self.addCleanup(f.doCleanups)
        store=SettingsStore(str(f.root/'settings.json'))
        store.update({'faceplate_lab_enabled':True,'signalbar_enabled':True})
        e=Engine(store,str(f.root/'artwork.json'),faceplate=f.coordinator)
        self.addCleanup(e.stop)
        return e,f

    def test_settings_slider_changes_the_displayed_gain_without_gif_reupload(self):
        e,f=self.setup_engine()
        with patch.object(f.coordinator,'_send_protected',side_effect=AssertionError('no GIF upload')):
            e.update_settings({'faceplate_brightness':85})
            e.update_settings({'faceplate_brightness':85})
            e.update_settings({'faceplate_brightness':60})
        levels=[p[0] for k,c,p in f.panel.events if (k,c)==(1,2)]
        self.assertEqual(levels,[85,60])
        self.assertFalse(any((k,c) in {(1,4),(2,2),(1,11)} for k,c,p in f.panel.events))
        self.assertEqual(e.settings.all()['faceplate_brightness'],60)
        self.assertEqual(f.coordinator.cached_status()['brightness_control']['last_commanded_percent'],60)

    def test_brightness_never_relights_a_manually_off_panel(self):
        e,f=self.setup_engine()
        f.coordinator.set_power(False,'manual');f.panel.events.clear()
        e.update_settings({'faceplate_brightness':90})
        self.assertFalse(f.coordinator.powered)
        self.assertNotIn((1,1,b'\x01'),f.panel.events)
        self.assertIn((1,2,bytes([90])),f.panel.events)

    def test_suspended_or_disabled_automation_saves_without_hardware(self):
        for kind in ('suspended','disabled','displays-off'):
            with self.subTest(kind=kind):
                e,f=self.setup_engine()
                if kind=='suspended':e._faceplate_suspended=True
                elif kind=='disabled':e.settings.update({'faceplate_lab_enabled':False})
                else:e.settings.update({'signalbar_enabled':False})
                with patch.object(f.coordinator,'set_brightness') as apply:
                    e.update_settings({'faceplate_brightness':75})
                apply.assert_not_called()
                self.assertEqual(e.settings.all()['faceplate_brightness'],75)

    def test_screensaver_dark_handoff_keeps_its_off_state_while_gain_is_saved(self):
        e,f=self.setup_engine()
        f.coordinator.set_power(False,'screensaver-exit');f.panel.events.clear()
        e.update_settings({'faceplate_brightness':80})
        self.assertNotIn((1,1,b'\x01'),f.panel.events)
        self.assertTrue(f.coordinator.restoration_status()['held_dark'])
        self.assertFalse(f.coordinator.powered)
