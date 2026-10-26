"""Offline handoff regression tests, including Pixel Faceplate's real reader.

RPC bodies and the claim helper are loaded from the production source. Engine,
settings persistence and hardware providers are explicit test doubles: this is
not a SteamOS or physical-panel certification. Separate-process tests use real
/proc, root/unprivileged UIDs, permissions and process death on Linux.
"""
from __future__ import annotations

import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("GCA_HANDOFF_SOURCE", ROOT))
FIXTURE = ROOT / "tests/fixtures/pixel_faceplate_031"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


claim = load_file("tested_faceplate_claim", SOURCE / "py_modules/signalbar/faceplate_claim.py")
peer = load_file("pixel_faceplate_handoff", FIXTURE / "handoff.py")


class Settings:
    def __init__(self, enabled):
        self._lock = threading.RLock()
        self.values = {"faceplate_lab_enabled": enabled, "faceplate_power_mode": "auto"}

    def all(self):
        with self._lock:
            return dict(self.values)

    def update(self, changes):
        with self._lock:
            self.values.update(changes)
        return self.all()

    def plan_update(self, changes):
        return ({key: self.values.get(key) for key in changes}, dict(changes))


class Engine:
    def __init__(self, enabled):
        self.settings = Settings(enabled)
        self._available = False
        self._stop = threading.Event()
        self.countdown = SimpleNamespace(end_action=Mock())
        self.assistant = Mock()
        self._assistant_wake_policy = lambda values: False
        self.faceplate = SimpleNamespace(device_status=lambda: {"available": True})
        self.faceplate_preferences = SimpleNamespace(
            read=lambda: SimpleNamespace(home_scene="dashboard", game_scene="artwork", revision=1),
            update=Mock())
        self.refresh_settings = Mock()
        self.activate_faceplate_setup = Mock(return_value=True)
        self.suspend_faceplate = Mock()
        self.resume_faceplate = Mock()
        self.stop = Mock()
        self.set_faceplate_power = Mock()

    def update_settings(self, changes):
        self.settings.update(changes)
        self.refresh_settings(changes)

    def import_configuration(self, values, *profiles):
        self.update_settings(values)

    def reset_configuration(self):
        self.update_settings({"faceplate_lab_enabled": True})

    reset_settings_only = reset_configuration

    def status(self):
        return self.settings.all()


class Budget:
    def __init__(self, *args, **kwargs):
        pass

    def call(self, callback):
        return callback()


def plugin_type():
    tree = ast.parse((SOURCE / "main.py").read_text())
    body = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Plugin")
    namespace = dict(asyncio=asyncio, threading=threading, time=time, os=os, Path=Path,
                     decky=SimpleNamespace(logger=Mock()), faceplate_claim=claim,
                     ShutdownBudget=Budget, clean_draft=lambda choices: dict(choices),
                     read_configuration_import=lambda path: (json.loads(Path(path).read_text()), {}, {}, {}))
    exec(compile(ast.Module(body=[body], type_ignores=[]), str(SOURCE / "main.py"), "exec"), namespace)
    return namespace["Plugin"]


Plugin = plugin_type()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.plugins = self.home / "plugins"
        self.plugins.mkdir()
        self.settings_dir = self.home / "settings/GabeCubeAura"
        self.settings_dir.mkdir(parents=True)
        self.proc = self.home / "proc"
        process = self.proc / str(os.getpid())
        process.mkdir(parents=True)
        (process / "cmdline").write_bytes(b"GabeCubeAura (/home/deck/homebrew/plugins/GabeCubeAura/main.py)\0")
        self.p = Plugin()
        self.p.engine = Engine(False)
        self.p.faceplate_settings_dir = str(self.settings_dir)
        self.p._onboarding_commit_lock = threading.RLock()
        self.p._onboarding_recovery_error = ""
        self.p.onboarding_draft = Mock()
        self.p.onboarding_transaction = Mock()
        self.p.onboarding_transaction.recover.return_value = None
        self.p.diagnostics = Mock()
        self.p.faceplate_power_events = Mock()
        self.p.faceplate_artwork_jobs = Mock()
        self.p.update_manager = Mock()
        self.p.pixel_studio = Mock()
        self.p._stop_cinema = Mock()
        self.p._configure_faceplate_power_events = Mock()

    def initial(self, enabled):
        self.p.engine.settings.update({"faceplate_lab_enabled": enabled})
        self.p._sync_faceplate_claim()
        self.assert_owner(enabled)

    def assert_owner(self, enabled):
        self.assertEqual(peer.faceplate_owner(str(self.plugins), str(self.proc)),
                         "GabeCubeAura" if enabled else "")

    def test_early_rpc_defers_until_startup_has_settings_directory(self):
        directory = self.p.faceplate_settings_dir
        del self.p.faceplate_settings_dir
        asyncio.run(self.p.set_setting("faceplate_lab_enabled", True))
        self.assert_owner(False)
        self.p.faceplate_settings_dir = directory
        self.p._sync_faceplate_claim()
        self.assert_owner(True)

    def test_manual_toggle_both_directions(self):
        for enabled in (True, False, True, False):
            asyncio.run(self.p.set_setting("faceplate_lab_enabled", enabled))
            self.assert_owner(enabled)

    def test_setup_both_directions(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.initial(not enabled)
                asyncio.run(self.p.complete_onboarding({"faceplate_requested": enabled}))
                self.assert_owner(enabled)

    def test_import_both_directions(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.initial(not enabled)
                path = self.home / "import.json"
                path.write_text(json.dumps({"faceplate_lab_enabled": enabled}))
                asyncio.run(self.p.import_configuration(str(path)))
                self.assert_owner(enabled)

    def test_legacy_reset(self):
        self.initial(False)
        asyncio.run(self.p.reset_configuration())
        self.assert_owner(True)

    def test_settings_reset(self):
        self.initial(False)
        asyncio.run(self.p.reset_settings_only())
        self.assert_owner(True)

    def test_toggle_post_commit_failure_still_releases(self):
        self.initial(True)
        self.p.engine.refresh_settings.side_effect = OSError("provider failed after saving")
        with self.assertRaises(OSError):
            asyncio.run(self.p.set_setting("faceplate_lab_enabled", False))
        self.assert_owner(False)

    def test_import_post_commit_failure_still_releases(self):
        self.initial(True)
        path = self.home / "import.json"
        path.write_text('{"faceplate_lab_enabled": false}')
        self.p.engine.refresh_settings.side_effect = OSError("provider failed after saving")
        with self.assertRaises(OSError):
            asyncio.run(self.p.import_configuration(str(path)))
        self.assert_owner(False)

    def test_invalid_import_keeps_current_owner(self):
        self.initial(True)
        with self.assertRaises(FileNotFoundError):
            asyncio.run(self.p.import_configuration(str(self.home / "missing.json")))
        self.assert_owner(True)

    def test_reset_draft_cleanup_failure_still_claims(self):
        self.initial(False)
        self.p.onboarding_draft.discard.side_effect = OSError("draft cleanup failed")
        with self.assertRaises(OSError):
            asyncio.run(self.p.reset_settings_only())
        self.assert_owner(True)

    def test_setup_rollback_restores_claim(self):
        self.initial(True)
        self.p.engine.refresh_settings.side_effect = [OSError("apply failed"), None]
        def recover(*args):
            self.p.engine.settings.update({"faceplate_lab_enabled": True})
            return "rolled-back"
        self.p.onboarding_transaction.recover.side_effect = recover
        with self.assertRaises(OSError):
            asyncio.run(self.p.complete_onboarding({"faceplate_requested": False}))
        self.assert_owner(True)

    def test_factory_reset_and_partial_failure(self):
        fake = ModuleType("signalbar.configuration_reset")
        for fails in (False, True):
            with self.subTest(fails=fails):
                self.initial(False)
                def reset(plugin, confirmation):
                    plugin.engine.reset_configuration()
                    if fails:
                        raise OSError("later cleanup failed")
                fake.factory_reset = reset
                with patch.dict(sys.modules, {"signalbar.configuration_reset": fake}):
                    if fails:
                        with self.assertRaises(OSError):
                            asyncio.run(self.p.factory_reset_configuration("RESET"))
                    else:
                        asyncio.run(self.p.factory_reset_configuration("RESET"))
                self.assert_owner(True)

    def test_power_off_and_suspend_keep_reservation(self):
        self.initial(True)
        asyncio.run(self.p.set_faceplate_power(False))
        self.assert_owner(True)
        self.p._handle_faceplate_power_event("sleep", True)
        self.assert_owner(True)
        self.p._handle_faceplate_power_event("sleep", False)
        self.assert_owner(True)

    def test_brightness_does_not_rewrite_claim(self):
        self.initial(True)
        with patch.object(claim, "claim", wraps=claim.claim) as writer:
            asyncio.run(self.p.set_setting("faceplate_brightness", 40))
        writer.assert_not_called()
        self.assert_owner(True)

    def test_clean_unload_and_uninstall_release(self):
        for method in ("_unload", "_uninstall"):
            with self.subTest(method=method):
                self.p._gabe_unloading = False
                self.initial(True)
                asyncio.run(getattr(self.p, method)())
                self.assert_owner(False)

    def test_late_callback_cannot_reclaim_after_unload(self):
        self.initial(True)
        asyncio.run(self.p._unload())
        self.p._sync_faceplate_claim()
        self.assert_owner(False)

    def test_cancelled_rpc_still_synchronizes_when_worker_finishes(self):
        self.initial(True)
        entered, proceed = threading.Event(), threading.Event()
        original_update = self.p.engine.update_settings
        def slow_update(changes):
            entered.set()
            if not proceed.wait(3):
                raise TimeoutError("test worker was not released")
            original_update(changes)
        self.p.engine.update_settings = slow_update
        async def exercise():
            task = asyncio.create_task(self.p.set_setting("faceplate_lab_enabled", False))
            try:
                self.assertTrue(await asyncio.get_running_loop().run_in_executor(None, entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                proceed.set()
        asyncio.run(exercise())  # drains the executor, including its finally block
        self.assert_owner(False)

    def test_start_failure_releases_claim(self):
        self.initial(False)
        self.p.engine.settings.update({"faceplate_lab_enabled": True})
        self.p.engine.start = Mock(side_effect=RuntimeError("startup failed"))
        source = ast.parse((SOURCE / "main.py").read_text())
        method = next(n for n in ast.walk(source)
                      if isinstance(n, ast.AsyncFunctionDef) and n.name == "_main")
        # Execute the actual startup segment, without constructing unrelated
        # providers. It must not strand a live claim when start raises.
        start = next(i for i, n in enumerate(method.body)
                     if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                     and ast.unparse(n.value.func) == "self._sync_faceplate_claim")
        segment = ast.Module(body=method.body[start:start+2], type_ignores=[])
        with self.assertRaises(RuntimeError):
            exec(compile(segment, str(SOURCE / "main.py"), "exec"),
                 dict(self=self.p, faceplate_claim=claim))
        self.assert_owner(False)

    def test_claim_precedes_engine_start(self):
        node = next(node for node in ast.walk(ast.parse((SOURCE / "main.py").read_text()))
                    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_main")
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
        sync = next(n for n in calls if ast.unparse(n.func) == "self._sync_faceplate_claim")
        start = next(n for n in calls if ast.unparse(n.func) == "self.engine.start")
        self.assertLess(sync.lineno, start.lineno)


class ClaimFileTests(unittest.TestCase):
    def test_format_and_pid_bound_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(claim.claim(tmp))
            path = Path(tmp) / claim.CLAIM_FILENAME
            self.assertEqual(json.loads(path.read_text()), {"plugin": "GabeCubeAura", "pid": os.getpid()})
            claim.release(tmp)
            self.assertFalse(path.exists())
            path.write_text(json.dumps({"plugin": "GabeCubeAura", "pid": os.getpid() + 1}))
            claim.release(tmp)
            self.assertTrue(path.exists())

    def test_restrictive_umask_does_not_hide_nonsecret_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory_mode = Path(tmp).stat().st_mode
            previous = os.umask(0o077)
            try:
                self.assertTrue(claim.claim(tmp))
            finally:
                os.umask(previous)
            self.assertEqual((Path(tmp) / claim.CLAIM_FILENAME).stat().st_mode & 0o777, 0o644)
            self.assertEqual(Path(tmp).stat().st_mode, directory_mode)

    def test_old_predictable_temporary_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = Path(tmp) / "unrelated-private-file"
            victim.write_text("must remain unchanged")
            (Path(tmp) / (claim.CLAIM_FILENAME + ".tmp")).symlink_to(victim)
            self.assertTrue(claim.claim(tmp))
            self.assertEqual(victim.read_text(), "must remain unchanged")
            self.assertFalse((Path(tmp) / claim.CLAIM_FILENAME).is_symlink())

    def test_failed_replace_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(claim.os, "replace", side_effect=OSError("replace failed")):
                self.assertFalse(claim.claim(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_concurrent_claims_are_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: claim.claim(tmp), range(80)))
            self.assertTrue(all(results))
            self.assertEqual(json.loads((Path(tmp) / claim.CLAIM_FILENAME).read_text())["pid"], os.getpid())
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_missing_and_malformed_claim_release_are_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            claim.release(tmp)
            for content in ("{", "null", "[]", '"text"'):
                (Path(tmp) / claim.CLAIM_FILENAME).write_text(content)
                claim.release(tmp)


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux /proc")
class RealProcessTests(unittest.TestCase):
    def test_live_process_and_crash_with_actual_proc(self):
        self.exercise(False)

    @unittest.skipUnless(os.geteuid() == 0, "requires root to emulate Decky's two UIDs")
    def test_root_writer_unprivileged_pixel_reader(self):
        self.exercise(True)

    def exercise(self, split_uids):
        with tempfile.TemporaryDirectory(prefix="gca-handoff-") as tmp:
            home = Path(tmp)
            home.chmod(0o755)
            settings = home / "settings/GabeCubeAura"
            settings.mkdir(parents=True)
            settings.chmod(0o700)
            if split_uids:
                os.chown(settings, 65534, 65534)
            script = home / "plugins/GabeCubeAura/main.py"
            script.parent.mkdir(parents=True)
            script.write_text(
                "import sys,os,importlib.util\n"
                f"s=importlib.util.spec_from_file_location('claim',{str(SOURCE / 'py_modules/signalbar/faceplate_claim.py')!r})\n"
                "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
                "os.umask(0o077)\nprint(m.claim(sys.argv[1]),flush=True)\nsys.stdin.readline()\n")
            writer = subprocess.Popen([sys.executable, str(script), str(settings)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            def drop_privileges():
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            reader = (f"import sys;sys.path.insert(0,{str(FIXTURE)!r});"
                      "from handoff import faceplate_owner;print(faceplate_owner(sys.argv[1]))")
            def read_owner():
                result = subprocess.run([sys.executable, "-c", reader, str(home / "plugins")],
                                        text=True, capture_output=True, timeout=5,
                                        preexec_fn=drop_privileges if split_uids else None)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()
            try:
                self.assertEqual(writer.stdout.readline().strip(), "True")
                self.assertEqual(read_owner(), "GabeCubeAura")
                writer.kill()
                writer.communicate(timeout=5)
                self.assertTrue((settings / claim.CLAIM_FILENAME).exists())
                self.assertEqual(read_owner(), "")
            finally:
                if writer.poll() is None:
                    writer.kill()
                writer.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
