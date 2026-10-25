"""Bounded first-run drafts and write-ahead recovery; no hardware or network."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import os
import errno

from signalbar.onboarding import OnboardingDraft, OnboardingTransaction, clean_draft, draft_error_code
from signalbar.settings import SettingsStore
from signalbar.faceplate.routing import FaceplatePreferencesStore
from test_cinema_integration import plugin_class


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.draft = OnboardingDraft(self.root/'setup-draft.json')

    def test_no_secrets_unsupported_choices_or_capture_fields(self):
        for value in ({'api_key':'secret'}, {'audio':'raw'}, {'step':[]}, {'brightness':True},
                      {'assistant_confirmed':None}, {'game':'performance'}):
            with self.assertRaises(ValueError): clean_draft(value)

    def test_bounded_strict_json_and_object_schema(self):
        for text in ('[]', 'null', '{"schema":true,"draft":{}}',
                     '{"schema":1,"schema":1,"draft":{}}',
                     '{"schema":1,"draft":{"brightness":NaN}}', ' '*13000):
            self.draft.path.write_text(text)
            with self.assertRaises(ValueError): self.draft.read()

    def test_symlink_is_neither_read_modified_nor_cleared(self):
        target = self.root/'target'; target.write_text('preserve')
        self.draft.path.symlink_to(target)
        for operation in (self.draft.read, lambda:self.draft.save({'step':'assistant'}), self.draft.clear):
            with self.assertRaises(ValueError): operation()
        self.assertEqual('preserve', target.read_text())

    def test_incremental_draft_private_and_resume_without_activation(self):
        self.draft.save({'step':'assistant', 'assistant_requested':True})
        self.draft.save({'step':'voice', 'assistant_confirmed':False})
        self.assertEqual('voice', self.draft.read()['step'])
        self.assertEqual(0o600, self.draft.path.stat().st_mode & 0o777)

    def test_explicit_reset_preserves_multiple_archives_without_overwrite(self):
        self.draft.path.write_text('invalid'*4000)
        self.assertTrue(self.draft.reset())
        archive=self.root/'setup-draft.json.invalid'
        self.assertEqual('invalid'*4000, archive.read_text())
        self.draft.path.write_text('new invalid')
        self.assertTrue(self.draft.reset())
        self.assertFalse(self.draft.path.exists())
        self.assertEqual('new invalid', (self.root/'setup-draft.json.invalid.1').read_text())
        self.assertEqual('invalid'*4000, archive.read_text())

    def test_archive_capacity_is_bounded_and_never_overwrites(self):
        for slot in range(64):
            path=self.root/('setup-draft.json.invalid'+(f'.{slot}' if slot else ''))
            path.write_text(f'old-{slot}')
        self.draft.path.write_text('current')
        with self.assertRaises(ValueError) as caught: self.draft.reset()
        self.assertEqual('draft_archive_full',draft_error_code(caught.exception))
        self.assertEqual('current',self.draft.path.read_text())
        self.assertEqual('old-63',(self.root/'setup-draft.json.invalid.63').read_text())

    def test_retry_finishes_own_backup_after_sync_failure(self):
        self.draft.path.write_text('original')
        with patch('signalbar.onboarding._sync_directory',side_effect=OSError(errno.EIO,'failure')):
            with self.assertRaises(OSError): self.draft.reset()
        self.assertEqual(2,self.draft.path.stat().st_nlink)
        self.assertTrue(self.draft.reset())
        self.assertFalse(self.draft.path.exists())
        self.assertEqual('original',(self.root/'setup-draft.json.invalid').read_text())
        self.assertFalse((self.root/'setup-draft.json.invalid.1').exists())

    def test_symlink_archive_is_preserved_and_next_slot_is_used(self):
        target=self.root/'unrelated';target.write_text('preserve')
        (self.root/'setup-draft.json.invalid').symlink_to(target)
        self.draft.path.write_text('draft')
        self.assertTrue(self.draft.reset())
        self.assertEqual('preserve',target.read_text())
        self.assertTrue((self.root/'setup-draft.json.invalid').is_symlink())
        self.assertEqual('draft',(self.root/'setup-draft.json.invalid.1').read_text())

    def test_unknown_owner_and_unrelated_hardlinks_are_not_repaired_blindly(self):
        self.draft.path.write_text('preserve')
        with patch('signalbar.onboarding.os.geteuid',return_value=os.geteuid()+1):
            for operation in (self.draft.read,self.draft.reset):
                with self.assertRaises(ValueError) as caught: operation()
                self.assertEqual('draft_unsafe',draft_error_code(caught.exception))
        os.link(self.draft.path,self.root/'unrelated-link')
        with self.assertRaises(ValueError): self.draft.reset()
        self.assertEqual('preserve',self.draft.path.read_text())

    def test_read_failure_reasons_are_safe_and_distinct(self):
        for content,code in [('[]','draft_schema'),('{','draft_invalid'),
                             (' '*13000,'draft_too_large')]:
            self.draft.path.write_text(content)
            with self.assertRaises(ValueError) as caught: self.draft.read()
            self.assertEqual(code,draft_error_code(caught.exception))
        with patch('signalbar.onboarding.os.open',side_effect=PermissionError(errno.EACCES,'secret path')):
            with self.assertRaises(ValueError) as caught: self.draft.read()
            self.assertEqual('draft_permissions',draft_error_code(caught.exception))

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        os.mkfifo(self.draft.path)
        with self.assertRaises(ValueError) as caught: self.draft.read()
        self.assertEqual('draft_unsafe',draft_error_code(caught.exception))

    def test_first_setup_replaces_wrong_owner_without_chown_or_reading_it(self):
        self.draft.path.write_text('{"schema":1,"draft":{"brightness":244}}')
        inode=self.draft.path.stat().st_ino
        with patch('signalbar.onboarding.os.geteuid',return_value=os.geteuid()+1):
            self.assertEqual({},self.draft.resume())
        self.assertNotEqual(inode,self.draft.path.stat().st_ino)
        self.assertEqual({},self.draft.resume())
        self.draft.remember({'step':'review','brightness':12})
        self.assertEqual(12,OnboardingDraft(self.draft.path).resume()['brightness'])

    def test_links_and_special_entries_cannot_block_or_change_external_targets(self):
        target=self.root/'external';target.write_text('untouched')
        for kind in ('link','dangling','fifo','hardlink'):
            with self.subTest(kind=kind):
                if kind=='link':self.draft.path.symlink_to(target)
                elif kind=='dangling':self.draft.path.symlink_to(self.root/'missing')
                elif kind=='fifo':os.mkfifo(self.draft.path)
                else:os.link(target,self.draft.path)
                self.assertEqual({},self.draft.resume())
                self.draft.remember({'step':'review'})
                self.assertEqual({'step':'review'},self.draft.resume())
                self.assertEqual('untouched',target.read_text())
                self.draft.discard()
                self.assertFalse(self.draft.path.exists())

    def test_nonempty_directory_uses_memory_and_reset_never_recurses(self):
        self.draft.path.mkdir();child=self.draft.path/'keep';child.write_text('keep')
        self.assertEqual({},self.draft.resume())
        self.draft.remember({'brightness':22})
        self.assertEqual({'brightness':22},self.draft.resume())
        self.assertTrue(self.draft.storage_error)
        self.draft.restart();self.assertEqual({},self.draft.resume())
        self.draft.remember({'step':'review'})
        self.draft.discard();self.assertEqual({},self.draft.resume())
        self.assertEqual('keep',child.read_text())
        self.assertEqual({},OnboardingDraft(self.draft.path).resume())

    def test_full_archive_and_storage_failures_do_not_gate_validated_progress(self):
        for slot in range(64):
            (self.root/('setup-draft.json.invalid'+(f'.{slot}' if slot else ''))).write_text('archive')
        self.draft.path.write_text('broken')
        self.assertEqual({},self.draft.resume())
        self.assertEqual(64,len(list(self.root.glob('*.invalid*'))))
        with patch.object(self.draft,'_write',side_effect=PermissionError(errno.EACCES,'private path')):
            self.assertEqual({'brightness':31},self.draft.remember({'brightness':31}))
            self.assertEqual({'brightness':31},self.draft.resume())
            self.draft.remember({'step':'review'})
            with self.assertRaises(ValueError):self.draft.remember({'api_key':'never'})
            self.assertEqual({'brightness':31,'step':'review'},self.draft.resume())
            self.draft.discard();self.assertEqual({},self.draft.resume())
        self.draft.remember({'brightness':17})
        self.assertFalse(self.draft.storage_error)
        self.assertEqual({'brightness':17},OnboardingDraft(self.draft.path).resume())


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.settings = SettingsStore(str(self.root/'config.json'))
        self.preferences = FaceplatePreferencesStore(self.root/'routes.json')
        self.transaction = OnboardingTransaction(self.root/'setup-transaction.json')
        self.changes = {'onboarding_completed':True, 'display_preset':'moderate', 'light_bar_day_brightness':12}

    def prepare(self):
        before, after = self.settings.plan_update(self.changes)
        self.transaction.prepare(before, after, {'home':'dashboard','game':'artwork'},
            {'home':'weather','game':'artwork'})
        return before, after

    def test_plan_has_no_io_and_only_changed_fields(self):
        before, after = self.settings.plan_update(self.changes)
        self.assertEqual(set(before), set(after))
        self.assertTrue(all(before[key] != after[key] for key in before))
        self.assertNotIn('gabe_assistant', before)
        self.assertFalse(Path(self.settings.path).exists())

    def test_crash_between_two_stores_is_reversed_before_runtime_starts(self):
        before, after = self.prepare()
        self.preferences.update(home_scene='weather')
        self.settings.update(self.changes)
        self.assertEqual('prepared', self.transaction.recover(self.settings, self.preferences))
        self.assertFalse(self.settings.all()['onboarding_completed'])
        self.assertEqual(9, self.settings.all()['light_bar_day_brightness'])
        self.assertEqual('dashboard', self.preferences.read().home_scene)
        self.assertFalse(self.transaction.path.exists())

    def test_committed_cleanup_never_reverts_the_confirmed_choices(self):
        self.prepare(); self.settings.update(self.changes)
        self.preferences.update(home_scene='weather'); self.transaction.committed()
        self.assertEqual('committed', self.transaction.recover(self.settings, self.preferences))
        self.assertEqual(12, self.settings.all()['light_bar_day_brightness'])
        self.assertEqual('weather', self.preferences.read().home_scene)

    def test_newer_choice_is_not_overwritten_by_recovery(self):
        self.prepare(); self.settings.update(self.changes)
        self.settings.update({'light_bar_day_brightness':77})
        with self.assertRaises(ValueError): self.transaction.recover(self.settings, self.preferences)
        self.assertEqual(77, self.settings.all()['light_bar_day_brightness'])
        self.assertTrue(self.transaction.path.exists())

    def test_corrupt_or_secret_injected_transaction_is_rejected(self):
        for value in ([], {'schema':1}, {'schema':1,'stage':'prepared',
                'before_settings':{'api_key':'secret'}, 'after_settings':{'api_key':'new'},
                'before_routes':{'home':'dashboard','game':'artwork'},
                'after_routes':{'home':'weather','game':'artwork'}}):
            self.transaction.path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): self.transaction.recover(self.settings,self.preferences)


class OnboardingRPCTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.settings = SettingsStore(str(self.root/'config.json'))
        self.preferences = FaceplatePreferencesStore(self.root/'routes.json')
        self.voice = {'voice_ready':True, 'voice_readiness':{'trial_verified':True}}
        self.detected = True
        self.effects = []
        self.plugin = plugin_class()()
        self.plugin._onboarding_commit_lock = threading.RLock()
        self.plugin._onboarding_recovery_error = ''
        self.plugin.onboarding_draft = OnboardingDraft(self.root/'setup-draft.json')
        self.plugin.onboarding_transaction = OnboardingTransaction(self.root/'setup-transaction.json')
        self.plugin._configure_faceplate_power_events = Mock()
        self.plugin.update_manager = SimpleNamespace(disconnect_private=Mock(side_effect=AssertionError('Do not disconnect GitHub')))
        self.plugin.engine = SimpleNamespace(settings=self.settings,
            faceplate_preferences=self.preferences, _available=False, _onboarding_applying=False,
            _onboarding_recovery_blocked=False,
            faceplate=SimpleNamespace(device_status=lambda:{'available':self.detected,'busy':False}),
            assistant=SimpleNamespace(status=Mock(side_effect=AssertionError('GCA setup must not inspect the voice owner')), configure=Mock()),
            _apply_settings=lambda *args:self.effects.append(('restore-runtime',None)),
            status=lambda:{'settings':self.settings.base_all(), 'routes':self.preferences.read().as_dict()},
            activate_faceplate_setup=Mock(),
            update_settings=self.update, refresh_settings=lambda changes:self.update({}))

    def update(self, changes):
        self.assertTrue(self.plugin.engine._onboarding_applying)
        return self.settings.update(changes)

    async def test_confirmed_setup_commits_both_stores_and_clears_draft(self):
        self.plugin.onboarding_draft.save({'step':'review','assistant_requested':True})
        await self.plugin.complete_onboarding({'assistant_requested':True, 'assistant_confirmed':True,
            'faceplate_requested':True,'home':'weather','game':'keep'})
        self.assertTrue(self.settings.all()['onboarding_completed'])
        self.assertFalse(self.settings.all()['gabe_assistant']['enabled'])
        self.plugin.engine.assistant.status.assert_not_called()
        self.plugin.engine.assistant.configure.assert_not_called()
        self.assertTrue(self.settings.all()['faceplate_lab_enabled'])
        self.assertEqual('dashboard',self.preferences.read().home_scene)
        self.assertFalse(self.plugin.onboarding_transaction.path.exists())
        self.assertFalse(self.plugin.onboarding_draft.path.exists())
        self.plugin.update_manager.disconnect_private.assert_not_called()

    async def test_keep_initial_calibration_still_needs_explicit_setup_confirmation(self):
        self.settings=SettingsStore(str(self.root/'config.json'),first_install_defaults=True)
        self.plugin.engine.settings=self.settings
        self.plugin.engine._available=True
        self.assertFalse(self.settings.all()['onboarding_completed'])
        self.plugin.onboarding_draft.save({'step':'review','preset':'custom','brightness':15})
        self.assertFalse(self.settings.all()['onboarding_completed'])
        before=self.settings.all()
        self.settings.update({'faceplate_dashboard_home_source':'artwork'})
        await self.plugin.complete_onboarding({'preset':'custom','brightness':15,
            'faceplate_requested':True,'home':'artwork-dashboard','game':'artwork-dashboard'})
        self.assertTrue(self.settings.all()['onboarding_completed'])
        self.assertEqual(self.settings.all()['light_bar_day_brightness'],15)
        self.assertEqual(self.settings.all()['faceplate_extension_saturation'],before['faceplate_extension_saturation'])
        self.assertEqual(self.preferences.read().home_scene,'dashboard')
        self.assertEqual(self.preferences.read().game_scene,'artwork-dashboard')
        self.assertEqual(self.settings.all()['faceplate_dashboard_home_source'],'weather')

    async def test_player_city_draft_resume_and_completion_save_the_shared_game_route(self):
        self.plugin.onboarding_draft.save({'step':'faceplate','faceplate_requested':True,'home':'native-clock','game':'player-city'})
        self.assertEqual(self.plugin.onboarding_draft.resume()['game'],'player-city')
        await self.plugin.complete_onboarding({'faceplate_requested':True,'home':'native-clock','game':'player-city'})
        self.assertEqual(self.preferences.read().game_scene,'player-city')
        self.assertEqual(self.preferences.read().home_scene,'dashboard')
        self.assertTrue(self.settings.all()['onboarding_completed'])
        self.assertFalse(self.plugin.onboarding_draft.path.exists())

    async def test_exception_after_settings_persist_restores_config_routes_and_intent(self):
        self.plugin.onboarding_draft.save({'step':'review','assistant_requested':False})
        before = self.settings.base_all()
        def fail(changes): self.settings.update(changes); raise RuntimeError('Provider failed after persist')
        self.plugin.engine.refresh_settings = fail
        with self.assertRaises(RuntimeError):
            await self.plugin.complete_onboarding({'assistant_requested':False,'faceplate_requested':True,'home':'weather'})
        self.assertEqual(before,self.settings.base_all())
        self.assertEqual('dashboard',self.preferences.read().home_scene)
        self.assertEqual('review',self.plugin.onboarding_draft.read()['step'])
        self.assertFalse(self.plugin.engine._onboarding_applying)

    async def test_voice_consent_is_unnecessary_and_legacy_choices_never_mutate_voice(self):
        for choices in ({},{'assistant_requested':None},{'assistant_requested':True,'assistant_confirmed':True},
                        {'assistant_requested':False,'assistant_confirmed':False}):
            before=deepcopy(self.settings.all()['gabe_assistant'])
            await self.plugin.complete_onboarding(choices)
            self.assertEqual(before,self.settings.all()['gabe_assistant'])
            self.assertTrue(self.settings.all()['onboarding_completed'])
        self.plugin.engine.assistant.status.assert_not_called()
        self.plugin.engine.assistant.configure.assert_not_called()

    async def test_absent_matrix_does_not_enable_it_or_modify_routes(self):
        self.settings.update({'faceplate_lab_enabled':False})
        self.detected=False
        await self.plugin.complete_onboarding({'assistant_requested':False,'faceplate_requested':True,'home':'weather'})
        self.assertFalse(self.settings.all()['faceplate_lab_enabled'])
        self.assertEqual('dashboard',self.preferences.read().home_scene)

    async def test_existing_voice_preferences_remain_available_for_explicit_dva_import(self):
        config=dict(self.settings.all()['gabe_assistant'],enabled=True,wake_enabled=True,language='en',character='eyes',microphone='saved-microphone')
        self.settings.update({'gabe_assistant':config})
        config=self.settings.all()['gabe_assistant']
        state=await self.plugin.get_onboarding()
        self.assertNotIn('voice_verified',state)
        await self.plugin.complete_onboarding({'assistant_requested':False,'assistant_confirmed':False})
        self.assertEqual(config,self.settings.all()['gabe_assistant'])
        self.plugin.engine.assistant.status.assert_not_called()
        self.plugin.engine.assistant.configure.assert_not_called()

    async def test_recovery_error_blocks_reapplication_and_is_visible(self):
        self.plugin._onboarding_recovery_error='ValueError'
        state=await self.plugin.get_onboarding()
        self.assertEqual('ValueError',state['recovery_error'])
        with self.assertRaises(ValueError): await self.plugin.complete_onboarding({'assistant_requested':False})
        self.assertFalse(self.settings.all()['onboarding_completed'])

    async def test_corrupt_draft_automatically_restarts_without_applying_settings(self):
        self.plugin.onboarding_draft.path.write_text('[]')
        before=self.settings.base_all()
        state=await self.plugin.get_onboarding()
        self.assertFalse(state['draft_error']); self.assertEqual({},state['draft'])
        self.assertEqual(before,self.settings.base_all())
        self.assertFalse(Path(self.settings.path).exists())
        self.assertTrue((self.root/'setup-draft.json.invalid').exists())
        await self.plugin.complete_onboarding({'assistant_requested':False})
        self.assertTrue(self.settings.all()['onboarding_completed'])

    async def test_second_recovery_is_acknowledged_without_touching_active_settings(self):
        before=self.settings.base_all()
        for content in ('[]','{'):
            self.plugin.onboarding_draft.path.write_text(content)
            state=await self.plugin.reset_onboarding_draft()
            self.assertFalse(state['draft_error'])
            self.assertNotIn('draft_reset_error',state)
            self.assertEqual(before,self.settings.base_all())
        self.assertTrue((self.root/'setup-draft.json.invalid.1').exists())
        self.assertEqual([],self.effects)

    async def test_reset_permissions_do_not_block_setup_and_journal_is_private(self):
        self.plugin.diagnostics=SimpleNamespace(record=Mock())
        before=self.settings.base_all()
        self.plugin.onboarding_draft.path.mkdir()
        with patch.object(self.plugin.onboarding_draft,'reset',side_effect=PermissionError(errno.EACCES,'secret-path')):
            state=await self.plugin.reset_onboarding_draft()
        self.assertNotIn('draft_reset_error',state)
        self.assertFalse(state['draft_error'])
        self.assertEqual('memory',state['draft_storage'])
        self.assertEqual(before,self.settings.base_all())
        await self.plugin.save_onboarding_draft({'step':'review'})
        self.assertEqual({'step':'review'},(await self.plugin.get_onboarding())['draft'])
        await self.plugin.complete_onboarding({'assistant_requested':False})
        self.assertTrue(self.settings.all()['onboarding_completed'])
        journal=str(self.plugin.diagnostics.record.call_args_list)
        self.assertNotIn('secret-path',journal)
        self.assertNotIn(str(self.root),journal)

    async def test_read_error_journal_is_deduplicated_and_recovers(self):
        journal=Mock();self.plugin.diagnostics=SimpleNamespace(record=journal)
        self.plugin.onboarding_draft.path.write_text('[]')
        await self.plugin.get_onboarding();await self.plugin.get_onboarding()
        self.assertEqual(1,journal.call_count)
        self.plugin.onboarding_draft.discard();await self.plugin.get_onboarding()
        self.assertEqual('ready',journal.call_args.kwargs['code'])
        self.assertEqual(2,journal.call_count)

    async def test_faceplate_only_confirmation_preserves_existing_bar_setup(self):
        self.settings.update({'onboarding_completed':True,'display_preset':'signals',
            'light_bar_day_brightness':34,'night_mode_brightness':42})
        self.plugin.engine._available=True
        await self.plugin.complete_onboarding({'faceplate_requested':True,'home':'native-clock','game':'keep'})
        saved=self.settings.base_all()
        self.assertTrue(saved['faceplate_setup_completed'])
        self.assertEqual('signals',saved['display_preset'])
        self.assertEqual(34,saved['light_bar_day_brightness'])
        self.assertEqual(42,saved['night_mode_brightness'])
        self.assertTrue(SettingsStore(str(self.root/'config.json')).all()['faceplate_setup_completed'])

    async def test_not_now_is_an_explicit_review_without_enabling_the_panel(self):
        await self.plugin.complete_onboarding({'faceplate_requested':False})
        self.assertTrue(self.settings.all()['faceplate_setup_completed'])
        self.assertFalse(self.settings.all()['faceplate_lab_enabled'])

    async def test_unplugged_confirmation_does_not_establish_faceplate_setup(self):
        self.settings.update({'faceplate_lab_enabled':False})
        self.detected=False
        await self.plugin.complete_onboarding({'faceplate_requested':True,'home':'native-clock'})
        self.assertFalse(self.settings.all()['faceplate_setup_completed'])
        self.assertFalse(self.settings.all()['faceplate_lab_enabled'])

    async def test_manual_faceplate_off_is_remembered_without_reenabling(self):
        self.plugin._sync_faceplate_claim=Mock()
        self.plugin.engine._onboarding_applying=True
        await self.plugin.set_setting('faceplate_lab_enabled',False)
        self.assertTrue(self.settings.all()['faceplate_setup_completed'])
        self.assertFalse(self.settings.all()['faceplate_lab_enabled'])
