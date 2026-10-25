# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Minute-granular Playtime facts and the approved native 64 x 9 timer rail."""

import math

from .scenes import Canvas, draw_text, measure_text

REVISION = "faceplate-playtime-1"
WARM = (255, 231, 190)
COLOURS = {"normal": (66, 220, 255), "warning": (255, 188, 65), "urgent": (255, 65, 58)}
BACKGROUND = (1, 5, 14)
BORDER = (20, 83, 111)
DIGITS = {
    "0": ("01110", "11011", "11011", "11011", "11011", "11011", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
}


def timer_facts(remaining_seconds):
    """No seconds or deadlines in render/cache identity: one update per minute."""
    remaining = float(remaining_seconds)
    if not math.isfinite(remaining) or remaining <= 0:
        return {}
    return {"state": "remaining", "minutes": int(math.ceil(remaining / 60)),
            "last_minute": remaining < 60,
            "urgency": "urgent" if remaining <= 300 else "warning" if remaining <= 900 else "normal"}


def _large_width(label):
    return sum(6 if character in DIGITS else measure_text(character) + 1
               for character in label) - 1


def _large_text(canvas, x, label, colour):
    for character in label:
        if character in DIGITS:
            for y, row in enumerate(DIGITS[character]):
                for dx, bit in enumerate(row):
                    if bit == "1":
                        canvas.pixel(x + dx, 46 + y, colour)
            x += 6
        else:
            draw_text(canvas, x, 48, character, colour)
            x += measure_text(character) + 1


def draw_timer_rail(canvas, countdown):
    """Replace only y45..53. Return false when the normal rail must survive."""
    if not isinstance(countdown, dict) or countdown.get("state") not in {"remaining", "ended"}:
        return False
    canvas.rect(0, 45, 64, 9, BACKGROUND)
    canvas.line(0, 45, 63, 45, BORDER)
    if countdown["state"] == "ended":
        label = "TIME'S UP"
        draw_text(canvas, (64 - measure_text(label)) // 2, 48, label, COLOURS["urgent"])
        return True
    minutes = max(1, min(9999, int(countdown.get("minutes", 1))))
    colour = COLOURS.get(countdown.get("urgency"), COLOURS["normal"])
    draw_text(canvas, 2, 48, "LEFT", WARM)
    if countdown.get("last_minute"):
        draw_text(canvas, 62 - measure_text("<1MIN"), 48, "<1MIN", colour)
    elif minutes < 60:
        label = str(minutes)
        _large_text(canvas, 48 - _large_width(label), label, colour)
        draw_text(canvas, 51, 48, "MIN", colour)
    else:
        hours, remainder = divmod(minutes, 60)
        label = f"{hours}H{remainder:02d}"
        width = _large_width(label)
        if width <= 42:
            _large_text(canvas, 62 - width, label, colour)
        else:
            draw_text(canvas, 62 - measure_text(label), 48, label, colour)
    return True


def overlay_timer(frame, countdown):
    if not isinstance(countdown, dict) or countdown.get("state") not in {"remaining", "ended"}:
        return frame
    canvas = Canvas()
    canvas.pixels = [tuple(frame[offset:offset + 3]) for offset in range(0, len(frame), 3)]
    return canvas.bytes() if draw_timer_rail(canvas, countdown) else frame
