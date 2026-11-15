"""Verify the quality and wire size of the same GIF with each profile."""
from io import BytesIO
from random import Random
import unittest

from PIL import Image, ImageSequence

from signalbar.faceplate import gif
from signalbar.faceplate.gif_transform import prepare_gif, rotate_gif


def decode(data):
    with Image.open(BytesIO(data)) as image:
        return image.info.get('loop'), [
            (frame.info['duration'], frame.convert('RGB').tobytes())
            for frame in ImageSequence.Iterator(image)
        ]


class FaceplateGifProfileTests(unittest.TestCase):
    def test_normal_retains_every_frame_and_light_preserves_the_loop_duration(self):
        rng = Random(15)
        palette = [(i, i, i) for i in range(256)]
        frames = [bytes(rng.randrange(64, 128) for _ in range(64 * 54)) for _ in range(24)]
        source = gif.encode(64, 54, palette, frames, delay_cs=(10, 11) * 12)
        normal = prepare_gif(source)
        self.assertLess(len(normal), len(source))
        self.assertEqual(decode(normal), decode(source))
        self.assertEqual(decode(rotate_gif(normal)), decode(rotate_gif(source)))

        light = prepare_gif(source, limit=32767)
        self.assertLess(max(len(light), len(rotate_gif(light))), 32768)
        loop, originals = decode(source)
        light_loop, selected = decode(light)
        self.assertEqual(light_loop, loop)
        self.assertGreater(len(selected), 1)
        self.assertLess(len(selected), len(originals))
        self.assertEqual(sum(delay for delay, _ in selected), 2520)
        remaining = iter(rgb for _, rgb in originals)
        for _, rgb in selected:
            self.assertIn(rgb, remaining)
