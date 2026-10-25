"""Lab 104 installer regressions; no real system service or machine is changed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.settings import SettingsStore
from signalbar.update_helper import (TransactionError, snapshot_user_state,
                                     verify_snapshot, restore_user_state)
from signalbar.updates import UpdateManager, UpdateError
from test_updates import FakeClient, FakeLogger, write_archive, write_plugin


class UpdateUnblockTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        archive = self.base / "candidate.zip"
        write_archive(archive, "1.1.1")
        active = self.base / "plugins/GabeCubeAura"
        write_plugin(active, "1.1.0")
        self.client = FakeClient(archive, "1.1.1")
        self.manager = UpdateManager(
            "1.1.0", SettingsStore(str(self.base / "settings/config.json")),
            str(self.base / "runtime"), str(active), FakeLogger(), client=self.client,
            companion_root=str(self.base / "share/components"),
        )
        self.manager.check()
        self.ready = self.manager.prepare()

    def test_missing_helper_runtime_is_visible_not_silent_ready(self):
        with patch("signalbar.updates.shutil.which", return_value=None):
            with self.assertRaises(UpdateError):
                self.manager.install(self.ready["confirmation_token"])
        state = self.manager.status()
        self.assertEqual(state["phase"], "error")
        self.assertEqual(state["error_category"], "helper_unavailable")
        self.assertTrue(state["error"])
        self.assertEqual(state["confirmation_token"], self.ready["confirmation_token"])

    def test_backup_error_is_visible_and_same_verified_token_can_retry(self):
        token = self.ready["confirmation_token"]
        with patch("signalbar.updates.shutil.which", return_value="/usr/bin/fake"), \
                patch.object(self.manager.recovery, "snapshot", side_effect=TransactionError("Recovery artwork backup exceeds 1 GB")):
            with self.assertRaises(UpdateError): self.manager.install(token)
        state = self.manager.status()
        self.assertEqual(state["phase"], "error")
        self.assertIn("1 GB", state["error"])
        self.assertFalse(state.get("pending_token"))
        with patch("signalbar.updates.shutil.which", return_value="/usr/bin/fake"), \
                patch("signalbar.updates.subprocess.run") as run:
            self.assertTrue(self.manager.install(token)["accepted"])
            run.assert_called_once()

    def test_permission_error_is_visible_and_does_not_start_service(self):
        with patch("signalbar.updates.shutil.copy2", side_effect=PermissionError("private path")), \
                patch("signalbar.updates.subprocess.run") as run:
            with self.assertRaises(UpdateError): self.manager.install(self.ready["confirmation_token"])
            run.assert_not_called()
        state = self.manager.status()
        self.assertEqual(state["error_category"], "permissions")
        self.assertNotIn("private path", state["error"])

    def test_backup_has_visible_phase_before_helper_starts(self):
        original = self.manager.recovery.snapshot
        def snapshot(token):
            self.assertEqual(self.manager.status()["phase"], "preparing_install")
            return original(token)
        with patch("signalbar.updates.shutil.which", return_value="/usr/bin/fake"), \
                patch.object(self.manager.recovery, "snapshot", side_effect=snapshot), \
                patch("signalbar.updates.subprocess.run"):
            self.manager.install(self.ready["confirmation_token"])

    def test_duplicate_install_is_refused(self):
        self.manager._operation_lock.acquire()
        try:
            with self.assertRaisesRegex(UpdateError, "Another update"):
                self.manager.install(self.ready["confirmation_token"])
        finally:
            self.manager._operation_lock.release()

    def test_late_duplicate_never_overwrites_active_transaction_state(self):
        token = self.ready["confirmation_token"]
        with patch("signalbar.updates.shutil.which", return_value="/usr/bin/fake"), \
                patch("signalbar.updates.subprocess.run"):
            self.manager.install(token)
            with self.assertRaises(UpdateError): self.manager.install(token)
        self.assertEqual(self.manager.status()["phase"], "installing")
        self.assertEqual(self.manager._state["pending_token"], token)

    def test_dismiss_failure_keeps_verified_candidate_retryable(self):
        with patch("signalbar.updates.shutil.which", return_value=None):
            with self.assertRaises(UpdateError): self.manager.install(self.ready["confirmation_token"])
        dismissed = self.manager.dismiss_error()
        self.assertEqual(dismissed["phase"], "ready")
        self.assertEqual(dismissed["confirmation_token"], self.ready["confirmation_token"])

    def test_interrupted_preparation_recovers_with_visible_error(self):
        self.manager._set(phase="preparing_install")
        resumed = UpdateManager("1.1.0", self.manager.settings,
            str(self.base / "runtime"), str(self.base / "plugins/GabeCubeAura"),
            FakeLogger(), client=self.client, companion_root=str(self.base / "share/components"))
        self.assertEqual(resumed.status()["phase"], "error")
        self.assertEqual(resumed.status()["error_category"], "interrupted")

    def test_manual_check_can_replace_old_ready_without_touching_old_stage(self):
        token = self.ready["confirmation_token"]
        archive = self.base / "next.zip"; write_archive(archive, "1.1.2")
        self.manager.client = FakeClient(archive, "1.1.2")
        self.assertEqual(self.manager.check()["phase"], "ready")
        next_state = self.manager.check(force_refresh=True)
        self.assertEqual(next_state["available_version"], "1.1.2")
        self.assertEqual(next_state["phase"], "available")
        self.assertFalse(next_state["confirmation_token"])
        self.assertTrue((self.manager.root / "staged" / token / "GabeCubeAura").exists())

    def test_check_same_release_preserves_verified_token(self):
        checked = self.manager.check(force_refresh=True)
        self.assertEqual(checked["phase"], "ready")
        self.assertEqual(checked["confirmation_token"], self.ready["confirmation_token"])

    def test_partial_snapshot_is_rebuilt_without_removing_user_files(self):
        token = self.ready["confirmation_token"]
        snapshot = self.manager.recovery.root / token / "snapshot"
        snapshot.mkdir(parents=True); (snapshot / "unfinished").write_bytes(b"partial")
        self.manager.settings.update({"mode": "idle"})
        rebuilt = self.manager.recovery.snapshot(token)
        self.assertTrue((rebuilt / "manifest.json").exists())
        self.assertTrue(Path(self.manager.settings.path).exists())
        self.assertFalse((rebuilt / "unfinished").exists())

    def test_artwork_over_old_128mb_limit_is_streamed_and_restorable(self):
        config = self.base / "config.json"; config.write_text('{}')
        user = self.base / "large-user"
        artwork = user / "steamgriddb/artwork/620/prepared/faceplate.gif"
        artwork.parent.mkdir(parents=True)
        with artwork.open('wb') as handle: handle.truncate(129 * 1024 * 1024)
        snapshot = self.base / "large-snapshot"
        original = Path.read_bytes
        def bounded_read(path):
            if path.stat().st_size > 1024 * 1024:
                self.fail("Large artwork must never be read whole")
            return original(path)
        with patch.object(Path, "read_bytes", bounded_read):
            snapshot_user_state(config, user, snapshot)
            manifest = verify_snapshot(snapshot)
            artwork.write_bytes(b"changed")
            restore_user_state(snapshot, config, user)
        self.assertEqual(artwork.stat().st_size, 129 * 1024 * 1024)
        self.assertEqual(manifest["files"][-1]["size"], 129 * 1024 * 1024)

    def test_storage_limit_remains_bounded_and_cleans_only_partial_snapshot(self):
        config = self.base / "limited-config.json"; config.write_text('{}')
        user = self.base / "limited-user"; user.mkdir()
        snapshot = self.base / "limited-snapshot"
        with patch("signalbar.update_helper.MAX_STATE_BYTES", 1):
            with self.assertRaises(TransactionError): snapshot_user_state(config, user, snapshot)
        self.assertFalse(snapshot.exists()); self.assertTrue(config.exists())


if __name__ == "__main__": unittest.main()
