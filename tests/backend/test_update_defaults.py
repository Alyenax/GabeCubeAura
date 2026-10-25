"""Default checks schedule discovery, without downloading or installing a release."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from signalbar.settings import SettingsStore
from signalbar.updates import UpdateManager
from test_updates import FakeClient, FakeLogger, write_archive

class UpdateDefaultTests(unittest.TestCase):
    def test_fresh_legacy_and_reset_enable_checks_but_preserve_a_saved_opt_out(self):
        for calibrated in (False, True):
            with self.subTest(calibrated=calibrated), tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'config.json'
                store=SettingsStore(str(path),first_install_defaults=calibrated)
                self.assertTrue(store.all()['updates_auto_check'])
                self.assertFalse(store.all()['updates_auto_install'])
                store.update({'updates_auto_check':False})
                resumed=SettingsStore(str(path),first_install_defaults=calibrated)
                self.assertFalse(resumed.all()['updates_auto_check'])
                resumed.reset_configuration()
                self.assertTrue(SettingsStore(str(path),first_install_defaults=calibrated).all()['updates_auto_check'])
                self.assertFalse(resumed.all()['updates_auto_install'])
                self.assertFalse(resumed.all()['onboarding_completed'])
                path.write_text(json.dumps({'onboarding_completed':True}))
                self.assertTrue(SettingsStore(str(path),first_install_defaults=calibrated).all()['updates_auto_check'])

    def test_default_startup_and_scheduled_checks_never_prepare_or_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'release.zip';write_archive(archive)
            store=SettingsStore(str(root/'settings.json'));client=FakeClient(archive);now=[1000.0]
            manager=UpdateManager('1.0.0',store,str(root/'runtime'),str(root/'plugins/GabeCubeAura'),
                FakeLogger(),client=client,clock=lambda:now[0])
            with patch.object(manager,'prepare',side_effect=AssertionError('Must not download automatically')), \
                 patch.object(client,'download_archive',side_effect=AssertionError('Must not download automatically')):
                self.assertEqual(manager._check_on_startup()['phase'],'available')
                self.assertEqual(len(client.calls),1)
                now[0]+=1;manager._automatic_tick();self.assertEqual(len(client.calls),1)
                now[0]+=store.all()['updates_check_interval_minutes']*60
                manager._automatic_tick();self.assertEqual(len(client.calls),2)
                self.assertFalse((root/'runtime/updates/staged').exists())
                self.assertEqual(manager.status()['confirmation_token'],'')
                store.update({'updates_auto_check':False});now[0]+=86400
                manager._automatic_tick();manager._check_on_startup();self.assertEqual(len(client.calls),2)
