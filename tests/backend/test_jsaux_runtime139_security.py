"""Independent runtime migration review: files only, no root, USB or /run use."""
import errno
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from signalbar.faceplate import runtime


class RuntimeSecurity139Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='j139-', dir='/private/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.run = self.root / 'run'
        self.run.mkdir(mode=0o755)
        self.canonical = self.run / 'decky/jsaux-broker/v1'
        self.canonical_patch = patch.object(runtime, 'CANONICAL_RUNTIME', self.canonical)
        self.canonical_patch.start()
        self.addCleanup(self.canonical_patch.stop)

    def tree(self, leaf_mode=0o755):
        self.canonical.parent.parent.mkdir(mode=0o755)
        self.canonical.parent.mkdir(mode=0o755)
        self.canonical.mkdir(mode=leaf_mode)
        return self.canonical

    def assert_private(self, path):
        self.assertEqual(0o700, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(os.geteuid(), path.stat().st_uid)

    def test_fresh_tree_is_private_without_changing_trusted_parent(self):
        self.assertEqual(self.canonical, runtime.provision_runtime())
        for path in (self.run/'decky', self.canonical.parent, self.canonical):
            self.assert_private(path)
        self.assertEqual(0o755, stat.S_IMODE(self.run.stat().st_mode))
        self.assertEqual([], list(self.canonical.iterdir()))

    def test_exact_legacy_leaf_tightens_without_changing_lock_or_files(self):
        self.tree()
        ownership = self.canonical/'ownership'; ownership.mkdir(mode=0o700)
        lock = ownership/'existing.lock'; lock.write_bytes(b'lock-preserved'); lock.chmod(0o600)
        original = lock.stat()
        self.assertEqual(self.canonical, runtime.provision_runtime())
        self.assert_private(self.canonical)
        self.assert_private(ownership)
        self.assertEqual(0o755, stat.S_IMODE(self.canonical.parent.stat().st_mode))
        self.assertEqual(b'lock-preserved', lock.read_bytes())
        self.assertEqual((original.st_dev, original.st_ino), (lock.stat().st_dev, lock.stat().st_ino))
        self.assertEqual(0o600, stat.S_IMODE(lock.stat().st_mode))
        self.assertEqual(['ownership'], [item.name for item in self.canonical.iterdir()])

    def test_other_leaf_modes_are_refused_unchanged(self):
        self.tree(0o700)
        for mode in (0o777, 0o775, 0o770, 0o750, 0o711, 0o701, 0o1755):
            with self.subTest(mode=oct(mode)):
                self.canonical.chmod(mode)
                with self.assertRaises(PermissionError): runtime.provision_runtime()
                self.assertEqual(mode, stat.S_IMODE(self.canonical.stat().st_mode))

    def test_unsafe_ancestor_is_not_repaired(self):
        self.tree()
        self.canonical.parent.chmod(0o777)
        with self.assertRaises(PermissionError): runtime.provision_runtime()
        self.assertEqual(0o777, stat.S_IMODE(self.canonical.parent.stat().st_mode))
        self.assertEqual(0o755, stat.S_IMODE(self.canonical.stat().st_mode))

    def test_foreign_leaf_owner_cannot_trigger_migration(self):
        self.tree()
        inode = self.canonical.stat().st_ino
        original_fstat = os.fstat
        def foreign(fd):
            info = original_fstat(fd)
            if info.st_ino == inode:
                fields = list(info); fields[4] = os.geteuid()+1
                return os.stat_result(fields)
            return info
        with patch.object(runtime.os, 'fstat', side_effect=foreign):
            with self.assertRaises(PermissionError): runtime.provision_runtime()
        self.assertEqual(0o755, stat.S_IMODE(self.canonical.stat().st_mode))

    def test_requested_identity_must_be_current_backend_identity(self):
        self.tree()
        with self.assertRaises(PermissionError):
            runtime.provision_runtime(expected_uid=os.geteuid()+1)
        self.assertEqual(0o755, stat.S_IMODE(self.canonical.stat().st_mode))

    def test_symlink_at_each_canonical_component_is_refused(self):
        self.tree()
        for component in (self.canonical, self.canonical.parent,
                          self.canonical.parent.parent, self.run):
            with self.subTest(component=component.name):
                real = component.with_name(component.name+'-real')
                component.rename(real); component.symlink_to(real, target_is_directory=True)
                try:
                    with self.assertRaises((PermissionError, OSError)):
                        runtime.provision_runtime()
                    self.assertEqual(0o755, stat.S_IMODE(real.stat().st_mode))
                finally:
                    component.unlink(); real.rename(component)

    def test_custom_0755_directory_is_not_the_legacy_migration(self):
        custom = self.root/'v1'; custom.mkdir(mode=0o755)
        with self.assertRaises(PermissionError): runtime.provision_runtime(custom)
        self.assertEqual(0o755, stat.S_IMODE(custom.stat().st_mode))
        custom.chmod(0o700)
        self.assertEqual(custom, runtime.provision_runtime(custom))

    def test_custom_symlink_parent_is_not_followed(self):
        real = self.root/'custom-real'; real.mkdir(mode=0o700)
        leaf = real/'v1'; leaf.mkdir(mode=0o700)
        alias = self.root/'custom-alias'; alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises((PermissionError, OSError)):
            runtime.provision_runtime(alias/'v1')
        self.assert_private(leaf)

    def test_migration_only_uses_fchmod_of_validated_directory_descriptor(self):
        self.tree()
        original_fchmod = os.fchmod
        calls = []
        expected = self.canonical.stat()
        def validate_fchmod(fd, mode):
            info = os.fstat(fd)
            self.assertEqual((expected.st_dev, expected.st_ino), (info.st_dev, info.st_ino))
            self.assertTrue(stat.S_ISDIR(info.st_mode))
            self.assertEqual(0o700, mode)
            calls.append(fd)
            return original_fchmod(fd, mode)
        with patch.object(runtime.os, 'chmod', side_effect=AssertionError('path chmod forbidden')), \
             patch.object(runtime.os, 'fchmod', side_effect=validate_fchmod):
            runtime.provision_runtime()
        self.assertEqual(1, len(calls))

    def test_canonical_ownership_first_provisions_private_runtime(self):
        self.assertEqual(self.canonical/'ownership', runtime.provision_ownership(self.canonical/'ownership'))
        self.assert_private(self.canonical)
        self.assert_private(self.canonical/'ownership')
        self.assertFalse((self.canonical/'credential.json').exists())
        self.assertFalse((self.canonical/'control.sock').exists())

    def test_custom_ownership_never_repairs_world_readable_directory(self):
        custom = self.root/'custom-ownership'; custom.mkdir(mode=0o755)
        with self.assertRaises(PermissionError): runtime.provision_ownership(custom)
        self.assertEqual(0o755, stat.S_IMODE(custom.stat().st_mode))

    def test_failed_fchmod_is_closed_and_diagnostic_has_no_paths_or_credentials(self):
        self.tree()
        with patch.object(runtime.os, 'fchmod', side_effect=PermissionError(errno.EACCES, 'private-secret-path')):
            with self.assertRaises(runtime.RuntimeSecurityError) as raised:
                runtime.provision_runtime()
        self.assertEqual(0o755, stat.S_IMODE(self.canonical.stat().st_mode))
        diagnostic = raised.exception.diagnostic
        self.assertTrue(set(diagnostic) <= {'reason','component','effective_uid','owner_uid','owner_gid','mode','expected_mode','errno'})
        rendered = json.dumps(diagnostic)
        self.assertNotIn('private-secret-path', rendered)
        self.assertNotIn(str(self.root), rendered)
        self.assertLess(len(rendered), 1000)

    def test_mkdir_eexist_race_reopens_and_revalidates_actual_inode(self):
        original_mkdir = os.mkdir
        injected = [False]
        def competing_mkdir(path, mode=0o777, *, dir_fd=None):
            if str(path) == 'decky' and dir_fd is not None and not injected[0]:
                injected[0] = True
                original_mkdir(path, mode, dir_fd=dir_fd)
                raise FileExistsError(errno.EEXIST, 'fixture race')
            return original_mkdir(path, mode, dir_fd=dir_fd)
        with patch.object(runtime.os, 'mkdir', side_effect=competing_mkdir):
            self.assertEqual(self.canonical, runtime.provision_runtime())
        self.assertTrue(injected[0])
        self.assert_private(self.canonical)

    def test_substitution_before_leaf_open_does_not_follow_symlink(self):
        self.tree()
        target = self.root/'outside'; target.mkdir(mode=0o755)
        old = self.canonical.with_name('old-v1')
        original_open = os.open
        injected = [False]
        def replacing_open(path, flags, mode=0o777, *, dir_fd=None):
            if str(path) == 'v1' and dir_fd is not None and not injected[0]:
                injected[0] = True
                self.canonical.rename(old)
                self.canonical.symlink_to(target, target_is_directory=True)
            return original_open(path, flags, mode, dir_fd=dir_fd)
        with patch.object(runtime.os, 'open', side_effect=replacing_open):
            with self.assertRaises((PermissionError, OSError)): runtime.provision_runtime()
        self.assertTrue(injected[0])
        self.assertEqual(0o755, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual(0o755, stat.S_IMODE(old.stat().st_mode))


if __name__ == '__main__': unittest.main()
