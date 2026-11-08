"""Fresh registry guards without blocking the capture consumer."""
import threading
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from signalbar.providers.screen_sync import FRAME_BYTES, ScreenCaptureService, _RegistryPoller


class RegistryPollingTests(unittest.TestCase):
    def until(self, predicate, timeout=.7):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertTrue(predicate())

    def test_slow_read_does_not_block_snapshot_and_publishes_complete_result(self):
        entered, release = threading.Event(), threading.Event()
        def read():
            entered.set()
            release.wait(.6)
            return [{"id": 54}]
        observer = _RegistryPoller(read, [], interval=.005).start()
        try:
            self.assertTrue(entered.wait(.4))
            start = time.monotonic()
            self.assertEqual(observer.snapshot(), ([], 0))
            self.assertLess(time.monotonic() - start, .05)
            release.set()
            self.until(lambda: observer.snapshot()[1] > 0)
            self.assertEqual(observer.snapshot()[0], [{"id": 54}])
        finally:
            release.set()
            self.assertTrue(observer.stop())

    def test_registry_failure_is_not_an_empty_graph(self):
        entered = threading.Event()
        def read():
            entered.set()
            raise OSError("unavailable")
        observer = _RegistryPoller(read, [{"id": 54}], interval=.005).start()
        try:
            self.assertTrue(entered.wait(.4))
            self.until(lambda: not observer._thread.is_alive())
            with self.assertRaisesRegex(RuntimeError, "registry check failed"):
                observer.snapshot()
        finally:
            self.assertTrue(observer.stop())

    def test_stale_graph_fails_closed_and_preview_change_preserves_inflight_grace(self):
        now = [100.]
        observer = _RegistryPoller(lambda: [], [], clock=lambda: now[0])
        now[0] += 3
        observer.set_interval(.5)
        self.assertEqual(observer.snapshot(), ([], 0))
        now[0] += 1.3
        with self.assertRaisesRegex(RuntimeError, "stopped responding"):
            observer.snapshot()

    def test_preview_wakes_existing_wait_and_shutdown_discards_late_results(self):
        entered, release = threading.Event(), threading.Event()
        def read():
            entered.set()
            release.wait(.6)
            return [{"id": 54}]
        observer = _RegistryPoller(read, [], interval=2).start()
        try:
            observer.set_interval(.005)
            self.assertTrue(entered.wait(.4))
            self.assertFalse(observer.stop(timeout=.001))
            release.set()
            self.assertTrue(observer.stop())
            self.assertEqual(observer.snapshot(), ([], 0))
        finally:
            release.set()
            observer.stop()

    def test_idle_shutdown_wakes_without_waiting_for_poll_interval(self):
        observer = _RegistryPoller(lambda: [], []).start()
        start = time.monotonic()
        self.assertTrue(observer.stop())
        self.assertLess(time.monotonic() - start, .2)

    def supervise_registry(self, fail=False):
        children, observers = [], []
        recording_started = threading.Event()
        def popen(command, **kwargs):
            child = subprocess.Popen(command, **kwargs)
            children.append(child)
            return child
        def factory(*args, **kwargs):
            observer = _RegistryPoller(*args, **kwargs)
            observers.append(observer)
            return observer
        service = ScreenCaptureService(popen=popen, registry_factory=factory)
        command = [sys.executable, "-c", "import os,time; "
                   f"[(os.write(1, bytes({FRAME_BYTES})),time.sleep(.05)) for _ in range(160)]"]
        def registry(_runtime):
            if fail:
                raise OSError("registry disappeared")
            recording_started.set()
            return [{"id": 80 + i, "type": "PipeWire:Interface:Link", "info": {
                "state": "active", "output-node-id": 54, "input-node-id": 70 + i,
            }} for i in range(2)]
        def discover():
            # Rediscovery after releasing our consumer must still see the
            # recorder, rather than incorrectly claiming the graph is empty.
            recorder = [{"id": 81, "type": "PipeWire:Interface:Link",
                         "info": {"state": "active", "output-node-id": 54, "input-node-id": 71}}]
            return "/private/tmp", (54, "fixture"), recorder if recording_started.is_set() else []
        try:
            with patch("signalbar.providers.screen_sync.shutil.which", return_value=sys.executable), \
                    patch.object(service, "_cleanup_orphan_captures", return_value=0), \
                    patch.object(service, "_discover_gamescope_node", side_effect=discover), \
                    patch.object(service, "_command_for_runtime", side_effect=lambda cmd, _: (cmd, "fixture")), \
                    patch.object(service, "_capture_command", return_value=command), \
                    patch.object(service, "_pipewire_dump", side_effect=registry):
                service.set_active(True)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    status = service.status()
                    # Failure evidence is recorded before the capture child is
                    # reaped. Wait for the completed release, not that earlier
                    # observation, before asserting the shutdown counters.
                    done = (bool(status["recent_failures"]) and status["capture_sessions_released"] >= 1
                            if fail else status["phase"] == "conflict")
                    if done:
                        break
                    time.sleep(.005)
                self.assertGreater(service.latest()[1], 4)
                if fail:
                    self.assertTrue(status["recent_failures"])
                    self.assertEqual(status["recent_failures"][-1]["failure"], "capture-error")
                    self.assertGreaterEqual(status["capture_sessions_released"], 1)
                else:
                    self.assertEqual(status["phase"], "conflict")
                    self.assertEqual(status["conflicting_consumers"], 1)
                service.stop(timeout=3)
        finally:
            service.stop(timeout=3)
        self.assertTrue(all(child.poll() is not None for child in children))
        self.assertTrue(all(observer._thread is None or not observer._thread.is_alive() for observer in observers))

    def test_existing_supervisor_stops_for_new_conflicting_consumer(self):
        self.supervise_registry()

    def test_existing_supervisor_releases_capture_after_registry_failure(self):
        self.supervise_registry(fail=True)


if __name__ == "__main__":
    unittest.main()
