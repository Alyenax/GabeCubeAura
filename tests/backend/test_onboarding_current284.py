"""Recover the observed onboarding veto without resetting active user data."""
import errno
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from signalbar.onboarding import OnboardingTransaction
from signalbar.settings import SettingsStore
from signalbar.faceplate.routing import FaceplatePreferencesStore, HOME_SCENES, GAME_SCENES
from test_cinema_integration import plugin_class


class KeepCurrentRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.settings=SettingsStore(str(self.root/'config.json'))
        self.settings.update({'faceplate_lab_enabled':True,'faceplate_brightness':70})
        self.preferences=FaceplatePreferencesStore(self.root/'routes.json')
        self.preferences.update(home_scene='library' if 'library' in HOME_SCENES else 'native-clock',
                                game_scene='clock' if 'clock' in GAME_SCENES else 'player-city')
        self.transaction=OnboardingTransaction(self.root/'setup-transaction.json')
        self.raw=b'{"schema":1,"stage":"prepared","broken":true}\n'
        self.transaction.path.write_bytes(self.raw)
        self.prepared=self.root/'prepared.gif';self.prepared.write_bytes(b'existing prepared image')
        self.draft=self.root/'setup-draft.json';self.draft.write_text('{"step":"review"}')
        self.original={p.name:p.read_bytes() for p in (Path(self.settings.path),self.preferences.path,self.prepared,self.draft)}
        self.effects=[]
        self.plugin=plugin_class()()
        self.plugin._onboarding_commit_lock=threading.RLock()
        self.plugin._onboarding_recovery_error='ValueError'
        self.plugin.onboarding_transaction=self.transaction
        self.plugin._configure_faceplate_power_events=Mock()
        self.plugin._onboarding_event=Mock()
        self.plugin.engine=SimpleNamespace(settings=self.settings,faceplate_preferences=self.preferences,
          _onboarding_recovery_blocked=True,_onboarding_applying=False,
          refresh_settings=lambda changes:self.record('refresh',changes),
          activate_faceplate_setup=lambda:self.record('activate'),
          status=lambda:{'recovery_blocked':self.plugin.engine._onboarding_recovery_blocked})

    def record(self,*args):
        self.assertFalse(self.plugin.engine._onboarding_recovery_blocked)
        self.assertTrue(self.transaction.path.with_name('setup-transaction.json.invalid').exists())
        self.effects.append(args)

    def assert_active_data_unchanged(self):
        for name,data in self.original.items():self.assertEqual((self.root/name).read_bytes(),data,name)

    async def test_invalid_journal_is_backed_up_before_runtime_restarts_with_current_settings(self):
        result=await self.plugin.recover_onboarding_current_settings()
        self.assertFalse(result['recovery_blocked'])
        self.assertEqual(self.plugin._onboarding_recovery_error,'')
        self.assertEqual(self.effects,[])
        self.assertFalse(self.transaction.path.exists())
        self.assertEqual((self.root/'setup-transaction.json.invalid').read_bytes(),self.raw)
        self.assert_active_data_unchanged()

    async def test_valid_but_conflicting_old_intent_does_not_revert_newer_display_choices(self):
        before,after=self.settings.plan_update({'faceplate_brightness':20})
        self.transaction._write(dict(schema=1,stage='prepared',before_settings=before,after_settings=after,
            before_routes={'home':'dashboard','game':'artwork'},after_routes={'home':'weather','game':'artwork'}))
        raw=self.transaction.path.read_bytes()
        with self.assertRaises(ValueError):self.transaction.recover(self.settings,self.preferences)
        await self.plugin.recover_onboarding_current_settings()
        self.assert_active_data_unchanged()
        self.assertEqual((self.root/'setup-transaction.json.invalid').read_bytes(),raw)

    async def test_failed_archive_is_nonblocking_and_retains_all_evidence(self):
        with patch('signalbar.onboarding._sync_directory',side_effect=OSError(errno.EIO,'disk failure')):
            result=await self.plugin.recover_onboarding_current_settings()
        self.assertFalse(result['recovery_blocked']);self.assertEqual(self.effects,[])
        self.assertEqual(self.transaction.path.read_bytes(),self.raw)
        self.assert_active_data_unchanged()

    async def test_symlink_is_preserved_without_following_it_or_blocking_the_guide(self):
        self.transaction.path.unlink();self.transaction.path.symlink_to(self.prepared)
        result=await self.plugin.recover_onboarding_current_settings()
        self.assertFalse(result['recovery_blocked']);self.assertEqual(self.effects,[])
        self.assertTrue(self.transaction.path.is_symlink());self.assert_active_data_unchanged()

    async def test_healthy_setup_does_not_archive_anything_or_restart_hardware(self):
        self.plugin._onboarding_recovery_error='';self.plugin.engine._onboarding_recovery_blocked=False
        await self.plugin.recover_onboarding_current_settings()
        self.assertEqual(self.transaction.path.read_bytes(),self.raw)
        self.assertEqual(self.effects,[])

    async def test_second_acknowledged_call_does_not_repeat_activation_or_overwrite_backup(self):
        await self.plugin.recover_onboarding_current_settings()
        await self.plugin.recover_onboarding_current_settings()
        self.assertEqual(self.effects,[])
        self.assertEqual(len(list(self.root.glob('setup-transaction.json.invalid*'))),1)

    async def test_active_setup_cannot_be_archived_underneath_its_writer(self):
        self.plugin.engine._onboarding_applying=True
        with self.assertRaises(ValueError):await self.plugin.recover_onboarding_current_settings()
        self.assertEqual(self.transaction.path.read_bytes(),self.raw)
        self.assertEqual(self.effects,[])

    async def test_absent_journal_allows_retry_after_archiving_was_already_completed(self):
        self.transaction.path.rename(self.root/'setup-transaction.json.invalid')
        await self.plugin.recover_onboarding_current_settings()
        self.assertFalse(self.plugin.engine._onboarding_recovery_blocked)

    def test_diagnostic_state_explains_conflict_without_copying_settings(self):
        before,after=self.settings.plan_update({'faceplate_brightness':20})
        self.transaction._write(dict(schema=1,stage='prepared',before_settings=before,after_settings=after,
            before_routes={'home':'dashboard','game':'artwork'},after_routes={'home':'weather','game':'artwork'}))
        result=self.transaction.diagnostic_state(self.preferences)
        self.assertEqual(result,{'state':'readable','stage':'prepared','route_conflict':True})
        self.assertNotIn('brightness',str(result));self.assertNotIn(str(self.root),str(result))

    async def test_actual_export_explains_pending_recovery_without_copying_the_journal(self):
        from signalbar.diagnostics import DiagnosticJournal
        self.plugin.diagnostics=DiagnosticJournal(self.root,'1.5.2')
        self.plugin.configuration_export_path=str(self.root/'configuration.json')
        self.plugin._cinema_diagnostic_snapshot=lambda:{}
        self.plugin._update_diagnostic_snapshot=lambda:{}
        self.plugin.engine.display_control_snapshot=lambda:{}
        self.transaction.path.write_text('{"PRIVATE":"sensitive interrupted intent"}')
        collector = patch('signalbar.system_diagnostics.collect',return_value={}) if importlib.util.find_spec('signalbar.system_diagnostics') else nullcontext()
        with collector:
            exported=await self.plugin.export_diagnostic_report()
        report=json.loads(Path(exported['path']).read_text())
        self.assertEqual(report['setup_recovery']['pending'],True)
        self.assertEqual(report['setup_recovery']['blocks_runtime'],False)
        self.assertEqual(report['setup_recovery']['transaction'],{'state':'unreadable','error':'ValueError'})
        self.assertNotIn('sensitive interrupted intent',json.dumps(report))
