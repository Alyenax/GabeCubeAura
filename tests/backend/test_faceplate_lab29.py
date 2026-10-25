"""Lab 29 — serial exclusivity, power safety and explicit plugin handoff."""
import errno
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signalbar import faceplate_claim
from signalbar.faceplate import protocol
from signalbar.faceplate.coordinator import (
    FaceplateCoordinator, verify_faceplate_power,
)
from signalbar.faceplate.transport import Link, LinkBusy, LinkError

ROOT = Path(__file__).resolve().parents[2]


class Reply:
    def __init__(self, status):
        self.status = status


class FakeLink:
    def __init__(self, commands, port=None, log=None):
        self.commands = commands
        self.brightness = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def command(self, value, timeout=1.0, retries=3):
        self.commands.append(value)
        return Reply(1)

    def write(self, value):
        self.brightness.append(value)


class Lab29Tests(unittest.TestCase):
    def test_brightness_diagnostic_distinguishes_target_from_last_usb_command(self):
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ROOT / "assets/faceplate", Path(folder) / "state.json",
                port_finder=lambda: None,
            )
            coordinator.configure(True, 100)
            diagnostic = coordinator.cached_status()["brightness_control"]
            self.assertEqual(diagnostic["target_percent"], 100)
            self.assertEqual(diagnostic["limit_reason"], "none")
            self.assertIsNone(diagnostic["last_commanded_percent"])
            link = FakeLink([])
            coordinator._write_brightness(link, 50)
            # A later target can change before any USB command is sent.
            coordinator.displayed_peak_load = .25
            diagnostic = coordinator.cached_status()["brightness_control"]
            self.assertEqual(diagnostic["requested_percent"], 100)
            self.assertEqual(diagnostic["target_percent"], 100)
            self.assertEqual(diagnostic["last_commanded_percent"], 50)
            self.assertEqual(diagnostic["limit_reason"], "none")
            self.assertFalse(diagnostic["command_acknowledged"])

    def test_non_faceplate_reply_is_rejected(self):
        class Unknown:
            def command(self, *_args, **_kwargs):
                return Reply(2)
        with self.assertRaisesRegex(LinkError, "rejected"):
            verify_faceplate_power(Unknown())

    def test_unresponsive_ch340_is_not_sent_brightness(self):
        class Silent(FakeLink):
            def command(self, value, timeout=1.0, retries=3):
                raise LinkError("no reply")
        values = []
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ROOT / "assets/faceplate", Path(folder) / "state.json",
                link_factory=lambda **kw: values.append(Silent([], **kw)) or values[-1],
                port_finder=lambda: "/dev/ttyUSB0",
            )
            coordinator.configure(True, 100)
            result = coordinator.set_brightness(100)
        self.assertFalse(result["ok"])
        self.assertFalse(values[0].brightness)

    def test_unknown_stored_image_uses_requested_brightness_without_a_load_scan(self):
        values = []
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ROOT / "assets/faceplate", Path(folder) / "state.json",
                link_factory=lambda **kw: values.append(FakeLink([], **kw)) or values[-1],
                port_finder=lambda: "/dev/ttyUSB0",
            )
            coordinator.configure(True, 100)
            result = coordinator.set_brightness(100)
        self.assertTrue(result["ok"])
        self.assertEqual(result["effective_brightness"], 100)
        self.assertEqual(values[0].brightness, [protocol.brightness(100)])

    def test_power_event_wait_is_bounded_during_in_flight_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(
                ROOT / "assets/faceplate", Path(folder) / "state.json",
                port_finder=lambda: "/dev/ttyUSB0",
            )
            # A real lock held by another operation mimics a long GIF commit.
            coordinator.lock.acquire()
            try:
                with patch("signalbar.faceplate.coordinator.POWER_EVENT_LOCK_TIMEOUT_SECONDS", 0.005):
                    result = coordinator.set_power(False, "sleep")
            finally:
                coordinator.lock.release()
        self.assertFalse(result["ok"])
        self.assertIn("deferred", result["error"])

    def test_claim_is_pid_bound_and_released(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(faceplate_claim.claim(folder))
            path = Path(folder) / faceplate_claim.CLAIM_FILENAME
            self.assertEqual(json.loads(path.read_text())["pid"], os.getpid())
            faceplate_claim.release(folder)
            self.assertFalse(path.exists())

    def test_release_cannot_delete_another_process_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / faceplate_claim.CLAIM_FILENAME
            path.write_text(json.dumps({"plugin": "GabeCubeAura", "pid": os.getpid()+1}))
            faceplate_claim.release(folder)
            self.assertTrue(path.exists())

    def test_exclusive_lock_failure_closes_descriptor(self):
        with patch("signalbar.faceplate.transport.port_owner_details", return_value=[]), \
             patch("signalbar.faceplate.transport.os.open", return_value=42), \
             patch("signalbar.faceplate.transport.os.close") as close, \
             patch("signalbar.faceplate.transport.fcntl.flock",
                   side_effect=BlockingIOError(errno.EWOULDBLOCK, "busy")):
            with self.assertRaises(LinkBusy):
                Link(port="/dev/ttyUSB0").open()
        close.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
