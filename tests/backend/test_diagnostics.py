import json
from pathlib import Path
import tempfile
import unittest

from signalbar.diagnostics import DiagnosticJournal, MAX_JOURNAL_BYTES


class DiagnosticJournalTests(unittest.TestCase):
    def test_player_city_waiting_and_tls_evidence_survive_private_export(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DiagnosticJournal(directory, '1.4.1-lab.216')
            journal.faceplate_runtime_path.write_text(json.dumps({
                'running': True,
                'routing': {'context': 'game', 'desired_scene': 'player-city', 'effective_scene': 'dashboard'},
                'player_city': {'appid': 367520, 'reason': 'tls_error',
                    'sample': {'appid': 367520, 'state': 'tls_error', 'usable': False,
                        'in_flight': False, 'next_poll_s': 240,
                        'url': 'https://private.invalid', 'path': '/home/deck/private', 'api_key': 'secret'},
                    'displayed': None, 'last_attempt': None},
                'flash_protection': {'player_city': {'retry_after_seconds': 0, 'shared_day_limit': 128}},
            }))
            report = journal.build_report()['report']['faceplate_runtime']
            self.assertEqual(report['routing']['desired_scene'], 'player-city')
            self.assertEqual(report['routing']['effective_scene'], 'dashboard')
            self.assertEqual(report['player_city']['reason'], 'tls_error')
            self.assertEqual(report['player_city']['sample']['appid'], 367520)
            self.assertEqual(report['player_city']['sample']['state'], 'tls_error')
            self.assertEqual(report['player_city']['sample']['next_poll_s'], 240)
            self.assertIsNone(report['player_city']['displayed'])
            self.assertEqual(report['flash_protection']['player_city']['retry_after_seconds'], 0)
            encoded = json.dumps(report)
            for forbidden in ('private.invalid', '/home/deck', 'api_key', 'secret'):
                self.assertNotIn(forbidden, encoded)

    def test_faceplate_brightness_survives_runtime_persistence_and_private_export(self):
        from signalbar.backend import Engine
        from signalbar.settings import SettingsStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = DiagnosticJournal(root, "1.4.1-lab.180")
            engine = Engine(SettingsStore(root / "settings.json"), root / "artwork.json",
                            faceplate_runtime_path=journal.faceplate_runtime_path)
            self.addCleanup(engine.stop)
            engine.faceplate.port_finder = lambda: None
            engine.faceplate.configure(True, 100)
            engine._write_faceplate_runtime_status()
            report = journal.build_report()["report"]["faceplate_runtime"]
            brightness = report["device"]["brightness_control"]
            self.assertEqual(brightness["requested_percent"], 100)
            self.assertEqual(brightness["target_percent"], 100)
            self.assertEqual(brightness["limit_reason"], "none")
            self.assertFalse(brightness["command_acknowledged"])
            self.assertEqual(brightness["estimate_source"], "not-used")
            self.assertNotIn("peak_rgb_load", brightness)
            self.assertNotIn("power_budget", brightness)
            self.assertNotIn("last_commanded_percent", brightness)
            raw = json.loads(journal.faceplate_runtime_path.read_text())
            raw["device"]["brightness_control"]["serial_path"] = "/private-device"
            journal.faceplate_runtime_path.write_text(json.dumps(raw))
            self.assertNotIn("/private-device", json.dumps(journal.build_report()["report"]))

    def test_cinema_probe_details_survive_private_report_redaction(self):
        with tempfile.TemporaryDirectory() as name:
            journal = DiagnosticJournal(name, '1.4.1-lab.128')
            detail = {'code': 'probe_failed', 'stage': 'verifying', 'probe': 'ffmpeg-decoders',
                      'reason': 'missing_capability', 'exit_code': 0, 'elapsed_ms': 57,
                      'missing': ['webp_anim']}
            journal.record('cinema_tools_failure', **detail)
            report = journal.build_report(cinema={'tools': {'last_failure': detail}})['report']
            self.assertEqual(report['cinema']['tools']['last_failure'], detail)
            self.assertEqual(report['events'][-1]['fields']['probe'], 'ffmpeg-decoders')

    def test_cinema_report_redacts_keys_and_personal_paths(self):
        with tempfile.TemporaryDirectory() as name:
            journal = DiagnosticJournal(name, '1.4.1-lab.126')
            report = journal.build_report(cinema={'state': 'complete', 'failed': 2,
                'last_failure': {'code': 'decode_failed', 'stage': 'optimizing_tv'},
                'api_key': 'abcdefghijklmnopqrstuvwxyz1234567890',
                'path': '/home/deck/private/media.webm'})['report']
            self.assertEqual(report['cinema']['failed'], 2)
            self.assertNotIn('abcdefghijklmnopqrstuvwxyz1234567890', json.dumps(report))
            self.assertNotIn('/home/deck', json.dumps(report))

    def test_unclean_restart_is_detected_and_report_is_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "home/deck/.local/state/gabecubeaura"
            first = DiagnosticJournal(root, "1.4.1-lab.16", clock=lambda: 100)
            first.begin_session()
            first.record(
                "steamgriddb_failed",
                api_key="abcdefghijklmnopqrstuvwxyz1234567890",
                detail="Bearer ghu_abcdefghijklmnopqrstuvwx /home/deck/private",
            )

            second = DiagnosticJournal(root, "1.4.1-lab.16", clock=lambda: 200)
            status = second.begin_session()
            report = second.build_report(reason="test")

            self.assertTrue(status["previous_session_unclean"])
            self.assertTrue(status["pending"])
            encoded = json.dumps(report["report"])
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz1234567890", encoded)
            self.assertNotIn("ghu_abcdefghijklmnopqrstuvwx", encoded)
            self.assertNotIn("/home/deck", encoded)
            self.assertIn("[redacted]", encoded)
            self.assertIn("$DECKY_USER_HOME", encoded)
            self.assertEqual(report["report"]["schema"], "gabecubeaura-lab-diagnostic-v1")

    def test_clean_finish_does_not_create_pending_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = DiagnosticJournal(root, "1.4.1-lab.16")
            first.begin_session()
            first.finish_session()
            second = DiagnosticJournal(root, "1.4.1-lab.16")
            status = second.begin_session()
            self.assertFalse(status["previous_session_unclean"])
            self.assertFalse(status["pending"])

    def test_long_event_names_remain_readable_while_fields_stay_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DiagnosticJournal(Path(directory), "1.4.1-lab.16")
            journal.record(
                "pixel_studio_start_requested",
                api_key="abcdefghijklmnopqrstuvwxyz1234567890",
            )
            report = journal.build_report(reason="test")["report"]
            event = report["events"][-1]
            self.assertEqual(event["event"], "pixel_studio_start_requested")
            self.assertEqual(event["fields"]["api_key"], "[redacted]")

    def test_success_deduplicates_the_pending_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = DiagnosticJournal(root, "1.4.1-lab.16")
            first.begin_session()
            second = DiagnosticJournal(root, "1.4.1-lab.16")
            second.begin_session()
            report = second.build_report()
            status = second.upload_succeeded(
                report["session"],
                "https://github.com/Alyenax/GabeCubeAura-Lab/issues/12",
            )
            self.assertFalse(status["pending"])
            self.assertFalse(second.automatic_upload_due())

    def test_journal_is_bounded_by_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DiagnosticJournal(Path(directory), "1.4.1-lab.16")
            journal.begin_session()
            for index in range(700):
                journal.record("large", index=index, detail="pixel studio event " * 38)
            self.assertLessEqual(journal.journal_path.stat().st_size, MAX_JOURNAL_BYTES + 2048)
            self.assertTrue(journal.previous_path.is_file())

    def test_report_includes_safe_faceplate_state_without_serial_path(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = DiagnosticJournal(Path(directory), "1.4.1-lab.18")
            journal.faceplate_runtime_path.write_text(json.dumps({
                "running": True,
                "flash_protection": {
                    "enabled": True, "policy": "precaution-v1", "hour_limit": 120,
                    "session": {"confirmed": 3, "reused": 2, "deferred": 1, "uncertain": 0},
                    "fingerprint": {"sha256": "secret-hash-must-not-escape"},
                    "api_key": "secret-key-must-not-escape",
                    "recent": [{"at": 1234, "scene": "weather", "outcome": "confirmed", "bytes": 3000, "sha256": "secret"}],
                },
                "routing": {
                    "context": "home", "desired_scene": "weather",
                    "effective_scene": "artwork", "generation": 4,
                    "preparation": {"state": "error", "error": "render failed"},
                },
                "worker": {
                    "enabled": True, "last_error": "render failed",
                    "last_queue_age_ms": 18, "ack_ema_ms": 1480,
                    "handler_ema_ms": 1620, "active_generation": 12,
                    "superseded_active": 7,
                },
                "weather": {"phase": "ready", "condition": "rain"},
                "device": {
                    "available": True, "busy": False, "phase": "idle",
                    "port": "/dev/ttyUSB0",
                },
                "uploads": {
                    "session": {"attempts": 4, "writes": 2, "failed": 1},
                    "today_utc": {"date_utc": "2026-10-08", "attempts": 9},
                    "total": {"attempts": 20, "writes": 8},
                    "estimate": {
                        "method": "logical-gif-payload-only",
                        "logical_flash_equivalents": 0.25,
                    },
                    "journal": [{
                        "timestamp_utc": "2026-10-08T10:00:00Z",
                        "reason": "performance:sample", "scene": "performance",
                        "size_bytes": 1234, "ack_ms": 1480,
                        "duration_ms": 1980, "outcome": "written",
                        "sha256": "secret-hash-must-not-escape",
                        "port": "/dev/ttyUSB0",
                    }],
                },
            }), encoding="utf-8")
            report = journal.build_report(
                reason="test",
                faceplate_artwork_job={
                    "state": "failed", "stage": "decode", "percent": 40,
                    "detail": "FFmpeg failed in /home/deck/private/source.webm",
                    "appid": 620, "mode": "animated",
                    "api_key": "abcdefghijklmnopqrstuvwxyz1234567890",
                    "source": "/home/deck/private/source.webm",
                },
            )["report"]

            encoded = json.dumps(report["faceplate_runtime"])
            self.assertEqual(
                report["faceplate_runtime"]["routing"]["desired_scene"], "weather",
            )
            self.assertIn("render failed", encoded)
            self.assertNotIn("ttyUSB", encoded)
            self.assertEqual(
                report["faceplate_runtime"]["worker"]["ack_ema_ms"], 1480,
            )
            self.assertEqual(
                report["faceplate_runtime"]["uploads"]["journal"][0]["outcome"],
                "written",
            )
            self.assertNotIn("sha256", encoded)
            self.assertNotIn("secret-key", encoded)
            self.assertEqual(report["faceplate_runtime"]["flash_protection"]["session"]["confirmed"], 3)
            self.assertEqual(report["faceplate_runtime"]["flash_protection"]["rate"]["hour_limit"], 120)
            self.assertEqual(report["faceplate_artwork_job"]["state"], "failed")
            self.assertIn("$DECKY_USER_HOME", report["faceplate_artwork_job"]["detail"])
            self.assertNotIn("api_key", json.dumps(report["faceplate_artwork_job"]))


if __name__ == "__main__":
    unittest.main()
