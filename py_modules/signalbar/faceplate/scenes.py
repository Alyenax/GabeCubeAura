# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Deterministic 64 x 54 software scenes for the JSAUX PIXEL faceplate.

This module deliberately has no transport, network, Decky, or sensor imports.
It only turns already-fetched values into RGB frames and bounded GIF payloads.
The caller remains responsible for deciding whether a payload may be uploaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from typing import Iterable, Sequence

from signalbar.faceplate.gif import encode as encode_indexed_gif
from signalbar.faceplate.gif import quantize
from signalbar.providers.weather_sequences import weather_loop_seconds


WIDTH = 64
HEIGHT = 54
PIXELS = WIDTH * HEIGHT
SCENE_REVISION = "faceplate-scenes-3"
SOLAR_TRANSITION_MINUTES = 45
MAX_WEATHER_FRAMES = 32
MAX_HOUR_PACK_FRAMES = 60
MAX_SCENE_GIF_BYTES = 512 * 1024
MAX_ARTWORK_FRAMES = 80
MAX_ARTWORK_GIF_BYTES = 2 * 1024 * 1024

WEATHER_VARIANTS = {
    "clear_day": ("Sun glints", "Solar bloom"),
    "clear_night": ("Breathing moon", "Lunar bloom"),
    "rain": ("Bluewater", "Pearl rain"),
    "cloud": ("Passing shadow", "Passing shadows", "Cross & gather", "Slow convergence"),
    "cloud_night": (
        "Night passing shadow", "Night passing shadows",
        "Night cross & gather", "Night slow convergence",
    ),
    "breaks": ("Sun through clouds", "Sun, fading clouds"),
    "breaks_night": ("Moon through clouds", "Moon, fading clouds"),
    "snow": ("Melting snowfall", "Snow takes hold"),
    "storm": ("Pulse and echoes", "Storm break"),
}

PHASE_PALETTES = {
    "dawn": {
        "sky": (8, 7, 24), "horizon": (80, 21, 58), "accent": (255, 112, 54),
        "cool": (116, 143, 255), "text": (255, 231, 190),
    },
    "day": {
        "sky": (2, 12, 25), "horizon": (4, 48, 76), "accent": (255, 200, 42),
        "cool": (43, 183, 255), "text": (230, 249, 255),
    },
    "dusk": {
        "sky": (12, 5, 27), "horizon": (91, 17, 67), "accent": (255, 100, 39),
        "cool": (147, 92, 255), "text": (255, 225, 205),
    },
    "night": {
        "sky": (1, 4, 14), "horizon": (5, 14, 39), "accent": (174, 139, 255),
        "cool": (62, 157, 255), "text": (218, 231, 255),
    },
}

BLACK = (0, 0, 0)
WHITE = (245, 248, 255)
GREY = (102, 117, 137)
LIGHT_GREY = (177, 190, 204)
SUN = (255, 196, 36)
SUN_LIGHT = (255, 239, 157)
MOON = (219, 229, 255)
CLOUD = (165, 181, 199)
CLOUD_LIGHT = (221, 230, 238)
RAIN = (36, 151, 255)
RAIN_LIGHT = (126, 220, 255)
SNOW = (229, 243, 255)
STORM = (145, 94, 255)
ALERT = (255, 90, 63)


# A compact, deliberately limited bitmap alphabet. All UI copy rendered by this
# module is uppercase and measured before drawing, so it can never overlap the
# fixed clock/weather regions.
FONT_3X5 = {
    " ": ("000",) * 5,
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("111", "100", "101", "101", "111"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "111"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"),
    "Q": ("111", "101", "101", "111", "001"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("111", "100", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    ":": ("0", "1", "0", "1", "0"),
    "%": ("101", "001", "010", "100", "101"),
    "-": ("000", "000", "111", "000", "000"),
    "+": ("010", "010", "111", "010", "010"),
    "/": ("001", "001", "010", "100", "100"),
    ".": ("0", "0", "0", "0", "1"),
    "°": ("11", "11", "00", "00", "00"),
    "?": ("111", "001", "011", "000", "010"),
    "<": ("001", "010", "100", "010", "001"),
    ">": ("100", "010", "001", "010", "100"),
    "'": ("1", "1", "0", "0", "0"),
}


@dataclass(frozen=True)
class SceneResult:
    """A rendered payload and the information needed to deduplicate it."""

    frames: tuple[bytes, ...]
    delay_cs: int
    signature: str
    condition: str
    variant: int
    phase: str
    temperature: int
    unit: str
    city: str
    delays_cs: tuple[int, ...] = ()
    revision: str = SCENE_REVISION

    def gif(self) -> bytes:
        return encode_rgb_gif(self.frames, self.delays_cs or self.delay_cs)


@dataclass(frozen=True)
class SnapshotResult:
    """A non-looping visual snapshot with a stable semantic signature."""

    frames: tuple[bytes, ...]
    signature: str
    revision: str = SCENE_REVISION

    def gif(self) -> bytes:
        return encode_rgb_gif(self.frames, 100, loop=False)


def _as_datetime(value, name):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"invalid {name}") from error
    raise TypeError(f"{name} must be a datetime or ISO-8601 string")


def _same_awareness(*values):
    awareness = {value.tzinfo is not None and value.utcoffset() is not None for value in values}
    if len(awareness) != 1:
        raise ValueError("now, sunrise and sunset must share timezone awareness")


def solar_phase(now, sunrise, sunset, transition_minutes=SOLAR_TRANSITION_MINUTES):
    """Return dawn/day/dusk/night around sunrise and sunset ±45 minutes."""
    now = _as_datetime(now, "now")
    sunrise = _as_datetime(sunrise, "sunrise")
    sunset = _as_datetime(sunset, "sunset")
    _same_awareness(now, sunrise, sunset)
    if sunset <= sunrise:
        raise ValueError("sunset must be later than sunrise")
    window = timedelta(minutes=int(transition_minutes))
    if sunrise - window <= now < sunrise + window:
        return "dawn"
    if sunrise + window <= now < sunset - window:
        return "day"
    if sunset - window <= now < sunset + window:
        return "dusk"
    return "night"


def _round_temperature(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("temperature must be finite")
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def display_temperature(temperature_c, unit="celsius"):
    """Return the displayed integer and suffix, with no leading plus sign."""
    if unit not in {"celsius", "fahrenheit", "c", "f"}:
        raise ValueError("unit must be celsius or fahrenheit")
    fahrenheit = unit in {"fahrenheit", "f"}
    value = float(temperature_c) * 9 / 5 + 32 if fahrenheit else float(temperature_c)
    rounded = _round_temperature(value)
    suffix = "F" if fahrenheit else "C"
    return rounded, suffix


def format_temperature(temperature_c, unit="celsius"):
    value, suffix = display_temperature(temperature_c, unit)
    return f"{value}°{suffix}"


def validate_variant(condition, variant):
    if condition not in WEATHER_VARIANTS:
        raise ValueError("unknown weather condition")
    if type(variant) is not int or not 0 <= variant < len(WEATHER_VARIANTS[condition]):
        raise ValueError("unknown weather variant")
    return condition, variant


def visual_signature(condition, variant, temperature_c, unit, phase, city, revision=SCENE_REVISION):
    """Stable signature for all visual inputs that justify a new GIF."""
    validate_variant(condition, variant)
    if phase not in PHASE_PALETTES:
        raise ValueError("unknown solar phase")
    value, suffix = display_temperature(temperature_c, unit)
    payload = {
        "city": str(city or "").strip(), "condition": condition, "phase": phase,
        "revision": str(revision), "temperature": value, "unit": suffix,
        "variant": variant,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Canvas:
    def __init__(self, colour=BLACK):
        self.pixels = [tuple(colour)] * PIXELS

    def pixel(self, x, y, colour):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.pixels[y * WIDTH + x] = tuple(colour)

    def rect(self, x, y, width, height, colour):
        for row in range(max(0, y), min(HEIGHT, y + height)):
            start, end = max(0, x), min(WIDTH, x + width)
            if end > start:
                self.pixels[row * WIDTH + start:row * WIDTH + end] = [tuple(colour)] * (end - start)

    def line(self, x0, y0, x1, y1, colour):
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self.pixel(x0, y0, colour)
            if x0 == x1 and y0 == y1:
                return
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    def circle(self, cx, cy, radius, colour, filled=True):
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                distance = (x - cx) ** 2 + (y - cy) ** 2
                if distance <= radius ** 2 and (filled or distance >= (radius - 1) ** 2):
                    self.pixel(x, y, colour)

    def bytes(self):
        return bytes(channel for pixel in self.pixels for channel in pixel)

    def copy_region_from(self, source, left, top, right, bottom):
        """Copy a clipped rectangle, preserving strict layout boundaries."""
        for y in range(max(0, top), min(HEIGHT, bottom)):
            for x in range(max(0, left), min(WIDTH, right)):
                self.pixels[y * WIDTH + x] = source.pixels[y * WIDTH + x]


def measure_text(text, scale=1):
    widths = [len(FONT_3X5.get(character, FONT_3X5["?"])[0]) for character in str(text).upper()]
    return (sum(widths) + max(0, len(widths) - 1)) * scale


def draw_text(canvas, x, y, text, colour=WHITE, scale=1):
    cursor = int(x)
    for character in str(text).upper():
        glyph = FONT_3X5.get(character, FONT_3X5["?"])
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    canvas.rect(cursor + column * scale, y + row * scale, scale, scale, colour)
        cursor += (len(glyph[0]) + 1) * scale
    return cursor - scale


def draw_text_centered(canvas, y, text, colour=WHITE, scale=1):
    width = measure_text(text, scale)
    draw_text(canvas, (WIDTH - width) // 2, y, text, colour, scale)


def _phase_background(canvas, phase, dashboard=False):
    palette = PHASE_PALETTES[phase]
    canvas.rect(0, 0, WIDTH, HEIGHT, BLACK)
    if dashboard:
        canvas.rect(0, 18, WIDTH, 25, palette["sky"])
    else:
        canvas.rect(0, 8, WIDTH, 38, palette["sky"])
    canvas.rect(0, 43 if dashboard else 45, WIDTH, 2, palette["horizon"])
    # Sparse points keep the ambience alive without filling the matrix.
    points = ((4, 21), (15, 31), (25, 20), (41, 29), (56, 23))
    for index, (x, y) in enumerate(points):
        if phase == "night" or (phase in {"dawn", "dusk"} and index % 2 == 0):
            canvas.pixel(x, y, palette["cool"])


def _draw_sun(canvas, cx, cy, tick, variant):
    radius = 7 + (1 if variant == 1 and tick % 4 in {1, 2} else 0)
    canvas.circle(cx, cy, radius, SUN)
    canvas.circle(cx - 2, cy - 2, 2, SUN_LIGHT)
    ray = 10 + (tick % 2 if variant == 0 else 0)
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0), (1, 1), (-1, 1), (1, -1), (-1, -1)):
        canvas.line(cx + dx * ray, cy + dy * ray, cx + dx * (ray + 2), cy + dy * (ray + 2), SUN_LIGHT)


def _draw_moon(canvas, cx, cy, tick, variant):
    radius = 8 + (1 if variant == 1 and tick % 4 == 2 else 0)
    canvas.circle(cx, cy, radius, MOON)
    canvas.circle(cx + 4, cy - 3, radius - 2, PHASE_PALETTES["night"]["sky"])
    if variant == 0 and tick % 4 in {1, 2}:
        canvas.pixel(cx - 7, cy - 7, WHITE)


def _draw_cloud(canvas, cx, cy, colour=CLOUD, light=CLOUD_LIGHT, width=0):
    canvas.rect(cx - 11 - width, cy, 23 + width * 2, 6, colour)
    canvas.circle(cx - 6 - width, cy, 6, colour)
    canvas.circle(cx + 1, cy - 3, 8, light)
    canvas.circle(cx + 8 + width, cy, 5, colour)


def _draw_rain(canvas, cx, cy, tick, variant):
    _draw_cloud(canvas, cx, cy - 7, CLOUD, CLOUD_LIGHT)
    offsets = (-8, 0, 8) if variant == 0 else (-10, -3, 5, 11)
    for index, offset in enumerate(offsets):
        fall = (tick * 2 + index * 3) % 7
        canvas.line(cx + offset, cy + 2 + fall, cx + offset - 2, cy + 6 + fall, RAIN_LIGHT if index % 2 else RAIN)


def _draw_snow(canvas, cx, cy, tick, variant):
    _draw_cloud(canvas, cx, cy - 8, CLOUD, CLOUD_LIGHT)
    flakes = ((-10, 2), (-3, 6), (5, 1), (11, 7), (0, 12), (8, 15))
    count = len(flakes) if variant else 4
    for index, (dx, base) in enumerate(flakes[:count]):
        y = cy + 2 + ((base + tick + index) % 16)
        canvas.pixel(cx + dx, y, SNOW)
        if (index + tick) % 3 == 0:
            canvas.pixel(cx + dx + 1, y, SNOW)


def _draw_storm(canvas, cx, cy, tick, variant):
    _draw_cloud(canvas, cx, cy - 8, (88, 91, 120), (130, 133, 158), width=1)
    if (tick + variant) % (4 if variant else 5) in {0, 1}:
        bolt = ALERT if variant else SUN_LIGHT
        canvas.line(cx + 2, cy, cx - 2, cy + 8, bolt)
        canvas.line(cx - 2, cy + 8, cx + 2, cy + 8, bolt)
        canvas.line(cx + 2, cy + 8, cx - 4, cy + 18, bolt)


def draw_weather_sprite(canvas, condition, variant, elapsed, cx=20, cy=28):
    """Draw one of all 22 mapped weather variants inside a 30 x 32 region."""
    validate_variant(condition, variant)
    loop = weather_loop_seconds(condition, variant)
    tick = int((max(0.0, float(elapsed)) % loop) * 5)
    if condition == "clear_day":
        _draw_sun(canvas, cx, cy, tick, variant)
    elif condition == "clear_night":
        _draw_moon(canvas, cx, cy, tick, variant)
    elif condition == "rain":
        _draw_rain(canvas, cx, cy, tick, variant)
    elif condition in {"cloud", "cloud_night"}:
        travel = (-3 + tick % 7) if variant in {0, 1} else (-2 + tick % 5)
        width = 1 if variant == 3 else 0
        colour = CLOUD if condition == "cloud" else GREY
        light = CLOUD_LIGHT if condition == "cloud" else LIGHT_GREY
        _draw_cloud(canvas, cx + travel, cy, colour, light, width)
        if variant == 1:
            # The plural native variant has a second, offset pass rather than
            # merely changing its label while producing identical pixels.
            _draw_cloud(canvas, cx - 10 - travel // 2, cy + 7, colour, light)
    elif condition in {"breaks", "breaks_night"}:
        if condition == "breaks":
            _draw_sun(canvas, cx - 6, cy - 5, tick, variant)
        else:
            _draw_moon(canvas, cx - 6, cy - 5, tick, variant)
        cloud_x = cx + (2 if variant == 0 else min(7, tick % 9))
        _draw_cloud(canvas, cloud_x, cy + 4)
    elif condition == "snow":
        _draw_snow(canvas, cx, cy, tick, variant)
    else:
        _draw_storm(canvas, cx, cy, tick, variant)


def _draw_temperature(canvas, x, y, temperature_c, unit, colour):
    value, suffix = display_temperature(temperature_c, unit)
    number = str(value)
    scale = 2 if measure_text(number, 2) + measure_text("°" + suffix, 1) + 2 <= WIDTH - x else 1
    end = draw_text(canvas, x, y, number, colour, scale)
    unit_y = y + (5 * scale - 5)
    draw_text(canvas, end + 2, unit_y, "°" + suffix, colour, 1)
    return value, suffix


def render_weather_frame(condition, variant, elapsed, temperature_c, unit="celsius", phase="day"):
    """Render an expressive Weather frame with a non-overlapping temperature."""
    validate_variant(condition, variant)
    if phase not in PHASE_PALETTES:
        raise ValueError("unknown solar phase")
    canvas = Canvas()
    _phase_background(canvas, phase)
    draw_weather_sprite(canvas, condition, variant, elapsed, cx=20, cy=28)
    _draw_temperature(canvas, 38, 20, temperature_c, unit, PHASE_PALETTES[phase]["text"])
    return canvas.bytes()


def _fit_context(text, max_width=60):
    cleaned = " ".join(str(text or "").upper().split())
    output = ""
    for character in cleaned:
        candidate = output + character
        if measure_text(candidate) > max_width:
            break
        output = candidate
    return output.rstrip()


def normalize_faceplate_status(status=None):
    """Reduce an untrusted runtime snapshot to stable renderer inputs."""
    value = status if isinstance(status, dict) else {}
    recording = str(value.get("recording", "unknown"))
    if recording not in {"active", "inactive", "unknown"}:
        recording = "unknown"
    recent_event = str(value.get("recent_event", ""))
    if recent_event not in {"notification", "achievement", "screenshot"}:
        recent_event = ""
    return {
        "recording": recording,
        "recording_sequence": max(0, int(value.get("recording_sequence", 0) or 0)),
        "recent_event": recent_event,
        "event_sequence": max(0, int(value.get("event_sequence", 0) or 0)) if recent_event else 0,
    }


def normalize_faceplate_battery(battery=None):
    """Keep only coarse, truthful P1 telemetry for the eight-pixel rail."""
    if not isinstance(battery, dict):
        return None
    try:
        level = max(0, min(4, int(battery.get("level", 0))))
        percent = max(0, min(100, int(battery.get("percent", 0))))
    except (TypeError, ValueError, OverflowError):
        return None
    return {
        "level": level,
        "percent": percent,
        "charging": battery.get("charging") is True,
    }


def status_rail_identity(status=None, battery=None, fallback="", session_text=""):
    """Return the exact semantic identity of pixels drawn by the rail."""
    return {
        "status": normalize_faceplate_status(status),
        "battery": normalize_faceplate_battery(battery),
        "fallback": str(fallback or ""),
        "session": str(session_text or ""),
    }


def _draw_status_battery(canvas, battery, y=47):
    battery = normalize_faceplate_battery(battery)
    if battery is None:
        return
    colour = (
        (80, 236, 142) if battery["level"] >= 2
        else (255, 178, 52) if battery["level"] else (255, 72, 76)
    )
    draw_text(canvas, 43, y, "P1", (228, 241, 255))
    left = 52
    canvas.rect(left, y, 10, 5, (228, 241, 255))
    canvas.rect(left + 10, y + 1, 1, 3, (228, 241, 255))
    canvas.rect(left + 1, y + 1, 8, 3, (3, 7, 14))
    for index in range(battery["level"]):
        canvas.rect(left + 1 + index * 2, y + 2, 2, 1, colour)
    if battery["charging"]:
        canvas.pixel(left + 5, y + 1, (125, 220, 255))


def _draw_status_event_icon(canvas, kind, x, y, colour):
    """Draw one unmistakable 6 x 5 event pictogram inside the left rail."""
    if kind == "notification":
        # Bell: a narrow dome, body and isolated clapper.
        canvas.line(x + 2, y, x + 3, y, colour)
        canvas.line(x + 1, y + 1, x + 4, y + 1, colour)
        canvas.line(x, y + 2, x + 5, y + 2, colour)
        canvas.line(x, y + 3, x + 5, y + 3, colour)
        canvas.line(x + 2, y + 4, x + 3, y + 4, colour)
    elif kind == "achievement":
        # Trophy cup with a single-pixel stem.
        canvas.line(x + 1, y, x + 4, y, colour)
        canvas.line(x, y + 1, x + 5, y + 1, colour)
        canvas.line(x + 1, y + 2, x + 4, y + 2, colour)
        canvas.line(x + 2, y + 3, x + 3, y + 3, colour)
        canvas.line(x + 1, y + 4, x + 4, y + 4, colour)
    elif kind == "screenshot":
        # Four corners remain readable after optical inter-diffusion.
        canvas.line(x, y, x + 2, y, colour)
        canvas.line(x, y, x, y + 2, colour)
        canvas.line(x + 3, y, x + 5, y, colour)
        canvas.line(x + 5, y, x + 5, y + 2, colour)
        canvas.line(x, y + 2, x, y + 4, colour)
        canvas.line(x, y + 4, x + 2, y + 4, colour)
        canvas.line(x + 5, y + 2, x + 5, y + 4, colour)
        canvas.line(x + 3, y + 4, x + 5, y + 4, colour)


def draw_status_rail(canvas, status=None, *, battery=None, fallback="",
                     session_text="", background=BLACK, y=45):
    """Draw one truthful primary state plus optional fresh P1 telemetry.

    REC has priority, then one recent event, then session/fallback text.  Fixed
    left and right boxes make overlap impossible on the 64 x 54 matrix.
    """
    status = normalize_faceplate_status(status)
    battery = normalize_faceplate_battery(battery)
    canvas.rect(0, y, WIDTH, HEIGHT - y, background)
    label = ""
    colour = (171, 218, 255)
    if status["recording"] == "active":
        canvas.circle(3, y + 4, 2, (238, 50, 68))
        label, colour = "REC", (246, 250, 255)
        draw_text(canvas, 7, y + 3, label, colour)
    elif status["recent_event"]:
        label = {
            "notification": "NOTE",
            "achievement": "WIN",
            "screenshot": "SHOT",
        }[status["recent_event"]]
        colour = {
            "notification": (77, 213, 255),
            "achievement": (255, 202, 68),
            "screenshot": (231, 242, 255),
        }[status["recent_event"]]
        _draw_status_event_icon(canvas, status["recent_event"], 2, y + 2, colour)
        draw_text(canvas, 10, y + 3, label, colour)
    elif session_text:
        draw_text(canvas, 2, y + 3, _fit_context(session_text, 38 if battery else 60), colour)
    elif fallback:
        fitted = _fit_context(fallback, 38 if battery else 60)
        if battery:
            draw_text(canvas, 2, y + 3, fitted, colour)
        else:
            draw_text_centered(canvas, y + 3, fitted, colour)
    _draw_status_battery(canvas, battery, y + 3)
    return status_rail_identity(
        status, battery, fallback=fallback, session_text=session_text,
    )


def select_dashboard_context(now, phase, sunrise, sunset, precipitation_probability=None):
    """Select exactly one short secondary datum for the dashboard."""
    now = _as_datetime(now, "now")
    sunrise = _as_datetime(sunrise, "sunrise")
    sunset = _as_datetime(sunset, "sunset")
    if precipitation_probability is not None:
        chance = max(0, min(100, _round_temperature(precipitation_probability)))
        if chance >= 30:
            return f"RAIN {chance}%"
    if phase in {"dawn", "day"} and now < sunset:
        return "SUNSET " + sunset.strftime("%H:%M")
    if phase in {"dusk", "night"}:
        next_rise = sunrise if now < sunrise else sunrise + timedelta(days=1)
        return "DAWN " + next_rise.strftime("%H:%M")
    return now.strftime("%a %d %b").upper()


def render_dashboard_frame(
    now, condition, variant, temperature_c, unit, sunrise, sunset, city="",
    precipitation_probability=None, context=None, clock_24h=True, phase=None,
    status=None, battery=None,
):
    """Render HH:MM, one compact weather group, and one contextual line."""
    now = _as_datetime(now, "now")
    sunrise = _as_datetime(sunrise, "sunrise")
    sunset = _as_datetime(sunset, "sunset")
    validate_variant(condition, variant)
    phase = phase or solar_phase(now, sunrise, sunset)
    if phase not in PHASE_PALETTES:
        raise ValueError("unknown solar phase")
    canvas = Canvas()
    _phase_background(canvas, phase, dashboard=True)

    if clock_24h:
        clock = now.strftime("%H:%M")
    else:
        clock = now.strftime("%I:%M").lstrip("0") or "0:00"
    clock_scale = 3 if measure_text(clock, 3) <= 60 else 2
    draw_text_centered(canvas, 1, clock, PHASE_PALETTES[phase]["text"], clock_scale)

    # Compact, fixed boxes: sprite x=2..27, temperature x=30..62,
    # context y=48..52. They never intersect regardless of the data.
    sprite = Canvas()
    draw_weather_sprite(sprite, condition, variant, 0, cx=14, cy=31)
    canvas.copy_region_from(sprite, 0, 18, 29, 45)
    _draw_temperature(canvas, 30, 27, temperature_c, unit, PHASE_PALETTES[phase]["text"])
    label = context if context is not None else select_dashboard_context(
        now, phase, sunrise, sunset, precipitation_probability,
    )
    draw_status_rail(
        canvas, status, battery=battery, fallback=label,
        background=BLACK, y=45,
    )
    return canvas.bytes()


def encode_rgb_gif(frames: Iterable[bytes], delay_cs, *, loop=True,
                   colours=32, max_frames=MAX_HOUR_PACK_FRAMES,
                   max_bytes=MAX_SCENE_GIF_BYTES):
    frames = tuple(bytes(frame) for frame in frames)
    max_frames = int(max_frames)
    if not frames or len(frames) > max_frames:
        raise ValueError(f"GIF must contain between 1 and {max_frames} frames")
    if any(len(frame) != PIXELS * 3 for frame in frames):
        raise ValueError("every frame must be RGB 64 x 54")
    if isinstance(delay_cs, (list, tuple)):
        delays = tuple(int(value) for value in delay_cs)
        if len(delays) != len(frames) or any(not 1 <= value <= 65535 for value in delays):
            raise ValueError("GIF frame delays must match frames and fit centiseconds")
    else:
        delays = int(delay_cs)
        if not 1 <= delays <= 65535:
            raise ValueError("GIF delay must fit the GIF centisecond field")
    palette, indexed = quantize(b"".join(frames), colours=int(colours))
    frame_size = PIXELS
    indexed_frames = [indexed[offset:offset + frame_size]
                      for offset in range(0, len(indexed), frame_size)]
    payload = encode_indexed_gif(
        WIDTH, HEIGHT, palette, indexed_frames, delays, loop=bool(loop),
    )
    if len(payload) > int(max_bytes):
        raise ValueError("faceplate scene GIF exceeds the software safety limit")
    return payload


def build_weather_scene(
    condition, variant, temperature_c, unit, phase, city="", revision=SCENE_REVISION,
    frame_count=MAX_WEATHER_FRAMES,
):
    validate_variant(condition, variant)
    if phase not in PHASE_PALETTES:
        raise ValueError("unknown solar phase")
    frame_count = int(frame_count)
    if not 1 <= frame_count <= MAX_WEATHER_FRAMES:
        raise ValueError("weather scene must contain between 1 and 32 frames")
    loop = weather_loop_seconds(condition, variant)
    frames = tuple(render_weather_frame(
        condition, variant, index * loop / frame_count, temperature_c, unit, phase,
    ) for index in range(frame_count))
    delay_cs = max(1, round(loop * 100 / frame_count))
    value, suffix = display_temperature(temperature_c, unit)
    return SceneResult(
        frames=frames, delay_cs=delay_cs,
        signature=visual_signature(condition, variant, temperature_c, unit, phase, city, revision),
        condition=condition, variant=variant, phase=phase, temperature=value,
        unit=suffix, city=str(city or "").strip(), revision=str(revision),
    )


def build_dashboard_hour_pack(
    hour, condition, variant, temperature_c, unit, sunrise, sunset, city="",
    precipitation_probability=None, context=None, clock_24h=True,
    revision=SCENE_REVISION, status=None, battery=None,
):
    """Build the experimental 60-frame/60-second clock pack, without upload.

    The hour is normalised to minute zero. A transport must not call this API
    continuously: its purpose is to make one prospective hour-long payload that
    can be validated for panel drift and flash policy independently.
    """
    requested_at = _as_datetime(hour, "hour")
    hour = requested_at.replace(second=0, microsecond=0)
    sunrise = _as_datetime(sunrise, "sunrise")
    sunset = _as_datetime(sunset, "sunset")
    frames = []
    phases = []
    for minute in range(MAX_HOUR_PACK_FRAMES):
        instant = hour + timedelta(minutes=minute)
        phase = solar_phase(instant, sunrise, sunset)
        phases.append(phase)
        frames.append(render_dashboard_frame(
            instant, condition, variant, temperature_c, unit, sunrise, sunset,
            city=city, precipitation_probability=precipitation_probability,
            context=context, clock_24h=clock_24h, phase=phase,
            status=status, battery=battery,
        ))
    value, suffix = display_temperature(temperature_c, unit)
    signature_payload = {
        "base": visual_signature(condition, variant, temperature_c, unit, phases[0], city, revision),
        "clock_24h": bool(clock_24h), "context": str(context or ""),
        "hour": hour.isoformat(), "phases": phases,
        "precipitation_probability": precipitation_probability,
        "rail": status_rail_identity(status, battery, fallback=str(context or "")),
    }
    signature = hashlib.sha256(json.dumps(
        signature_payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    first_delay = max(1, min(6000, round(
        (60.0 - requested_at.second - requested_at.microsecond / 1_000_000) * 100,
    )))
    return SceneResult(
        frames=tuple(frames), delay_cs=6000, signature=signature,
        condition=condition, variant=variant, phase=phases[0], temperature=value,
        unit=suffix, city=str(city or "").strip(),
        delays_cs=(first_delay,) + (6000,) * (MAX_HOUR_PACK_FRAMES - 1),
        revision=str(revision),
    )


def build_dashboard_snapshot(
    instant, condition, variant, temperature_c, unit, sunrise, sunset, city="",
    precipitation_probability=None, context=None, clock_24h=True,
    revision=SCENE_REVISION, status=None, battery=None,
):
    """Build one persistent clock frame with no GIF loop or backward jump.

    The scheduler predicts the minute that will be visible after the serial ACK.
    Keeping a single frame makes the panel hold that value until the next
    ACK-paced update; the firmware can therefore never wrap to an older minute.
    """
    instant = _as_datetime(instant, "instant").replace(second=0, microsecond=0)
    sunrise = _as_datetime(sunrise, "sunrise")
    sunset = _as_datetime(sunset, "sunset")
    phase = solar_phase(instant, sunrise, sunset)
    frame = render_dashboard_frame(
        instant, condition, variant, temperature_c, unit, sunrise, sunset,
        city=city, precipitation_probability=precipitation_probability,
        context=context, clock_24h=clock_24h, phase=phase,
        status=status, battery=battery,
    )
    value, suffix = display_temperature(temperature_c, unit)
    identity = {
        "base": visual_signature(
            condition, variant, temperature_c, unit, phase, city, revision,
        ),
        "clock_24h": bool(clock_24h), "context": str(context or ""),
        "instant": instant.isoformat(),
        "precipitation_probability": precipitation_probability,
        "rail": status_rail_identity(status, battery, fallback=str(context or "")),
    }
    signature = hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return SceneResult(
        frames=(frame,), delay_cs=100, signature=signature,
        condition=condition, variant=variant, phase=phase, temperature=value,
        unit=suffix, city=str(city or "").strip(), revision=str(revision),
    )


def _bounded_metric(value, minimum=0.0, maximum=100.0):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("performance metric must be finite")
    return max(minimum, min(maximum, value))


def render_performance_frame(cpu_load, gpu_load, cpu_temp_c, gpu_temp_c):
    """Compatibility name only; CPU/GPU is no longer a matrix feature."""
    raise ValueError("CPU/GPU display has been removed from the Faceplate")


def build_performance_snapshot(cpu_load, gpu_load, cpu_temp_c, gpu_temp_c,
                               revision=SCENE_REVISION):
    """Compatibility name only; no hidden legacy matrix renderer."""
    raise ValueError("CPU/GPU display has been removed from the Faceplate")


def frame_colours(frame: Sequence[int]):
    """Return the RGB colours used by a frame; useful for preview validation."""
    frame = bytes(frame)
    if len(frame) != PIXELS * 3:
        raise ValueError("frame must be RGB 64 x 54")
    return {tuple(frame[index:index + 3]) for index in range(0, len(frame), 3)}


def build_weather_unavailable(payload):
    """Safe static fallback with no fabricated weather facts or solar times."""
    from .artwork_dashboard import build_artwork_dashboard
    canvas = Canvas((2, 7, 14))
    draw_text(canvas, 28, 25, "--", (125, 152, 181))
    return build_artwork_dashboard(
        (canvas.bytes(),), payload["display_at"], payload.get("session_minutes", 0),
        weather={"condition": "", "temperature_c": None}, forecast={},
        unit=payload.get("unit", "celsius"),
        show_clock=payload.get("dashboard_show_clock", False),
        clock_24h=payload.get("clock_24h", True),
        show_status_rail=payload.get("dashboard_show_status_rail", True),
        show_weather_notch=payload.get("show_weather_notch", True),
        bottom_mode=payload.get("bottom_mode", "next_hour"),
        controllers=payload.get("controllers", ()),
        battery_style=payload.get("battery_style", "percent"),
        game_running=payload.get("game_running", False),
        game_row=payload.get("game_row", "existing"),
        game_stats=payload.get("game_stats"), countdown=payload.get("countdown"),
        battery=payload.get("battery"), status=payload.get("status"),
        show_p2=payload.get("show_p2", False),
        connected_controller_count=payload.get("connected_controller_count"),
        clock_position=payload.get("clock_position", "left"),
        weather_position=payload.get("weather_position", "right"),
        ux_enabled=payload.get("ux_enabled", False),
    )
