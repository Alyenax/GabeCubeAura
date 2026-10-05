"""Deterministic physical previews used only by the guided setup."""

from __future__ import annotations

import math

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame


IMMERSIVE_PREVIEW_DURATION = 10.0
IMMERSIVE_AUDIO_FRACTION = 0.52
SAPPHIRE = ((99, 135, 233), (78, 118, 228), (78, 118, 228))
SCREEN_PANORAMA = (
    (15, 35, 80),
    (18, 118, 180),
    (42, 188, 184),
    (164, 58, 170),
    (235, 108, 42),
)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _lerp_colour(first, second, amount):
    amount = _clamp(amount)
    return tuple(
        int(round(start + (end - start) * amount))
        for start, end in zip(first, second)
    )


def _mirrored_sapphire():
    outer, shoulder, centre = SAPPHIRE
    colours = []
    for index in range(LED_COUNT):
        distance = abs(index - 8) / 8.0
        colours.append(
            _lerp_colour(centre, shoulder, distance * 2.0)
            if distance <= 0.5 else
            _lerp_colour(shoulder, outer, (distance - 0.5) * 2.0)
        )
    return colours


def synthetic_slow_prism_frame(elapsed_s):
    """A source-independent Slow Prism breath using its real Sapphire roles."""
    elapsed = max(0.0, float(elapsed_s))
    breath = 0.5 + 0.5 * math.sin(2.0 * math.pi * elapsed / 2.45)
    shoulder = 0.5 + 0.5 * math.sin(2.0 * math.pi * elapsed / 1.63 + 0.8)
    spread = 0.34 + 0.58 * (breath * 0.72 + shoulder * 0.28)
    frame = []
    for index, colour in enumerate(_mirrored_sapphire()):
        distance = abs(index - 8) / 8.0
        coverage = _clamp((spread - distance) / 0.19)
        if coverage < 0.035:
            frame.append((0, 0, 0))
            continue
        side_motion = 0.92 + 0.08 * math.sin(elapsed * 2.3 + distance * 1.7)
        intensity = (0.30 + coverage * (0.38 + breath * 0.22)) * side_motion
        frame.append(tuple(int(round(channel * intensity)) for channel in colour))
    return normalize_frame(frame)


def _panorama_colour(position):
    scaled = (_clamp(position % 1.0) * len(SCREEN_PANORAMA))
    index = min(len(SCREEN_PANORAMA) - 1, int(scaled))
    next_index = (index + 1) % len(SCREEN_PANORAMA)
    return _lerp_colour(
        SCREEN_PANORAMA[index], SCREEN_PANORAMA[next_index], scaled - index,
    )


def synthetic_screen_sync_frame(elapsed_s):
    """A moving horizontal scene representative of Screen Sync panorama."""
    elapsed = max(0.0, float(elapsed_s))
    pan = elapsed * 0.075 + math.sin(elapsed * 0.72) * 0.055
    scene_light = 0.76 + 0.10 * math.sin(elapsed * 1.35)
    frame = []
    for index in range(LED_COUNT):
        position = index / (LED_COUNT - 1)
        colour = _panorama_colour(position + pan)
        local_light = scene_light + 0.07 * math.sin(elapsed * 1.8 + index * 0.42)
        frame.append(tuple(int(round(channel * local_light)) for channel in colour))
    return normalize_frame(frame)


def immersive_preview_output(elapsed_s, duration_s=IMMERSIVE_PREVIEW_DURATION):
    """Return the current synthetic Audio Sync or Screen Sync preview frame."""
    duration = max(2.0, float(duration_s))
    elapsed = max(0.0, min(duration, float(elapsed_s)))
    audio_seconds = duration * IMMERSIVE_AUDIO_FRACTION
    if elapsed < audio_seconds:
        return ProviderOutput(
            "audio-sync:slow-prism-demo",
            synthetic_slow_prism_frame(elapsed),
            "Guided synthetic Slow Prism preview",
        )
    return ProviderOutput(
        "screen-sync:panorama-demo",
        synthetic_screen_sync_frame(elapsed - audio_seconds),
        "Guided synthetic Screen Sync preview",
    )
