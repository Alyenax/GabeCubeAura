"""Exercise explicit artwork Apply through Decky, route queue and receipt."""

import asyncio
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from signalbar.backend import Engine
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.steamgriddb import DASHBOARD_PACK_REVISION, SteamGridDBFaceplate
from signalbar.faceplate import protocol
from signalbar.faceplate import FaceplateRevisionConflict
from signalbar.faceplate.transport import GifCommitUnconfirmed
from signalbar.models import GameState
from signalbar.settings import SettingsStore


class ArtworkActivationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        with patch.dict(sys.modules, {"decky": types.ModuleType("decky")}):
            spec = importlib.util.spec_from_file_location(
                "lab103_artwork_rpc", Path(__file__).resolve().parents[2] / "main.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.plugin = module.Plugin()
        self.library = SteamGridDBFaceplate(self.root / "library")
        self.faceplate = FaceplateCoordinator(
            self.root / "assets", self.root / "panel.json", steamgriddb=self.library,
            port_finder=Mock(return_value="/test/faceplate"),
        )
        settings = SettingsStore(str(self.root / "settings.json"))
        settings.update({"faceplate_lab_enabled": True, "signalbar_enabled": True,
                         "faceplate_brightness": 81, "steam_control_enabled": True})
        self.engine = Engine(settings, str(self.root / "cache"), faceplate=self.faceplate)
        self.addCleanup(self.engine.stop)
        self.engine._game = GameState(620, "Prepared game")
        self.engine.assistant = Mock(active=False)
        self.engine._faceplate_continuity = Mock(return_value=("", False))
        self.engine._faceplate_artwork_dashboard_facts = Mock(return_value={})
        self.engine._write_faceplate_runtime_status = Mock()
        self.engine.status = Mock(return_value={"faceplate": {"phase": "queued"}})
        self.engine.faceplate_worker = Mock()
        self.engine.faceplate_worker.status.return_value = {"busy": False, "queued": False}
        self.engine.faceplate_worker.submit.return_value = 11
        self.engine.faceplate.synchronize_artwork = Mock()
        self.engine.faceplate.synchronize_scene = Mock()
        self.plugin.engine = self.engine
        self.plugin.diagnostics = Mock()
        self.plugin.faceplate_artwork_jobs = Mock()
        self.plugin.faceplate_artwork_jobs.status.return_value = {"state": "ready"}
        self.before = settings.all()

    def prepare(self, mode="static", draft=False, dashboard=True, colour=(30, 100, 160)):
        root = self.library._prepared_root(620, mode, draft=draft)
        root.mkdir(parents=True, exist_ok=True)
        rgb = bytes(colour) * (64 * 54)
        gif = encode_frame(rgb)
        count = 3 if mode != "static" else 1
        manifest = {"schema": 2, "appid": 620, "mode": mode, "ready": True,
                    "sha256": hashlib.sha256(gif).hexdigest(), "frames": count}
        (root / "faceplate.gif").write_bytes(gif)
        if dashboard:
            pack = rgb * count
            (root / "artwork-dashboard.rgb").write_bytes(pack)
            manifest.update({"dashboard_pack": "artwork-dashboard.rgb",
                             "dashboard_pack_frames": count,
                             "dashboard_pack_sha256": hashlib.sha256(pack).hexdigest(),
                             "dashboard_pack_revision": DASHBOARD_PACK_REVISION})
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest, gif

    def assert_bar_untouched(self):
        after = self.engine.settings.all()
        for key in ("signalbar_enabled", "steam_control_enabled", "home_display",
                    "game_display", "faceplate_brightness", "light_bar_day_brightness"):
            self.assertEqual(self.before[key], after[key], key)
        self.engine.faceplate.synchronize_scene.assert_not_called()
        self.engine.faceplate.synchronize_artwork.assert_not_called()
        self.plugin.faceplate_artwork_jobs.start.assert_not_called()

    def test_static_apply_selects_actual_prepared_content_and_queues_once_in_game(self):
        manifest, gif = self.prepare(draft=True)
        result = asyncio.run(self.plugin.activate_faceplate_artwork(
            620, "static", True, manifest["sha256"], "artwork",
        ))
        self.assertEqual(result["appid"], 620)
        self.assertEqual(self.library.selected(620)[0], gif)
        self.assertEqual(self.engine.faceplate_preferences.read().game_scene, "artwork")
        self.engine.faceplate_worker.submit.assert_called_once()
        payload = self.engine.faceplate_worker.submit.call_args.args[1]
        self.assertEqual((payload["kind"], payload["appid"]), ("artwork", 620))
        self.assert_bar_untouched()

    def test_prepared_animation_apply_does_not_decode_or_generate_in_game(self):
        manifest, gif = self.prepare("animated", draft=True)
        with patch.object(self.library, "prepare_choice", side_effect=AssertionError("no decoder")), \
                patch.object(self.library, "_download_to", side_effect=AssertionError("no download")):
            asyncio.run(self.plugin.activate_faceplate_artwork(
                620, "animated", True, manifest["sha256"], "artwork-dashboard",
            ))
        self.assertEqual(self.library.selected(620)[0], gif)
        self.assertEqual(self.engine.faceplate_preferences.read().game_scene, "artwork-dashboard")
        self.assertEqual(self.engine.faceplate_worker.submit.call_args.args[1]["kind"], "artwork-dashboard")
        self.engine.faceplate_worker.submit.assert_called_once()
        self.assert_bar_untouched()

    def test_home_only_assignment_preserves_game_route_and_full_frame_pack(self):
        self.engine.faceplate_preferences.update(game_scene="weather")
        manifest, _ = self.prepare("animated", draft=True)
        asyncio.run(self.plugin.assign_faceplate_dashboard_artwork(
            620, "animated", True, True, manifest["sha256"],
        ))
        preferences = self.engine.faceplate_preferences.read()
        self.assertEqual((preferences.home_scene, preferences.game_scene), ("artwork-dashboard", "weather"))
        self.assertFalse((self.library.artwork_root / "620" / "active.json").exists())
        home = self.library.home_dashboard_manifest(620)
        self.assertEqual(home["dashboard_pack_frames"], manifest["dashboard_pack_frames"])
        self.assertEqual(home["dashboard_pack_sha256"], manifest["dashboard_pack_sha256"])
        self.assertEqual(self.engine.faceplate_router.status()["desired_scene"], "weather")
        # Missing weather now queues the neutral scene, never the artwork
        # assigned exclusively to Home. The game route is still Weather.
        self.engine.faceplate_worker.submit.assert_called_once()
        fallback = self.engine.faceplate_worker.submit.call_args.args[1]
        self.assertEqual(fallback['kind'], 'weather')
        self.assertTrue(fallback['weather_unavailable'])
        self.assertNotIn('appid', fallback)
        self.assert_bar_untouched()

    def test_both_dashboard_assignment_selects_game_dashboard_immediately(self):
        self.engine.faceplate_preferences.update(home_scene="dashboard", game_scene="weather")
        manifest, _ = self.prepare(draft=True)
        asyncio.run(self.plugin.assign_faceplate_dashboard_artwork(
            620, "static", True, False, manifest["sha256"],
        ))
        preferences = self.engine.faceplate_preferences.read()
        self.assertEqual((preferences.home_scene, preferences.game_scene), ("artwork-dashboard", "artwork-dashboard"))
        self.assertEqual(self.engine.settings.all()["faceplate_dashboard_home_appid"], 620)
        self.assertEqual(self.engine.faceplate_worker.submit.call_args.args[1]["kind"], "artwork-dashboard")
        self.engine.faceplate_worker.submit.assert_called_once()
        self.assert_bar_untouched()

    def test_disabled_or_assistant_priority_is_not_overridden_by_apply(self):
        self.prepare()
        for paused in ("global-off", "assistant", "suspended"):
            self.engine.faceplate_worker.submit.reset_mock()
            self.engine.settings.update({"signalbar_enabled": paused != "global-off"})
            self.engine.assistant.active = paused == "assistant"
            self.engine._faceplate_suspended = paused == "suspended"
            asyncio.run(self.plugin.activate_faceplate_artwork(620, "static"))
            self.engine.faceplate_worker.submit.assert_not_called()
        self.engine.faceplate.synchronize_scene.assert_not_called()

    def test_stale_or_busy_draft_does_not_activate_or_select_scene(self):
        manifest, _ = self.prepare(draft=True)
        original = self.engine.faceplate_preferences.read()
        for state, sha in (("running", manifest["sha256"]), ("ready", "stale")):
            self.plugin.faceplate_artwork_jobs.status.return_value = {"state": state}
            with self.assertRaises(ValueError):
                asyncio.run(self.plugin.activate_faceplate_artwork(620, "static", True, sha))
        self.assertEqual(self.engine.faceplate_preferences.read(), original)
        self.assertIsNone(self.library.selected(620))
        self.engine.faceplate_worker.submit.assert_not_called()

    def test_dashboard_without_prepared_pack_is_not_silently_applied(self):
        self.prepare(dashboard=False)
        with self.assertRaisesRegex(ValueError, "Prepare"):
            asyncio.run(self.plugin.activate_faceplate_artwork(
                620, "static", presentation="artwork-dashboard",
            ))
        self.engine.faceplate_worker.submit.assert_not_called()
        self.assertIsNone(self.library.selected(620))

    def test_receipt_poll_is_no_probe_no_media_and_nonblocking_during_usb(self):
        self.assertTrue(self.faceplate.device_status()["available"])
        self.faceplate.phase = "sent-unconfirmed"
        self.faceplate.delivery = {"state": "unconfirmed", "scene": "artwork", "signature": "test"}
        self.faceplate.port_finder.side_effect = AssertionError("no discovery during receipt")
        self.faceplate.steamgriddb.status = Mock(side_effect=AssertionError("no media status"))
        with self.faceplate.lock:
            status = asyncio.run(self.plugin.get_faceplate_delivery_status())
        self.assertEqual(status["delivery"]["state"], "unconfirmed")
        self.assertTrue(status["available"])
        self.assertEqual(status["port"], "/test/faceplate")
        self.assertEqual(status["apply_deferred_reason"], "")
        self.engine.faceplate_worker.submit.assert_not_called()
        self.engine.status.assert_not_called()

    def test_applied_static_reaches_serial_worker_and_receipt_requires_real_ack(self):
        self.faceplate.device_status()
        manifest, gif = self.prepare(draft=True)
        received = []

        class Link:
            last_transfer_timings = {}
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def command(self, *args, **kwargs): return protocol.Reply(1, 1, b"\x01")
            def write(self, *args): pass
            def send_gif(self, data, cancelled=None):
                received.append(data)
                return True

        self.faceplate.link_factory = Link
        self.faceplate.identity_reader = lambda port: 1
        self.faceplate.synchronize_artwork = FaceplateCoordinator.synchronize_artwork.__get__(self.faceplate)
        asyncio.run(self.plugin.activate_faceplate_artwork(620, "static", True, manifest["sha256"]))
        self.assertEqual(received, [])  # Apply returns before the sole USB worker.
        request = self.engine.faceplate_worker.submit.call_args
        result = self.engine._handle_faceplate_scene({"payload": request.args[1], "metadata": request.args[2]})
        self.assertEqual(received, [gif])
        self.assertTrue(result["found"])
        receipt = asyncio.run(self.plugin.get_faceplate_delivery_status())
        self.assertEqual(receipt["delivery"]["state"], "confirmed")
        self.assertTrue(receipt["available"])
        self.assertEqual(receipt["routing"]["preparation"]["state"], "ready")

    def test_missing_final_ack_does_not_claim_applied_or_retry_selection(self):
        self.prepare()

        class Link:
            last_transfer_timings = {"payload_complete": True, "end_sent": True}
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def command(self, *args, **kwargs): return protocol.Reply(1, 1, b"\x01")
            def write(self, *args): pass
            def send_gif(self, data, cancelled=None): raise GifCommitUnconfirmed("final reply missing")

        self.faceplate.link_factory = Link
        self.faceplate.identity_reader = lambda port: 1
        self.faceplate.synchronize_artwork = FaceplateCoordinator.synchronize_artwork.__get__(self.faceplate)
        asyncio.run(self.plugin.activate_faceplate_artwork(620, "static"))
        request = self.engine.faceplate_worker.submit.call_args
        result = self.engine._handle_faceplate_scene({"payload": request.args[1], "metadata": request.args[2]})
        self.assertTrue(result["sent_unconfirmed"])
        receipt = asyncio.run(self.plugin.get_faceplate_delivery_status())
        self.assertEqual(receipt["routing"]["preparation"]["state"], "unconfirmed")
        self.assertFalse(receipt["last_synchronized"])
        self.assertEqual(self.faceplate.writes_session, 0)
        self.assertEqual(self.engine._reconcile_faceplate(), 0)
        self.engine.faceplate_worker.submit.assert_called_once()

    def test_route_revision_conflict_is_not_reported_as_applied(self):
        self.prepare()
        self.engine.update_faceplate_routing = Mock(side_effect=FaceplateRevisionConflict("route changed"))
        with self.assertRaisesRegex(ValueError, "route changed"):
            asyncio.run(self.plugin.activate_faceplate_artwork(620, "static"))
        self.engine.faceplate_worker.submit.assert_not_called()
        self.plugin.diagnostics.record.assert_called_once_with(
            'faceplate_artwork_apply_failed', appid=620, mode='static',
            destination='game', stage='select-display', error_type='FaceplateRevisionConflict')


if __name__ == "__main__":
    unittest.main()
