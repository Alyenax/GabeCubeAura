# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Dynamic renderers for the three Faceplate V2 candidate collections.

The catalogue GIFs are design fixtures.  This module applies the same visual
grammar to live Weather, Dashboard and Performance values so choosing a V2
collection changes the real faceplate rather than only Pixel Studio previews.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math

from signalbar.faceplate.scenes import (
    BLACK,
    HEIGHT,
    PHASE_PALETTES,
    WIDTH,
    Canvas,
    SceneResult,
    SnapshotResult,
    display_temperature,
    draw_status_rail,
    draw_text,
    draw_text_centered,
    measure_text,
    select_dashboard_context,
    solar_phase,
    status_rail_identity,
    validate_variant,
)
V2_SCENE_REVISION = "faceplate-v2-runtime-2"
V2_THEMES = ("night-paper", "sun-cut", "winter-loom")

WHITE = (242, 246, 240)
BONE = (248, 226, 177)
PALE = (210, 225, 230)
CLOUD = (135, 151, 162)
CLOUD_LIGHT = (205, 216, 220)
SUN = (255, 183, 42)
SUN_LIGHT = (255, 235, 151)
RAIN = (43, 153, 226)
RAIN_LIGHT = (117, 212, 245)
SNOW = (231, 242, 240)
ALERT = (240, 72, 45)

FONT_5X7 = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    ":": ("0", "1", "0", "0", "1", "0", "0"),
    "-": ("000", "000", "000", "111", "000", "000", "000"),
    "%": ("10001", "00010", "00100", "00100", "01000", "10001", "00000"),
}


def _theme(value):
    value = str(value or "").strip().lower()
    if value not in V2_THEMES:
        raise ValueError("unknown V2 faceplate theme")
    return value


def _instant(value, name="instant"):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"invalid {name}") from error
    raise TypeError(f"{name} must be a datetime or ISO-8601 string")


def _signature(kind, theme, values):
    payload = {"kind": kind, "revision": V2_SCENE_REVISION, "theme": theme, **values}
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _bounded(value, minimum=0.0, maximum=100.0):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("performance metric must be finite")
    return max(minimum, min(maximum, value))


def _draw_5x7(canvas, x, y, text, colour, scale=1, spacing=1):
    cursor = x
    for character in str(text):
        glyph = FONT_5X7[character]
        width = len(glyph[0])
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    canvas.rect(cursor + column * scale, y + row * scale, scale, scale, colour)
        cursor += width * scale + spacing
    return cursor - spacing


def _measure_5x7(text, scale=1, spacing=1):
    return sum(len(FONT_5X7[char][0]) * scale for char in str(text)) + max(0, len(str(text)) - 1) * spacing


def _draw_temperature(canvas, value, suffix, x, y, colour=WHITE, accent=PALE, scale=2):
    end = draw_text(canvas, x, y, str(value), colour, scale)
    draw_text(canvas, end + 2, y + 5 * scale - 5, f"°{suffix}", accent)


def _draw_temperature_centered(canvas, value, suffix, y, colour=WHITE, accent=PALE, scale=2):
    width = measure_text(str(value), scale) + 2 + measure_text(f"°{suffix}")
    _draw_temperature(canvas, value, suffix, (WIDTH - width) // 2, y, colour, accent, scale)


def _draw_cloud_round(canvas, cx, cy, dark=CLOUD, light=CLOUD_LIGHT, wide=0):
    canvas.rect(cx - 10 - wide, cy, 21 + wide * 2, 5, dark)
    canvas.circle(cx - 6 - wide, cy, 5, dark)
    canvas.circle(cx, cy - 3, 7, light)
    canvas.circle(cx + 7 + wide, cy, 5, dark)


def _draw_cloud_cut(canvas, cx, cy, dark=CLOUD, light=CLOUD_LIGHT, width=22):
    half = width // 2
    canvas.rect(cx - half, cy - 1, width, 7, dark)
    canvas.rect(cx - half + 3, cy - 5, width - 9, 5, light)
    canvas.rect(cx - half + 7, cy - 8, width - 15, 4, light)
    canvas.rect(cx - half - 2, cy + 2, 5, 3, dark)


def _draw_cloud_woven(canvas, cx, cy, dark=CLOUD, light=CLOUD_LIGHT):
    for x, y, colour in (
        (-10, 0, dark), (-8, -2, dark), (-6, -4, light), (-4, -6, light),
        (-2, -6, light), (0, -8, light), (2, -8, light), (4, -6, light),
        (6, -4, dark), (8, -2, dark), (10, 0, dark), (-6, 2, dark),
        (-2, 2, light), (2, 2, light), (6, 2, dark),
    ):
        canvas.rect(cx + x, cy + y, 4, 4, colour)


def _draw_sun(canvas, cx, cy, radius=7, tick=0, cut=False, highlight=SUN_LIGHT):
    if cut:
        canvas.rect(cx - radius, cy - radius + 2, radius * 2 + 1, radius * 2 - 3, SUN)
        canvas.rect(cx - radius + 2, cy - radius, radius * 2 - 3, radius * 2 + 1, SUN)
        canvas.rect(cx - 2, cy - 2, 4, 4, highlight)
    else:
        canvas.circle(cx, cy, radius, SUN)
        canvas.circle(cx - 2, cy - 2, 2, highlight)
    ray = radius + 3 + (tick % 2)
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0), (1, 1), (-1, 1), (1, -1), (-1, -1)):
        canvas.line(cx + dx * ray, cy + dy * ray, cx + dx * (ray + 1), cy + dy * (ray + 1), highlight)


def _draw_moon(canvas, cx, cy, radius=8, background=BLACK, woven=False):
    if woven:
        for row in range(-radius, radius + 1, 2):
            extent = int(math.sqrt(max(0, radius * radius - row * row)))
            canvas.rect(cx - extent, cy + row, extent * 2 + 1, 2, PALE)
    else:
        canvas.circle(cx, cy, radius, PALE)
    canvas.circle(cx + 4, cy - 3, max(1, radius - 2), background)


def _star(canvas, x, y, colour=PALE):
    for px, py in ((x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        canvas.pixel(px, py, colour)


def _offsets(condition, variant, index, frame_count):
    phase = index / frame_count
    wave = math.sin(phase * math.tau)
    breathe = (1 - math.cos(phase * math.tau)) / 2
    if condition in {"cloud", "cloud_night"}:
        if variant == 0:
            return (round(4 * wave),)
        if variant == 1:
            return (round(4 * wave), round(-3 * wave))
        if variant == 2:
            return (round(6 * wave), round(-6 * wave))
        return (-3 + round(3 * breathe), 3 - round(3 * breathe))
    if condition in {"breaks", "breaks_night"}:
        return (round(5 * breathe) if variant else round(2 * wave),)
    return (0,)


def _weather_paper(condition, variant, index, frame_count, temperature, suffix):
    canvas = Canvas(BLACK)
    night = condition in {"clear_night", "cloud_night", "breaks_night", "storm"}
    ink = (7, 20, 38) if night else (7, 27, 43)
    points = ((0, 48), (8, 43), (14, 47), (23, 40), (31, 47), (40, 42), (51, 47), (58, 41), (63, 45))
    for left, right in zip(points, points[1:]):
        canvas.line(*left, *right, ink)
    canvas.rect(0, 48, 64, 6, ink)
    if night:
        for x, y in ((5, 9), (28, 6), (34, 13), (58, 8)):
            canvas.pixel(x, y, CLOUD)
    tick = index % frame_count
    if condition == "clear_day":
        _draw_sun(canvas, 18, 25, 8 + (1 if variant and tick in {2, 3} else 0), tick)
    elif condition == "clear_night":
        _draw_moon(canvas, 18, 24, 9 + (1 if variant and tick == 2 else 0), BLACK)
    elif condition in {"cloud", "cloud_night"}:
        tones = ((75, 91, 104), (171, 186, 194)) if night else (CLOUD, CLOUD_LIGHT)
        for layer, offset in enumerate(_offsets(condition, variant, index, frame_count)):
            _draw_cloud_round(canvas, 18 + offset, 27 + layer * 5, *tones)
    elif condition in {"breaks", "breaks_night"}:
        _draw_moon(canvas, 13, 21, 7, BLACK) if night else _draw_sun(canvas, 13, 21, 7, tick, highlight=SUN)
        _draw_cloud_round(canvas, 21 + _offsets(condition, variant, index, frame_count)[0], 29, CLOUD, CLOUD_LIGHT)
    else:
        dark, light = ((71, 75, 93), (139, 143, 158)) if condition == "storm" else (CLOUD, CLOUD_LIGHT)
        _draw_cloud_round(canvas, 18, 21, dark, light, wide=1)
        if condition == "rain":
            for drop, dx in enumerate(((-8, 0, 8) if variant == 0 else (-10, -3, 4, 11))):
                y = 29 + ((index * 3 + drop * 4) % 12)
                canvas.line(18 + dx, y, 16 + dx, y + 4, RAIN)
        elif condition == "snow":
            xs = (-9, -2, 6) if variant == 0 else (-11, -5, 2, 8, 12)
            for flake, dx in enumerate(xs):
                y = 29 + ((index * 2 + flake * 4) % 15)
                canvas.rect(18 + dx, y, 2, 2, SNOW)
            if variant:
                canvas.rect(5, 47, min(26, index * 4), 1, SNOW)
        elif condition == "storm" and ((variant == 0 and tick in {1, 2}) or (variant == 1 and tick == 1)):
            colour = SUN_LIGHT if variant == 0 else ALERT
            canvas.line(20, 28, 15, 37, colour); canvas.line(15, 37, 19, 37, colour); canvas.line(19, 37, 13, 46, colour)
    _draw_temperature(canvas, temperature, suffix, 38, 20, WHITE, CLOUD, 2)
    return canvas.bytes()


def _weather_cut(condition, variant, index, frame_count, temperature, suffix):
    canvas = Canvas(BLACK)
    night = condition in {"clear_night", "cloud_night", "breaks_night", "storm"}
    tick = index % frame_count
    if condition == "clear_day":
        canvas.circle(9, 27, 17 + (1 if variant and tick == 2 else 0), SUN)
        canvas.rect(0, 27, 26, 4, SUN_LIGHT); canvas.rect(0, 34, 20, 3, (133, 45, 28))
    elif condition == "clear_night":
        canvas.circle(10, 26, 18, PALE); canvas.circle(17, 20, 15, BLACK)
        if tick in {1, 2}:
            _star(canvas, 25, 10, (108, 160, 205))
    elif condition in {"cloud", "cloud_night"}:
        dark = (69, 73, 85) if night else (101, 111, 116)
        light = (137, 143, 151) if night else (216, 210, 188)
        for layer, offset in enumerate(_offsets(condition, variant, index, frame_count)):
            _draw_cloud_cut(canvas, 14 + offset, 24 + layer * 7, dark, light, 27 - layer * 4)
        canvas.line(0, 43, 29, 34, dark)
    elif condition in {"breaks", "breaks_night"}:
        _draw_moon(canvas, 7, 21, 13, BLACK) if night else canvas.circle(5, 21, 14, SUN)
        _draw_cloud_cut(canvas, 18 + _offsets(condition, variant, index, frame_count)[0], 29, (84, 91, 97), (203, 206, 194), 25)
    else:
        _draw_cloud_cut(canvas, 14, 19, (68, 75, 83), (151, 158, 158), 30)
        if condition == "rain":
            for drop, x in enumerate((2, 9, 16, 23, 29)[:3 + variant]):
                y = 28 + ((index * 4 + drop * 5) % 15)
                canvas.line(x, y, x - 4, y + 7, RAIN); canvas.pixel(x - 4, y + 7, RAIN)
        elif condition == "snow":
            for flake, (x, base) in enumerate(((2, 0), (9, 4), (17, 1), (25, 6), (30, 3))):
                if variant == 0 and flake >= 3:
                    break
                y = 28 + ((base + index * 2) % 16)
                canvas.rect(x, y, 3, 2, SNOW)
            if variant:
                canvas.rect(0, 47, min(31, 6 + index * 4), 2, SNOW)
        elif condition == "storm" and ((variant == 0 and tick in {0, 1}) or (variant == 1 and tick == 1)):
            canvas.rect(13, 27, 5, 9, ALERT); canvas.rect(9, 34, 8, 4, ALERT); canvas.rect(8, 37, 5, 10, ALERT)
    value = str(temperature)
    _draw_5x7(canvas, 62 - _measure_5x7(value, 2, 1), 5, value, BONE, 2, 1)
    diagonal = (111, 42, 31) if not night else (46, 71, 91)
    draw_text(canvas, 49, 22, f"°{suffix}", diagonal)
    canvas.line(38, 45, 63, 38, diagonal)
    return canvas.bytes()


def _weather_loom(condition, variant, index, frame_count, temperature, suffix):
    canvas = Canvas(BLACK)
    night = condition in {"clear_night", "cloud_night", "breaks_night", "storm"}
    canvas.rect(0, 0, WIDTH, 3, (6, 25, 40))
    for x in range(2, 63, 8):
        canvas.rect(x, 1, 2, 2, CLOUD if night else (144, 83, 40))
    tick = index % frame_count
    if condition == "clear_day":
        for y in range(-7, 8, 2):
            extent = int(math.sqrt(max(0, 49 - y * y)))
            canvas.rect(32 - extent, 20 + y, extent * 2 + 1, 2, SUN)
        for x, y in ((32, 8), (32, 31), (20, 20), (44, 20)):
            canvas.rect(x - 1, y - 1, 3, 3, SUN)
    elif condition == "clear_night":
        _draw_moon(canvas, 32, 20, 9 + (1 if variant and tick == 2 else 0), BLACK, woven=True)
        for x, y in ((17, 11), (48, 9), (51, 26)):
            canvas.rect(x, y, 2, 2, (92, 163, 202))
    elif condition in {"cloud", "cloud_night"}:
        for layer, offset in enumerate(_offsets(condition, variant, index, frame_count)):
            _draw_cloud_woven(canvas, 32 + offset, 19 + layer * 7, (76, 96, 104) if night else CLOUD, (151, 174, 180) if night else CLOUD_LIGHT)
    elif condition in {"breaks", "breaks_night"}:
        _draw_moon(canvas, 24, 17, 7, BLACK, woven=True) if night else _draw_sun(canvas, 24, 17, 6, tick, cut=True, highlight=SUN)
        _draw_cloud_woven(canvas, 37 + _offsets(condition, variant, index, frame_count)[0], 22, CLOUD, CLOUD_LIGHT)
    else:
        _draw_cloud_woven(canvas, 32, 15, CLOUD, CLOUD_LIGHT)
        if condition == "rain":
            xs = (21, 29, 37) if variant == 0 else (17, 25, 33, 41, 49)
            for drop, x in enumerate(xs):
                y = 24 + ((index * 3 + drop * 5) % 10)
                canvas.rect(x, y, 2, 4, RAIN); canvas.rect(x - 2, y + 4, 2, 2, RAIN)
        elif condition == "snow":
            xs = (21, 31, 41) if variant == 0 else (15, 23, 31, 39, 47)
            for flake, x in enumerate(xs):
                y = 25 + ((index * 2 + flake * 4) % 13)
                canvas.rect(x, y, 2, 2, SNOW); canvas.pixel(x - 1, y + 1, SNOW); canvas.pixel(x + 2, y + 1, SNOW)
            if variant:
                for x in range(14, 15 + index * 5, 4):
                    canvas.rect(x, 39, 3, 2, SNOW)
        elif condition == "storm" and ((variant == 0 and tick in {1, 2}) or (variant == 1 and tick == 1)):
            for x, y in ((33, 22), (31, 26), (29, 30), (31, 30), (29, 34), (27, 36)):
                canvas.rect(x, y, 4, 4, ALERT if variant else SUN)
    _draw_temperature_centered(canvas, temperature, suffix, 42, BONE, CLOUD, 2)
    return canvas.bytes()


def build_v2_weather_scene(theme, condition, variant, temperature_c, unit, phase, city=""):
    theme = _theme(theme)
    validate_variant(condition, int(variant))
    if phase not in PHASE_PALETTES:
        raise ValueError("unknown solar phase")
    variant = int(variant)
    temperature, suffix = display_temperature(temperature_c, unit)
    frame_count = 6 if condition in {"clear_day", "clear_night", "storm"} else 8
    renderer = {"night-paper": _weather_paper, "sun-cut": _weather_cut, "winter-loom": _weather_loom}[theme]
    frames = tuple(renderer(condition, variant, index, frame_count, temperature, suffix) for index in range(frame_count))
    if condition == "storm":
        delays = (18, 18, 35, 55, 65, 120)
    elif condition in {"clear_day", "clear_night"}:
        delays = (38, 38, 48, 38, 38, 90)
    elif condition in {"rain", "snow"}:
        delays = (24,) * frame_count
    else:
        delays = (34,) * (frame_count - 1) + (70,)
    signature = _signature("weather", theme, {
        "city": str(city or "").strip(), "condition": condition, "phase": phase,
        "temperature": temperature, "unit": suffix, "variant": variant,
    })
    return SceneResult(
        frames, delays[0], signature, condition, variant, phase, temperature,
        suffix, str(city or "").strip(), delays, V2_SCENE_REVISION,
    )


def _dashboard_frame(theme, phase, clock, temperature, suffix, status=None,
                     battery=None, context=""):
    canvas = Canvas(BLACK)
    label = f"{temperature}°{suffix}"
    rail_background = BLACK
    if theme == "night-paper":
        colour = {"dawn": BONE, "day": WHITE, "dusk": (246, 188, 147), "night": PALE}[phase]
        draw_text_centered(canvas, 3, clock, colour, 3)
        horizon = {"dawn": (72, 40, 45), "day": (20, 61, 77), "dusk": (80, 29, 47), "night": (10, 29, 51)}[phase]
        rail_background = horizon
        canvas.rect(0, 44, 64, 10, horizon)
        canvas.line(0, 44, 15, 38, horizon); canvas.line(15, 38, 29, 45, horizon); canvas.line(29, 45, 46, 39, horizon); canvas.line(46, 39, 63, 45, horizon)
        canvas.circle(8, 40, 5, SUN) if phase in {"dawn", "day"} else _draw_moon(canvas, 8, 40, 5, BLACK)
        draw_text(canvas, 20, 39, label, (143, 183, 199))
    elif theme == "sun-cut":
        _draw_5x7(canvas, (64 - _measure_5x7(clock, 2, 1)) // 2, 5, clock, BONE, 2, 1)
        disk = SUN if phase in {"dawn", "day"} else (137, 59, 47)
        canvas.circle(-1 if phase in {"dawn", "dusk"} else 64, 47, 16, disk)
        canvas.line(0, 47, 63, 36, (108, 46, 34))
        draw_text(canvas, 4, 45, label, WHITE)
    else:
        x = (WIDTH - measure_text(clock, 3)) // 2
        draw_text(canvas, x + 1, 13, clock, (51, 71, 78), 3); draw_text(canvas, x, 12, clock, BONE, 3)
        for sx in range(4, 61, 7):
            canvas.rect(sx, 4, 3, 2, (117, 59, 39) if phase in {"dawn", "dusk"} else (65, 119, 132))
            canvas.rect(61 - sx, 46, 3, 2, (56, 100, 78))
        draw_text_centered(canvas, 40, label, (159, 196, 200))
    draw_status_rail(
        canvas, status, battery=battery, fallback=context,
        background=rail_background, y=45,
    )
    return canvas.bytes()


def build_v2_dashboard_snapshot(theme, instant, condition, variant, temperature_c, unit,
                                sunrise, sunset, city="", precipitation_probability=None,
                                clock_24h=True, status=None, battery=None):
    theme = _theme(theme)
    validate_variant(condition, int(variant))
    instant = _instant(instant).replace(second=0, microsecond=0)
    sunrise, sunset = _instant(sunrise, "sunrise"), _instant(sunset, "sunset")
    phase = solar_phase(instant, sunrise, sunset)
    context = select_dashboard_context(
        instant, phase, sunrise, sunset, precipitation_probability,
    )
    if clock_24h:
        clock = instant.strftime("%H:%M")
    else:
        clock = instant.strftime("%I:%M").lstrip("0") or "0:00"
    temperature, suffix = display_temperature(temperature_c, unit)
    frame = _dashboard_frame(
        theme, phase, clock, temperature, suffix, status=status, battery=battery,
        context=context,
    )
    signature = _signature("dashboard", theme, {
        "city": str(city or "").strip(), "clock": clock, "condition": condition,
        "instant": instant.isoformat(), "phase": phase,
        "precipitation_probability": precipitation_probability,
        "rail": status_rail_identity(status, battery, fallback=context),
        "temperature": temperature, "unit": suffix, "variant": int(variant),
    })
    return SceneResult(
        (frame,), 100, signature, condition, int(variant), phase, temperature,
        suffix, str(city or "").strip(), (), V2_SCENE_REVISION,
    )


def _performance_frame(theme, cpu, gpu, cpu_temp, gpu_temp):
    raise ValueError("CPU/GPU display has been removed from the Faceplate")


def build_v2_performance_snapshot(theme, cpu_load, gpu_load, cpu_temp_c, gpu_temp_c):
    raise ValueError("CPU/GPU display has been removed from the Faceplate")
