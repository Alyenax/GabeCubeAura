"""Real pipe/child supervision and the diagnostic export used by private Labs."""
import json
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from signalbar.arbiter.guard import ManualClock
from signalbar.backend import Engine
from signalbar.diagnostics import DiagnosticJournal
from signalbar.providers.screen_sync import (
    FIRST_FRAME_TIMEOUT_SECONDS, FRAME_BYTES, ScreenCaptureService,
)
from signalbar.settings import SettingsStore


class CaptureEvidenceTests(unittest.TestCase):
    def capture_context(self, service):
        stack = ExitStack()
        stack.enter_context(patch("signalbar.providers.screen_sync.shutil.which", return_value=sys.executable))
        stack.enter_context(patch.object(service, "_cleanup_orphan_captures", return_value=0))
        stack.enter_context(patch.object(service, "_pipewire_dump", return_value=[]))
        stack.enter_context(patch.object(service, "_discover_gamescope_node", return_value=(
            "/run/user/1000", (54, "gamescope"), [{"id": 54, "info": {"state": "idle"}}],
        )))
        stack.enter_context(patch.object(service, "_command_for_runtime", side_effect=lambda cmd, _: (cmd, "test")))
        return stack

    def test_real_child_first_frame_after_old_deadline_stays_on_same_capture(self):
        children = []
        def popen(*args, **kwargs):
            child = subprocess.Popen(*args, **kwargs)
            children.append(child)
            return child
        service = ScreenCaptureService(popen=popen)
        service._active = True
        # Keep the child alive after emitting a complete frame so supervision
        # sees a slow but healthy source, rather than an EOS fixture.
        command = [sys.executable, "-c", "import os,time; time.sleep(1.8); "
                   f"os.write(1,bytes({FRAME_BYTES})); time.sleep(60)"]
        real_select = select.select
        def until_frame(*args):
            if service.latest()[1]:
                service._stop.set()
            return real_select(*args)
        timer = threading.Timer(5.0, service._stop.set)
        timer.start()
        try:
            with self.capture_context(service), \
                    patch.object(service, "_capture_command", return_value=command), \
                    patch("signalbar.providers.screen_sync.select.select", side_effect=until_frame):
                service._supervise()
            self.assertEqual(len(children), 1)
            self.assertEqual(service.latest()[1], 1)
            self.assertGreater(service.status()["attempt"]["first_frame_after_s"], 1.5)
            self.assertEqual(service.status()["capture_sessions_released"], 0)
            self.assertIsNotNone(children[0].poll())
        finally:
            timer.cancel()
            for child in children:
                service._terminate_process(child)
                child.stdout.close()
                child.stderr.close()

    def test_empty_live_pipe_times_out_and_keeps_first_frame_evidence(self):
        clock = ManualClock(100)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = SimpleNamespace(stdout=stdout, stderr=stderr, poll=lambda: None)
            service = ScreenCaptureService(clock=clock, popen=lambda *_a, **_kw: process)
            service._active = True
            def advance(*_args):
                clock.advance(1)
                return [], [], []
            with self.capture_context(service), \
                    patch("signalbar.providers.screen_sync.select.select", side_effect=advance), \
                    patch.object(service, "_pipewire_dump", return_value=[{"id": 54, "info": {"state": "idle"}}]), \
                    patch.object(service, "_terminate_process"), \
                    patch.object(service, "_wait", side_effect=lambda _: service._stop.set()):
                service._supervise()
            failure = service.status()["recent_failures"][-1]
            self.assertEqual(failure["failure"], "first-frame-timeout")
            self.assertGreater(failure["elapsed_s"], FIRST_FRAME_TIMEOUT_SECONDS)
            self.assertEqual(failure["bytes_received"], 0)
            self.assertEqual(failure["frames_received"], 0)
            self.assertIsNone(failure["first_frame_after_s"])
            self.assertIsNone(failure["exit_code"])
            self.assertEqual(failure["producer_state"], "idle")

    def test_failure_history_is_bounded_retained_and_exported_through_real_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = ManualClock(100)
            capture = ScreenCaptureService(clock=clock)
            capture._attempt_started_at = 99
            capture._bytes_seen = FRAME_BYTES + 17
            capture._frames_seen = 1
            capture._first_frame_at = 99.5
            for index in range(5):
                capture._capture_selector = f"test {index}"
                capture._frames_seen = 1
                with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                    process = SimpleNamespace(stdout=stdout, stderr=stderr, poll=lambda: 1)
                    stderr.write(b"ERROR not-negotiated: /home/deck/private/capture token=secretvalue\n")
                    stderr.seek(0)
                    capture._release_failed_capture(process, "Capture ended")
            status = capture.status()
            self.assertEqual(len(status["recent_failures"]), 3)
            self.assertEqual(status["recent_failures"][0]["selector"], "test 2")
            failure = status["recent_failures"][-1]
            self.assertEqual(failure["failure"], "negotiation")
            self.assertEqual(failure["bytes_received"], FRAME_BYTES + 17)
            self.assertEqual(failure["frames_received"], 1)
            self.assertEqual(failure["first_frame_after_s"], 0.5)
            self.assertEqual(failure["exit_code"], 1)
            # A new attempt clears only its local errors; failed selectors keep
            # their own error and counters until the next full retry cycle.
            capture._stderr.clear()
            status["recent_failures"][-1]["stderr_tail"].clear()
            self.assertTrue(capture.status()["recent_failures"][-1]["stderr_tail"])
            engine = Engine(SettingsStore(root / "settings.json"), str(root / "cache"))
            self.addCleanup(engine.stop)
            engine.screen_sync.capture = capture
            journal = DiagnosticJournal(root, "1.4.1-lab.208")
            exported = journal._sanitize(engine.display_control_snapshot())["screen_sync"]
            self.assertEqual(exported["recent_failures"][-1]["failure"], "negotiation")
            self.assertEqual(exported["capture_sessions_released"], 5)
            self.assertIn("not-negotiated", json.dumps(exported))
            self.assertNotIn("/home/deck", json.dumps(exported))
            self.assertNotIn("secretvalue", json.dumps(exported))


if __name__ == "__main__":
    unittest.main()
