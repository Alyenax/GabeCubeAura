# SPDX-License-Identifier: GPL-3.0-only AND BSD-3-Clause
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Reusable 64x54 Steam artwork logo composition for Lab 30.

Decode a transparent Steam logo once at artwork preparation time, then blend
the prepared pixels into static or animated RGB frames. No Pillow dependency.
Based on Eli Hodapp's artwork/layout work in Pixel Faceplate (BSD-3-Clause).
Upstream: https://github.com/hodapp/pixel-faceplate
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import math

from . import protocol

WIDTH, HEIGHT = protocol.WIDTH, protocol.HEIGHT
FRAME_BYTES = WIDTH * HEIGHT * 3
STYLES = ("art", "logo", "logo_dim", "logo_only")
POSITIONS = ("top", "centre", "bottom", "bottom_rail")


@dataclass(frozen=True)
class Logo:
    width: int
    height: int
    pixels: tuple


def validate_layout(style="art", position="bottom"):
    if style not in STYLES or position not in POSITIONS:
        raise ValueError("unsupported Faceplate artwork presentation")
    return style, position


@lru_cache(maxsize=16)
def _prepare_file(path, mtime_ns):
    # Import lazily to keep the scene renderer independent of Steam artwork
    # lookup; only the explicitly requested preparation does image decoding.
    from . import artwork
    size = artwork.image_size(path)
    if not size or not all(size):
        return None
    width, height = size
    dw = 4 * (WIDTH - 6)
    dh = max(1, round(height * dw / width))
    if dh > 4 * HEIGHT:
        dh = 4 * HEIGHT
        dw = max(1, round(width * dh / height))
    rgba = artwork._gst_decode(path, dw, dh, alpha=True)
    if rgba is None or len(rgba) != dw * dh * 4:
        return None
    xs = [x for x in range(dw) if any(rgba[(y * dw + x) * 4 + 3] > 8
                                      for y in range(dh))]
    ys = [y for y in range(dh) if any(rgba[(y * dw + x) * 4 + 3] > 8
                                      for x in range(dw))]
    if not xs or not ys:
        return None
    left, right, top, bottom = xs[0], xs[-1] + 1, ys[0], ys[-1] + 1
    box_w, box_h = right - left, bottom - top
    scale = min((WIDTH - 6) / box_w, (HEIGHT - 6) / box_h)
    lw, lh = max(1, int(box_w * scale)), max(1, int(box_h * scale))
    pixels = []
    for ty in range(lh):
        y0 = top + int(ty / scale)
        y1 = top + max(int(ty / scale) + 1, int((ty + 1) / scale))
        for tx in range(lw):
            x0 = left + int(tx / scale)
            x1 = left + max(int(tx / scale) + 1, int((tx + 1) / scale))
            red = green = blue = alpha_sum = count = 0
            for y in range(y0, min(y1, dh)):
                for x in range(x0, min(x1, dw)):
                    idx = (y * dw + x) * 4
                    alpha = rgba[idx + 3]
                    red += rgba[idx] * alpha
                    green += rgba[idx + 1] * alpha
                    blue += rgba[idx + 2] * alpha
                    alpha_sum += alpha
                    count += 1
            if alpha_sum and count:
                pixels.append((tx, ty, alpha_sum / (255 * count),
                               (red / alpha_sum, green / alpha_sum, blue / alpha_sum)))
    return Logo(lw, lh, tuple(pixels)) if pixels else None


def prepare_logo(appid):
    """Use the user's active Steam account logo; never download anything."""
    try:
        from .artwork import find_logo
        path = find_logo(int(appid))
        if path is None:
            return None
        source = Path(path)
        return _prepare_file(str(source), source.stat().st_mtime_ns)
    except (OSError, ValueError, TypeError):
        return None


def validate_logo_scale(value=100):
    if type(value) is not int or not 50 <= value <= 100:
        raise ValueError("Logo size must be an integer from 50 to 100 percent")
    return value


@lru_cache(maxsize=32)
def _resize_logo(logo, width, height):
    """Area-filter premultiplied RGBA once per prepared logo and target size."""
    cells = {}
    sx, sy = width / logo.width, height / logo.height
    for x, y, alpha, colour in logo.pixels:
        left, right = x * sx, (x + 1) * sx
        top, bottom = y * sy, (y + 1) * sy
        for ty in range(int(top), min(height, math.ceil(bottom))):
            for tx in range(int(left), min(width, math.ceil(right))):
                area = (min(right, tx + 1) - max(left, tx)) * (min(bottom, ty + 1) - max(top, ty))
                weight = alpha * area
                cell = cells.setdefault((tx, ty), [0., 0., 0., 0.])
                cell[0] += weight
                for channel in range(3):
                    cell[channel + 1] += colour[channel] * weight
    return {(x, y): (min(1., cell[0]), tuple(v / cell[0] for v in cell[1:]))
            for (x, y), cell in cells.items() if cell[0] > 0}


def compose_frame(frame, logo, style="art", position="bottom", logo_scale=100):
    """Blend a cached transparent logo in one 64x54 RGB frame.

    Absence of a logo always falls back to the original artwork, including
    logo-only mode. This avoids an unexpectedly blank faceplate.
    """
    validate_layout(style, position)
    validate_logo_scale(logo_scale)
    frame = bytes(frame)
    if len(frame) != FRAME_BYTES:
        raise ValueError("Faceplate artwork frame is not RGB 64x54")
    if style == "art" or logo is None:
        return frame
    if not isinstance(logo, Logo):
        raise TypeError("Faceplate logo must be a prepared Logo")
    # Artwork Dashboard owns rows 45-53 for live state.  The ordinary bottom
    # anchor therefore ends at row 42; the explicit bottom_rail choice keeps
    # the historical edge anchor and tells the dashboard compositor to remove
    # its rail.  This makes overlap structurally impossible instead of relying
    # on a logo-specific magic offset.
    maximum_height = HEIGHT - 6 if position == "bottom_rail" else 40
    scale = min(1.0, maximum_height / max(1, logo.height))
    logo_width = max(1, round(logo.width * scale))
    logo_height = max(1, round(logo.height * scale))
    if logo_scale != 100:
        logo_width = max(1, round(logo_width * logo_scale / 100))
        logo_height = max(1, round(logo_height * logo_scale / 100))
    x0 = (WIDTH - logo_width) // 2
    if position == "top":
        y0 = 2
    elif position == "centre":
        y0 = max(2, (45 - logo_height) // 2)
    elif position == "bottom":
        y0 = max(2, 43 - logo_height)
    else:
        y0 = HEIGHT - logo_height - 3
    out = bytearray(FRAME_BYTES) if style == "logo_only" else bytearray(frame)
    if style == "logo_dim":
        fade = 6
        for y in range(HEIGHT):
            lower = y - (y0 - fade)
            upper = (y0 + logo_height + fade) - y
            into = upper if position == "top" else (
                min(lower, upper) if position == "centre" else lower
            )
            if into <= 0:
                continue
            keep = 1.0 - 0.5 * min(1.0, into / fade)
            start = 3 * y * WIDTH
            for i in range(start, start + 3 * WIDTH):
                out[i] = int(out[i] * keep)
    peak = max((max(colour) for _x, _y, coverage, colour in logo.pixels
                if coverage > 0.5), default=255)
    gain = min(2.0, 255 / peak) if peak else 1.0
    if logo_scale == 100:
        # Keep the historical 100% rendering byte-for-byte, including tall logos.
        placed = {}
        for x, y, alpha, colour in logo.pixels:
            px, py = min(logo_width - 1, int(x * scale)), min(logo_height - 1, int(y * scale))
            previous = placed.get((px, py))
            if previous is None or alpha > previous[0]:
                placed[(px, py)] = (alpha, colour)
    else:
        placed = _resize_logo(logo, logo_width, logo_height)
    for (x, y), (alpha, colour) in placed.items():
        idx = 3 * ((y0 + y) * WIDTH + x0 + x)
        for channel in range(3):
            bright = min(255.0, colour[channel] * gain)
            out[idx + channel] = round(out[idx + channel] * (1 - alpha) + bright * alpha)
    return bytes(out)
