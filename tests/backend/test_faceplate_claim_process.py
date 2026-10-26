"""Real Linux directory flock regression tests; no /proc or USB substitutes."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from signalbar import faceplate_claim


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux directory flock")
class ClaimProcessTests(unittest.TestCase):
    def start_writer(self, directory):
        code = (
            "import fcntl,json,os,sys\n"
            f"sys.path.insert(0,{str(Path(faceplate_claim.__file__).resolve().parents[1])!r})\n"
            "from signalbar import faceplate_claim\n"
            "fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY)\n"
            "try:\n"
            " fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
            " print('unlocked',flush=True)\n"
            "except BlockingIOError:\n"
            " print('blocked',flush=True)\n"
            "finally:\n"
            " os.close(fd)\n"
            "assert faceplate_claim.claim(sys.argv[1])\n"
            "print(json.dumps({'claimed':os.getpid()}),flush=True)\n"
            "sys.stdin.readline()\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        return process

    def read_line(self, process):
        buffered = getattr(process, "_reply_buffer", b"")
        while b"\n" not in buffered:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0], "writer timed out")
            data = os.read(process.stdout.fileno(), 4096)
            if not data:
                self.fail("writer exited: " + process.stderr.read())
            buffered += data
        line, process._reply_buffer = buffered.split(b"\n", 1)
        return line.decode().strip()

    def test_release_cannot_unlink_replacement_claim_from_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(faceplate_claim.claim(directory))
            path = Path(directory) / faceplate_claim.CLAIM_FILENAME
            original_remove = os.remove
            writers = []
            def remove_after_replacement_attempt(target):
                # Run a replacement backend after the old PID check, before
                # unlink. It must wait on the actual kernel directory lock.
                writer = self.start_writer(directory)
                writers.append(writer)
                self.assertEqual(self.read_line(writer), "blocked")
                original_remove(target)
            with patch.object(faceplate_claim.os, "remove", side_effect=remove_after_replacement_attempt):
                faceplate_claim.release(directory)
            writer = writers[0]
            replacement = json.loads(self.read_line(writer))["claimed"]
            self.assertIsNone(writer.poll())
            self.assertEqual(json.loads(path.read_text())["pid"], replacement)

    def test_directory_symlink_keeps_existing_behavior_and_shared_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "settings"
            directory.mkdir()
            alias = Path(temporary) / "alias"
            alias.symlink_to(directory, target_is_directory=True)
            mode = directory.stat().st_mode
            self.assertTrue(faceplate_claim.claim(str(alias)))
            with faceplate_claim._directory_lock(str(alias)):
                writer = self.start_writer(directory)
                self.assertEqual(self.read_line(writer), "blocked")
            replacement = json.loads(self.read_line(writer))["claimed"]
            path = directory / faceplate_claim.CLAIM_FILENAME
            self.assertEqual(json.loads(path.read_text())["pid"], replacement)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(directory.stat().st_mode, mode)

    def test_separate_settings_directories_do_not_share_a_process_lock(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with faceplate_claim._directory_lock(first):
                writer = self.start_writer(second)
                self.assertEqual(self.read_line(writer), "unlocked")
                pid = json.loads(self.read_line(writer))["claimed"]
                self.assertEqual(json.loads((Path(second) / faceplate_claim.CLAIM_FILENAME).read_text())["pid"], pid)

    def test_process_death_releases_directory_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            code = (
                "import fcntl,os,sys\n"
                "fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY)\n"
                "fcntl.flock(fd,fcntl.LOCK_EX)\n"
                "print('locked',flush=True)\n"
                "sys.stdin.readline()\n"
            )
            holder = subprocess.Popen([sys.executable, "-c", code, directory],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(self.read_line(holder), "locked")
                writer = self.start_writer(directory)
                self.assertEqual(self.read_line(writer), "blocked")
                holder.kill()
                holder.communicate(timeout=5)
                self.assertIn("claimed", json.loads(self.read_line(writer)))
            finally:
                if holder.poll() is None:
                    holder.kill()
                holder.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
