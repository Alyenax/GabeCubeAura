"""An optional guide must survive unusable legacy files without applying them."""
import asyncio
import errno
import os
from pathlib import Path
from unittest.mock import Mock,patch
import unittest
import test_onboarding138 as fixture
from signalbar.onboarding import OnboardingTransaction, DraftError


class OptionalGuideTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.OnboardingRPCTests.setUp
    update=fixture.OnboardingRPCTests.update

    async def test_directory_at_both_guide_paths_cannot_block_restart_save_or_completion(self):
        self.plugin.onboarding_transaction.path.mkdir()
        self.plugin.onboarding_draft.path.mkdir()
        self.plugin._onboarding_recovery_error='ValueError'
        before=self.settings.base_all();routes=self.preferences.read().as_dict()
        media=self.root/'keep.gif';media.write_bytes(b'keep media')
        result=await self.plugin.restart_onboarding()
        self.assertNotIn('draft_reset_error',result);self.assertFalse(result['recovery_error'])
        self.assertEqual(result['draft'],{});self.assertEqual(result['draft_storage'],'memory')
        self.assertEqual(self.settings.base_all(),before);self.assertEqual(self.preferences.read().as_dict(),routes)
        self.assertEqual(await self.plugin.save_onboarding_draft({'step':'brightness','brightness':37}),{'step':'brightness','brightness':37})
        await self.plugin.complete_onboarding({'faceplate_requested':None,'brightness':37})
        self.assertTrue(self.settings.all()['onboarding_completed'])
        self.assertEqual(media.read_bytes(),b'keep media');self.assertTrue(self.plugin.onboarding_draft.path.is_dir())
        self.assertEqual(list(self.plugin.onboarding_transaction.path.iterdir()),[])
        restarted=OnboardingTransaction(self.plugin.onboarding_transaction.path)
        restarted.start_guidance();self.assertEqual(restarted.diagnostic_state(self.preferences)['legacy_file']['kind'],'directory')

    async def test_foreign_owner_rejection_is_diagnostic_only_not_a_guide_error(self):
        self.plugin.onboarding_transaction.path.write_text('old journal')
        self.plugin.onboarding_draft.path.write_text('old draft')
        before=self.settings.base_all()
        with patch('signalbar.onboarding.os.geteuid',return_value=os.geteuid()+1):
            result=await self.plugin.restart_onboarding()
        self.assertNotIn('draft_reset_error',result);self.assertFalse(result['recovery_error'])
        self.assertEqual(self.settings.base_all(),before)
        self.assertEqual(self.plugin.onboarding_transaction.path.read_text(),'old journal')
        await self.plugin.complete_onboarding({'faceplate_requested':None})
        self.assertTrue(self.settings.all()['onboarding_completed'])

    async def test_legacy_symlink_and_fifo_are_never_followed_by_transaction_recovery(self):
        media=self.root/'private.gif';media.write_bytes(b'unchanged')
        for kind in ('symlink','fifo'):
            with self.subTest(kind=kind):
                path=self.plugin.onboarding_transaction.path;path.unlink(missing_ok=True)
                if kind=='symlink':path.symlink_to(media)
                else:os.mkfifo(path)
                result=await asyncio.wait_for(self.plugin.restart_onboarding(),3)
                self.assertNotIn('draft_reset_error',result)
                await self.plugin.complete_onboarding({'faceplate_requested':None})
                self.assertEqual(media.read_bytes(),b'unchanged')
                self.assertEqual(self.plugin.onboarding_transaction.diagnostic_state(self.preferences)['legacy_file']['kind'],kind)
        path.unlink()

    async def test_unwritable_progress_can_remain_in_memory_while_actual_settings_save(self):
        self.plugin.onboarding_transaction.path.write_text('preserved')
        before=self.settings.base_all()
        with patch.object(self.plugin.onboarding_transaction,'keep_current',side_effect=PermissionError(errno.EACCES,'do not expose')), \
             patch.object(self.plugin.onboarding_draft,'_write',side_effect=PermissionError(errno.EROFS,'do not expose')):
            result=await self.plugin.restart_onboarding()
            self.assertNotIn('draft_reset_error',result);self.assertEqual(result['draft_storage'],'memory')
            self.assertEqual(self.settings.base_all(),before)
            await self.plugin.complete_onboarding({'faceplate_requested':None})
        self.assertTrue(self.settings.all()['onboarding_completed'])
        self.assertEqual(self.plugin.onboarding_transaction.path.read_text(),'preserved')

    async def test_in_process_failure_rolls_back_only_current_choices_without_reading_legacy_file(self):
        path=self.plugin.onboarding_transaction.path;path.mkdir()
        before=self.settings.base_all();routes=self.preferences.read().as_dict()
        self.plugin.engine.refresh_settings=Mock(side_effect=[ValueError('apply failed'),None])
        with self.assertRaisesRegex(ValueError,'apply failed'):
            await self.plugin.complete_onboarding({'brightness':38,'faceplate_requested':None})
        self.assertEqual(self.settings.base_all(),before);self.assertEqual(self.preferences.read().as_dict(),routes)
        self.assertFalse(self.plugin.engine._onboarding_applying)
        self.assertEqual(list(path.iterdir()),[])

    async def test_starting_again_never_replays_old_prepared_values_over_saved_choices(self):
        transaction=self.plugin.onboarding_transaction
        before,after=self.settings.plan_update({'light_bar_day_brightness':20})
        routes={'home':self.preferences.read().home_scene,'game':self.preferences.read().game_scene}
        transaction.prepare(before,after,routes,routes)
        self.settings.update({'light_bar_day_brightness':39});saved=self.settings.base_all()
        with patch.object(transaction,'recover',side_effect=AssertionError('Do not replay an old guide')):
            transaction.start_guidance()
        self.assertEqual(self.settings.base_all(),saved)
        self.assertTrue(transaction.path.with_name(transaction.path.name+'.invalid').exists())
