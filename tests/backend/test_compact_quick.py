import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.providers.countdown import CountdownProvider
from signalbar.faceplate.routing import FaceplatePreferencesStore


class CompactQuickTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = SettingsStore(str(Path(directory.name)/'settings.json'))
        self.engine = Engine(self.store, str(Path(directory.name)/'cache.json'),
                             faceplate_preferences=FaceplatePreferencesStore(Path(directory.name)/'routes.json'))
        self.addCleanup(self.engine.stop)
        self.now = 100.
        self.engine.countdown = CountdownProvider(lambda: self.now)

    def test_extension_keeps_generation_and_power_consent(self):
        self.engine.start_free_timer(30, 'sleep')
        generation = self.engine.countdown.end_action.generation
        self.engine.extend_free_timer(15)
        self.assertEqual(self.engine.countdown.personal_status()['remaining_seconds'], 2700)
        self.assertEqual(self.engine.countdown.end_action.generation, generation)
        self.assertEqual(self.engine.countdown.end_action.status()['action'], 'sleep')
        self.engine.stop_free_timer()
        self.assertEqual(self.engine.countdown.end_action.status()['phase'], 'cancelled')

    def test_invalid_or_absent_timer_cannot_start_or_arm_one(self):
        for minutes in (True, 0, -1, 241, 1.5, '15'):
            with self.assertRaises(ValueError): self.engine.extend_free_timer(minutes)
        with self.assertRaises(RuntimeError): self.engine.extend_free_timer(15)
        self.assertFalse(self.engine.countdown.personal_status()['active'])
        self.assertEqual(self.engine.countdown.end_action.status()['phase'], 'idle')

    def test_families_priority_never_hides_or_modifies_personal_timer(self):
        self.engine._game = type(self.engine._game)(42, 'Example')
        self.engine.start_free_timer(30)
        self.engine.countdown.start('parental', 60)
        self.engine.extend_free_timer(15)
        status = self.engine.status()
        self.assertEqual(status['personal_timer']['remaining_seconds'], 2700)
        self.assertEqual(status['countdown']['source'], 'parental')
        self.engine.stop_free_timer()
        self.assertEqual(self.engine.status()['countdown']['source'], 'parental')

    def test_four_hour_cap_and_expiry_never_restart_a_timer(self):
        self.engine.start_free_timer(240, 'shutdown')
        with self.assertRaises(RuntimeError): self.engine.extend_free_timer(15)
        self.now += 14401
        with self.assertRaises(RuntimeError): self.engine.extend_free_timer(15)
        self.assertFalse(self.engine.countdown.personal_status()['active'])

    def plugin(self):
        with patch.dict(sys.modules, {'decky':types.SimpleNamespace(logger=Mock())}):
            spec=importlib.util.spec_from_file_location('compact_quick_main',Path(__file__).resolve().parents[2]/'main.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        plugin=module.Plugin();plugin.engine=self.engine
        plugin.diagnostics=Mock()
        plugin._configure_faceplate_power_events=Mock()
        return plugin

    def test_each_quick_ambience_is_returned_and_persisted_without_changing_brightness(self):
        plugin=self.plugin()
        self.engine.update_settings({'light_bar_day_brightness':13})
        for preset in ('custom','moderate','atmosphere','signals','immersive','immersive-plus','festive','custom'):
            result=asyncio.run(plugin.set_setting('display_preset',preset))
            self.assertEqual(result['display_preset'],preset)
            self.assertEqual(result['light_bar_day_brightness'],13)
            reloaded=SettingsStore(self.store.path)
            self.assertEqual(reloaded.all()['display_preset'],preset)

    def test_each_quick_faceplate_route_is_returned_and_persisted_without_usb(self):
        plugin=self.plugin()
        # Only preference/response semantics are under test, not hardware delivery.
        with patch.object(self.engine,'_reconcile_faceplate') as reconcile:
            for home in ('dashboard','weather','native-clock'):
                for game in ('artwork','dashboard','weather','artwork-dashboard'):
                    revision=self.engine.faceplate_preferences.read().revision
                    result=asyncio.run(plugin.set_faceplate_routing(home,game,revision))
                    self.assertEqual(result['faceplate']['routing']['routes'],{'home':home,'game':game})
                    reloaded=FaceplatePreferencesStore(self.engine.faceplate_preferences.path)
                    self.assertEqual(reloaded.read().home_scene,home)
                    self.assertEqual(reloaded.read().game_scene,game)
            self.assertTrue(reconcile.called)

    def test_faceplate_brightness_keeps_global_light_routes_and_presets(self):
        plugin = self.plugin()
        before = self.store.all()
        routes = self.engine.faceplate_preferences.read()
        with patch.object(self.engine.faceplate, 'configure') as configure:
            for value in (5, 35, 100):
                result = asyncio.run(plugin.set_setting('faceplate_brightness', value))
                self.assertEqual(result['faceplate_brightness'], value)
                self.assertEqual(result['display_preset'], before['display_preset'])
                self.assertEqual(result['light_bar_day_brightness'], before['light_bar_day_brightness'])
                self.assertEqual(self.engine.faceplate_preferences.read(), routes)
                self.assertEqual(SettingsStore(self.store.path).all()['faceplate_brightness'], value)
            self.assertEqual(configure.call_count, 3)

    def test_retired_listening_switch_is_absent_and_migration_preferences_remain(self):
        plugin=self.plugin()
        config=dict(self.store.all()['gabe_assistant'],enabled=True,wake_enabled=True,language='en',character='gabe',microphone='my-mic')
        self.engine.update_settings({'gabe_assistant':config})
        before=self.store.all()
        self.assertFalse(hasattr(plugin,'set_gabe_listening'))
        self.assertEqual(self.store.all(),before)
        for key in ('language','character','microphone','confirm_game_close','wake_enabled','enabled'):
            self.assertEqual(before['gabe_assistant'][key],config[key])
        plugin._configure_faceplate_power_events.assert_not_called()

    def test_rpc_extension_does_not_change_settings_or_trigger_hardware(self):
        plugin=self.plugin();self.engine.start_free_timer(5, 'sleep')
        before=self.store.all()
        result=asyncio.run(plugin.extend_free_timer(15))
        self.assertEqual(result['personal_timer']['remaining_seconds'],1200)
        self.assertEqual(self.store.all(),before)
        plugin._configure_faceplate_power_events.assert_not_called()

    def test_quick_ui_markers_are_included_in_the_existing_diagnostic_journal(self):
        plugin=self.plugin()
        before=self.store.all()
        for source in ('panel:mounted','timer:opened','timer:failed:shutdown',
                       'ambience:opening','ambience:opened','ambience:selected:signals',
                       'ambience:requested:signals','ambience:saved:signals',
                       'faceplate:failed:weather'):
            asyncio.run(plugin.report_runtime_diagnostic('quick_panel_ui',0,source,0))
            self.assertEqual(plugin.diagnostics.record.call_args.kwargs['source'],source)
        self.assertEqual(plugin.diagnostics.record.call_count,9)
        self.assertEqual(self.store.all(),before)
        plugin._configure_faceplate_power_events.assert_not_called()
