"""Manual brightness policy; transport confirmation remains independent."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.settings import SettingsStore
from signalbar.faceplate import gif, power
import test_screensaver_restore148 as restore_fixture


class ManualBrightness185Tests(unittest.TestCase):
    def test_fresh_install_starts_at_seventy_and_persists_later_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'settings.json')
            store = SettingsStore(path)
            self.assertEqual(store.all()['faceplate_brightness'], 70)
            store.update({'faceplate_brightness': 95})
            self.assertEqual(SettingsStore(path).all()['faceplate_brightness'], 95)

    def test_existing_saved_choices_survive_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            for value in (5,35,70,85,100):
                path = Path(folder)/f'{value}.json'
                path.write_text(json.dumps({'faceplate_brightness': value}))
                self.assertEqual(SettingsStore(str(path)).all()['faceplate_brightness'], value)

    def test_legacy_existing_configuration_retains_its_previous_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'settings.json'
            path.write_text('{}')
            self.assertEqual(SettingsStore(str(path)).all()['faceplate_brightness'], 100)

    def test_explicit_reset_uses_the_new_default(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder)/'settings.json'))
            store.update({'faceplate_brightness': 90})
            store.reset_configuration()
            self.assertEqual(store.all()['faceplate_brightness'], 70)

    def fixture(self, brightness):
        f = restore_fixture.Restore148Tests(); f.setUp()
        self.addCleanup(f.doCleanups)
        f.coordinator.configure(True, brightness)
        return f

    @staticmethod
    def levels(f):
        return [payload[0] for kind, cmd, payload in f.panel.events if (kind,cmd)==(1,2)]

    def test_dark_and_white_animations_do_not_profile_or_modify_the_command(self):
        for requested in (70,85,100):
            with self.subTest(requested=requested):
                f = self.fixture(requested)
                with patch.object(power,'record_encoded',side_effect=AssertionError('encoder profile forbidden')), patch.object(power,'profile',side_effect=AssertionError('delivery profile forbidden')):
                    for index, colour in enumerate(((10,20,30),(255,255,255),(20,30,40))):
                        data = gif.encode(64,54,[(0,0,0),colour],[bytes([1])*3456]*80)
                        result = f.coordinator.synchronize_scene(data,'dashboard',str(index))
                        self.assertTrue(result['synchronized'])
                        self.assertEqual(f.panel.stored,data)
                        self.assertEqual(f.coordinator.effective_brightness,requested)
                self.assertEqual(self.levels(f),[requested])
                self.assertFalse(f.coordinator.state.get('power_profiles'))

    def test_missing_commit_keeps_manual_level_and_truthful_pending_restoration(self):
        f = self.fixture(85)
        self.assertTrue(f.coordinator.set_power(False,'screensaver-exit')['ok'])
        f.panel.lose_end = True
        data = gif.encode(64,54,[(255,255,255)],[bytes(3456)])
        result = f.coordinator.synchronize_scene(data,'dashboard','failed')
        self.assertTrue(result['sent_unconfirmed'])
        status = f.coordinator.cached_status()
        self.assertEqual(status['brightness_control']['target_percent'],85)
        self.assertEqual(status['brightness_control']['last_commanded_percent'],85)
        self.assertEqual(status['brightness_control']['limit_reason'],'none')
        self.assertEqual(status['brightness_control']['estimate_source'],'not-used')
        self.assertFalse(status['brightness_control']['command_acknowledged'])
        self.assertIsNone(status['brightness_control']['peak_rgb_load'])
        self.assertTrue(f.coordinator.restoration_status()['held_dark'])
        self.assertFalse(status['powered'])

    def test_previously_prepared_profiles_never_reinstate_a_content_limit(self):
        f = self.fixture(100)
        data = gif.encode(64,54,[(255,255,255)],[bytes(3456)])
        old = power.profile(data)
        f.coordinator.state['power_profiles']={old['sha256']:old}
        result = f.coordinator.synchronize_scene(data,'dashboard','old',power_profile=old)
        self.assertTrue(result['synchronized'])
        self.assertEqual(self.levels(f),[100])

    def test_cached_pixels_are_reused_by_hash_without_profile_validation(self):
        from types import SimpleNamespace
        from signalbar.backend.engine import Engine
        with tempfile.TemporaryDirectory() as folder:
            e = Engine.__new__(Engine)
            e._faceplate_scene_cache = folder
            e._faceplate_state_directory = folder
            payload = {'kind':'dashboard'}
            ticket = SimpleNamespace(scene='dashboard', content_key='same-pixels')
            data = gif.encode(64,54,[(40,50,60)],[bytes(3456)])
            with patch('signalbar.backend.engine.render_isolated',return_value=(data,{'signature':'fixture'})) as render, patch.object(power,'profile',side_effect=AssertionError('cache must not profile')):
                e._render_faceplate_scene(payload,ticket)
                manifest_path = next(Path(folder).glob('*.json'))
                manifest = json.loads(manifest_path.read_text())
                sha = manifest.pop('gif_sha256')
                manifest['power_profile']={'sha256':sha,'peak_load':1.0}
                manifest_path.write_text(json.dumps(manifest))
                self.assertEqual(e._render_faceplate_scene(payload,ticket)[0],data)
                self.assertEqual(render.call_count,1)
                manifest['power_profile']='malformed legacy profile'
                manifest_path.write_text(json.dumps(manifest))
                self.assertEqual(e._render_faceplate_scene(payload,ticket)[0],data)
                self.assertEqual(render.call_count,2)
