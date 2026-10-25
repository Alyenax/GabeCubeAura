"""Lab 30 — lossless orientation of complete 64 x 54 GIF animations."""
import io
import unittest

from signalbar.faceplate import gif
from signalbar.faceplate.gif_transform import GifTransformError, rotate_gif

try:
    from PIL import Image
except ImportError:
    Image = None

W, H = 64, 54
PALETTE = [(i, (i * 3) & 255, (i * 7) & 255) for i in range(256)]


def make_frames(count):
    return [bytes(((x + y * 3 + n * 17) & 255
                  for y in range(H) for x in range(W))) for n in range(count)]


class GifRotationTests(unittest.TestCase):
    def test_rejects_malformed_or_partial_gif(self):
        for bad in (b"", b"GIF89a", b"GIF89a" + bytes(100)):
            with self.subTest(bad=bad[:10]), self.assertRaises(GifTransformError):
                rotate_gif(bad)

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_rotates_every_animated_frame_and_preserves_timing(self):
        for count in (1, 2, 8, 40, 80, 192):
            with self.subTest(frames=count):
                frames = make_frames(count)
                original = gif.encode(W, H, PALETTE, frames,
                                      delay_cs=[10 + n for n in range(count)],
                                      loop=count > 1)
                rotated = rotate_gif(original)
                with Image.open(io.BytesIO(rotated)) as im:
                    self.assertEqual(im.n_frames, count)
                    for n, frame in enumerate(frames):
                        im.seek(n)
                        self.assertEqual(
                            im.convert("RGB").tobytes(),
                            b"".join(bytes(PALETTE[pixel])
                                     for pixel in frame[::-1]),
                        )
                        if count > 1:
                            self.assertEqual(im.info.get("duration"), (10 + n) * 10)

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_two_rotations_restore_pixels(self):
        frames = make_frames(3)
        original = gif.encode(W, H, PALETTE, frames, delay_cs=10)
        double = rotate_gif(rotate_gif(original))
        with Image.open(io.BytesIO(double)) as im:
            for i, frame in enumerate(frames):
                im.seek(i)
                self.assertEqual(
                    im.convert("RGB").tobytes(),
                    b"".join(bytes(PALETTE[pixel]) for pixel in frame),
                )

    def test_rejects_frames_beyond_the_native_animation_budget(self):
        original=gif.encode(W,H,PALETTE,make_frames(193),delay_cs=12)
        with self.assertRaisesRegex(GifTransformError,'too many GIF frames'):
            rotate_gif(original)


if __name__ == "__main__":
    unittest.main()
