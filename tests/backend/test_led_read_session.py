"""Descriptor lifecycle and fresh ownership reads on replaceable fixtures."""
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.hardware import ValveLedHardware
from signalbar.models import normalize_frame
from signalbar.renderer.renderer import Renderer


class LedReadSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = []
        for i in range(17):
            path = Path(self.directory.name) / f"valve-leds[{i}]"
            path.mkdir()
            (path / "multi_intensity").write_text("0 0 0")
            (path / "brightness").write_text("255")
            self.paths.append(str(path))
        self.first = Path(self.paths[0])
        for name, value in [("effect", "normal"), ("enabled", "1"), ("brightness_scale", "91")]:
            (self.first / name).write_text(value)
        self.hardware = ValveLedHardware(self.paths, cache_reads=True)
        self.addCleanup(self.hardware.close_read_handles)
        self.blue = normalize_frame([(0, 0, 255)] * 17)

    def assert_handles_closed(self, descriptors):
        self.assertFalse(self.hardware._read_handles)
        for descriptor in descriptors:
            with self.assertRaises(OSError) as error:
                os.fstat(descriptor)
            self.assertEqual(error.exception.errno, errno.EBADF)

    def test_repeated_reads_are_fresh_non_inheritable_and_bounded(self):
        self.hardware.begin_read_session()
        self.hardware.read_signature()
        descriptors = [entry[0] for entry in self.hardware._read_handles.values()]
        self.assertEqual(len(descriptors), 37)
        self.assertTrue(all(not os.get_inheritable(fd) for fd in descriptors))
        with patch("signalbar.hardware.valve_leds.os.open", side_effect=AssertionError("reopened")):
            (self.first / "brightness_scale").write_text("72")
            self.assertEqual(self.hardware.read_brightness_scale(), 72)
            (self.first / "multi_intensity").write_text("1 2 3")
            self.assertEqual(self.hardware.read_signature()[1][0][0], "1 2 3")
        self.hardware.close_read_handles()
        self.assert_handles_closed(descriptors)
        self.assertEqual(self.hardware.read_brightness_scale(), 72)
        self.assertFalse(self.hardware._read_handles)  # status does not reopen a session

    def test_renderer_release_restores_and_closes_then_reclaims(self):
        now = [100.0]
        renderer = Renderer(self.hardware, clock=lambda: now[0])
        renderer.set_output_brightness_scale(34)
        self.assertTrue(renderer.render(self.blue))
        descriptors = [entry[0] for entry in self.hardware._read_handles.values()]
        self.assertEqual(len(descriptors), 37)
        self.assertTrue(renderer.relinquish())
        self.assert_handles_closed(descriptors)
        self.assertEqual((self.first / "brightness_scale").read_text(), "91")
        self.assertEqual((self.first / "effect").read_text(), "normal")
        now[0] += .1
        self.assertTrue(renderer.render(self.blue))
        self.assertTrue(self.hardware._read_handles)
        renderer.relinquish()

    def test_external_priority_and_gain_remain_authoritative(self):
        renderer = Renderer(self.hardware)
        renderer.set_output_brightness_scale(34)
        renderer.render(self.blue)
        (self.first / "effect").write_text("patrol")
        (self.first / "brightness_scale").write_text("72")
        self.assertEqual(self.hardware.native_priority_state(self.hardware.read_signature())[0], "effect")
        self.assertFalse(renderer.relinquish())
        self.assertEqual((self.first / "effect").read_text(), "patrol")
        self.assertEqual((self.first / "brightness_scale").read_text(), "72")
        self.assertFalse(self.hardware._read_handles)

    def test_replacement_permission_change_and_unplug_fail_closed(self):
        for event in ("replace", "permissions", "unlink"):
            with self.subTest(event=event):
                hardware = ValveLedHardware(self.paths, cache_reads=True)
                hardware.begin_read_session()
                hardware.read_signature()
                descriptors = [entry[0] for entry in hardware._read_handles.values()]
                target = self.first / "brightness_scale"
                mode = target.stat().st_mode
                if event == "replace":
                    replacement = self.first / "new"
                    replacement.write_text("91")
                    replacement.replace(target)
                elif event == "permissions":
                    target.chmod(0o600)
                else:
                    target.unlink()
                with self.assertRaises(OSError):
                    hardware.read_brightness_scale()
                self.assertFalse(hardware._read_handles)
                for fd in descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(fd)
                with self.assertRaises(OSError):
                    hardware.begin_read_session()
                target.write_text("91")
                target.chmod(mode)

    def test_read_error_invalidates_all_handles_and_release_keeps_recovery(self):
        journal = Path(self.directory.name) / "recovery.json"
        renderer = Renderer(self.hardware, brightness_recovery_path=str(journal))
        renderer.set_output_brightness_scale(34)
        renderer.render(self.blue)
        descriptors = [entry[0] for entry in self.hardware._read_handles.values()]
        with patch("signalbar.hardware.valve_leds.os.pread", side_effect=OSError(errno.ENODEV, "unplug")):
            with self.assertRaises(OSError):
                self.hardware.read_signature()
        self.assert_handles_closed(descriptors)
        self.assertFalse(renderer.relinquish())
        self.assertTrue(journal.exists())

    def test_mapping_change_closes_old_reads_and_unchanged_frame_skips_writes(self):
        renderer = Renderer(self.hardware)
        renderer.render(self.blue)
        with patch.object(self.hardware, "write_frame", side_effect=AssertionError("duplicate write")):
            self.assertFalse(renderer.render(self.blue))
        descriptors = [entry[0] for entry in self.hardware._read_handles.values()]
        self.hardware.set_reverse(True)
        self.assert_handles_closed(descriptors)
        renderer.relinquish(False)

    def test_bad_attribute_never_returns_old_bytes_and_render_failure_closes(self):
        for payload in (b"", b"x" * 4096, b"\xff"):
            hardware = ValveLedHardware(self.paths, cache_reads=True)
            hardware.begin_read_session()
            hardware.read_signature()
            with patch("signalbar.hardware.valve_leds.os.pread", return_value=payload):
                with self.assertRaises(OSError):
                    hardware.read_signature()
            self.assertFalse(hardware._read_handles)
        renderer = Renderer(self.hardware)
        with patch.object(self.hardware, "write_frame", side_effect=OSError(errno.EIO, "write failed")):
            with self.assertRaises(OSError):
                renderer.render(self.blue)
        self.assertFalse(self.hardware._read_handles)
        self.assertTrue(renderer.failed)

    def test_explicit_sleep_resume_invalidation_keeps_values_uncached(self):
        renderer = Renderer(self.hardware)
        renderer.render(self.blue)
        descriptors = [entry[0] for entry in self.hardware._read_handles.values()]
        renderer.close_read_session()
        self.assert_handles_closed(descriptors)
        (self.first / "brightness_scale").write_text("72")
        self.assertEqual(renderer.calibration_status()["detected_brightness"], 72)
        self.assertFalse(self.hardware._read_handles)
        renderer.relinquish(False)


if __name__ == "__main__":
    unittest.main()
