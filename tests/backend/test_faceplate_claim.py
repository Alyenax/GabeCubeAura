from __future__ import annotations

import json
import os
import tempfile
import unittest

from signalbar import faceplate_claim


class FaceplateClaimTests(unittest.TestCase):
    def test_claim_names_this_process_and_release_removes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(faceplate_claim.claim(tmp))
            path = os.path.join(tmp, faceplate_claim.CLAIM_FILENAME)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"plugin": "GabeCubeAura", "pid": os.getpid()})
            faceplate_claim.release(tmp)
            self.assertFalse(os.path.exists(path))

    def test_release_leaves_another_process_claim_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, faceplate_claim.CLAIM_FILENAME)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"plugin": "GabeCubeAura", "pid": os.getpid() + 1}, handle)
            faceplate_claim.release(tmp)
            self.assertTrue(os.path.exists(path))

    def test_release_without_claim_and_unwritable_claim_are_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            faceplate_claim.release(tmp)
            blocker = os.path.join(tmp, "file")
            open(blocker, "w").close()
            self.assertFalse(faceplate_claim.claim(os.path.join(blocker, "settings")))


if __name__ == "__main__":
    unittest.main()
