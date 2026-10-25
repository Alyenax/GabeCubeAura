import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.recovery import RecoveryVault, RecoveryError
from signalbar.settings import SettingsStore
from signalbar.update_helper import (TransactionError,
                                     restore_user_state, run_transaction)
from signalbar.updates import UpdateManager, validate_and_stage_archive
from test_updates import FakeLogger, FakeService, RefusesToStopService, fake_exchange, write_plugin
import test_updates as fixtures


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.config = self.base / "settings/GabeCubeAura/config.json"
        self.user = self.base / "share/gabecubeaura"
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(b'{"choice":"before"}')
        self.art = self.user / "steamgriddb/artwork/620/prepared/static/faceplate.gif"
        self.art.parent.mkdir(parents=True)
        self.art.write_bytes(b"old-artwork")
        self.selection = self.art.parents[2] / "active.json"
        self.selection.write_bytes(b'{"mode":"static"}')
        self.auth = self.user / "steamgriddb/auth.json"
        self.auth.write_bytes(b"private-key-never-backed-up")
        self.vault = RecoveryVault(self.base / "runtime/updates", self.config, self.user)

    def test_durable_archive_and_state_survive_transient_package_deletion(self):
        previous = self.base / "previous/GabeCubeAura"
        write_plugin(previous, "1.0.0")
        self.vault.capture("a" * 32, "1.0.0", previous)
        import shutil
        shutil.rmtree(previous)
        metadata, archive, snapshot = self.vault.current()
        self.assertEqual(metadata["version"], "1.0.0")
        validate_and_stage_archive(archive, self.base / "check", "1.0.0")
        self.assertFalse((snapshot / "user/steamgriddb/auth.json").exists())
        self.config.write_bytes(b"changed")
        self.art.write_bytes(b"changed")
        restore_user_state(snapshot, self.config, self.user)
        self.assertEqual(self.art.read_bytes(), b"old-artwork")
        self.assertEqual(json.loads(self.config.read_bytes())["choice"], "before")
        self.assertEqual(self.auth.read_bytes(), b"private-key-never-backed-up")

    def test_corrupt_archive_is_rejected(self):
        previous = self.base / "previous/GabeCubeAura"
        write_plugin(previous, "1.0.0")
        self.vault.capture("a" * 32, "1.0.0", previous)
        _, archive, _ = self.vault.current()
        archive.write_bytes(archive.read_bytes() + b"corruption")
        with self.assertRaises(RecoveryError):
            self.vault.current()

    def test_corrupt_snapshot_aborts_before_any_restore_write(self):
        snapshot = self.vault.snapshot("a" * 32)
        self.config.write_bytes(b"current")
        (snapshot / "user/steamgriddb/artwork/620/prepared/static/faceplate.gif").write_bytes(b"bad")
        with self.assertRaises(TransactionError):
            restore_user_state(snapshot, self.config, self.user)
        self.assertEqual(self.config.read_bytes(), b"current")

    def test_symlink_ancestor_aborts_before_removing_current_selections(self):
        snapshot = self.vault.snapshot("a" * 32)
        import shutil
        shutil.rmtree(self.user / "steamgriddb/artwork/620/prepared")
        outside = self.base / "outside"
        outside.mkdir()
        (self.user / "steamgriddb/artwork/620/prepared").symlink_to(outside, target_is_directory=True)
        self.config.write_bytes(b"current")
        with self.assertRaises(TransactionError):
            restore_user_state(snapshot, self.config, self.user)
        self.assertEqual(self.config.read_bytes(), b"current")

    def test_new_home_and_game_selections_are_removed_when_absent_from_backup(self):
        self.selection.unlink()
        snapshot = self.vault.snapshot("a" * 32)
        self.selection.write_bytes(b"new")
        home = self.selection.with_name("home.json")
        home.write_bytes(b"new")
        restore_user_state(snapshot, self.config, self.user)
        self.assertFalse(self.selection.exists())
        self.assertFalse(home.exists())
        self.assertTrue(self.art.exists())

    def _transaction(self):
        raw = fixtures.UpdateTests()._transaction(self.base)
        old = self.vault.snapshot("a" * 32)
        self.config.write_bytes(b'{"choice":"current"}')
        current = self.vault.snapshot("b" * 32)
        raw["restore_state"] = {"snapshot": str(old), "failure_snapshot": str(current),
                                "settings_path": str(self.config), "user_root": str(self.user)}
        return raw

    def test_restore_transaction_restores_settings_before_successful_restart(self):
        raw = self._transaction()
        def healthy(*_args):
            self.assertEqual(json.loads(self.config.read_bytes())["choice"], "before")
            return True
        result = run_transaction(raw, service=FakeService(), health_waiter=healthy, exchanger=fake_exchange)
        self.assertEqual(result["result"], "updated")

    def test_failed_recovery_restores_current_code_and_current_settings(self):
        raw = self._transaction()
        result = run_transaction(raw, service=FakeService(), health_waiter=lambda *_: False, exchanger=fake_exchange)
        self.assertEqual(result["result"], "rolled_back")
        self.assertEqual(json.loads(self.config.read_bytes())["choice"], "current")
        self.assertEqual(json.loads((Path(raw["active_dir"]) / "package.json").read_text())["version"], "1.0.0")

    def test_stop_refusal_does_not_restore_or_swap(self):
        raw = self._transaction()
        with patch("signalbar.update_helper.restore_user_state") as restore:
            run_transaction(raw, service=RefusesToStopService(), exchanger=fake_exchange)
        restore.assert_not_called()
        self.assertEqual(json.loads(self.config.read_bytes())["choice"], "current")

    def test_capture_rejects_unsafe_token_and_preserves_source(self):
        previous = self.base / "previous/GabeCubeAura"
        write_plugin(previous, "1.0.0")
        with self.assertRaises(RecoveryError):
            self.vault.capture("../../outside", "1.0.0", previous)
        self.assertTrue(previous.exists())

    def test_capture_failure_keeps_previous_package_even_after_cleanup_deadline(self):
        token = "a" * 32
        previous = self.vault.root.parent / "rollback" / token / "GabeCubeAura"
        write_plugin(previous, "1.0.0")
        manager = UpdateManager("1.1.0", SettingsStore(str(self.config)), self.base / "runtime",
                                self.base / "plugins/GabeCubeAura", FakeLogger(),
                                companion_root=self.user / "components")
        manager._set(completed_token=token, last_result="updated", rollback_version="1.0.0")
        os.utime(previous.parent, (1, 1))
        with patch.object(manager.recovery, "capture", side_effect=OSError("disk full")):
            manager._cleanup_completed_transaction()
            manager._cleanup_expired()
            self.assertIn("disk full", manager.status()["recovery_error"])
        self.assertTrue(previous.exists())

    def test_local_recovery_preparation_survives_manager_restart(self):
        previous = self.base / "previous/GabeCubeAura"
        write_plugin(previous, "1.0.0")
        self.vault.capture("a" * 32, "1.0.0", previous)
        def manager():
            return UpdateManager("1.1.0", SettingsStore(str(self.config)), self.base / "runtime",
                                 self.base / "plugins/GabeCubeAura", FakeLogger(),
                                 companion_root=self.user / "components")
        original = manager().prepare_previous_version()
        restored = manager().status()
        self.assertEqual(restored["phase"], "ready")
        self.assertTrue(restored["recovery_prepared"])
        self.assertEqual(restored["confirmation_token"], original["confirmation_token"])
        self.assertEqual(restored["available_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
