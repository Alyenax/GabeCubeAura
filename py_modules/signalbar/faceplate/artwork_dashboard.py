# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Lightweight runtime compositor for prepared Artwork Dashboard backgrounds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from .scenes import (
    BLACK, HEIGHT, MAX_ARTWORK_FRAMES, MAX_ARTWORK_GIF_BYTES, PIXELS, WIDTH,
    Canvas, draw_text, measure_text,
)
from . import gif
from .playtime import draw_timer_rail


REVISION = "artwork-dashboard-26-umbrella-lowered"
TREATMENTS = ("none", "cinema", "hero-cut", "palette-echo")
COMPRESSION_LEVELS = ("compatible", "balanced", "fine")
CLOCK_SIZES = ("compact", "large")
REFRESH_POLICIES = {"economy": 5, "minute": 1}
SOURCE_FRAME_DELAY_CS = 10
TERMINAL_SCAN_FRAMES = 4


@dataclass(frozen=True)
class ArtworkDashboardResult:
    frames: tuple[bytes, ...]
    delay_cs: int
    signature: str
    compression: str = "compatible"

    def gif(self):
        # Every quality level remains a canonical hardware GIF: one global
        # palette, full 64 x 54 opaque frames and no partial-frame disposal
        # state. Compatible is the Lab 56 hardware-proven fixed 3-3-2 path.
        # The two higher-fidelity levels add deterministic spatial dithering
        # while keeping that same global table. They never introduce local
        # palettes, temporal noise or extra frames.
        if not self.frames or len(self.frames) > MAX_ARTWORK_FRAMES:
            raise ValueError(
                f"GIF must contain between 1 and {MAX_ARTWORK_FRAMES} frames"
            )
        compression = (
            self.compression if self.compression in COMPRESSION_LEVELS
            else "compatible"
        )
        if compression == "compatible":
            indexed = tuple(_index_332(frame) for frame in self.frames)
        elif compression == "balanced":
            indexed = tuple(_index_332_ordered(frame) for frame in self.frames)
        else:
            indexed = tuple(_index_332_error_diffusion(frame) for frame in self.frames)
        payload = gif.encode(
            WIDTH, HEIGHT, PALETTE_332, indexed, self.delay_cs,
            loop=len(indexed) > 1,
        )
        if len(payload) > MAX_ARTWORK_GIF_BYTES:
            raise ValueError("Artwork Dashboard GIF exceeds the software safety limit")
        return payload


def quantize_battery(percent, charging=False, *, step=1):
    if percent is None:
        return None
    numeric = max(0, min(100, float(percent)))
    value = int(round(numeric))
    level = 4 if value >= 88 else 3 if value >= 63 else 2 if value >= 38 else 1 if value >= 13 else 0
    # Faceplate-only displayed percent buckets. Native controller telemetry
    # stays exact; tiny battery fluctuations must not rewrite a whole GIF.
    step = 5 if step == 5 else 1
    displayed_percent = max(0, min(100, ((value + step // 2) // step) * step))
    if numeric < 100:
        displayed_percent = min(99, displayed_percent)
    return {"level": level, "charging": bool(charging), "percent": displayed_percent}


PALETTE_332 = tuple(
    (round(red * 255 / 7), round(green * 255 / 7), round(blue * 255 / 3))
    for red in range(8) for green in range(8) for blue in range(4)
)


def _index_332(rgb):
    rgb = bytes(rgb)
    if len(rgb) != PIXELS * 3:
        raise ValueError("Artwork Dashboard frame must be RGB 64 x 54")
    out = bytearray(PIXELS)
    for pixel, offset in enumerate(range(0, len(rgb), 3)):
        red = (rgb[offset] * 7 + 127) // 255
        green = (rgb[offset + 1] * 7 + 127) // 255
        blue = (rgb[offset + 2] * 3 + 127) // 255
        out[pixel] = (red << 5) | (green << 2) | blue
    return bytes(out)


_BAYER_4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def _palette_index(red, green, blue):
    red = max(0, min(7, int(round(red * 7 / 255))))
    green = max(0, min(7, int(round(green * 7 / 255))))
    blue = max(0, min(3, int(round(blue * 3 / 255))))
    return (red << 5) | (green << 2) | blue


def _index_332_ordered(rgb):
    """Use a stable 4 x 4 screen to recover gradients without frame noise."""
    rgb = bytes(rgb)
    if len(rgb) != PIXELS * 3:
        raise ValueError("Artwork Dashboard frame must be RGB 64 x 54")
    out = bytearray(PIXELS)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixel = y * WIDTH + x
            offset = pixel * 3
            colour = tuple(rgb[offset:offset + 3])
            if colour in DASHBOARD_INK:
                out[pixel] = _palette_index(*colour)
                continue
            threshold = (_BAYER_4[y & 3][x & 3] - 7.5) / 16.0
            out[pixel] = _palette_index(
                colour[0] + threshold * (255 / 7) * 0.7,
                colour[1] + threshold * (255 / 7) * 0.7,
                colour[2] + threshold * (255 / 3) * 0.7,
            )
    return bytes(out)


def _index_332_error_diffusion(rgb):
    """Diffuse quantisation error spatially while preserving live UI ink."""
    rgb = bytes(rgb)
    if len(rgb) != PIXELS * 3:
        raise ValueError("Artwork Dashboard frame must be RGB 64 x 54")
    out = bytearray(PIXELS)
    current = [[0.0] * (WIDTH + 2) for _ in range(3)]
    following = [[0.0] * (WIDTH + 2) for _ in range(3)]
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixel = y * WIDTH + x
            offset = pixel * 3
            colour = tuple(rgb[offset:offset + 3])
            if colour in DASHBOARD_INK:
                out[pixel] = _palette_index(*colour)
                continue
            values = [
                max(0.0, min(255.0, colour[channel] + current[channel][x + 1]))
                for channel in range(3)
            ]
            out[pixel] = _palette_index(*values)
            quantized = PALETTE_332[out[pixel]]
            for channel in range(3):
                error = values[channel] - quantized[channel]
                current[channel][x + 2] += error * 7 / 16
                following[channel][x] += error * 3 / 16
                following[channel][x + 1] += error * 5 / 16
                following[channel][x + 2] += error / 16
        current, following = following, [[0.0] * (WIDTH + 2) for _ in range(3)]
    return bytes(out)


def _mix(left, right, amount):
    return tuple(round(left[channel] * (1.0 - amount) + right[channel] * amount)
                 for channel in range(3))


def _dark_ratio(row):
    pixels = len(row) // 3
    if not pixels:
        return 1.0
    return sum(
        1 for offset in range(0, pixels * 3, 3)
        if max(row[offset:offset + 3]) <= 8
    ) / pixels


def stabilize_dashboard_loop(backgrounds):
    """Repair terminal decoder debris without inventing loop motion.

    The former whole-frame bridge towards frame zero could import a black edge
    from the first source frame into the final four frames. This pass changes
    only proven decoder damage: a bounded empty tail or an isolated black row
    backed by visible temporal predecessors. Frame count, ordering and cadence
    remain unchanged; authored seams and duplicate holds are untouched.
    """
    frames = [bytes(frame) for frame in backgrounds]
    if len(frames) < 2 or any(len(frame) != PIXELS * 3 for frame in frames):
        return tuple(frames)

    trailing = 0
    for frame in reversed(frames):
        if _dark_ratio(frame) < 0.99:
            break
        trailing += 1
    if 0 < trailing <= 3 and trailing < len(frames):
        previous = frames[-trailing - 1]
        if _dark_ratio(previous) <= 0.95:
            frames[-trailing:] = [previous] * trailing

    row_bytes = WIDTH * 3
    scan_start = max(1, len(frames) - TERMINAL_SCAN_FRAMES)
    for index in range(scan_start, len(frames)):
        current = bytearray(frames[index])
        previous = frames[index - 1]
        earlier = frames[index - 2] if index >= 2 else previous
        for row in range(HEIGHT):
            start, end = row * row_bytes, (row + 1) * row_bytes
            if _dark_ratio(current[start:end]) < 0.95:
                continue
            before = previous[start:end]
            before_earlier = earlier[start:end]
            # Two preceding visible rows prove that this one-frame black band
            # is decoder debris. Never compare against frame zero: doing so was
            # the source of the terminal band regression.
            if _dark_ratio(before) <= 0.25 and _dark_ratio(before_earlier) <= 0.25:
                current[start:end] = before
        frames[index] = bytes(current)
    return tuple(frames)


def _treat(frame, treatment, *, show_clock=True):
    treatment = treatment if treatment in TREATMENTS else "none"
    source = bytes(frame)
    if len(source) != PIXELS * 3:
        raise ValueError("Artwork Dashboard background must be RGB 64 x 54")
    if treatment == "none":
        return source
    out = bytearray(source)
    for y in range(HEIGHT):
        # The upper readability fade belongs to the clock. A hidden clock
        # must leave the same treatment as the centre, including in games.
        edge = max(0.0, 1.0 - min(y, HEIGHT - 1 - y) / 13.0)
        protect_top = y < 16 and show_clock
        for x in range(WIDTH):
            offset = (y * WIDTH + x) * 3
            colour = tuple(source[offset:offset + 3])
            if treatment == "hero-cut":
                amount = 0.62 * edge if (protect_top and y < 15) or y >= 43 else 0.08
                target = (5, 8, 18)
            elif treatment == "palette-echo":
                luma = round(sum(colour) / 3)
                target = (12, 24 + luma // 7, 46 + luma // 5)
                amount = 0.46 + 0.28 * (edge if show_clock or y >= 16 else 0.0)
            else:
                target = BLACK
                amount = 0.72 * edge if protect_top or y >= 42 else 0.12
            out[offset:offset + 3] = bytes(_mix(colour, target, amount))
    return bytes(out)


# Lab 44 pixel contract.  These are sampled from the approved 64 x 54 model;
# they are deliberately not approximate UI colours.  Artwork and Weather
# dashboards both pass through this compositor and therefore share one exact
# geometry and palette.
WARM_WHITE = (255, 231, 190)
WEATHER_WHITE = (226, 247, 255)
WEATHER_BLUE = (66, 220, 255)
WEATHER_ICON_BLUE = (73, 221, 255)
WEATHER_NIGHT = (133, 157, 201)
WEATHER_SUN = (255, 200, 75)
MOON_IVORY = (255, 224, 155)
MOON_SHADOW = (111, 125, 145)
TEMPERATURE_AMBER = (255, 188, 65)
MORNING_BLUE = (102, 190, 255)
AFTERNOON_ORANGE = (255, 145, 72)
SEPARATOR_GREY = (125, 152, 181)
PLAYER_ONE = (66, 220, 255)
PLAYER_TWO = (255, 188, 65)
NOTCH_BACKGROUND = (1, 7, 18)
NOTCH_BORDER = (30, 116, 157)
RAIL_BACKGROUND = (1, 5, 14)
RAIL_BORDER = (20, 83, 111)
DURATION_HAND = (255, 224, 89)
PROGRESS_EMPTY = (33, 54, 76)
DASHBOARD_INK = frozenset({
    WARM_WHITE, WEATHER_WHITE, WEATHER_BLUE, WEATHER_ICON_BLUE, WEATHER_NIGHT,
    WEATHER_SUN, TEMPERATURE_AMBER, MORNING_BLUE, AFTERNOON_ORANGE,
    SEPARATOR_GREY, PLAYER_ONE, PLAYER_TWO, NOTCH_BACKGROUND, NOTCH_BORDER,
    RAIL_BACKGROUND, RAIL_BORDER, MOON_IVORY, MOON_SHADOW, DURATION_HAND, PROGRESS_EMPTY,
})

CLOCK_ORIGIN = (2, 3)
NOTCH_LEFT = 37
NOTCH_ICON_ORIGIN = (38, 2)
NOTCH_TEMPERATURE_RIGHT = 61
RAIL_TOP = 45
RAIL_TEXT_Y = 48


RAIN_MARK = (
    "00000000", "000CCC00", "00CCCCC0", "0CCCCCCC",
    "00B0B0B0", "0B0B0B00", "00B00000", "00000000",
)
# Approved seven-column scalloped umbrella. The cyan percentage identifies
# probability; the separate forecast icon continues to describe the weather.
UMBRELLA_MARK = (
    "0011100", "0111110", "1111111", "1001001",
    "0001000", "0101000", "0011000",
)
MOON_MARK = (
    "00000000", "00YYG000", "0YYGGG00", "0YYGGG00",
    "0YYYGG00", "00YYY000", "00000000", "00000000",
)

_WEATHER_MARKS = {
    "clear_day": (
        "Y....Y", "..YY..", ".YYYY.", ".YYYY.", "..YY..", "Y....Y",
    ),
    "clear_night": MOON_MARK,
    "cloud": (
        "......", "..II..", ".I..I.", "IIIIII", "......", "......",
    ),
    "cloud_night": (
        "......", "..NN..", ".N..N.", "NNNNNN", "......", "......",
    ),
    "rain": RAIN_MARK,
    "storm": (
        "..II..", ".I..I.", "IIIIII", "...Y..", "..Y...", ".Y...C",
    ),
    "snow": (
        "..II..", ".I..I.", "IIIIII", "......", ".I.I.I", "I.I.I.",
    ),
    "breaks": (
        "....YY", "....YY", "..II..", ".IIII.", "IIIIII", "......",
    ),
    "breaks_night": (
        "....II", "....II", "..NN..", ".NNNN.", "NNNNNN", "......",
    ),
}


def _safe_number(value, low=-100, high=100):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if low <= value <= high else None


def _temperature(value, unit):
    value = _safe_number(value)
    if value is None:
        return "--°"
    if str(unit) == "fahrenheit":
        value = value * 9.0 / 5.0 + 32.0
        suffix = "F"
    else:
        suffix = "C"
    return f"{round(value)}°{suffix}"


def _weather_icon_bounds(condition):
    rows = _WEATHER_MARKS.get(condition, _WEATHER_MARKS["cloud"])
    if len(rows) == 6:
        return 0, 6
    columns = [x for row in rows for x, token in enumerate(row) if token != "0"]
    left = min(columns)
    return left, max(columns) - left + 1


def _weather_icon(canvas, condition, x, y, *, compact=False, ux_enabled=False):
    """Preserve the authored 8 x 8 rain/moon and the other 6 x 6 marks."""
    if ux_enabled and condition not in _WEATHER_MARKS:
        draw_text(canvas, x + 1, y, "?", SEPARATOR_GREY)
        return
    condition = str(condition or "cloud")
    rows = _WEATHER_MARKS.get(condition, _WEATHER_MARKS["cloud"])
    if len(rows) == 8 and compact:
        # The authored blank first/last rows are part of the matrix contract.
        # Lift the 8-row grid so its last lit row stays within the bottom rail.
        y -= 1
        x -= _weather_icon_bounds(condition)[0]
    elif len(rows) == 6 and not compact:
        x += 1
        y += 1
    colours = {
        "I": WEATHER_WHITE,
        "C": SEPARATOR_GREY if condition == "rain" else WEATHER_ICON_BLUE,
        "B": WEATHER_BLUE,
        "G": MOON_SHADOW,
        "N": WEATHER_NIGHT,
        "Y": MOON_IVORY if condition == "clear_night" else WEATHER_SUN,
    }
    for row, pattern in enumerate(rows):
        for column, token in enumerate(pattern):
            colour = colours.get(token)
            if colour is not None:
                canvas.pixel(x + column, y + row, colour)


class _OffsetCanvas(Canvas):
    """Translate existing notch primitives without resampling or corner fills."""
    def __init__(self, target, dx):
        self.target, self.dx = target, dx

    def pixel(self, x, y, colour):
        self.target.pixel(x + self.dx, y, colour)

    def rect(self, x, y, width, height, colour):
        self.target.rect(x + self.dx, y, width, height, colour)


def _draw_weather_notch(canvas):
    """Draw the approved 27 x 11 chamfered notch at x=37..63."""
    canvas.rect(38, 1, 25, 9, NOTCH_BACKGROUND)
    canvas.rect(37, 2, 27, 7, NOTCH_BACKGROUND)
    canvas.line(38, 0, 62, 0, NOTCH_BORDER)
    canvas.pixel(37, 1, NOTCH_BORDER)
    canvas.pixel(63, 1, NOTCH_BORDER)
    canvas.pixel(37, 9, NOTCH_BORDER)
    canvas.pixel(63, 9, NOTCH_BORDER)
    canvas.line(38, 10, 62, 10, NOTCH_BORDER)


def _droplet(canvas, x, y, colour=WEATHER_BLUE):
    canvas.pixel(x + 2, y, colour)
    canvas.line(x + 1, y + 1, x + 3, y + 1, colour)
    canvas.line(x, y + 2, x + 4, y + 2, colour)
    canvas.line(x + 1, y + 3, x + 3, y + 3, colour)
    canvas.pixel(x + 2, y + 4, colour)


def _precipitation_risk_icon(canvas, x, y):
    """Approved scalloped umbrella in the existing 7-column risk seat."""
    for row, pattern in enumerate(UMBRELLA_MARK):
        for column, token in enumerate(pattern):
            if token == "1":
                canvas.pixel(x + column, y - 1 + row, WEATHER_BLUE)


def _notch_temperature(canvas, value, unit, *, label=None):
    label = _temperature(value, unit) if label is None else label
    width = measure_text(label)
    if width <= 14:
        draw_text(canvas, NOTCH_TEMPERATURE_RIGHT - width, 3, label, TEMPERATURE_AMBER)
        return
    # Keep a 27-pixel notch even for -100 C / -148 F. Long values occupy
    # one native numeric line and a small degree/unit line, never the icon.
    number = label[:-2]
    number_x = NOTCH_TEMPERATURE_RIGHT - measure_text(number)
    if measure_text(number) > 14 and number.startswith("-"):
        # A two-column minus keeps one dark gutter even at -100 C / -148 F.
        digits_x = NOTCH_TEMPERATURE_RIGHT - measure_text(number[1:])
        canvas.line(digits_x - 3, 3, digits_x - 2, 3, TEMPERATURE_AMBER)
        draw_text(canvas, digits_x, 1, number[1:], TEMPERATURE_AMBER)
    else:
        draw_text(canvas, number_x, 1, number, TEMPERATURE_AMBER)
    canvas.rect(55, 6, 2, 2, TEMPERATURE_AMBER)
    unit_rows = ("111", "100", "100", "111") if label[-1] == "C" else (
        "111", "100", "110", "100",
    )
    for dy, row in enumerate(unit_rows):
        for dx, bit in enumerate(row):
            if bit == "1":
                canvas.pixel(58 + dx, 6 + dy, TEMPERATURE_AMBER)


def _battery_bar(canvas, x, y, battery, colour, ux_enabled=False):
    if ux_enabled and (battery or {}).get("percent") is None:
        draw_text(canvas, x + 3, y, "?", SEPARATOR_GREY)
        return
    canvas.rect(x, y, 12, 5, WEATHER_WHITE)
    canvas.pixel(x + 12, y + 1, WEATHER_WHITE)
    canvas.pixel(x + 12, y + 2, WEATHER_WHITE)
    canvas.pixel(x + 12, y + 3, WEATHER_WHITE)
    canvas.rect(x + 1, y + 1, 10, 3, (2, 6, 12))
    percent = max(0, min(100, int((battery or {}).get("percent", 0) or 0)))
    width = round(percent / 10)
    if width:
        canvas.rect(x + 1, y + 1, width, 3, colour)


def _draw_bottom_row(canvas, mode, *, controllers=(), battery_style="percent",
                     show_p2=False, forecast=None, unit="celsius", ux_enabled=False,
                     game_running=False, show_game_session=False,
                     session_minutes=0, connected_controller_count=None, countdown=None,
                     game_row="existing", game_stats=None):
    if draw_timer_rail(canvas, countdown):
        return
    y = RAIL_TEXT_Y
    canvas.rect(0, RAIL_TOP, WIDTH, HEIGHT - RAIL_TOP, RAIL_BACKGROUND)
    canvas.line(0, RAIL_TOP, WIDTH - 1, RAIL_TOP, RAIL_BORDER)
    if game_running and game_row in ("a", "b", "c", "d", "e"):
        from .bottom_stats import draw_stats_row
        if draw_stats_row(canvas, game_row, session_minutes=session_minutes,
                          game_stats=game_stats, controllers=controllers,
                          battery_style=battery_style, show_p2=show_p2,
                          connected_controller_count=connected_controller_count):
            return
        mode = "controllers"
        show_game_session = False
    if mode == "controllers":
        items = list(controllers or ())[:2]
        if not items:
            draw_text(canvas, 2, y, "P1 --", PLAYER_ONE)
            return
        # With two pads, P2 deliberately takes the left slot and P1 stays on
        # the right.  The 14-column neutral gap remains readable through the
        # physical diffuser; a lone P1 moves right only during a game.
        display = [(1, items[0], 39 if game_running else 2)] if len(items) == 1 else [
            (2, items[1], 2), (1, items[0], 39),
        ]
        for player, battery, left in display:
            colour = PLAYER_ONE if player == 1 else PLAYER_TWO
            draw_text(canvas, left, y, f"P{player}", colour)
            if battery_style == "bar":
                _battery_bar(canvas, left + 10, y, battery, colour, ux_enabled)
            else:
                raw = (battery or {}).get("percent")
                value = _safe_number(raw, 0, 100)
                label = "--%" if value is None else f"{round(value)}%"
                right = 63 if left > 30 else 29
                label_x = min(left + 12, right + 1 - measure_text(label))
                draw_text(canvas, label_x, y, label, colour)
        return
    forecast = forecast if isinstance(forecast, dict) else {}
    if mode == "today":
        # The same approved rail in both UX modes: weather, blue morning,
        # spaced slash, orange afternoon. Retain units, not AM/PM labels.
        morning = _temperature(forecast.get("morning_temperature_c"), unit)
        afternoon = _temperature(forecast.get("afternoon_temperature_c"), unit)
        morning_x = 20
        slash_x = max(33, morning_x + measure_text(morning) + 1)
        afternoon_x = max(39, slash_x + measure_text("/") + 1)
        # Keep familiar coordinates for ordinary readings. Move the complete
        # row left only when longer negative/Fahrenheit values need room;
        # the six-column icon and dark gutters must move together.
        shift = max(0, afternoon_x + measure_text(afternoon) - 63)
        icon_width = _weather_icon_bounds(forecast.get("today_condition"))[1]
        _weather_icon(canvas, forecast.get("today_condition"), 17 - icon_width - shift, 48,
                      compact=True, ux_enabled=ux_enabled)
        draw_text(canvas, morning_x - shift, y, morning, MORNING_BLUE)
        draw_text(canvas, slash_x - shift, y, "/", SEPARATOR_GREY)
        draw_text(canvas, afternoon_x - shift, y, afternoon, AFTERNOON_ORANGE)
        return
    chance = _safe_number(forecast.get("next_hour_precipitation_probability"), 0, 100)
    label = "--%" if chance is None else f"{round(chance)}%"
    temperature = _temperature(forecast.get("next_hour_temperature_c"), unit)
    if ux_enabled:
        # Keep the approved compact UX temperature, including its degree mark
        # unless a long negative reading requires the existing short form.
        temperature = temperature.removesuffix("C").removesuffix("F")
        if measure_text(temperature) > 14:
            temperature = temperature.replace("°", "")
    # Five elements, four genuinely dark gutters, 2-column outer margins.
    # No invisible 100% placeholder: divide the free space between elements
    # using their real native widths. Layout only changes with forecast data,
    # never with background animation frames.
    icon_width = _weather_icon_bounds(forecast.get("next_hour_condition"))[1]
    available_temperature = 60 - (measure_text("+1H") + icon_width + 7 + measure_text(label)) - 4
    if measure_text(temperature) > available_temperature:
        temperature = temperature.removesuffix("C").removesuffix("F")
    if measure_text(temperature) > available_temperature:
        temperature = temperature.replace("°", "")
    widths = (measure_text("+1H"), icon_width, measure_text(temperature), 7, measure_text(label))
    gutter, extra = divmod(60 - sum(widths), 4)
    positions = [2]
    for index in range(4):
        positions.append(positions[-1] + widths[index] + gutter + (index < extra))
    draw_text(canvas, positions[0], y, "+1H", WARM_WHITE)
    _weather_icon(canvas, forecast.get("next_hour_condition"), positions[1], 47,
                  compact=True, ux_enabled=ux_enabled)
    draw_text(canvas, positions[2], y, temperature, WARM_WHITE)
    _precipitation_risk_icon(canvas, positions[3], 48)
    draw_text(canvas, positions[4], y, label, WEATHER_BLUE)


def _overlay(frame, instant, session_minutes, battery, *, treatment,
             show_clock, clock_size, show_session, show_battery,
             show_status_rail, status=None, weather=None,
             bottom_mode="next_hour", controllers=(), battery_style="percent",
             show_p2=False, forecast=None, unit="celsius",
             show_weather_notch=True, clock_24h=True, ux_enabled=False,
             clock_position="left", game_running=False, show_game_session=False,
             connected_controller_count=None, countdown=None,
             game_row="existing", game_stats=None, weather_position="right"):
    canvas = Canvas()
    canvas.pixels = [tuple(frame[offset:offset + 3]) for offset in range(0, len(frame), 3)]
    # Local veils protect text without turning the artwork into a JPEG covered
    # by boxes. The top left remains visually open; the black Weather notch is
    # a separate, stable object on the right.
    clock = instant.strftime("%H:%M") if clock_24h else instant.strftime("%I:%M").lstrip("0")
    suffix = "" if clock_24h else "AM" if instant.hour < 12 else "PM"
    clock_width = measure_text(clock) + (2 + measure_text(suffix) if suffix else 0)
    alignment = "left" if show_weather_notch else clock_position
    clock_x = max(2, (WIDTH - clock_width) // 2) if alignment == "center" else (
        WIDTH - 2 - clock_width if alignment == "right" else 2
    )
    for y in range(10) if show_clock else ():
        for x in range(max(0, clock_x - 2), min(WIDTH, clock_x + clock_width + 2)):
            index = y * WIDTH + x
            canvas.pixels[index] = _mix(canvas.pixels[index], BLACK, .58 - y * .035)
    if show_clock:
        draw_text(canvas, clock_x, CLOCK_ORIGIN[1], clock, WARM_WHITE)
    if show_clock and suffix:
        draw_text(
            canvas, clock_x + measure_text(clock) + 2,
            CLOCK_ORIGIN[1], suffix, SEPARATOR_GREY,
        )
    weather = weather if isinstance(weather, dict) else {}
    if show_weather_notch:
        left = {'left': 0, 'center': 18, 'right': 37}.get(weather_position, 37)
        notch = _OffsetCanvas(canvas, left - NOTCH_LEFT)
        _draw_weather_notch(notch)
        _weather_icon(notch, weather.get("condition"), *NOTCH_ICON_ORIGIN, ux_enabled=ux_enabled)
        _notch_temperature(notch, weather.get("temperature_c"), unit)
    # An active timer has priority over the optional logo/status exclusion.
    if show_status_rail or countdown:
        _draw_bottom_row(
            canvas, bottom_mode, controllers=controllers,
            battery_style=battery_style, show_p2=show_p2,
            forecast=forecast, unit=unit, ux_enabled=ux_enabled,
            game_running=game_running, show_game_session=show_game_session,
            session_minutes=session_minutes,
            connected_controller_count=connected_controller_count,
            countdown=countdown, game_row=game_row, game_stats=game_stats,
        )
    return canvas.bytes()


def build_artwork_dashboard(backgrounds, instant, session_minutes, battery=None,
                            *, treatment="none", show_clock=False,
                            clock_size="large", show_status_rail=True,
                            show_session=True, show_battery=True,
                            background_signature="", source_frame_count=None,
                            status=None, weather=None, bottom_mode="next_hour",
                            controllers=(), battery_style="percent", show_p2=False,
                            forecast=None, unit="celsius",
                            show_weather_notch=True, clock_24h=True,
                            compression="compatible", ux_enabled=False,
                            clock_position="left", game_running=False,
                            show_game_session=False, connected_controller_count=None,
                            countdown=None, game_row="existing", game_stats=None,
                            weather_position="right"):
    if isinstance(instant, str):
        instant = datetime.fromisoformat(instant)
    if not isinstance(instant, datetime):
        raise TypeError("Artwork Dashboard instant must be ISO-8601 or datetime")
    instant = instant.replace(second=0, microsecond=0)
    # Wall-clock time is Home-only. Ignore legacy artwork clock flags in game,
    # including callers outside the normal route builder.
    show_clock = bool(show_clock) and not game_running
    if game_running and game_row in ('a','c','e'):
        controllers = [dict(item) for item in list(controllers or ())[:1]]
        show_p2 = False
        connected_controller_count = min(1,len(controllers))
        if game_row == 'a' and battery_style == 'percent':
            for item in controllers:
                if type(item.get('percent')) is int:
                    item['percent'] = min(99,item['percent'])
    elif bottom_mode == 'controllers':
        show_p2 = True
        show_game_session = False
    weather_position = weather_position if weather_position in {"left", "center", "right"} and not show_clock else "right"
    clock_size = clock_size if clock_size in CLOCK_SIZES else "large"
    compression = str(compression or "compatible").strip().lower()
    if compression not in COMPRESSION_LEVELS:
        compression = "compatible"
    backgrounds = stabilize_dashboard_loop(tuple(backgrounds))
    frames = tuple(_overlay(
        _treat(frame, treatment, show_clock=show_clock), instant, session_minutes, battery,
        treatment=treatment, show_clock=bool(show_clock),
        clock_size=clock_size, show_status_rail=bool(show_status_rail),
        show_session=bool(show_session), show_battery=bool(show_battery),
        status=status, weather=weather, bottom_mode=bottom_mode,
        controllers=controllers, battery_style=battery_style,
        show_p2=show_p2, forecast=forecast, unit=unit,
        show_weather_notch=bool(show_weather_notch),
        clock_24h=bool(clock_24h),
        ux_enabled=bool(ux_enabled),
        clock_position=clock_position, game_running=bool(game_running),
        show_game_session=bool(show_game_session),
        connected_controller_count=connected_controller_count,
        countdown=countdown, game_row=game_row, game_stats=game_stats,
        weather_position=weather_position,
    ) for frame in backgrounds)
    if not frames:
        raise ValueError("Artwork Dashboard requires a prepared background pack")
    # The Dashboard is a composited version of the prepared artwork, not a
    # lower-fidelity derivative. Keep every frame at the source 10 fps cadence.
    # Static sources remain persistent instead of receiving invented motion.
    delay_cs = 100 if len(frames) == 1 else SOURCE_FRAME_DELAY_CS
    identity = {
        "background": str(background_signature),
        "instant": instant.isoformat() if show_clock else None, "revision": REVISION,
        "show_clock": bool(show_clock),
        "show_status_rail": bool(show_status_rail or countdown),
        "game_row": game_row if game_running and show_status_rail and not countdown else "existing",
        "game_stats": game_stats if game_running and show_status_rail and not countdown and game_row in ("a", "b", "d", "e") else None,
        "bottom_mode": bottom_mode,
        "battery_style": battery_style,
        "show_p2": bool(show_p2),
        "controllers": list(controllers or ())[:2 if show_p2 else 1] if (bottom_mode == "controllers" or game_row in ("a", "c", "e")) and not countdown else [],
        "weather": weather if show_weather_notch else None,
        "show_weather_notch": bool(show_weather_notch),
        "weather_position": weather_position if show_weather_notch else None,
        "clock_24h": bool(clock_24h) if show_clock else None,
        "clock_position": clock_position if show_clock and not show_weather_notch else None,
        "game_running": bool(game_running),
        "show_game_session": bool(show_game_session),
        "session_minutes": session_minutes if game_running and not countdown and (game_row in ("a", "c") or show_game_session and bottom_mode == "controllers") else 0,
        "connected_controller_count": connected_controller_count,
        "countdown": countdown,
        "forecast": forecast if bottom_mode in {"next_hour", "today"} and not countdown else None,
        "unit": unit,
        "source_frame_count": source_frame_count, "treatment": treatment,
        "compression": compression,
        "ux_enabled": bool(ux_enabled),
    }
    signature = hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return ArtworkDashboardResult(frames, delay_cs, signature, compression)
