import json
import asyncio
import importlib.util
import sys
import types
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from signalbar.distribution import supports_private_tools, speech_release_client
from signalbar.diagnostics import DiagnosticJournal
from signalbar.settings import SettingsStore
from signalbar.updates import UpdateManager
from signalbar.screen_sync_trace import ScreenSyncTrace


class PublicDistributionTests(unittest.TestCase):
    def test_native_export_rpc_creates_only_a_local_redacted_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {"decky": types.ModuleType("decky")}):
            root = Path(__file__).resolve().parents[2]
            spec = importlib.util.spec_from_file_location("public_export_main_test", root / "main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            plugin = module.Plugin()
            plugin.diagnostics = DiagnosticJournal(Path(directory) / "state", "1.4.1")
            plugin.diagnostics.record("manual_test", api_key="secret-value", path="/home/deck/private")
            plugin.configuration_export_path = Path(directory) / "Documents" / "configuration.json"
            plugin.update_manager = Mock()
            plugin.engine = types.SimpleNamespace(display_control_snapshot=lambda:{
                'owner':'GabeCubeAura','screen_sync':{'phase':'capturing','frame_age_s':0.1}})
            plugin.engine.screen_sync_trace = ScreenSyncTrace()
            plugin.engine.screen_sync_trace.begin_preview(15)
            plugin.engine.screen_sync_trace.record('gstreamer-stage', stage='waiting-streaming')
            result = asyncio.run(plugin.export_diagnostic_report())
            report = Path(result["path"]).read_text()
            self.assertNotIn("secret-value", report)
            self.assertNotIn("/home/deck", report)
            self.assertEqual(json.loads(report)["schema"], "gabecubeaura-lab-diagnostic-v1")
            self.assertEqual(json.loads(report)['display_control']['screen_sync']['phase'],'capturing')
            self.assertIn('gstreamer-stage',[row['event'] for row in json.loads(report)['screen_sync_trace']['records']])
            plugin.update_manager.upload_diagnostic_report.assert_not_called()
            self.assertEqual(Path(result["path"]).stat().st_mode & 0o777, 0o600)

    def test_build_capability_is_not_an_update_channel_preference(self):
        for version in ("1.4.1", "1.5.0-beta.1", "1.5.0-beta1", "unknown"):
            self.assertFalse(supports_private_tools(version))
        for version in ("1.4.1-lab.84", "v1.4.1-lab.84", "1.4.1-test.1"):
            self.assertTrue(supports_private_tools(version))

    def test_inherited_upload_consent_cannot_enable_public_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            first = DiagnosticJournal(directory, "1.4.1-lab.83")
            first.begin_session()
            first.set_automatic_upload(True)
            public = DiagnosticJournal(directory, "1.4.1")
            self.assertTrue(public.begin_session()["pending"])
            self.assertFalse(public.status()["automatic_upload"])
            self.assertFalse(public.automatic_upload_due())
            self.assertFalse(public.set_automatic_upload(True)["automatic_upload"])
            # Local diagnostics are still available; the historical schema stays compatible.
            report = public.build_report()["report"]
            self.assertEqual(report["schema"], "gabecubeaura-lab-diagnostic-v1")
            self.assertTrue(report["events"])

    def test_private_build_preserves_existing_upload_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            lab = DiagnosticJournal(directory, "1.4.1-lab.84")
            self.assertTrue(lab.status()["automatic_upload"])
            self.assertFalse(lab.set_automatic_upload(False)["automatic_upload"])
            self.assertFalse(DiagnosticJournal(directory, "1.4.1-lab.84").status()["automatic_upload"])

    def test_public_build_preserves_private_token_but_never_uses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SettingsStore(str(root / "config.json"))
            settings.update({"updates_channel": "private"})
            state = root / "runtime/updates/update-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"phase": "ready", "checked_channel": "private",
                                         "available_version": "1.4.1-lab.999",
                                         "confirmation_token": "private-prepared-token"}))
            auth = Mock()
            manager = UpdateManager("1.4.1", settings, str(root / "runtime"), str(root / "plugin"), Mock(), private_auth=auth)
            self.assertEqual(manager.status()["channel"], "stable")
            self.assertFalse(manager.status()["private_tools"])
            self.assertEqual(manager.status()["phase"], "idle")
            self.assertEqual(manager.status()["available_version"], "")
            self.assertEqual(manager.status()["confirmation_token"], "")
            self.assertEqual(manager._release_client().repository, "GabeCubeAura")
            for action in (lambda: manager._release_client("private"), manager.start_private_authorization,
                           manager.poll_private_authorization, lambda: manager.upload_diagnostic_report({}),
                           lambda: manager.set_preferences(True, True, 60, "private")):
                with self.assertRaises(RuntimeError):
                    action()
            auth.access_token.assert_not_called()
            auth.start.assert_not_called()
            auth.disconnect.assert_not_called()
            self.assertEqual(settings.all()["updates_channel"], "private")

    def test_unpublished_public_speech_pack_does_not_request_private_credentials(self):
        public = Mock(installed_version="1.4.1")
        with self.assertRaisesRegex(RuntimeError, "public speech module"):
            speech_release_client(public)
        public._release_client.assert_not_called()
        lab = Mock(installed_version="1.4.1-lab.84")
        speech_release_client(lab)
        lab._release_client.assert_called_once_with("private")

    def test_renderer_setting_and_brightness_are_not_migrated_by_ui_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"lab58_ux_enabled": False, "faceplate_brightness": 70}))
            settings = SettingsStore(str(path))
            self.assertFalse(settings.all()["lab58_ux_enabled"])
            self.assertEqual(settings.all()["faceplate_brightness"], 70)
