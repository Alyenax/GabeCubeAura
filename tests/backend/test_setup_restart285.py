"""One explicit restart recovers the guide without resetting the application."""
import errno
import json
from unittest.mock import AsyncMock,patch
import unittest
import test_onboarding138 as baseline


class SetupRestartTests(unittest.IsolatedAsyncioTestCase):
    setUp=baseline.OnboardingRPCTests.setUp
    update=baseline.OnboardingRPCTests.update

    async def test_value_error_journal_and_draft_are_backed_up_and_new_guide_can_complete(self):
        self.settings.update({'onboarding_completed':True,'faceplate_lab_enabled':True})
        before=self.settings.base_all();routes=self.preferences.read().as_dict()
        self.plugin.onboarding_draft.save({'step':'review','brightness':99})
        draft=self.plugin.onboarding_draft.path.read_bytes()
        raw=b'{"old interrupted setup":';self.plugin.onboarding_transaction.path.write_bytes(raw)
        self.plugin._onboarding_recovery_error='ValueError';self.plugin.engine._onboarding_recovery_blocked=True
        prepared=self.root/'prepared.gif';prepared.write_bytes(b'kept prepared image')
        result=await self.plugin.restart_onboarding()
        self.assertEqual(result['draft'],{});self.assertFalse(result['recovery_error'])
        self.assertEqual(self.settings.base_all(),before);self.assertEqual(self.preferences.read().as_dict(),routes)
        self.assertEqual(prepared.read_bytes(),b'kept prepared image')
        self.assertEqual((self.root/'setup-transaction.json.invalid').read_bytes(),raw)
        self.assertEqual((self.root/'setup-draft.json.invalid').read_bytes(),draft)
        self.plugin.engine.activate_faceplate_setup.assert_not_called()
        await self.plugin.complete_onboarding({'faceplate_requested':None})
        self.assertTrue(self.settings.all()['onboarding_completed']);self.assertFalse(self.plugin.onboarding_transaction.path.exists())
        self.assertFalse(self.plugin.engine._onboarding_recovery_blocked)

    async def test_archive_failure_keeps_evidence_but_cannot_prevent_a_fresh_guide(self):
        self.plugin.onboarding_transaction.path.write_text('broken')
        self.plugin._onboarding_recovery_error='ValueError';self.plugin.engine._onboarding_recovery_blocked=True
        before=self.settings.base_all()
        with patch('signalbar.onboarding.os.link',side_effect=PermissionError(errno.EACCES,'private path')):
            result=await self.plugin.restart_onboarding()
        self.assertNotIn('draft_reset_error',result)
        self.assertEqual(result['draft'],{});self.assertFalse(result['recovery_error'])
        self.assertEqual(self.plugin.onboarding_transaction.path.read_text(),'broken')
        self.assertEqual(self.settings.base_all(),before);self.assertNotIn('private path',str(result))
        self.assertEqual(self.plugin.onboarding_transaction.diagnostic_state(self.preferences)['state'],'session-only')
        await self.plugin.complete_onboarding({'faceplate_requested':None})
        self.assertTrue(self.settings.all()['onboarding_completed'])

    async def test_an_active_setup_cannot_be_reset_under_its_writer(self):
        self.plugin.engine._onboarding_applying=True
        result=await self.plugin.restart_onboarding()
        self.assertEqual(result['draft_reset_error'],'setup_busy');self.assertEqual(self.effects,[])

    async def test_failed_device_metadata_cannot_turn_successful_restart_into_an_exception(self):
        self.plugin.get_onboarding=AsyncMock(side_effect=RuntimeError('metadata unavailable'))
        result=await self.plugin.restart_onboarding()
        self.assertEqual(result['draft'],{});self.assertNotIn('draft_reset_error',result)
        self.assertFalse(result['faceplate_detected'])
