"""Artwork palette state and disk cache.

Image decoding happens in Steam's browser canvas; this provider owns validated
17-pixel results and persists them by AppID, artwork fingerprint, and row mode.
"""

from __future__ import annotations

import json
import math
import os
import threading

from signalbar.models import ProviderOutput, normalize_frame


def _srgb_to_linear(channel):
    value = max(0.0, min(1.0, float(channel) / 255.0))
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel):
    value = max(0.0, min(1.0, float(channel)))
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055
    return int(round(max(0.0, min(1.0, encoded)) * 255.0))


def _rgb_to_oklab(colour):
    red, green, blue = (_srgb_to_linear(channel) for channel in colour)
    light = math.copysign(abs(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue) ** (1.0 / 3.0), 1)
    middle = math.copysign(abs(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue) ** (1.0 / 3.0), 1)
    short = math.copysign(abs(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue) ** (1.0 / 3.0), 1)
    return (
        0.2104542553 * light + 0.7936177850 * middle - 0.0040720468 * short,
        1.9779984951 * light - 2.4285922050 * middle + 0.4505937099 * short,
        0.0259040371 * light + 0.7827717662 * middle - 0.8086757660 * short,
    )


def _oklab_to_linear(lightness, axis_a, axis_b):
    light = lightness + 0.3963377774 * axis_a + 0.2158037573 * axis_b
    middle = lightness - 0.1055613458 * axis_a - 0.0638541728 * axis_b
    short = lightness - 0.0894841775 * axis_a - 1.2914855480 * axis_b
    light, middle, short = light ** 3, middle ** 3, short ** 3
    return (
        4.0767416621 * light - 3.3077115913 * middle + 0.2309699292 * short,
        -1.2684380046 * light + 2.6097574011 * middle - 0.3413193965 * short,
        -0.0041960863 * light - 0.7034186147 * middle + 1.7076147010 * short,
    )


def artwork_vibrance(colour, percent=100):
    """Adjust perceptual chroma while retaining lightness and compressing gamut."""
    clean = tuple(max(0, min(255, int(round(float(channel))))) for channel in colour)
    amount = max(0.0, min(2.0, float(percent) / 100.0))
    if amount == 1.0:
        return clean
    lightness, axis_a, axis_b = _rgb_to_oklab(clean)
    chroma = math.hypot(axis_a, axis_b)
    if amount <= 1.0:
        multiplier = amount
    else:
        # Low-chroma artwork receives the strongest lift. Already vivid
        # colours approach a neutral multiplier before gamut compression.
        headroom = max(0.0, 1.0 - chroma / 0.28)
        multiplier = 1.0 + (amount - 1.0) * headroom
    target_a, target_b = axis_a * multiplier, axis_b * multiplier

    def in_gamut(scale):
        return all(
            -0.000001 <= channel <= 1.000001
            for channel in _oklab_to_linear(lightness, target_a * scale, target_b * scale)
        )

    scale = 1.0
    if not in_gamut(scale):
        low, high = 0.0, 1.0
        for _ in range(16):
            middle = (low + high) * 0.5
            if in_gamut(middle):
                low = middle
            else:
                high = middle
        scale = low
    return tuple(
        _linear_to_srgb(channel)
        for channel in _oklab_to_linear(lightness, target_a * scale, target_b * scale)
    )


def _apply_vibrance(colours, percent):
    return tuple(artwork_vibrance(colour, percent) for colour in colours)


class ArtworkProvider:
    name = "artwork"

    def __init__(self, cache_path):
        self.cache_path = cache_path
        self._lock = threading.RLock()
        self._cache = {}
        self._current = None
        self._load()

    @staticmethod
    def key(appid, fingerprint, mode, manual_y):
        suffix = f"{float(manual_y):.3f}" if mode == "manual" else "-"
        return f"{int(appid)}:{fingerprint}:{mode}:{suffix}"

    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict):
                self._cache = raw
        except (OSError, ValueError, TypeError):
            self._cache = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        temporary = self.cache_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self._cache, handle, separators=(",", ":"), sort_keys=True)
        os.replace(temporary, self.cache_path)

    @staticmethod
    def _dominant_palettes(raw):
        if not isinstance(raw, dict):
            return {}
        palettes = {}
        for count in (2, 3):
            values = raw.get(str(count), raw.get(count))
            if not isinstance(values, (list, tuple)) or len(values) != count:
                continue
            try:
                colours = []
                for colour in values:
                    if not isinstance(colour, (list, tuple)) or len(colour) != 3:
                        raise ValueError("invalid dominant colour")
                    colours.append(tuple(max(0, min(255, int(round(float(channel))))) for channel in colour))
                palettes[str(count)] = colours
            except (TypeError, ValueError, OverflowError):
                continue
        return palettes

    def activate_cached(self, appid, fingerprint, mode, manual_y):
        with self._lock:
            entry = self._cache.get(self.key(appid, fingerprint, mode, manual_y))
            if not isinstance(entry, dict):
                self._current = None
                return False
            try:
                frame = normalize_frame(entry.get("colors"))
            except (ValueError, TypeError):
                self._current = None
                return False
            palettes = self._dominant_palettes(entry.get("dominant_palettes"))
            self._current = {**entry, "frame": frame, "appid": int(appid),
                             "dominant_palettes": palettes}
            # v0.7.1 caches remain valid for Artwork, but are resampled once so
            # the launch-animation palette is not guessed from the 17-pixel row.
            return set(palettes) == {"2", "3"}

    def submit(self, appid, fingerprint, mode, manual_y, colors, sample_y,
               filename="", source="hero", dominant_palettes=None):
        frame = normalize_frame(colors)
        palettes = self._dominant_palettes(dominant_palettes)
        if set(palettes) != {"2", "3"}:
            raise ValueError("artwork sampling must include two- and three-colour palettes")
        entry = {
            "colors": [list(pixel) for pixel in frame],
            "dominant_palettes": {
                count: [list(colour) for colour in values]
                for count, values in palettes.items()
            },
            "sample_y": float(sample_y),
            "filename": os.path.basename(str(filename or "")),
            "source": str(source or "hero"),
        }
        with self._lock:
            self._cache[self.key(appid, fingerprint, mode, manual_y)] = entry
            # Bound cache growth without adding a database.
            while len(self._cache) > 256:
                self._cache.pop(next(iter(self._cache)))
            self._save()
            self._current = {**entry, "frame": frame, "appid": int(appid)}

    def clear(self):
        with self._lock:
            self._current = None

    def output(self, appid, vibrance=100):
        with self._lock:
            if not self._current or self._current.get("appid") != int(appid or 0):
                return ProviderOutput(self.name, None, "artwork not sampled")
            return ProviderOutput(
                self.name,
                _apply_vibrance(self._current["frame"], vibrance),
                "Steam Library artwork",
            )

    def dominant_palettes(self, appid=0, vibrance=100):
        with self._lock:
            if not self._current or self._current.get("appid") != int(appid or 0):
                return {}
            return {
                count: [list(colour) for colour in _apply_vibrance(values, vibrance)]
                for count, values in self._current.get("dominant_palettes", {}).items()
            }

    def status(self, colour_count=2, vibrance=100):
        with self._lock:
            if not self._current:
                return {}
            palettes = self._current.get("dominant_palettes", {})
            selected = palettes.get(str(3 if int(colour_count) == 3 else 2), ())
            return {
                "sample_y": self._current["sample_y"],
                "filename": self._current["filename"],
                "source": self._current.get("source", "hero"),
                "colors": [list(pixel) for pixel in _apply_vibrance(self._current["frame"], vibrance)],
                "dominant_colors": [list(colour) for colour in _apply_vibrance(selected, vibrance)],
            }
