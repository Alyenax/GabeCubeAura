"""Persistent user-authored light-bar display for Customization+."""

from __future__ import annotations

import math
import threading
import time

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame
from signalbar.providers.controller import DURATIONS as CONTROLLER_DURATIONS
from signalbar.providers.controller import VARIANTS as CONTROLLER_VARIANTS
from signalbar.providers.controller import controller_frame
from signalbar.providers.events import VARIANT_DURATIONS, event_frame
from signalbar.providers.launch_artwork import PATTERNS, pattern_frame
from signalbar.providers.weather_sequences import weather_loop_seconds, weather_sequence


WEATHER_VARIANT_COUNTS = {
    "clear_day": 2, "clear_night": 2, "rain": 2, "cloud": 4,
    "breaks": 2, "breaks_night": 2, "snow": 2, "storm": 2,
}
EVENT_PATTERNS = {f"event:{variant}" for variant in VARIANT_DURATIONS
                  if not variant.startswith("record-")}
CONTROLLER_PATTERNS = {
    f"controller:{kind}:{variant}"
    for kind, variants in CONTROLLER_VARIANTS.items() for variant in variants
}
WEATHER_PATTERNS = {
    f"weather:{condition}:{variant}"
    for condition, count in WEATHER_VARIANT_COUNTS.items() for variant in range(count)
}
CUSTOMIZATION_PATTERNS = {"steady"} | PATTERNS | EVENT_PATTERNS | CONTROLLER_PATTERNS | WEATHER_PATTERNS
BLACK = (0, 0, 0)


def _colour(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("a colour needs three RGB channels")
    return tuple(max(0, min(255, int(round(float(channel))))) for channel in value)


def _scale(colour, level):
    level = max(0, min(255, int(level)))
    return tuple(round(channel * level / 255) for channel in colour)


def _recolour(frame, palette, brightness, phase):
    """Keep an existing animation's light/dark choreography, using user hues."""
    result = []
    for index, pixel in enumerate(frame):
        level = max(pixel)
        if level <= 0:
            result.append(BLACK)
            continue
        selected = palette[(index + int(phase * .7)) % len(palette)]
        result.append(_scale(selected, round(brightness * level / 255)))
    return result


def customization_frame(pattern, colours, elapsed_seconds, brightness=128,
                        speed=50, direction="forward"):
    """Render one logical frame; brightness is the exact 0..255 RGB ceiling."""
    if pattern not in CUSTOMIZATION_PATTERNS:
        raise ValueError(f"unknown customization pattern: {pattern}")
    if not isinstance(colours, (list, tuple)) or not 1 <= len(colours) <= 3:
        raise ValueError("Customization+ needs one, two or three colours")
    palette = tuple(_colour(value) for value in colours)
    brightness = max(0, min(255, int(brightness)))
    speed = max(1, min(100, int(speed)))
    phase = max(0.0, float(elapsed_seconds)) * (.2 + speed * .028)

    if brightness == 0:
        frame = [BLACK] * LED_COUNT
    elif pattern == "steady":
        frame = [_scale(palette[0], brightness)] * LED_COUNT
    elif pattern.startswith("event:"):
        variant = pattern.split(":", 1)[1]
        kind = variant.split("-", 1)[0]
        duration = VARIANT_DURATIONS[variant]
        frame = _recolour(event_frame(kind, phase % duration, variant), palette, brightness, phase)
    elif pattern.startswith("controller:"):
        _, kind, variant = pattern.split(":", 2)
        duration = CONTROLLER_DURATIONS[kind]
        elapsed = phase % duration
        frame = _recolour(controller_frame(
            kind, variant, elapsed, 74, 35,
            intro_age=elapsed if kind == "duo" else None,
            continuous=kind == "charging",
        ), palette, brightness, phase)
    elif pattern.startswith("weather:"):
        _, condition, raw_variant = pattern.split(":", 2)
        variant = int(raw_variant)
        elapsed = phase % weather_loop_seconds(condition, variant)
        frame = _recolour(weather_sequence(condition, variant, elapsed), palette, brightness, phase)
    else:
        shared_palette = palette if len(palette) > 1 else (palette[0], palette[0])
        raw = pattern_frame(pattern, shared_palette, phase)
        frame = [_scale(pixel, brightness) for pixel in raw]

    if direction == "reverse":
        frame.reverse()
    return normalize_frame(frame)


def calibration_frame(elapsed_seconds, brightness=160):
    """Ten-second optical check for colour, white balance and moving contrast."""
    elapsed = max(0.0, float(elapsed_seconds))
    brightness = max(34, min(255, int(brightness)))
    if elapsed < 3.2:
        anchors = ((0, 170, 255), (112, 42, 255), (255, 48, 140))
        frame = []
        for index in range(LED_COUNT):
            distance = abs(index - 8)
            colour = anchors[2] if distance <= 2 else anchors[1] if distance <= 5 else anchors[0]
            frame.append(_scale(colour, brightness))
        return normalize_frame(frame)
    if elapsed < 6.4:
        anchors = ((118, 150, 216), (201, 232, 255), (255, 255, 255))
        frame = []
        for index in range(LED_COUNT):
            distance = abs(index - 8)
            colour = anchors[2] if distance <= 1 else anchors[1] if distance <= 4 else anchors[0]
            level = 0.72 if distance <= 1 else 0.56 if distance <= 4 else 0.38
            frame.append(_scale(colour, round(brightness * level)))
        return normalize_frame(frame)

    # A synthetic centre-out crest makes the hardware gain test independent
    # from programme audio while retaining the geometry used by Hi-Fi Crest.
    phase = ((elapsed - 6.4) % 1.20) / 1.20
    palette = ((0, 170, 255), (112, 42, 255), (255, 48, 140))
    frame = []
    for index in range(LED_COUNT):
        distance = abs(index - 8) / 8.0
        colour = palette[2] if distance <= .24 else palette[1] if distance <= .66 else palette[0]
        ring = math.exp(-(((distance - phase) / .15) ** 2))
        level = min(1.0, .10 + ring * .82)
        frame.append(_scale(colour, round(brightness * level)))
    return normalize_frame(frame)


def calibration_stage(elapsed_seconds):
    elapsed = max(0.0, float(elapsed_seconds))
    if elapsed < 3.2:
        return "colour-separation"
    if elapsed < 6.4:
        return "white-balance"
    return "motion-contrast"


class CustomizationProvider:
    name = "customization"

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.RLock()
        self._preview_until = 0.0
        self._calibration_started_at = 0.0
        self._calibration_until = 0.0

    def preview(self, seconds=8.0):
        with self._lock:
            self._preview_until = self.clock() + max(1.0, min(30.0, float(seconds)))
        return True

    def preview_calibration(self, seconds=10.0):
        with self._lock:
            now = self.clock()
            duration = max(9.6, min(30.0, float(seconds)))
            self._calibration_started_at = now
            self._calibration_until = now + duration
        return True

    def stop_preview(self):
        with self._lock:
            self._preview_until = 0.0
            self._calibration_started_at = 0.0
            self._calibration_until = 0.0

    def output(self, values, enabled=False):
        with self._lock:
            now = self.clock()
            preview = now < self._preview_until
            calibration = now < self._calibration_until
            calibration_elapsed = max(0.0, now - self._calibration_started_at)
        if calibration:
            return ProviderOutput(
                "customization:calibration",
                calibration_frame(calibration_elapsed, values.get("audio_sync_brightness", 160)),
                "Light bar calibration preview",
            )
        if not enabled and not preview:
            return ProviderOutput(self.name, None, "Customization+ is not selected here")
        count = max(1, min(3, int(values.get("customization_colour_count", 1))))
        colours = [values[f"customization_colour_{index}"] for index in range(1, count + 1)]
        frame = customization_frame(
            values.get("customization_pattern", "steady"), colours, self.clock(),
            values.get("customization_brightness", 128),
            values.get("customization_speed", 50),
            values.get("customization_direction", "forward"),
        )
        provider = "customization:preview" if preview else f"customization:{values.get('customization_pattern', 'steady')}"
        return ProviderOutput(provider, frame, "Customization+ user display")

    def status(self, values):
        with self._lock:
            now = self.clock()
            preview = now < self._preview_until
            calibration = now < self._calibration_until
            calibration_elapsed = max(0.0, now - self._calibration_started_at)
        count = max(1, min(3, int(values.get("customization_colour_count", 1))))
        colours = [values[f"customization_colour_{index}"] for index in range(1, count + 1)]
        status_frame = (
            calibration_frame(calibration_elapsed, values.get("audio_sync_brightness", 160))
            if calibration else customization_frame(
                values.get("customization_pattern", "steady"), colours, self.clock(),
                values.get("customization_brightness", 128),
                values.get("customization_speed", 50),
                values.get("customization_direction", "forward"),
            )
        )
        return {
            "preview_active": preview,
            "calibration_preview_active": calibration,
            "calibration_stage": calibration_stage(calibration_elapsed) if calibration else "idle",
            "calibration_remaining_s": max(0.0, self._calibration_until - now),
            "colors": [list(pixel) for pixel in status_frame],
        }
