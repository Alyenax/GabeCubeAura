"""Test an explicit GIF probe through the real worker and serial packet path."""
from io import BytesIO
import hashlib
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageSequence
from signalbar.backend.engine import Engine
from signalbar.faceplate import gif, protocol
from signalbar.faceplate.gif_probe import EXACT_SIZES_BYTES, SIZES_KIB, build
from signalbar.faceplate.gif_transform import rotate_gif
from signalbar.faceplate.service import FaceplateWorker
from signalbar.support_snapshot import runtime

import test_screensaver_restore148 as fixture


def decoded(data):
    with Image.open(BytesIO(data)) as image:
        return image.info.get("loop"), [
            (f.info.get("duration"), f.convert("RGB").tobytes())
            for f in ImageSequence.Iterator(image)
        ]


class LosslessGifTests(unittest.TestCase):
    def test_global_palette_borrow_preserves_all_pixels_delays_and_loop(self):
        palette = tuple((i, 0, 0) for i in range(256))
        base = bytes(range(256)) * 13 + bytes(range(128))
        update = b"\xff" + base[1:3455] + b"\x00"
        frames = (base, update, update, base)
        before = gif.encode(64, 54, palette, frames, (2, 7, 13, 21))
        after = gif.encode(64, 54, palette, frames, (2, 7, 13, 21), reuse_pixels=True)
        self.assertLess(len(after), len(before))
        self.assertEqual(decoded(before), decoded(after))
        self.assertEqual(decoded(rotate_gif(before)), decoded(rotate_gif(after)))

    def test_every_index_changes_keeps_opaque_path_and_identical_bytes(self):
        palette = tuple((i, i, i) for i in range(4))
        frames = (bytes((0, 1, 2, 3)) * 864, bytes((1, 2, 3, 0)) * 864)
        self.assertEqual(gif.encode(64, 54, palette, frames),
                         gif.encode(64, 54, palette, frames, reuse_pixels=True))

    def test_probes_are_different_sizes_but_the_same_dim_pattern(self):
        reference = None
        previous = 0
        for size in SIZES_KIB:
            data, count = build(size)
            loop, frames = decoded(data)
            self.assertIsNone(loop)
            self.assertEqual(count, len(frames))
            reference = reference or frames[0][1]
            self.assertTrue(all(frame == reference for _, frame in frames))
            self.assertEqual(data, rotate_gif(data))
            self.assertLess(abs(len(data) - size * 1024), 550)
            self.assertGreater(len(data), previous)
            self.assertLess(len(data), protocol.MAX_GIF_BYTES)
            previous = len(data)

    def test_exact_probes_decode_to_identical_frames_and_delays(self):
        data_at_limit, count_at_limit = build(EXACT_SIZES_BYTES[0])
        data_over_limit, count_over_limit = build(EXACT_SIZES_BYTES[1])
        self.assertEqual((len(data_at_limit), len(data_over_limit)), (32768, 32769))
        loop, frames = decoded(data_at_limit)
        self.assertIsNone(loop)
        self.assertEqual(count_at_limit, len(frames))
        self.assertEqual(count_over_limit, len(frames))
        self.assertEqual((loop, frames), decoded(data_over_limit))
        self.assertEqual((loop, frames), decoded(rotate_gif(data_at_limit)))
        self.assertEqual((loop, frames), decoded(rotate_gif(data_over_limit)))


class GifSizeTestWorkerTests(unittest.TestCase):
    def setUp(self):
        self.serial = fixture.Restore148Tests()
        self.serial.setUp()
        self.addCleanup(self.serial.doCleanups)
        engine = Engine.__new__(Engine)
        engine.faceplate = self.serial.coordinator
        engine.settings = SimpleNamespace(all=lambda: {"faceplate_lab_enabled": True})
        engine._faceplate_gif_test_lock = threading.Lock()
        engine._faceplate_gif_tests = []
        engine._faceplate_preview_until = 0
        engine._gif_size_test_allowed = lambda: True
        engine.faceplate_worker = FaceplateWorker(
            lambda req: engine._handle_gif_size_test(req["payload"], req["_cancelled"]),
            enabled=True)
        self.addCleanup(engine.faceplate_worker.stop)
        self.engine = engine

    def test_accepted_stored_and_begin_refused_keep_their_own_evidence(self):
        engine = self.engine
        with patch.object(engine.faceplate.flash, "preflight",
                          wraps=engine.faceplate.flash.preflight) as preflight:
            first = engine.run_faceplate_gif_size_test(1)
            stored = engine.run_faceplate_gif_size_test(1)
            self.serial.panel.refuse_begin = True
            refused = engine.run_faceplate_gif_size_test(56)
        self.assertEqual(first["state"], "confirmed")
        self.assertEqual(stored["state"], "already-stored")
        self.assertEqual(refused["state"], "begin-refused")
        self.assertEqual(self.serial.panel.commits, 1)
        self.assertGreater(preflight.call_count, 0)
        records = runtime(engine)["gif_size_tests"]
        self.assertEqual([r["state"] for r in records],
                         ["confirmed", "already-stored", "begin-refused"])
        wire = records[-1]["transfer"]
        self.assertEqual(refused["size_bytes"], wire["expected_bytes"])
        self.assertEqual((0, 0, False), (wire["begin_status"], wire["chunks"], wire["end_sent"]))

    def test_exact_sizes_reach_usb_with_rotation_and_a_cached_recovery_alias(self):
        engine = self.engine
        engine.faceplate.rotate_180 = True
        at_limit, over_limit = EXACT_SIZES_BYTES
        exact_data, _ = build(at_limit)
        engine.faceplate._restore_alias = (
            hashlib.sha256(exact_data).hexdigest(), rotate_gif(exact_data))
        accepted = engine.run_faceplate_gif_size_test(at_limit)
        self.serial.panel.refuse_begin = True
        refused = engine.run_faceplate_gif_size_test(over_limit)

        self.assertEqual(accepted, {"state": "confirmed", "size_bytes": 32768})
        self.assertEqual(refused, {"state": "begin-refused", "size_bytes": 32769})
        self.assertEqual(self.serial.panel.stored, exact_data)
        self.assertEqual(self.serial.panel.commits, 1)
        begins = [payload for kind, cmd, payload in self.serial.panel.events if (kind, cmd) == (1, 4)]
        self.assertEqual([int.from_bytes(payload[:4], "big") for payload in begins], [32768, 32769])
        records = runtime(engine)["gif_size_tests"]
        self.assertEqual([r["target_bytes"] for r in records], [32768, 32769])
        self.assertEqual([r["transfer"]["expected_bytes"] for r in records], [32768, 32769])
        self.assertGreater(records[0]["transfer"]["chunks"], 0)
        self.assertTrue(records[0]["transfer"]["end_sent"])
        self.assertEqual(records[1]["transfer"]["chunks"], 0)
        self.assertFalse(records[1]["transfer"]["end_sent"])

    def test_explicit_off_or_foreign_owner_never_sends_a_usb_command(self):
        engine = self.engine
        engine.faceplate.powered = False
        self.assertEqual(engine.run_faceplate_gif_size_test(1)["state"], "unavailable")
        self.assertFalse(self.serial.panel.events)
        engine.faceplate.powered = True
        with patch("signalbar.faceplate.coordinator.port_owner_details", return_value=["other process"]):
            self.assertEqual(engine.run_faceplate_gif_size_test(1)["state"], "busy")
        self.assertFalse(self.serial.panel.events)

    def test_admission_does_not_displace_an_active_scene(self):
        active, release = threading.Event(), threading.Event()
        def hold(_):
            active.set()
            release.wait(1)
        self.engine.faceplate_worker.handler = hold
        self.engine.faceplate_worker.submit("existing", {})
        self.addCleanup(release.set)
        self.assertTrue(active.wait(1))
        self.assertEqual(self.engine.run_faceplate_gif_size_test(4)["state"], "busy")
        self.assertFalse(self.serial.panel.events)
