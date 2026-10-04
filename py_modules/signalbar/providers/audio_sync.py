"""Local PipeWire output capture and audio-reactive 17-pixel rendering."""

from __future__ import annotations

import colorsys
import math
import os
import select
import shutil
import struct
import subprocess
import threading
import time
from collections import deque

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame
from signalbar.providers.screen_sync import ScreenCaptureService


SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_BYTES = 2
FFT_SIZE = 2048
ANALYSIS_HOP = 2880
BLOCK_FRAMES = ANALYSIS_HOP
BLOCK_BYTES = BLOCK_FRAMES * CHANNELS * SAMPLE_BYTES
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_BYTES
CAPTURE_LATENCY_MS = 50.0
ANALYSIS_WINDOW_MS = FFT_SIZE / SAMPLE_RATE * 1000.0
ANALYSIS_HOP_MS = ANALYSIS_HOP / SAMPLE_RATE * 1000.0
LED_REQUEST_INTERVAL_MS = 60.0
LED_RENDER_FLOOR_MS = 50.0
MAX_PENDING_BLOCKS = 16
CAPTURE_REVISION = "1.3.2-independent-pattern-palette-v5"

EXPERIMENTAL_STYLES = {
    "velvet-relay", "negative-bloom", "stereo-lanterns",
    "constellation", "slow-prism",
}
HIFI_RENDER_STYLES = {"hifi-crest", *EXPERIMENTAL_STYLES}
VALID_STYLES = {
    *HIFI_RENDER_STYLES, "spectrum", "spatial", "bass",
    "audio-pulse",
}
# Every renderer uses the same rolling programme-level analysis. The name is
# retained because the engine imports it to decide when a contextual Screen
# Sync palette needs a live Gamescope capture.
ADAPTIVE_STYLES = set(VALID_STYLES)
VALID_REACTIVITY = {"calm", "balanced", "fast", "punchy"}
VALID_PALETTES = {
    "aurora", "ember", "magma", "forest", "ice", "copper", "solar",
    "pearl", "glacier", "lagoon", "lime", "orchid", "plasma",
    "sunset", "deep-sea", "silver", "candy", "sapphire", "coastline",
    "screen-sync", "artwork", "custom",
}

PALETTES = {
    "aurora": ((0, 170, 255), (112, 42, 255), (255, 48, 140)),
    "ember": ((255, 162, 28), (255, 72, 18), (178, 18, 80)),
    # Palette tuples follow the optical layout: high-frequency outer edges,
    # mid-frequency shoulders, low-frequency centre.
    "magma": ((255, 255, 46), (255, 173, 41), (255, 4, 0)),
    "forest": ((138, 255, 196), (72, 224, 115), (57, 122, 41)),
    "ice": ((30, 220, 255), (40, 112, 255), (132, 68, 255)),
    "copper": ((255, 210, 122), (246, 154, 60), (185, 90, 42)),
    "solar": ((255, 255, 255), (255, 226, 90), (255, 154, 31)),
    "pearl": ((255, 255, 255), (201, 232, 255), (118, 150, 216)),
    "glacier": ((216, 255, 255), (93, 222, 255), (40, 103, 216)),
    "lagoon": ((183, 255, 245), (33, 215, 192), (8, 125, 145)),
    "lime": ((242, 255, 176), (168, 239, 69), (60, 140, 70)),
    "orchid": ((255, 225, 255), (238, 114, 222), (123, 59, 167)),
    "plasma": ((245, 236, 255), (164, 90, 255), (84, 38, 183)),
    "sunset": ((255, 240, 176), (255, 141, 84), (195, 60, 114)),
    "deep-sea": ((126, 235, 255), (35, 125, 219), (20, 37, 94)),
    "silver": ((255, 255, 255), (199, 208, 218), (95, 104, 117)),
    "candy": ((113, 255, 255), (255, 104, 231), (255, 57, 106)),
    # Physical Steam Machine observations take priority over display previews.
    # Sapphire keeps the cobalt download-like tone that remains clean through
    # the diffuser; Coastline is the brighter cyan shoreline alternative.
    "sapphire": ((99, 135, 233), (78, 118, 228), (78, 118, 228)),
    "coastline": ((11, 94, 142), (8, 127, 191), (26, 159, 255)),
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _lerp_colour(first, second, amount):
    amount = _clamp(float(amount))
    return tuple(int(round(a + (b - a) * amount)) for a, b in zip(first, second))


def _palette_frame(colours):
    first, middle, last = colours
    out = []
    for index in range(LED_COUNT):
        position = index / (LED_COUNT - 1)
        out.append(
            _lerp_colour(first, middle, position * 2.0)
            if position <= 0.5 else
            _lerp_colour(middle, last, (position - 0.5) * 2.0)
        )
    return out


def _mirrored_palette_frame(colours):
    """Build an edge, shoulder, centre, shoulder, edge colour gradient."""
    outer, shoulder, centre = colours
    frame = []
    midpoint = (LED_COUNT - 1) / 2.0
    for index in range(LED_COUNT):
        distance = abs(index - midpoint) / midpoint
        if distance <= 0.5:
            frame.append(_lerp_colour(centre, shoulder, distance * 2.0))
        else:
            frame.append(_lerp_colour(shoulder, outer, (distance - 0.5) * 2.0))
    return frame


def _rgb_to_oklab(colour):
    linear = []
    for channel in colour:
        value = channel / 255.0
        linear.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = linear
    light = (0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1 / 3)
    medium = (0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1 / 3)
    short = (0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1 / 3)
    return (
        0.2104542553 * light + 0.793617785 * medium - 0.0040720468 * short,
        1.9779984951 * light - 2.428592205 * medium + 0.4505937099 * short,
        0.0259040371 * light + 0.7827717662 * medium - 0.808675766 * short,
    )


def _lab_distance(first, second):
    return sum((left - right) ** 2 for left, right in zip(first, second))


def _colour_hls(colour):
    red, green, blue = (channel / 255.0 for channel in colour)
    return colorsys.rgb_to_hls(red, green, blue)


def _hls_colour(hue, lightness, saturation):
    red, green, blue = colorsys.hls_to_rgb(
        hue % 1.0,
        _clamp(lightness),
        _clamp(saturation),
    )
    return tuple(int(round(channel * 255.0)) for channel in (red, green, blue))


def _limited_hue(base, candidate, maximum_shift):
    """Keep a sampled hue near the palette family on the shortest colour arc."""
    delta = (candidate - base + 0.5) % 1.0 - 0.5
    return (base + _clamp(delta, -maximum_shift, maximum_shift)) % 1.0


def _harmonized_optical_palette(colours, weights=None):
    """Turn sampled colours into dark edges, mid shoulders and a light centre.

    Dynamic image palettes are source material, not direct LED assignments. A
    white or black cluster must not take over the centre, and unrelated source
    hues must not create a noisy mirrored rainbow. The strongest useful hue is
    therefore retained as the family anchor, while nearby sampled hues add a
    restrained variation between the three optical roles.
    """
    palette = [tuple(colour) for colour in colours[:3]]
    while len(palette) < 3:
        palette.append(palette[-1] if palette else (112, 42, 255))
    source_weights = list(weights or (1.0,) * len(palette))
    while len(source_weights) < len(palette):
        source_weights.append(1.0)
    hls = [_colour_hls(colour) for colour in palette]

    chromatic = [index for index, (_hue, _light, saturation) in enumerate(hls)
                 if saturation >= 0.12]
    if not chromatic:
        # Preserve a genuinely neutral scene without allowing pure white or
        # black to flatten the optical hierarchy.
        return ((34, 34, 34), (92, 92, 92), (190, 190, 190))

    total_weight = max(1e-6, sum(source_weights))
    centre_index = max(
        chromatic,
        key=lambda index: (
            source_weights[index] / total_weight
            * (0.55 + hls[index][2] * 0.75)
            * (0.72 + (1.0 - abs(hls[index][1] - 0.50) * 2.0) * 0.28)
        ),
    )
    centre_hue = hls[centre_index][0]
    ordered = sorted(
        chromatic,
        key=lambda index: (
            index == centre_index,
            source_weights[index] * (0.45 + hls[index][2]),
        ),
        reverse=True,
    )
    shoulder_index = next((index for index in ordered if index != centre_index), centre_index)
    outer_index = next(
        (index for index in ordered if index not in {centre_index, shoulder_index}),
        shoulder_index,
    )

    # The hue travel is deliberately narrower toward the physical edges. The
    # diffuser then reads as one coherent family instead of three colour blocks.
    shoulder_hue = _limited_hue(centre_hue, hls[shoulder_index][0], 32.0 / 360.0)
    outer_hue = _limited_hue(centre_hue, hls[outer_index][0], 20.0 / 360.0)
    weighted_lightness = sum(
        lightness * weight for (_hue, lightness, _saturation), weight in zip(hls, source_weights)
    ) / total_weight
    centre_lightness = _clamp(0.57 + weighted_lightness * 0.12, 0.59, 0.67)
    shoulder_lightness = centre_lightness - 0.24
    outer_lightness = shoulder_lightness - 0.17

    useful_saturations = [hls[index][2] for index in chromatic]
    source_saturation = sum(useful_saturations) / len(useful_saturations)
    centre_saturation = _clamp(source_saturation * 0.95, 0.54, 0.90)
    shoulder_saturation = _clamp(
        (centre_saturation + hls[shoulder_index][2]) * 0.50,
        0.48,
        0.88,
    )
    outer_saturation = _clamp(
        (shoulder_saturation + hls[outer_index][2]) * 0.50,
        0.42,
        0.84,
    )
    return (
        _hls_colour(outer_hue, outer_lightness, outer_saturation),
        _hls_colour(shoulder_hue, shoulder_lightness, shoulder_saturation),
        _hls_colour(centre_hue, centre_lightness, centre_saturation),
    )


def _percentile(values, amount):
    """Return a linearly interpolated percentile without adding dependencies."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = _clamp(float(amount)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _soft_normalize(value, low, high):
    silence = max(0.00035, low * 0.20)
    if value <= silence:
        return 0.0
    anchor = low * 0.30
    span = max(0.0008, high - anchor)
    linear = _clamp((value - anchor) / span, 0.0, 1.35)
    if linear <= 1.0:
        return linear
    return min(1.18, 1.0 + (1.0 - math.exp(-(linear - 1.0) * 2.2)) * 0.18)


def _three_colour_palette(colours, previous=None):
    """Reduce image samples to three harmonized optical LED roles."""
    samples = []
    for raw in colours:
        colour = tuple(max(0, min(255, int(round(channel)))) for channel in raw)
        red, green, blue = (channel / 255.0 for channel in colour)
        value = max(red, green, blue)
        saturation = 0.0 if value <= 0.0 else (value - min(red, green, blue)) / value
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        if luminance <= 0.018:
            continue
        weight = (0.35 + saturation * 0.65) * (0.55 + min(1.0, value * 1.35) * 0.45)
        samples.append((colour, _rgb_to_oklab(colour), weight))
    if not samples:
        return tuple(previous) if previous and len(previous) == 3 else _harmonized_optical_palette(
            PALETTES["sapphire"],
        )

    first = max(samples, key=lambda sample: sample[2] * (0.6 + math.hypot(sample[1][1], sample[1][2]) * 4.0))
    centroids = [first[1]]
    while len(centroids) < 3:
        centroids.append(max(
            samples,
            key=lambda sample: min(_lab_distance(sample[1], centroid) for centroid in centroids) * sample[2],
        )[1])

    groups = None
    for _iteration in range(8):
        groups = [[] for _centroid in centroids]
        for sample in samples:
            selected = min(
                range(len(centroids)),
                key=lambda index: _lab_distance(sample[1], centroids[index]),
            )
            groups[selected].append(sample)
        for index, group in enumerate(groups):
            if not group:
                continue
            total = sum(sample[2] for sample in group)
            centroids[index] = tuple(
                sum(sample[1][channel] * sample[2] for sample in group) / total
                for channel in range(3)
            )

    palette = []
    for index, group in enumerate(groups or []):
        if not group:
            palette.append(samples[index % len(samples)][0])
            continue
        total = sum(sample[2] for sample in group)
        palette.append(tuple(int(round(
            sum(sample[0][channel] * sample[2] for sample in group) / total
        )) for channel in range(3)))
    while len(palette) < 3:
        palette.append(palette[-1] if palette else samples[0][0])

    weights = [sum(sample[2] for sample in group) for group in (groups or [])]
    return _harmonized_optical_palette(palette, weights)


class AudioSyncProcessor:
    """Analyse stereo S16LE PCM and render stable, expressive LED frames."""

    _SMOOTHING = {
        "calm": (0.30, 0.12),
        "balanced": (0.58, 0.24),
        "fast": (0.82, 0.42),
        # One complete 60 ms analysis block is the fastest meaningful response
        # without changing the PipeWire and renderer cadence.
        "punchy": (1.0, 1.0),
    }
    _HIFI_REACTIVITY = {
        "calm": ((0.45, 0.10), (0.82, 0.12), (0.72, 0.15), (0.72, 0.20), 0.05),
        "balanced": ((0.62, 0.16), (0.95, 0.17), (0.88, 0.22), (0.90, 0.30), 0.08),
        "fast": ((0.78, 0.24), (0.98, 0.25), (0.96, 0.32), (0.97, 0.42), 0.12),
        "punchy": ((1.0, 1.0), (1.0, 1.0), (1.0, 1.0), (1.0, 1.0), 1.0),
    }
    _HIFI_CREST_MOTION = {
        "calm": (0.24, 2.75, 0.52),
        "balanced": (0.24, 2.75, 0.52),
        "fast": (0.24, 2.75, 0.52),
        # Three visible states at the 60 ms cadence: centre, shoulders, edges.
        # A new crest can launch every two blocks without becoming a solid band.
        "punchy": (0.12, 1.0 / 0.12, 0.18),
    }

    def __init__(self, sample_rate=SAMPLE_RATE):
        self.sample_rate = int(sample_rate)
        self._levels = [0.0] * LED_COUNT
        self._left = 0.0
        self._right = 0.0
        self._frame = None
        self._screen_palette = None
        self._reset_hifi()

    def _reset_hifi(self):
        spectrum_size = FFT_SIZE // 2 + 1
        self._hifi_previous_spectrum = [[0.0] * spectrum_size for _channel in range(2)]
        self._hifi_energy_history = {
            key: deque(maxlen=170) for key in ("bass", "mid", "high", "stereo")
        }
        self._hifi_flux_history = {
            key: deque(maxlen=70) for key in ("bass", "mid", "high")
        }
        self._hifi_ranges = {
            "bass": [0.003, 0.09], "mid": [0.003, 0.075],
            "high": [0.0015, 0.045], "stereo": [0.003, 0.08],
        }
        self._hifi_levels = {
            key: 0.0 for key in ("bass", "mid", "high", "left", "right")
        }
        self._hifi_kick = 0.0
        self._hifi_snap = 0.0
        self._hifi_shimmer = 0.0
        self._hifi_bed = 0.0
        self._hifi_last_crest = -10.0
        self._hifi_crests = []
        self._hifi_step = 0
        self._hifi_time_s = None
        self._hifi_palette = None
        self._hifi_palette_source = "selected"
        self._hifi_last_spectra = None
        self._spectrum_db_history = deque(maxlen=170)
        self._spectrum_db_range = [-58.0, -18.0]
        self._pattern_last_kick = 0.0
        self._pattern_last_pulse = -10.0
        self._pattern_pulses = []
        self._pattern_hue_shift = 0.0
        self._pattern_hue_target = 0.0

    def reset(self, preserve_palette=False):
        preserved_palette = self._hifi_palette if preserve_palette else None
        preserved_screen_palette = self._screen_palette if preserve_palette else None
        preserved_source = self._hifi_palette_source if preserve_palette else "selected"
        self._levels = [0.0] * LED_COUNT
        self._left = 0.0
        self._right = 0.0
        self._frame = None
        self._reset_hifi()
        if preserve_palette:
            self._hifi_palette = preserved_palette
            self._screen_palette = preserved_screen_palette
            self._hifi_palette_source = preserved_source
        else:
            self._screen_palette = None

    @staticmethod
    def _fft(values):
        """In-place radix-2 FFT, kept dependency-free for SteamOS."""
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

    @staticmethod
    def _decode(raw):
        minimum = FFT_SIZE * CHANNELS * SAMPLE_BYTES
        if not isinstance(raw, (bytes, bytearray, memoryview)) or len(raw) < minimum:
            raise ValueError(f"audio block must contain at least {minimum} stereo S16LE bytes")
        view = memoryview(raw)[-minimum:]
        samples = struct.unpack(f"<{FFT_SIZE * CHANNELS}h", view)
        left = [samples[index] / 32768.0 for index in range(0, len(samples), 2)]
        right = [samples[index] / 32768.0 for index in range(1, len(samples), 2)]
        return left, right

    def _spectrum(self, mono, sensitivity):
        windowed = [
            sample * (0.5 - 0.5 * math.cos(2.0 * math.pi * index / (FFT_SIZE - 1)))
            for index, sample in enumerate(mono)
        ]
        transformed = self._fft(windowed)
        magnitudes = [abs(value) / (FFT_SIZE / 2.0) for value in transformed[:FFT_SIZE // 2]]
        minimum_hz, maximum_hz = 45.0, 16000.0
        edges = [
            minimum_hz * ((maximum_hz / minimum_hz) ** (index / LED_COUNT))
            for index in range(LED_COUNT + 1)
        ]
        gain_db = (float(sensitivity) - 100.0) * 0.22
        levels = []
        for index in range(LED_COUNT):
            start = max(1, int(math.floor(edges[index] * FFT_SIZE / self.sample_rate)))
            end = max(start + 1, int(math.ceil(edges[index + 1] * FFT_SIZE / self.sample_rate)))
            end = min(end, len(magnitudes))
            energy = math.sqrt(sum(value * value for value in magnitudes[start:end]) / max(1, end - start))
            db = 20.0 * math.log10(max(1e-8, energy)) + gain_db
            levels.append(_clamp((db + 58.0) / 48.0))
        return levels

    def _adaptive_spectrum(self, spectra):
        """Keep spectral shape while adapting to quiet and loud programmes.

        One shared loudness range moves the complete spectrum together. This
        deliberately avoids normalising each LED independently, which would
        turn broadband noise into a permanently full rainbow and erase the
        musical balance between bass, mids and treble.
        """
        if not spectra:
            return [0.0] * LED_COUNT
        minimum_hz, maximum_hz = 45.0, 16000.0
        edges = [
            minimum_hz * ((maximum_hz / minimum_hz) ** (index / LED_COUNT))
            for index in range(LED_COUNT + 1)
        ]
        band_db = []
        for index in range(LED_COUNT):
            start = max(1, int(math.floor(edges[index] * FFT_SIZE / self.sample_rate)))
            end = max(start + 1, int(math.ceil(edges[index + 1] * FFT_SIZE / self.sample_rate)))
            end = min(end, len(spectra[0]))
            energies = []
            for spectrum in spectra:
                selected = spectrum[start:end]
                energies.append(math.sqrt(
                    sum(value * value for value in selected) / max(1, len(selected))
                ))
            energy = sum(energies) / max(1, len(energies))
            band_db.append(20.0 * math.log10(max(1e-8, energy)))

        anchor = _percentile(band_db, 0.76)
        self._spectrum_db_history.append(anchor)
        if len(self._spectrum_db_history) >= 12 and self._hifi_step % 8 == 0:
            target_low = _percentile(self._spectrum_db_history, 0.15) - 7.0
            target_high = max(target_low + 18.0, _percentile(self._spectrum_db_history, 0.92) + 3.0)
            low, high = self._spectrum_db_range
            low += (target_low - low) * (0.18 if target_low < low else 0.08)
            high += (target_high - high) * (0.20 if target_high < high else 0.055)
            self._spectrum_db_range = [low, high]

        low, high = self._spectrum_db_range
        span = max(18.0, high - low)
        programme = _clamp((anchor - low) / span, 0.0, 1.18)
        if max(band_db) < -86.0:
            return [0.0] * LED_COUNT
        return [
            _clamp(programme + (value - anchor) / 34.0, 0.0, 1.0)
            for value in band_db
        ]

    @staticmethod
    def _blackman(values):
        return [
            sample * (
                0.42
                - 0.5 * math.cos(2.0 * math.pi * index / (FFT_SIZE - 1))
                + 0.08 * math.cos(4.0 * math.pi * index / (FFT_SIZE - 1))
            )
            for index, sample in enumerate(values)
        ]

    def _hifi_spectra(self, left, right, sensitivity):
        # Retain the low-level gain for compatibility tests and callers. The
        # normal provider path fixes it at 100 because programme-level matching
        # handles real source differences after warm-up.
        gain = 2.0 ** ((float(sensitivity) - 100.0) / 50.0)
        spectra = []
        for channel in (left, right):
            transformed = self._fft(self._blackman([sample * gain for sample in channel]))
            spectra.append([
                abs(value) / (FFT_SIZE / 2.0)
                for value in transformed[:FFT_SIZE // 2 + 1]
            ])
        return spectra

    def _band_rms(self, spectrum, low_hz, high_hz):
        start = max(1, int(math.ceil(low_hz * FFT_SIZE / self.sample_rate)))
        end = min(len(spectrum), int(math.ceil(high_hz * FFT_SIZE / self.sample_rate)))
        selected = spectrum[start:end]
        return math.sqrt(sum(value * value for value in selected) / max(1, len(selected)))

    def _hifi_target_palette(self, palette, custom_colours, screen_colours,
                             artwork_colours):
        artwork = list(artwork_colours or [])
        if palette == "screen-sync":
            supplied = list(screen_colours or [])
            if len(supplied) >= 3:
                self._screen_palette = _three_colour_palette(supplied, self._screen_palette)
                target = self._screen_palette
                self._hifi_palette_source = "screen-sync"
            elif len(artwork) >= 3:
                self._screen_palette = _three_colour_palette(artwork, self._screen_palette)
                target = self._screen_palette
                self._hifi_palette_source = "artwork"
            elif self._hifi_palette is not None:
                target = self._hifi_palette
                self._hifi_palette_source = "held-transition"
            else:
                target = self._screen_palette or PALETTES["sapphire"]
                self._hifi_palette_source = "sapphire-fallback"
        elif palette == "artwork":
            if len(artwork) >= 3:
                self._screen_palette = _three_colour_palette(artwork, self._screen_palette)
                target = self._screen_palette
                self._hifi_palette_source = "artwork"
            elif self._hifi_palette is not None:
                target = self._hifi_palette
                self._hifi_palette_source = "held-transition"
            else:
                target = self._screen_palette or PALETTES["sapphire"]
                self._hifi_palette_source = "sapphire-fallback"
        elif palette == "custom" and custom_colours:
            target = tuple(tuple(colour) for colour in custom_colours)
            self._hifi_palette_source = "selected"
        else:
            target = PALETTES.get(palette, PALETTES["sapphire"])
            self._hifi_palette_source = "selected"
        if self._hifi_palette is None:
            self._hifi_palette = tuple(tuple(float(channel) for channel in colour) for colour in target)
        else:
            self._hifi_palette = tuple(
                tuple(old + (new - old) * 0.18 for old, new in zip(old_colour, new_colour))
                for old_colour, new_colour in zip(self._hifi_palette, target)
            )
        return self._hifi_palette

    def _hifi_crest(self, left, right, *, brightness, sensitivity, reactivity,
                    palette, custom_colours, screen_colours, artwork_colours,
                    crest_strength, edge_reach, background_level, timestamp_s=None):
        spectra = self._hifi_spectra(left, right, sensitivity)
        self._hifi_last_spectra = spectra
        bands = {"bass": (45.0, 180.0), "mid": (180.0, 2200.0), "high": (2200.0, 14000.0)}
        raw = {}
        flux_raw = {}
        for name, (low_hz, high_hz) in bands.items():
            channel_energy = [self._band_rms(spectrum, low_hz, high_hz) for spectrum in spectra]
            raw[name] = sum(channel_energy) * 0.5
            start = max(1, int(math.ceil(low_hz * FFT_SIZE / self.sample_rate)))
            end = min(len(spectra[0]), int(math.ceil(high_hz * FFT_SIZE / self.sample_rate)))
            positive = []
            for channel in range(2):
                positive.extend(
                    max(0.0, current - previous)
                    for current, previous in zip(
                        spectra[channel][start:end],
                        self._hifi_previous_spectrum[channel][start:end],
                    )
                )
            flux_raw[name] = math.sqrt(
                sum(value * value for value in positive) / max(1, len(positive))
            )
        raw["left"] = self._band_rms(spectra[0], 45.0, 2200.0)
        raw["right"] = self._band_rms(spectra[1], 45.0, 2200.0)
        self._hifi_previous_spectrum = spectra

        observed = {
            "bass": raw["bass"], "mid": raw["mid"], "high": raw["high"],
            "stereo": (raw["left"] + raw["right"]) * 0.5,
        }
        for key, value in observed.items():
            history = self._hifi_energy_history[key]
            history.append(value)
            if len(history) >= 12 and self._hifi_step % 8 == 0:
                target_low = _percentile(history, 0.15)
                target_high = max(target_low + 0.0008, _percentile(history, 0.92))
                low, high = self._hifi_ranges[key]
                low += (target_low - low) * (0.18 if target_low < low else 0.09)
                high += (target_high - high) * (0.22 if target_high < high else 0.055)
                self._hifi_ranges[key] = [low, high]

        target = {
            key: _soft_normalize(raw[key], *self._hifi_ranges[key])
            for key in ("bass", "mid", "high")
        }
        left_target = _soft_normalize(raw["left"], *self._hifi_ranges["stereo"])
        right_target = _soft_normalize(raw["right"], *self._hifi_ranges["stereo"])
        centre = (left_target + right_target) * 0.5
        balance = (right_target - left_target) / (left_target + right_target + 0.08)
        width = _clamp(0.92 + abs(balance) * 0.52, 0.92, 1.28)
        target["left"] = _clamp(centre + (left_target - centre) * width)
        target["right"] = _clamp(centre + (right_target - centre) * width)

        level_smoothing, kick_smoothing, snap_smoothing, shimmer_smoothing, bed_alpha = (
            self._HIFI_REACTIVITY[reactivity]
        )
        for key in self._hifi_levels:
            attack, decay = level_smoothing
            alpha = attack if target[key] >= self._hifi_levels[key] else decay
            self._hifi_levels[key] += (target[key] - self._hifi_levels[key]) * alpha

        flux = {}
        for key in ("bass", "mid", "high"):
            history = self._hifi_flux_history[key]
            history.append(flux_raw[key])
            if len(history) < 8:
                flux[key] = _clamp(flux_raw[key] * 42.0, 0.0, 1.35)
            else:
                floor = _percentile(history, 0.50)
                ceiling = max(floor + 0.00001, _percentile(history, 0.94))
                flux[key] = _clamp((flux_raw[key] - floor) / (ceiling - floor), 0.0, 1.35)

        kick_target = _clamp(flux["bass"] * 0.86 + self._hifi_levels["bass"] * 0.16)
        snap_target = _clamp(flux["mid"] * 0.72 + flux["high"] * 0.28)
        shimmer_target = _clamp(flux["high"])
        for attribute, current_target, smoothing in (
            ("_hifi_kick", kick_target, kick_smoothing),
            ("_hifi_snap", snap_target, snap_smoothing),
            ("_hifi_shimmer", shimmer_target, shimmer_smoothing),
        ):
            current = getattr(self, attribute)
            attack, decay = smoothing
            setattr(self, attribute, current + (current_target - current) * (
                attack if current_target >= current else decay
            ))
        bed_target = (
            self._hifi_levels["bass"] * 0.42
            + self._hifi_levels["mid"] * 0.38
            + self._hifi_levels["high"] * 0.20
        )
        self._hifi_bed += (bed_target - self._hifi_bed) * bed_alpha

        time_s = (
            float(timestamp_s)
            if isinstance(timestamp_s, (int, float)) and math.isfinite(timestamp_s)
            else self._hifi_step * ANALYSIS_HOP / self.sample_rate
        )
        self._hifi_time_s = time_s
        crest_cooldown, crest_speed, crest_lifetime_base = (
            self._HIFI_CREST_MOTION[reactivity]
        )
        if (
            kick_target > 0.70
            and time_s - self._hifi_last_crest >= crest_cooldown - 0.000001
        ):
            self._hifi_crests.append((time_s, _clamp(0.45 + kick_target * 0.55)))
            self._hifi_last_crest = time_s
        strength_scale = _clamp(float(crest_strength) / 100.0, 0.0, 2.5)
        reach_scale = _clamp(float(edge_reach) / 100.0, 0.5, 2.0)
        background_scale = _clamp(float(background_level) / 100.0, 0.0, 1.5)
        crest_lifetime = crest_lifetime_base * reach_scale
        self._hifi_crests = [
            crest for crest in self._hifi_crests
            if time_s - crest[0] < crest_lifetime + 0.02
        ]

        selected_palette = self._hifi_target_palette(
            palette, custom_colours, screen_colours, artwork_colours,
        )
        base = _mirrored_palette_frame(selected_palette)
        stereo_balance = _clamp(
            (self._hifi_levels["right"] - self._hifi_levels["left"]) * 2.0,
            -0.45, 0.45,
        )
        frame = []
        for index, colour in enumerate(base):
            x = index / 8.0 - 1.0
            absolute = abs(x)
            center_shape = math.exp(-((absolute / 0.24) ** 2))
            shoulder_shape = math.exp(-(((absolute - 0.48) / 0.24) ** 2))
            edge_shape = math.exp(-(((absolute - 0.93) / 0.22) ** 2))
            side = 1.0 - stereo_balance if x < 0 else 1.0 + stereo_balance
            ring = 0.0
            for started_at, strength in self._hifi_crests:
                age = time_s - started_at
                radius = age * crest_speed
                ring = max(
                    ring,
                    math.exp(-(((absolute - radius) / 0.14) ** 2))
                    * max(0.0, 1.0 - age / crest_lifetime) * strength,
                )
            background = (
                0.025
                + self._hifi_bed * 0.20
                + center_shape * self._hifi_kick * 0.62
                + shoulder_shape * self._hifi_snap * 0.42 * side
                + edge_shape * self._hifi_shimmer * 0.28 * side
            ) * background_scale
            intensity = _clamp(
                background + ring * 0.44 * strength_scale,
                0.0, 0.90,
            )
            frame.append(self._scaled(tuple(colour), intensity ** 0.68, brightness))
        self._hifi_step += 1
        return frame

    @staticmethod
    def _optical_scaled(colour, level, brightness):
        """Encode an active point for the Steam Machine diffuser.

        Very dark RGB values are either invisible or drift toward red/cyan on
        the physical bar. These experimental patterns therefore use a binary
        dark gate, then keep active colours above a useful peak while limiting
        white-rich output. Motion is expressed primarily through coverage.
        """
        level = _clamp(level)
        if level < 0.055:
            return (0, 0, 0)
        clean = tuple(max(0, min(255, int(round(channel)))) for channel in colour)
        hue, lightness, saturation = _colour_hls(clean)
        if saturation < 0.08 and lightness > 0.62:
            # Pure white blooms strongly under the diffuser. A warm neutral
            # remains readable without becoming a second light source.
            clean = (255, 226, 194)
        elif saturation < 0.18:
            # The tested dark neutral tendency is cyan. Apply a modest warm
            # counter-bias before the common output ceiling.
            clean = (
                min(255, int(round(clean[0] * 1.05 + 2))),
                int(round(clean[1] * 0.97)),
                int(round(clean[2] * 0.86)),
            )
        ceiling = _clamp(float(brightness) / 255.0)
        amount = ceiling * (0.28 + level * 0.56)
        output = [channel * amount for channel in clean]
        peak = max(output)
        useful_floor = min(34.0, max(0.0, float(brightness)))
        if 0.0 < peak < useful_floor:
            output = [channel * useful_floor / peak for channel in output]
            peak = useful_floor
        if peak > 212.0:
            output = [channel * 212.0 / peak for channel in output]
        return tuple(max(0, min(255, int(round(channel)))) for channel in output)

    def _update_pattern_pulses(self, time_s, reactivity):
        threshold = 0.64
        cooldown = 0.12 if reactivity == "punchy" else 0.18
        if (
            self._hifi_kick >= threshold
            and self._pattern_last_kick < threshold
            and time_s - self._pattern_last_pulse >= cooldown - 0.000001
        ):
            self._pattern_pulses.append((time_s, _clamp(0.48 + self._hifi_kick * 0.52)))
            self._pattern_last_pulse = time_s
        self._pattern_last_kick = self._hifi_kick
        self._pattern_pulses = [
            pulse for pulse in self._pattern_pulses
            if time_s - pulse[0] <= 0.66
        ][-2:]

    def _experimental_pattern(self, style, brightness, reactivity):
        time_s = self._hifi_time_s if self._hifi_time_s is not None else 0.0
        self._update_pattern_pulses(time_s, reactivity)
        selected = tuple(
            tuple(int(round(channel)) for channel in colour)
            for colour in (self._hifi_palette or PALETTES["sapphire"])
        )
        base = _mirrored_palette_frame(selected)
        frame = []

        if style == "velvet-relay":
            for index, colour in enumerate(base):
                distance = abs(index - 8) / 8.0
                wave = 0.0
                for started_at, strength in self._pattern_pulses:
                    age = max(0.0, time_s - started_at)
                    radius = _clamp(age / 0.36) * 1.06
                    width = 0.18 + age * 0.12
                    wave = max(
                        wave,
                        math.exp(-(((distance - radius) / width) ** 2))
                        * max(0.0, 1.0 - age / 0.58) * strength,
                    )
                presence = _clamp(self._hifi_bed * 4.0)
                bed = (0.06 + self._hifi_snap * 0.11 + self._hifi_shimmer * 0.07 * distance) * presence
                frame.append(self._optical_scaled(colour, bed + wave * 0.67, brightness))

        elif style == "negative-bloom":
            for index, colour in enumerate(base):
                distance = abs(index - 8) / 8.0
                cut = 0.0
                rim = 0.0
                for started_at, strength in self._pattern_pulses:
                    age = max(0.0, time_s - started_at)
                    radius = _clamp(age / 0.42) * 1.08
                    cut = max(
                        cut,
                        math.exp(-(((distance - radius) / 0.17) ** 2))
                        * max(0.0, 1.0 - age / 0.60) * strength,
                    )
                    rim = max(
                        rim,
                        math.exp(-(((distance - radius - 0.17) / 0.13) ** 2))
                        * max(0.0, 1.0 - age / 0.56) * strength,
                    )
                presence = _clamp(self._hifi_bed * 4.0)
                level = (0.16 + self._hifi_snap * 0.10 + self._hifi_shimmer * 0.05 * distance) * presence
                frame.append(
                    (0, 0, 0)
                    if cut > 0.44
                    else self._optical_scaled(colour, level + rim * 0.30, brightness)
                )

        elif style == "stereo-lanterns":
            for index, colour in enumerate(base):
                position = (index - 8) / 8.0
                left_width = 0.28 + self._hifi_levels["left"] * 0.12
                right_width = 0.28 + self._hifi_levels["right"] * 0.12
                left_lobe = (
                    math.exp(-(((position + 0.55) / left_width) ** 2))
                    * self._hifi_levels["left"]
                )
                right_lobe = (
                    math.exp(-(((position - 0.55) / right_width) ** 2))
                    * self._hifi_levels["right"]
                )
                mono = (
                    math.exp(-((position / 0.20) ** 2))
                    * max(0.0, self._hifi_kick - 0.36) * 0.46
                )
                frame.append(self._optical_scaled(
                    colour, 0.035 + (left_lobe + right_lobe) * 0.52 + mono, brightness,
                ))

        elif style == "constellation":
            levels = [0.0] * LED_COUNT
            seeds = sorted((
                (8, self._hifi_kick * 0.76),
                (4, self._hifi_snap * 0.57),
                (12, self._hifi_snap * 0.57),
                (1, self._hifi_shimmer * 0.48),
                (15, self._hifi_shimmer * 0.48),
            ), key=lambda item: item[1], reverse=True)[:5]
            for index, strength in seeds:
                if strength < 0.12:
                    continue
                levels[index] = max(levels[index], strength)
                if index > 0:
                    levels[index - 1] = max(levels[index - 1], strength * 0.24)
                if index < LED_COUNT - 1:
                    levels[index + 1] = max(levels[index + 1], strength * 0.24)
            frame = [
                self._optical_scaled(colour, level, brightness)
                for colour, level in zip(base, levels)
            ]

        elif style == "slow-prism":
            if self._hifi_step % 8 == 1:
                self._pattern_hue_target = _clamp(
                    (self._hifi_shimmer - self._hifi_levels["bass"]) * (26.0 / 360.0),
                    -26.0 / 360.0, 26.0 / 360.0,
                )
            self._pattern_hue_shift += (
                self._pattern_hue_target - self._pattern_hue_shift
            ) * 0.08
            shifted = []
            for colour in selected:
                hue, lightness, saturation = _colour_hls(colour)
                shifted.append(_hls_colour(
                    hue + self._pattern_hue_shift, lightness, saturation,
                ))
            base = _mirrored_palette_frame(tuple(shifted))
            spread = 0.20 + self._hifi_bed * 0.86
            for index, colour in enumerate(base):
                distance = abs(index - 8) / 8.0
                edge = _clamp((spread - distance) / 0.22)
                side = (
                    self._hifi_levels["left"]
                    if index < 8 else self._hifi_levels["right"]
                )
                frame.append(self._optical_scaled(
                    colour, 0.035 + edge * (0.22 + side * 0.30), brightness,
                ))

        else:
            frame = [(0, 0, 0)] * LED_COUNT
        return frame

    def _smooth(self, levels, reactivity):
        attack, decay = self._SMOOTHING.get(reactivity, self._SMOOTHING["balanced"])
        smoothed = []
        for previous, current in zip(self._levels, levels):
            alpha = attack if current >= previous else decay
            smoothed.append(previous + (current - previous) * alpha)
        self._levels = smoothed
        return smoothed

    @staticmethod
    def _rms(values):
        return math.sqrt(sum(value * value for value in values) / max(1, len(values)))

    @staticmethod
    def _scaled(colour, level, brightness):
        amount = _clamp(level) * _clamp(float(brightness) / 255.0)
        return tuple(int(round(channel * amount)) for channel in colour)

    @staticmethod
    def palette(values):
        name = values.get("audio_sync_palette", "aurora")
        if name == "custom":
            colours = (
                tuple(values.get("audio_sync_colour_low", (0, 170, 255))),
                tuple(values.get("audio_sync_colour_middle", (112, 42, 255))),
                tuple(values.get("audio_sync_colour_high", (255, 48, 140))),
            )
        else:
            colours = PALETTES.get(name, PALETTES["sapphire"])
        return _palette_frame(colours)

    def process(self, raw, *, style="spectrum", brightness=160, sensitivity=100,
                reactivity="balanced", palette="aurora", custom_colours=None,
                screen_colours=None, artwork_colours=None, crest_strength=100,
                edge_reach=100, background_level=100, timestamp_s=None):
        style = style if style in VALID_STYLES else "hifi-crest"
        reactivity = reactivity if reactivity in VALID_REACTIVITY else "balanced"
        values = {
            "audio_sync_palette": palette if palette in VALID_PALETTES else "aurora",
        }
        if custom_colours:
            values.update({
                "audio_sync_colour_low": custom_colours[0],
                "audio_sync_colour_middle": custom_colours[1],
                "audio_sync_colour_high": custom_colours[2],
            })
        left, right = self._decode(raw)
        adaptive_frame = self._hifi_crest(
            left, right, brightness=brightness, sensitivity=sensitivity,
            reactivity=reactivity, palette=palette,
            custom_colours=custom_colours, screen_colours=screen_colours,
            artwork_colours=artwork_colours, crest_strength=crest_strength,
            edge_reach=edge_reach, background_level=background_level,
            timestamp_s=timestamp_s,
        )
        active_palette = tuple(
            tuple(int(round(channel)) for channel in colour)
            for colour in (self._hifi_palette or PALETTES["sapphire"])
        )
        colours = _palette_frame(active_palette)
        if style in HIFI_RENDER_STYLES:
            frame = (
                adaptive_frame
                if style == "hifi-crest"
                else self._experimental_pattern(style, brightness, reactivity)
            )
            self._left = self._hifi_levels["left"]
            self._right = self._hifi_levels["right"]
            self._levels = [
                self._hifi_levels[
                    "bass" if index < 5 else "mid" if index < 12 else "high"
                ]
                for index in range(LED_COUNT)
                ]
        else:
            levels = self._smooth(
                self._adaptive_spectrum(self._hifi_last_spectra), reactivity,
            )
            self._left = self._hifi_levels["left"]
            self._right = self._hifi_levels["right"]

            if style == "spectrum":
                frame = [self._scaled(colour, level, brightness) for colour, level in zip(colours, levels)]
            elif style == "spatial":
                frame = []
                for index, colour in enumerate(colours):
                    position = index / (LED_COUNT - 1)
                    level = self._left * (1.0 - position) + self._right * position
                    frame.append(self._scaled(colour, level, brightness))
            elif style == "bass":
                bass = _clamp(self._hifi_levels["bass"] * 1.10)
                bass_colours = _mirrored_palette_frame(
                    (colours[0], colours[LED_COUNT // 2], colours[-1])
                )
                frame = []
                for index, colour in enumerate(bass_colours):
                    distance = abs(index - (LED_COUNT - 1) / 2.0) / ((LED_COUNT - 1) / 2.0)
                    frame.append(self._scaled(colour, bass * (1.0 - 0.50 * distance), brightness))
            elif style == "audio-pulse":
                base = _mirrored_palette_frame(
                    (colours[0], colours[LED_COUNT // 2], colours[-1])
                )
                pulse = _clamp((self._left + self._right) * 0.62 + max(levels[:9]) * 0.58)
                frame = [self._scaled(tuple(colour), pulse, brightness) for colour in base]
            else:
                frame = [(0, 0, 0)] * LED_COUNT

        self._frame = normalize_frame(frame)
        return self._frame

    @property
    def levels(self):
        return tuple(self._levels)

    @property
    def stereo(self):
        return self._left, self._right

    @property
    def screen_palette(self):
        return tuple(self._screen_palette or ())

    @property
    def hifi_metrics(self):
        return {
            "impact": self._hifi_kick,
            "attack": self._hifi_snap,
            "texture": self._hifi_shimmer,
            "stereo": abs(self._hifi_levels["left"] - self._hifi_levels["right"]),
            "window_s": min(
                10.2,
                len(self._hifi_energy_history["bass"]) * ANALYSIS_HOP / self.sample_rate,
            ),
        }

    @classmethod
    def response_timing(cls, reactivity):
        """Return discrete 90% response times for the selected 60 ms profile."""
        reactivity = reactivity if reactivity in cls._HIFI_REACTIVITY else "balanced"
        level, impact, attack, texture, bed_alpha = cls._HIFI_REACTIVITY[reactivity]
        crest_cooldown, crest_speed, crest_lifetime = cls._HIFI_CREST_MOTION[reactivity]

        def time_to_ninety(alpha):
            alpha = _clamp(alpha, 0.0001, 0.9999)
            frames = math.ceil(math.log(0.1) / math.log(1.0 - alpha))
            return round(frames * ANALYSIS_HOP_MS, 1)

        def pair(values):
            return {
                "rise_ms": time_to_ninety(values[0]),
                "fall_ms": time_to_ninety(values[1]),
            }

        return {
            "reactivity": reactivity,
            "level": pair(level),
            "impact": pair(impact),
            "attack": pair(attack),
            "texture": pair(texture),
            "background": pair((bed_alpha, bed_alpha)),
            "crest": {
                "cooldown_ms": round(crest_cooldown * 1000.0, 1),
                "centre_to_edge_ms": round(1000.0 / crest_speed, 1),
                "lifetime_ms": round(crest_lifetime * 1000.0, 1),
            },
        }

    @property
    def palette_source(self):
        return self._hifi_palette_source


class AudioCaptureService:
    """Supervise pw-record against the current PipeWire sink monitor."""

    def __init__(self, clock=time.monotonic, popen=subprocess.Popen):
        self._clock = clock
        self._popen = popen
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._process = None
        self._active = False
        self._block = None
        self._block_at = 0.0
        self._sequence = 0
        self._phase = "off"
        self._error = ""
        self._runtime_dir = ""
        self._capture_identity = ""
        self._stderr = deque(maxlen=12)
        self._blocks_seen = 0
        self._started_at = 0.0
        self._pending = deque(maxlen=MAX_PENDING_BLOCKS)
        self._dropped_blocks = 0
        self._buffered_bytes = 0
        self._buffer = bytearray()
        self._block_times = deque(maxlen=64)

    @staticmethod
    def capture_command(executable):
        properties = '{"stream.capture.sink":true,"media.category":"Capture","media.role":"Music","node.name":"GabeCubeAura-Audio-Sync"}'
        return [
            executable, "--record", "--raw", f"--rate={SAMPLE_RATE}",
            f"--channels={CHANNELS}", "--channel-map=stereo", "--format=s16",
            "--latency=50ms", f"--properties={properties}", "-",
        ]

    def set_active(self, active):
        active = bool(active)
        with self._lock:
            changed = active != self._active
            self._active = active
            if changed:
                self._pending.clear()
                self._block = None
                self._block_at = 0.0
                self._buffered_bytes = 0
                self._buffer.clear()
            if not active:
                self._phase = "off"
                self._error = ""
            if active and (self._thread is None or not self._thread.is_alive()):
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._supervise, name="gabecubeaura-audio-capture", daemon=True,
                )
                self._thread.start()
        if changed:
            self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.5)
        with self._lock:
            self._active = False
            self._phase = "off"
            self._process = None
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None

    def latest(self):
        with self._lock:
            return self._block, self._sequence, self._block_at

    def pending_after(self, sequence):
        with self._lock:
            while self._pending and self._pending[0][0] <= sequence:
                self._pending.popleft()
            return [
                (block, current_sequence, sampled_at)
                for current_sequence, block, sampled_at in self._pending
                if current_sequence > sequence
            ]

    def ingest(self, chunk, received_at=None):
        """Append PCM without discarding a partial analysis hop."""
        if not chunk:
            return 0
        received_at = self._clock() if received_at is None else float(received_at)
        emitted = 0
        with self._lock:
            self._buffer.extend(chunk)
            while len(self._buffer) >= BLOCK_BYTES:
                block = bytes(self._buffer[:BLOCK_BYTES])
                del self._buffer[:BLOCK_BYTES]
                sampled_at = received_at - len(self._buffer) / BYTES_PER_SECOND
                self._block = block
                self._block_at = sampled_at
                self._sequence += 1
                self._blocks_seen += 1
                if len(self._pending) == self._pending.maxlen:
                    self._dropped_blocks += 1
                self._pending.append((self._sequence, block, sampled_at))
                self._block_times.append(sampled_at)
                emitted += 1
            self._buffered_bytes = len(self._buffer)
        return emitted

    def status(self):
        with self._lock:
            age = max(0.0, self._clock() - self._block_at) if self._block_at else None
            elapsed = max(0.001, self._clock() - self._started_at) if self._started_at else 0.0
            if len(self._block_times) >= 2:
                block_span = max(0.001, self._block_times[-1] - self._block_times[0])
                blocks_per_second = (len(self._block_times) - 1) / block_span
            else:
                blocks_per_second = self._blocks_seen / elapsed if elapsed else 0.0
            return {
                "revision": CAPTURE_REVISION,
                "phase": self._phase,
                "error": self._error,
                "runtime_dir": self._runtime_dir,
                "capture_identity": self._capture_identity,
                "source": "Default PipeWire output",
                "sample_rate": SAMPLE_RATE,
                "channels": CHANNELS,
                "frame_age_s": age,
                "blocks_per_second": blocks_per_second,
                "capture_latency_ms": CAPTURE_LATENCY_MS,
                "analysis_window_ms": ANALYSIS_WINDOW_MS,
                "analysis_hop_ms": ANALYSIS_HOP_MS,
                "target_blocks_per_second": 1000.0 / ANALYSIS_HOP_MS,
                "led_request_interval_ms": LED_REQUEST_INTERVAL_MS,
                "led_render_floor_ms": LED_RENDER_FLOOR_MS,
                "buffered_ms": self._buffered_bytes / BYTES_PER_SECOND * 1000.0,
                "queued_blocks": len(self._pending),
                "dropped_blocks": self._dropped_blocks,
                "stderr_tail": list(self._stderr),
            }

    def _wait(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _set_state(self, phase, error=""):
        with self._lock:
            self._phase = phase
            self._error = str(error)[:300]

    def _supervise(self):
        backoff = 0.5
        runtime_cursor = 0
        while not self._stop.is_set():
            with self._lock:
                active = self._active
            if not active:
                self._wait(0.25)
                continue
            process = None
            try:
                executable = shutil.which("pw-record") or shutil.which("pw-cat")
                if not executable:
                    raise RuntimeError("PipeWire pw-record is not installed")
                runtime_dirs = ScreenCaptureService._runtime_dirs()
                if not runtime_dirs:
                    raise RuntimeError("PipeWire session was not found")
                # Prefer a normal desktop/Gaming Mode user over a root-owned
                # PipeWire graph, then rotate across every visible session if
                # the preferred one is temporarily unavailable.
                runtime_dirs = sorted(
                    runtime_dirs,
                    key=lambda candidate: (
                        (ScreenCaptureService._runtime_owner(candidate) or (0, ""))[0] == 0,
                        candidate,
                    ),
                )
                runtime_dir = runtime_dirs[runtime_cursor % len(runtime_dirs)]
                command, identity = ScreenCaptureService._command_for_runtime(
                    self.capture_command(executable), runtime_dir,
                )
                environment = dict(os.environ)
                environment["XDG_RUNTIME_DIR"] = runtime_dir
                with self._lock:
                    self._runtime_dir = runtime_dir
                    self._capture_identity = identity
                    self._stderr.clear()
                process = self._popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL, env=environment, bufsize=0,
                )
                with self._lock:
                    self._process = process
                    self._started_at = self._clock()
                    self._blocks_seen = 0
                    self._block_times.clear()
                    self._pending.clear()
                    self._dropped_blocks = 0
                    self._buffered_bytes = 0
                    self._buffer.clear()
                os.set_blocking(process.stdout.fileno(), False)
                os.set_blocking(process.stderr.fileno(), False)
                last_audio = self._clock()
                self._set_state("capturing")
                backoff = 0.5
                while not self._stop.is_set():
                    with self._lock:
                        active = self._active
                    if not active or process.poll() is not None:
                        break
                    readable, _, _ = select.select(
                        [process.stdout.fileno(), process.stderr.fileno()], [], [], 0.20,
                    )
                    if process.stdout.fileno() in readable:
                        chunk = os.read(process.stdout.fileno(), BLOCK_BYTES * 2)
                        if chunk:
                            received_at = self._clock()
                            self.ingest(chunk, received_at)
                            last_audio = received_at
                    if process.stderr.fileno() in readable:
                        message = os.read(process.stderr.fileno(), 2048).decode("utf-8", "replace").strip()
                        if message:
                            self._stderr.append(message[-240:])
                    if self._clock() - last_audio > 2.0:
                        raise RuntimeError("PipeWire audio capture stopped producing samples")
                if process.poll() not in (None, 0) and active:
                    detail = self._stderr[-1] if self._stderr else "pw-record stopped"
                    raise RuntimeError(detail)
            except Exception as error:
                runtime_cursor += 1
                self._set_state("error", error)
                self._wait(backoff)
                backoff = min(5.0, backoff * 2.0)
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1.0)
                with self._lock:
                    if self._process is process:
                        self._process = None


class AudioSyncProvider:
    def __init__(self, capture=None, processor=None, clock=time.monotonic):
        self.capture = capture or AudioCaptureService(clock=clock)
        self.processor = processor or AudioSyncProcessor()
        self.clock = clock
        self._active = False
        self._sequence = -1
        self._frame = None
        self._preview_until = 0.0

    @property
    def previewing(self):
        return self.clock() < self._preview_until

    def preview(self, seconds=15.0):
        self._preview_until = self.clock() + max(1.0, float(seconds))
        return True

    def set_active(self, active):
        active = bool(active)
        if active != self._active:
            self._active = active
            if not active:
                self.processor.reset()
                self._sequence = -1
                self._frame = None
        self.capture.set_active(active)

    def stop(self, preserve_palette=False):
        self._preview_until = 0.0
        self._active = False
        self.capture.stop()
        self.processor.reset(preserve_palette=preserve_palette)
        self._frame = None

    def output(self, values, screen_colours=None, artwork_colours=None):
        if not self._active:
            return ProviderOutput("audio-sync", None, "Audio Sync is off")
        capture_status = self.capture.status()
        if capture_status.get("phase") != "capturing":
            return ProviderOutput(
                "audio-sync", None,
                capture_status.get("error") or "Waiting for PipeWire audio capture",
            )
        raw, sequence, sampled_at = self.capture.latest()
        if raw is None or not sampled_at or self.clock() - sampled_at > 1.0:
            return ProviderOutput("audio-sync", None, "Waiting for fresh audio samples")
        pending = getattr(self.capture, "pending_after", None)
        blocks = pending(self._sequence) if callable(pending) else []
        if not blocks and sequence != self._sequence:
            blocks = [(raw, sequence, sampled_at)]
        for block, block_sequence, block_at in blocks:
            if self.clock() - block_at > 1.0:
                self._sequence = block_sequence
                continue
            self._frame = self.processor.process(
                block,
                style=values["audio_sync_style"],
                brightness=values["audio_sync_brightness"],
                # Programme loudness is already matched by the rolling 10.2 s
                # range. Keep the analysis neutral instead of exposing a
                # pre-normalisation trim that mostly disappears after warm-up.
                sensitivity=100,
                reactivity=values["audio_sync_reactivity"],
                palette=values["audio_sync_palette"],
                custom_colours=(
                    values["audio_sync_colour_low"],
                    values["audio_sync_colour_middle"],
                    values["audio_sync_colour_high"],
                ),
                screen_colours=screen_colours,
                artwork_colours=artwork_colours,
                crest_strength=values.get("audio_sync_lab_crest_strength", 100),
                edge_reach=values.get("audio_sync_lab_edge_reach", 100),
                background_level=values.get("audio_sync_lab_background", 100),
                timestamp_s=block_at,
            )
            self._sequence = block_sequence
        return ProviderOutput(f"audio-sync:{values['audio_sync_style']}", self._frame, "Live system audio")

    def status(self, reactivity="balanced"):
        status = self.capture.status()
        left, right = self.processor.stereo
        status.update({
            "active": self._active,
            "preview_active": self.previewing,
            "preview_remaining_s": max(0.0, self._preview_until - self.clock()),
            "colors": [list(pixel) for pixel in self._frame] if self._frame else [],
            "levels": [round(level, 4) for level in self.processor.levels],
            "left_level": round(left, 4),
            "right_level": round(right, 4),
            "screen_palette": [list(colour) for colour in self.processor.screen_palette],
            "hifi_metrics": {
                key: round(value, 4)
                for key, value in self.processor.hifi_metrics.items()
            },
            "palette_source": self.processor.palette_source,
            "response_timing": self.processor.response_timing(reactivity),
        })
        return status
