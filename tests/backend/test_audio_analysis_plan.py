"""Numerical compatibility checks against the pre-plan radix-2 calculation."""
import math
import random
import struct
import unittest
from unittest.mock import patch

from signalbar.providers import audio_sync as audio


def legacy_fft(values):
    result = [complex(value, 0.0) for value in values]
    size = len(result)
    j = 0
    for index in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if index < j:
            result[index], result[j] = result[j], result[index]
    length = 2
    while length <= size:
        angle = -2.0 * math.pi / length
        root = complex(math.cos(angle), math.sin(angle))
        for start in range(0, size, length):
            factor = complex(1.0, 0.0)
            half = length // 2
            for offset in range(half):
                even = result[start + offset]
                odd = factor * result[start + offset + half]
                result[start + offset] = even + odd
                result[start + offset + half] = even - odd
                factor *= root
        length <<= 1
    return result


def bits(values):
    return b"".join(struct.pack(">dd", complex(value).real, complex(value).imag)
                    for value in values)


class AnalysisPlanTests(unittest.TestCase):
    def test_fft_and_blackman_keep_exact_arithmetic_including_signed_zero(self):
        rng = random.Random(261)
        vectors = [[0.0] * audio.FFT_SIZE, [-0.0] * audio.FFT_SIZE,
                   [1.0] + [0.0] * (audio.FFT_SIZE - 1)]
        vectors += [[rng.uniform(-1, 1) for _ in range(audio.FFT_SIZE)] for _ in range(8)]
        for values in vectors:
            self.assertEqual(bits(audio.AudioSyncProcessor._fft(values)), bits(legacy_fft(values)))
            expected = [sample * (0.42 - 0.5 * math.cos(2.0 * math.pi * i / (audio.FFT_SIZE - 1))
                                  + 0.08 * math.cos(4.0 * math.pi * i / (audio.FFT_SIZE - 1)))
                        for i, sample in enumerate(values)]
            self.assertEqual(bits(audio.AudioSyncProcessor._blackman(values)), bits(expected))

    def test_small_inputs_and_iterators_retain_legacy_behavior(self):
        for size in (0, 1, 2, 4, 16, 256, audio.FFT_SIZE):
            values = [(-1.0 if i % 2 else .25) for i in range(size)]
            self.assertEqual(bits(audio.AudioSyncProcessor._fft(iter(values))), bits(legacy_fft(values)))
            self.assertEqual(bits(audio.AudioSyncProcessor._blackman(iter(values))),
                             bits(audio.AudioSyncProcessor._blackman(values)))

    def test_reusing_plan_does_not_reuse_samples_or_recompute_trigonometry(self):
        audio.AudioSyncProcessor._fft([0.0] * audio.FFT_SIZE)
        values = [1.0] + [0.0] * (audio.FFT_SIZE - 1)
        expected = bits(legacy_fft(values))
        with patch.object(audio.math, "cos", side_effect=AssertionError("recomputed cosine")), \
                patch.object(audio.math, "sin", side_effect=AssertionError("recomputed sine")):
            self.assertEqual(bits(audio.AudioSyncProcessor._fft(values)), expected)
            self.assertEqual(len(audio.AudioSyncProcessor._blackman(values)), audio.FFT_SIZE)


if __name__ == "__main__":
    unittest.main()
