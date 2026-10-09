from __future__ import annotations

import os
import unittest

from signalbar.faceplate import protocol


class Framing(unittest.TestCase):
    def test_known_frame_from_vendor_plugin(self):
        # The stock plugin hard-codes this GIF-begin frame for its rainbow asset.
        expected = bytes.fromhex("445901040008000004A46CEAA0642CF6")
        body = expected[:-2]
        self.assertEqual(protocol.crc16_kermit(body), 0x2CF6)
        self.assertEqual(protocol.frame(1, 4, body[6:]), expected)

    def test_chunks_cover_the_gif(self):
        data = bytes(range(256)) * 5
        chunks = list(protocol.gif_chunks(data))
        self.assertEqual(len(chunks), 3)
        rebuilt = b"".join(c[8:-2] for c in chunks)
        self.assertEqual(rebuilt, data)
        self.assertEqual([int.from_bytes(c[6:8], "big") for c in chunks], [0, 1, 2])

    def test_parse_resyncs_past_junk_and_bad_crc(self):
        good = protocol.frame(1, 2, b"\x00")
        bad = bytearray(protocol.frame(1, 1, b"\x00"))
        bad[-1] ^= 0xFF
        buffer = bytearray(b"\x00\xFF" + bytes(bad) + good + good[:4])
        replies, _junk = protocol.parse(buffer)
        self.assertEqual([(r.kind, r.cmd, r.status) for r in replies], [(1, 2, 0)])
        self.assertEqual(bytes(buffer), good[:4])


if __name__ == "__main__":
    unittest.main()
