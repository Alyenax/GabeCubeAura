# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Nuit decoupee V3 scenes for the 64 x 54 JSAUX PIXEL faceplate.

V3 uses a wider, structured palette in broad clusters.  Fine information
remains high-contrast because the faceplate diffuser blends isolated pixels.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math

from signalbar.faceplate.scenes import (
    BLACK, HEIGHT, PHASE_PALETTES, WIDTH, Canvas, SceneResult,
    display_temperature, draw_status_rail, draw_text, draw_text_centered,
    measure_text, select_dashboard_context, solar_phase, status_rail_identity,
    validate_variant,
)


V3_SCENE_REVISION = "faceplate-night-paper-v3-runtime-2"
V3_THEME = "night-paper-v3"

# Complete working palette.  A frame deliberately uses a coherent subset.
PALETTE = {
    "ink": BLACK, "deep": (2, 5, 14), "navy": (5, 12, 29),
    "blue_black": (8, 19, 39), "blue_1": (13, 31, 57),
    "blue_2": (24, 52, 82), "blue_3": (42, 79, 111),
    "blue_4": (72, 113, 145), "blue_5": (111, 153, 180),
    "violet_1": (43, 35, 75), "violet_2": (75, 60, 112),
    "violet_3": (119, 96, 155), "lilac": (174, 154, 198),
    "cloud_1": (31, 43, 65), "cloud_2": (57, 72, 96),
    "cloud_3": (91, 108, 132), "cloud_4": (143, 158, 177),
    "paper": (207, 216, 225), "ivory": (244, 231, 199),
    "amber_1": (102, 49, 53), "amber_2": (166, 76, 68),
    "amber_3": (226, 126, 87), "amber_4": (255, 186, 111),
    "rain_1": (31, 91, 145), "rain_2": (55, 142, 198),
    "rain_3": (121, 202, 230), "snow": (226, 239, 239),
    "alert": (246, 78, 52), "green": (104, 184, 150),
    # Phase ramps: ordered, familiar colour harmonies rather than arbitrary
    # intermediate RGB values.  The diffuser blends the shallow 4-6 px bands.
    "dawn_0": (7, 9, 25), "dawn_1": (17, 20, 48),
    "dawn_2": (37, 35, 78), "dawn_3": (70, 52, 105),
    "dawn_4": (111, 73, 119), "dawn_5": (159, 94, 119),
    "dawn_6": (207, 124, 108), "dawn_7": (242, 170, 116),
    "day_0": (3, 14, 34), "day_1": (6, 30, 59),
    "day_2": (10, 52, 88), "day_3": (17, 76, 115),
    "day_4": (30, 101, 139), "day_5": (55, 132, 164),
    "day_6": (91, 163, 188), "day_7": (137, 190, 207),
    "dusk_0": (10, 7, 28), "dusk_1": (29, 17, 55),
    "dusk_2": (55, 28, 79), "dusk_3": (87, 43, 96),
    "dusk_4": (126, 57, 102), "dusk_5": (171, 76, 99),
    "dusk_6": (219, 107, 91), "dusk_7": (247, 154, 99),
    "night_0": (1, 4, 15), "night_1": (3, 8, 26),
    "night_2": (5, 14, 40), "night_3": (8, 22, 55),
    "night_4": (13, 32, 70), "night_5": (23, 43, 86),
    "night_6": (39, 55, 101), "night_7": (59, 68, 113),
}


def _instant(value, name="instant"):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"invalid {name}") from error
    raise TypeError(f"{name} must be a datetime or ISO-8601 string")


def _signature(kind, values):
    payload = {"kind": kind, "revision": V3_SCENE_REVISION, "theme": V3_THEME, **values}
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _check_theme(theme):
    if str(theme or "").strip().lower() != V3_THEME:
        raise ValueError("unknown V3 faceplate theme")


def _sky(canvas, phase, bottom=43):
    bands = tuple(PALETTE[f"{phase}_{index}"] for index in range(8))
    # Eight shallow bands survive quantisation and blend into a smooth-looking
    # ramp behind the physical diffuser.  Boundaries are gently staggered so
    # the result keeps the cut-paper identity instead of looking like stripes.
    for index, colour in enumerate(bands):
        top = round(index * bottom / len(bands))
        lower = round((index + 1) * bottom / len(bands))
        canvas.rect(0, top, WIDTH, max(1, lower - top), colour)
        if index and lower < bottom:
            next_colour = bands[min(index + 1, len(bands) - 1)]
            canvas.line(0, lower, 15, lower - 1, next_colour)
            canvas.line(15, lower - 1, 36, lower + 1, next_colour)
            canvas.line(36, lower + 1, 63, lower, next_colour)


def _moon(canvas, x, y, phase, tick=0):
    canvas.circle(x, y, 8, PALETTE["ivory"])
    canvas.circle(x + 4, y - 3, 7, PALETTE["blue_1"] if phase == "night" else PALETTE["violet_1"])
    if tick % 4 == 1:
        canvas.pixel(x - 5, y - 3, PALETTE["paper"])


def _sun(canvas, x, y, tick=0):
    canvas.circle(x, y, 8, PALETTE["amber_3"])
    canvas.circle(x - 2, y - 2, 4, PALETTE["amber_4"])
    radius = 11 + (tick % 2)
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        canvas.line(x + dx * radius, y + dy * radius, x + dx * (radius + 2), y + dy * (radius + 2), PALETTE["amber_4"])


def _cloud(canvas, x, y, tick=0, night=False, wide=0):
    low = PALETTE["cloud_1"] if night else PALETTE["cloud_2"]
    middle = PALETTE["cloud_2"] if night else PALETTE["cloud_3"]
    high = PALETTE["cloud_3"] if night else PALETTE["cloud_4"]
    canvas.rect(x - 12 - wide, y, 25 + wide * 2, 6, low)
    canvas.circle(x - 7 - wide, y, 6, middle)
    canvas.circle(x, y - 4, 8, high)
    canvas.circle(x + 8 + wide, y, 6, middle)
    canvas.rect(x - 8, y + 4, 17, 2, PALETTE["blue_2"] if tick % 3 == 1 else low)


def _weather_motion(condition, variant, index, count):
    wave = math.sin(index / count * math.tau)
    if condition in {"cloud", "cloud_night", "breaks", "breaks_night"}:
        amount = 2 + min(variant, 2)
        return round(amount * wave), 0
    if condition in {"rain", "snow"}:
        return 0, index % 4
    return 0, index % 2


def _temperature(canvas, value, suffix):
    label = str(value)
    width = measure_text(label, 2) + 2 + measure_text(f"°{suffix}")
    x = 61 - width
    draw_text(canvas, x, 21, label, PALETTE["ivory"], 2)
    draw_text(canvas, x + measure_text(label, 2) + 2, 26, f"°{suffix}", PALETTE["paper"])


def _weather_frame(condition, variant, phase, temperature, suffix, index, count):
    canvas = Canvas(BLACK)
    _sky(canvas, phase)
    dx, dy = _weather_motion(condition, variant, index, count)
    night = "night" in condition or phase == "night"
    if condition == "clear_day":
        _sun(canvas, 21, 24 + dy, index)
    elif condition == "clear_night":
        _moon(canvas, 21, 24 + dy, phase, index)
        for x, y in ((7, 12), (29, 9), (35, 18)):
            canvas.pixel(x, y, PALETTE["lilac"] if (x + index) % 3 else PALETTE["paper"])
    elif condition in {"cloud", "cloud_night"}:
        _cloud(canvas, 21 + dx, 25, index, night, wide=variant % 2)
        if variant >= 1:
            _cloud(canvas, 7 - dx, 15, index + 1, night, wide=-2)
    elif condition in {"breaks", "breaks_night"}:
        (_moon if night else _sun)(canvas, 17, 21, phase, index) if night else _sun(canvas, 17, 21, index)
        _cloud(canvas, 24 + dx, 28, index, night, wide=variant)
    elif condition in {"rain", "storm"}:
        _cloud(canvas, 20, 19, index, phase == "night", wide=2)
        if condition == "storm" and index in ({1, 2} if variant == 0 else {2}):
            canvas.line(18, 25, 14, 33, PALETTE["amber_4"])
            canvas.line(14, 33, 18, 33, PALETTE["amber_4"])
            canvas.line(18, 33, 13, 41, PALETTE["alert"])
        else:
            for drop in range(5):
                x = 7 + drop * 7 + ((index + drop) % 2)
                y = 29 + ((drop * 3 + index * 3) % 12)
                colour = ("rain_1", "rain_2", "rain_3")[(drop + variant) % 3]
                canvas.line(x, y, x - 1, y + 3, PALETTE[colour])
    elif condition == "snow":
        _cloud(canvas, 20, 18, index, phase == "night", wide=2)
        for flake in range(7):
            x = 5 + flake * 6 + ((index + flake) % 3)
            y = 29 + ((flake * 5 + index * 2) % 14)
            colour = PALETTE["snow"] if flake % 2 else PALETTE["blue_5"]
            canvas.pixel(x, y, colour); canvas.pixel(x + 1, y, colour)
    _temperature(canvas, temperature, suffix)
    canvas.rect(0, 43, WIDTH, 11, PALETTE["deep"])
    canvas.line(0, 44, 15, 40, PALETTE["blue_2"])
    canvas.line(15, 40, 31, 45, PALETTE["blue_2"])
    canvas.line(31, 45, 49, 41, PALETTE["violet_2"])
    canvas.line(49, 41, 63, 45, PALETTE["violet_2"])
    return canvas.bytes()


def build_v3_weather_scene(theme, condition, variant, temperature_c, unit, phase, city=""):
    _check_theme(theme)
    validate_variant(condition, int(variant))
    if phase not in PHASE_PALETTES:
        raise ValueError("unknown solar phase")
    variant = int(variant)
    temperature, suffix = display_temperature(temperature_c, unit)
    count = 6 if condition in {"clear_day", "clear_night", "storm"} else 8
    frames = tuple(_weather_frame(condition, variant, phase, temperature, suffix, i, count) for i in range(count))
    if condition == "storm": delays = (18, 18, 35, 55, 65, 120)
    elif condition in {"clear_day", "clear_night"}: delays = (38, 38, 48, 38, 38, 90)
    elif condition in {"rain", "snow"}: delays = (24,) * count
    else: delays = (34,) * (count - 1) + (70,)
    signature = _signature("weather", {
        "city": str(city or "").strip(), "condition": condition, "phase": phase,
        "temperature": temperature, "unit": suffix, "variant": variant,
    })
    return SceneResult(frames, delays[0], signature, condition, variant, phase,
                       temperature, suffix, str(city or "").strip(), delays,
                       V3_SCENE_REVISION)


def _dashboard_frame(clock, phase, condition, variant, temperature, suffix, index,
                     status=None, battery=None, context=""):
    canvas = Canvas(BLACK)
    _sky(canvas, phase, 45)
    # Stable information zones; only the atmosphere between them breathes.
    draw_text_centered(canvas, 1, clock, PALETTE["ivory"], 3)
    night = phase == "night"
    if condition in {"clear_night", "breaks_night", "cloud_night"} or night:
        _moon(canvas, 18, 29 + (index % 2), phase, index)
    else:
        _sun(canvas, 18, 29 + (index % 2), index)
    if "cloud" in condition or "breaks" in condition or condition in {"rain", "snow", "storm"}:
        _cloud(canvas, 31 + round(math.sin(index / 8 * math.tau) * 2), 32, index, night, wide=1)
    if condition == "rain":
        for n in range(4):
            x = 18 + n * 7 + ((index + n) % 2)
            canvas.line(x, 38, x - 1, 41, PALETTE[("rain_1", "rain_2", "rain_3")[n % 3]])
    elif condition == "snow":
        for n in range(5): canvas.pixel(17 + n * 6, 38 + ((n + index) % 3), PALETTE["snow"])
    temperature_label = f"{temperature}°{suffix}"
    draw_text(
        canvas, WIDTH - 2 - measure_text(temperature_label), 31,
        temperature_label, PALETTE["paper"],
    )
    # The old design fixture painted REC, 03 and P1 unconditionally.  The
    # runtime rail now renders only fresh Steam/controller facts.
    draw_status_rail(
        canvas, status, battery=battery, fallback=context,
        background=PALETTE["deep"], y=45,
    )
    return canvas.bytes()


def build_v3_dashboard_snapshot(theme, instant, condition, variant, temperature_c, unit,
                                sunrise, sunset, city="", precipitation_probability=None,
                                clock_24h=True, status=None, battery=None):
    _check_theme(theme)
    validate_variant(condition, int(variant))
    instant = _instant(instant).replace(second=0, microsecond=0)
    sunrise, sunset = _instant(sunrise, "sunrise"), _instant(sunset, "sunset")
    phase = solar_phase(instant, sunrise, sunset)
    context = select_dashboard_context(
        instant, phase, sunrise, sunset, precipitation_probability,
    )
    clock = instant.strftime("%H:%M") if clock_24h else (instant.strftime("%I:%M").lstrip("0") or "0:00")
    temperature, suffix = display_temperature(temperature_c, unit)
    frames = tuple(_dashboard_frame(
        clock, phase, condition, int(variant), temperature, suffix, i,
        status=status, battery=battery, context=context,
    ) for i in range(8))
    delays = (45, 45, 45, 45, 45, 45, 45, 90)
    signature = _signature("dashboard", {
        "city": str(city or "").strip(), "clock": clock, "condition": condition,
        "instant": instant.isoformat(), "phase": phase,
        "precipitation_probability": precipitation_probability,
        "rail": status_rail_identity(status, battery, fallback=context),
        "temperature": temperature, "unit": suffix, "variant": int(variant),
    })
    return SceneResult(frames, delays[0], signature, condition, int(variant), phase,
                       temperature, suffix, str(city or "").strip(), delays,
                       V3_SCENE_REVISION)
