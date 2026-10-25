import json
"""Reset contracts: preserve creations/access, or explicitly erase GCA user data."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate
from signalbar.faceplate.artwork_jobs import ArtworkPreparationJobs
from signalbar.updates import GitHubDeviceAuth
from signalbar.configuration_reset import factory_reset, FACTORY_RESET_CONFIRMATION
from signalbar.onboarding import OnboardingDraft


class ConfigurationResetTests(unittest.TestCase):
    def test_first_install_follows_gca_but_preserves_existing_choices_and_reset(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            first=SettingsStore(str(path),first_install_defaults=True)
            self.assertTrue(first.all()['faceplate_lab_enabled'])
            self.assertFalse(first.all()['onboarding_completed'])
            self.assertFalse(path.exists(), 'Loading does not save preferences')
            source=(Path(__file__).resolve().parents[2]/'main.py').read_text()
            self.assertIn('SettingsStore(settings_path, first_install_defaults=True)',source)
            for enabled in (False,True):
                first.update({'faceplate_lab_enabled':enabled})
                self.assertEqual(enabled,SettingsStore(str(path),first_install_defaults=True).all()['faceplate_lab_enabled'])
            first.reset_configuration()
            self.assertTrue(SettingsStore(str(path),first_install_defaults=True).all()['faceplate_lab_enabled'])
            path.write_text(json.dumps({'onboarding_completed':True}))
            self.assertTrue(SettingsStore(str(path),first_install_defaults=True).all()['faceplate_lab_enabled'])
            path.write_text('broken')
            self.assertFalse(SettingsStore(str(path),first_install_defaults=True).all()['faceplate_lab_enabled'])

    def fixture(self, directory):
        root = Path(directory)
        store = SettingsStore(str(root / 'settings' / 'config.json'))
        store.update({'light_bar_day_brightness': 34, 'night_mode_enabled': False, 'onboarding_completed': True,
                      'faceplate_dashboard_show_bottom_row': False})
        engine = Engine(store, str(root / 'settings' / 'artwork-cache.json'),
                        faceplate_preferences=FaceplatePreferencesStore(root / 'routing.json'))
        self.addCleanup(engine.stop)
        library = SteamGridDBFaceplate(root / 'steamgriddb')
        engine.faceplate.steamgriddb = library
        library.root.mkdir()
        library.auth_path.write_text('{"api_key":"test-only-steamgriddb-key"}')
        content = library.artwork_root / '620' / 'prepared' / 'static' / 'scene.gif'
        content.parent.mkdir(parents=True)
        content.write_bytes(b'test-only-created-artwork')
        library.set_preference('static')
        engine.ambience.save('Evening', {'home_display': 'audio_sync', 'night_mode_enabled': False})
        auth = GitHubDeviceAuth(root / 'updates' / 'private-auth.json', client_id='test-client-1234', repository_id=1)
        auth._state = {'schema': 1, 'phase': 'connected', 'access_token': 'test-only-token', 'refresh_token': 'test-only-refresh'}
        auth.path.parent.mkdir(parents=True,exist_ok=True)
        auth.path.write_text(json.dumps(auth._state))
        manager = SimpleNamespace(_operation_lock=threading.Lock(), status=lambda: {'phase': 'idle'},
                                  disconnect_private_authorization=auth.disconnect)
        plugin = SimpleNamespace(engine=engine, update_manager=manager,
                                 faceplate_artwork_jobs=ArtworkPreparationJobs(library, lambda: {'appid': 0}))
        return plugin, library, auth, content

    def test_settings_only_preserves_credentials_library_and_named_creations_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            plugin, library, auth, content = self.fixture(folder)
            retained = {path: path.read_bytes() for path in (library.auth_path, auth.path, content, plugin.engine.ambience.path)}
            plugin.engine.faceplate_preferences.update(home_scene='weather', game_scene='weather')
            plugin.engine.reset_settings_only()
            for path, data in retained.items():
                self.assertEqual(data, path.read_bytes(), path.name)
            self.assertTrue(plugin.engine.settings.all()['faceplate_dashboard_show_bottom_row'])
            self.assertEqual('dashboard', plugin.engine.faceplate_preferences.read().home_scene)
            self.assertEqual('artwork', plugin.engine.faceplate_preferences.read().game_scene)
            self.assertEqual('animated_any', library.preference())
            self.assertEqual(1, len(plugin.engine.ambience.status()['profiles']))

    def test_complete_reset_removes_local_access_and_all_saved_artwork_and_ambiences(self):
        with tempfile.TemporaryDirectory() as folder:
            plugin, library, auth, content = self.fixture(folder)
            other = Path(folder) / 'DVA-and-DAS-unrelated'
            other.mkdir(); (other / 'keep.gif').write_bytes(b'unrelated-content')
            # A link inside the owned library must not delete its external target.
            (library.artwork_root / 'external').symlink_to(other, target_is_directory=True)
            cache = Path(plugin.engine._faceplate_scene_cache)
            cache.mkdir(); (cache / 'old.gif').write_bytes(b'derived-artwork')
            plugin.onboarding_draft=OnboardingDraft(Path(folder)/'setup-draft.json')
            plugin.onboarding_draft.path.mkdir()
            protected=plugin.onboarding_draft.path/'unrelated'
            protected.write_text('keep')
            plugin.onboarding_draft.remember({'brightness':34})
            factory_reset(plugin, FACTORY_RESET_CONFIRMATION)
            self.assertEqual({},plugin.onboarding_draft.resume())
            self.assertEqual('keep',protected.read_text())
            self.assertFalse(library.auth_path.exists())
            self.assertFalse(auth.path.exists())
            self.assertFalse(content.exists())
            self.assertFalse(library.artwork_root.exists())
            self.assertFalse(cache.exists())
            self.assertEqual([], plugin.engine.ambience.status()['profiles'])
            self.assertEqual(b'unrelated-content', (other / 'keep.gif').read_bytes())
            self.assertFalse(plugin.engine.settings.all()['onboarding_completed'])
            self.assertFalse(plugin.faceplate_artwork_jobs.status().get('state') in {'running','queued'})
            # Retrying after a lost response remains harmless and complete.
            factory_reset(plugin, FACTORY_RESET_CONFIRMATION)

    def test_no_deletion_without_confirmation_or_during_an_update(self):
        with tempfile.TemporaryDirectory() as folder:
            plugin, library, auth, content = self.fixture(folder)
            before = content.read_bytes()
            for token in ('', 'reset-settings'):
                with self.assertRaisesRegex(ValueError, 'Confirm'):
                    factory_reset(plugin, token)
            plugin.update_manager.status = lambda: {'phase': 'installing'}
            with self.assertRaisesRegex(ValueError, 'current update'):
                factory_reset(plugin, FACTORY_RESET_CONFIRMATION)
            self.assertEqual(before, content.read_bytes())
            self.assertTrue(auth.path.exists()); self.assertTrue(library.auth_path.exists())

    def test_linked_library_refuses_erasure_and_keeps_its_target(self):
        with tempfile.TemporaryDirectory() as folder:
            plugin, library, auth, content = self.fixture(folder)
            target = library.root.with_name('external-library')
            library.root.rename(target); library.root.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'linked'):
                factory_reset(plugin, FACTORY_RESET_CONFIRMATION)
            self.assertTrue((target / 'auth.json').exists())
            self.assertTrue(auth.path.exists())

    def test_native_rpc_keeps_legacy_reset_non_erasing_and_gates_the_new_factory_route(self):
        import asyncio, importlib.util, sys, types
        from unittest.mock import Mock
        source = Path(__file__).resolve().parents[2] / 'main.py'
        with patch.dict(sys.modules, {'decky': types.ModuleType('decky')}):
            spec = importlib.util.spec_from_file_location('gca_reset201_rpc', source)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            plugin = module.Plugin(); plugin.engine = Mock()
            plugin.engine.status.return_value = {'version': '1.4.1-lab.201'}
            plugin._sync_faceplate_claim = Mock(); plugin._configure_faceplate_power_events = Mock()
            with tempfile.TemporaryDirectory() as folder:
                plugin.onboarding_draft=OnboardingDraft(Path(folder)/'setup-draft.json')
                plugin.onboarding_draft.path.mkdir()
                for reset in (plugin.reset_configuration,plugin.reset_settings_only):
                    plugin.onboarding_draft.remember({'brightness':37})
                    asyncio.run(reset())
                    self.assertEqual({},plugin.onboarding_draft.resume())
                plugin.engine.reset_configuration.assert_called_once_with()
                plugin.engine.reset_settings_only.assert_called_once_with()
            with patch('signalbar.configuration_reset.factory_reset') as factory:
                asyncio.run(plugin.factory_reset_configuration(FACTORY_RESET_CONFIRMATION))
                factory.assert_called_once_with(plugin, FACTORY_RESET_CONFIRMATION)
            plugin.engine.settings.all.return_value = {'faceplate_dashboard_home_appid': 620}
            plugin.engine.faceplate.steamgriddb.home_dashboard_manifest.return_value = {'ready': True}
            self.assertEqual({'appid': 620, 'ready': True}, asyncio.run(plugin.get_faceplate_dashboard_background_status()))
            plugin.engine.faceplate.steamgriddb.library_entries.assert_not_called()
