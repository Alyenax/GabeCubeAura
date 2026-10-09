from __future__ import annotations

import io
import os
import random
import unittest

from signalbar.faceplate import gif

try:
    from PIL import Image
except ImportError:  # the device has no Pillow; run these on a dev box
    Image = None


@unittest.skipIf(Image is None, "Pillow not installed")
class GifRoundTrip(unittest.TestCase):
    W, H = 64, 54

    def decode(self, data, count):
        # Pillow hands back later animation frames as RGB, so compare colours.
        image = Image.open(io.BytesIO(data))
        frames = []
        for index in range(count):
            image.seek(index)
            frames.append(image.convert("RGB").tobytes())
        return frames

    @staticmethod
    def rgb(palette, frame):
        return b"".join(bytes(palette[i]) for i in frame)

    def test_noise_frames(self):
        rng = random.Random(1)
        frames = [bytes(rng.randrange(256) for _ in range(self.W * self.H)) for _ in range(3)]
        data = gif.encode(self.W, self.H, gif.PALETTE_332, frames, delay_cs=5)
        self.assertEqual(self.decode(data, 3), [self.rgb(gif.PALETTE_332, f) for f in frames])

    def test_flat_and_gradient(self):
        frames = [bytes(self.W * self.H), bytes((i * 4) & 0xFF for i in range(self.W * self.H))]
        data = gif.encode(self.W, self.H, gif.PALETTE_332, frames)
        self.assertEqual(self.decode(data, 2), [self.rgb(gif.PALETTE_332, f) for f in frames])

    def test_small_palette(self):
        frame = bytes(i % 3 for i in range(self.W * self.H))
        palette = [(0, 0, 0), (255, 0, 0), (0, 0, 255)]
        data = gif.encode(self.W, self.H, palette, [frame])
        self.assertEqual(self.decode(data, 1), [self.rgb(palette, frame)])

    def test_table_overflow_resets(self):
        # Large noisy single frame forces the 4096-code clear path.
        rng = random.Random(7)
        w, h = 200, 200
        frame = bytes(rng.randrange(256) for _ in range(w * h))
        data = gif.encode(w, h, gif.PALETTE_332, [frame])
        self.assertEqual(self.decode(data, 1), [self.rgb(gif.PALETTE_332, frame)])


class Quantize(unittest.TestCase):
    def test_few_colours_are_exact(self):
        rgb = bytes([255, 0, 0, 0, 0, 255] * 1728)
        palette, indices = gif.quantize(rgb)
        self.assertEqual(sorted(palette), [(0, 0, 255), (255, 0, 0)])
        self.assertEqual(b"".join(bytes(palette[i]) for i in indices), rgb)

    def test_many_colours_stay_close(self):
        rng = random.Random(3)
        rgb = bytes(rng.randrange(256) for _ in range(64 * 54 * 3))
        palette, indices = gif.quantize(rgb)
        self.assertLessEqual(len(palette), 256)
        worst = max(abs(palette[i][k] - rgb[3 * n + k]) for n, i in enumerate(indices) for k in range(3))
        self.assertLess(worst, 128)

    def test_speed(self):
        import time
        rng = random.Random(4)
        rgb = bytes(rng.randrange(256) for _ in range(64 * 54 * 3))
        started = time.perf_counter()
        gif.quantize(rgb)
        self.assertLess(time.perf_counter() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
