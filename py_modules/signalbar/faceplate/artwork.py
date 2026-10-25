"""Render Steam and SteamGridDB artwork for the 64 x 54 faceplate.

The composition and GStreamer strategy are adapted from hodapp/pixel-faceplate
(BSD-3-Clause), copyright 2026 Eli Hodapp. Artwork discovery deliberately uses
GabeCubeAura's existing active-account lookup so the matrix and light bar agree.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
import shutil
import subprocess

from signalbar.steam.artwork_cache import (
    IMAGE_EXTENSIONS,
    _find_artwork_details,
    _grid_directories,
    _valid_image,
    steam_roots,
)

from .protocol import HEIGHT, WIDTH


FRAME_BYTES = WIDTH * HEIGHT * 3
ART_GAMMA = 0.7
LOGO_STEMS = ("logo", "logo_2x")


def clean_environment():
    env = dict(os.environ)
    for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    return env


def image_size(path):
    """Return PNG/JPEG dimensions without adding an image dependency."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64 * 1024)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(head):
            if head[index] != 0xFF:
                index += 1
                continue
            marker = head[index + 1]
            length = int.from_bytes(head[index + 2:index + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return (
                    int.from_bytes(head[index + 7:index + 9], "big"),
                    int.from_bytes(head[index + 5:index + 7], "big"),
                )
            index += 2 + length
    return None


def _gst_decode(path, width, height, alpha=False, timeout=5.0):
    """Decode and Lanczos-scale one image to packed RGB/RGBA bytes."""
    executable = shutil.which("gst-launch-1.0")
    if not executable or not os.path.isfile(path):
        return None
    pixel_format = "RGBA" if alpha else "RGB"
    command = [
        executable, "-q", "filesrc", f"location={path}", "!", "decodebin", "!",
        "videoconvert", "!", "videoscale", "method=3", "add-borders=false", "!",
        f"video/x-raw,format={pixel_format},width={width},height={height},pixel-aspect-ratio=1/1",
        "!", "imagefreeze", "num-buffers=1", "!", "fdsink", "fd=1",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False,
            env=clean_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    row = width * (4 if alpha else 3)
    stride = (row + 3) & ~3
    if result.returncode or len(result.stdout) < stride * height:
        return None
    if stride == row:
        return result.stdout[:row * height]
    return b"".join(
        result.stdout[y * stride:y * stride + row] for y in range(height)
    )


def _crop(rgb, width, x0, y0):
    out = bytearray()
    for y in range(y0, y0 + HEIGHT):
        start = 3 * (y * width + x0)
        out += rgb[start:start + 3 * WIDTH]
    return bytes(out)


def decode_image(path, ybias=0.5):
    """Crop an arbitrary Steam artwork image into one native panel frame."""
    dimensions = image_size(path) or (WIDTH, HEIGHT)
    width, height = dimensions
    if not width or not height:
        return None
    if width * HEIGHT > height * WIDTH:
        target_width, target_height = max(WIDTH, round(width * HEIGHT / height)), HEIGHT
    else:
        target_width, target_height = WIDTH, max(HEIGHT, round(height * WIDTH / width))
    rgb = _gst_decode(str(path), target_width, target_height)
    if rgb is None:
        return None
    return _crop(
        rgb, target_width, (target_width - WIDTH) // 2,
        int((target_height - HEIGHT) * max(0.0, min(1.0, ybias))),
    )


def sharpen(rgb, amount=0.8):
    out = bytearray(rgb)
    for y in range(1, HEIGHT - 1):
        for x in range(1, WIDTH - 1):
            index = 3 * (y * WIDTH + x)
            for channel in range(3):
                total = 0
                for row_delta in (-WIDTH * 3, 0, WIDTH * 3):
                    neighbour = index + row_delta + channel
                    total += rgb[neighbour - 3] + rgb[neighbour] + rgb[neighbour + 3]
                value = rgb[index + channel] + amount * (rgb[index + channel] - total / 9)
                out[index + channel] = max(0, min(255, int(value)))
    return bytes(out)


def lift(rgb, gamma=ART_GAMMA):
    table = bytes(int(round(255 * (value / 255.0) ** gamma)) for value in range(256))
    return bytes(rgb).translate(table)


def find_logo(appid):
    """Find the active account's custom logo, then Steam's cached logo."""
    try:
        appid = int(appid)
    except (TypeError, ValueError):
        return None
    for root in steam_roots():
        for grid in _grid_directories(root):
            for extension in IMAGE_EXTENSIONS:
                candidate = grid / f"{appid & 0xFFFFFFFF}_logo.{extension}"
                if _valid_image(candidate):
                    return candidate
    for root in steam_roots():
        cache = root / "appcache/librarycache"
        for extension in IMAGE_EXTENSIONS:
            for stem in LOGO_STEMS:
                name = f"{stem}.{extension}"
                candidates = [cache / str(appid) / name]
                candidates.extend(Path(value) for value in sorted(
                    glob.glob(str(cache / str(appid) / "*" / name))
                ))
                candidates.append(cache / f"{appid}_{name}")
                for candidate in candidates:
                    if _valid_image(candidate):
                        return candidate
    return None


def overlay_logo(rgb, path, margin=3, max_height=HEIGHT // 2):
    """Trim, resize and alpha-blend a Steam logo over a dark lower band."""
    dimensions = image_size(path) if path else None
    if not dimensions or not all(dimensions):
        return rgb
    source_width, source_height = dimensions
    decoded_width = 4 * (WIDTH - 2 * margin)
    decoded_height = max(1, round(source_height * decoded_width / source_width))
    if decoded_height > 4 * HEIGHT:
        decoded_height = 4 * HEIGHT
        decoded_width = max(1, round(source_width * decoded_height / source_height))
    rgba = _gst_decode(str(path), decoded_width, decoded_height, alpha=True)
    if rgba is None:
        return rgb
    xs = [x for x in range(decoded_width) if any(
        rgba[4 * (y * decoded_width + x) + 3] > 8 for y in range(decoded_height)
    )]
    ys = [y for y in range(decoded_height) if any(
        rgba[4 * (y * decoded_width + x) + 3] > 8 for x in range(decoded_width)
    )]
    if not xs or not ys:
        return rgb
    left, right, top, bottom = xs[0], xs[-1] + 1, ys[0], ys[-1] + 1
    box_width, box_height = right - left, bottom - top
    scale = min((WIDTH - 2 * margin) / box_width, max_height / box_height)
    logo_width = max(1, int(box_width * scale))
    logo_height = max(1, int(box_height * scale))
    origin_x = (WIDTH - logo_width) // 2
    origin_y = HEIGHT - logo_height - margin
    out = bytearray(rgb)
    fade = 6
    for y in range(max(0, origin_y - fade), HEIGHT):
        keep = 1.0 - 0.5 * min(1.0, (y - (origin_y - fade)) / fade)
        row = 3 * y * WIDTH
        for index in range(row, row + 3 * WIDTH):
            out[index] = int(out[index] * keep)
    pixels = []
    for target_y in range(logo_height):
        source_y0 = top + int(target_y / scale)
        source_y1 = top + max(int(target_y / scale) + 1, int((target_y + 1) / scale))
        for target_x in range(logo_width):
            source_x0 = left + int(target_x / scale)
            source_x1 = left + max(int(target_x / scale) + 1, int((target_x + 1) / scale))
            red = green = blue = alpha = count = 0
            for source_y in range(source_y0, min(source_y1, decoded_height)):
                for source_x in range(source_x0, min(source_x1, decoded_width)):
                    index = 4 * (source_y * decoded_width + source_x)
                    pixel_alpha = rgba[index + 3]
                    red += rgba[index] * pixel_alpha
                    green += rgba[index + 1] * pixel_alpha
                    blue += rgba[index + 2] * pixel_alpha
                    alpha += pixel_alpha
                    count += 1
            if alpha:
                pixels.append((
                    target_x, target_y, alpha / (255 * count),
                    (red / alpha, green / alpha, blue / alpha),
                ))
    peak = max((max(colour) for _, _, coverage, colour in pixels if coverage > 0.5), default=255)
    gain = min(2.0, 255.0 / peak) if peak else 1.0
    for target_x, target_y, coverage, colour in pixels:
        index = 3 * ((origin_y + target_y) * WIDTH + origin_x + target_x)
        for channel in range(3):
            lifted = min(255.0, colour[channel] * gain)
            out[index + channel] = int(out[index + channel] * (1 - coverage) + lifted * coverage)
    return bytes(out)


def artwork(appid, preferred_source="hero", style="logo_dim", position="bottom"):
    """Render the best available local game art; never downloads an image."""
    order = []
    for source in (preferred_source, "hero", "capsule", "header"):
        if source in {"hero", "header", "capsule"} and source not in order:
            order.append(source)
    for source in order:
        path, actual_source, _custom = _find_artwork_details(appid, source)
        if path is None:
            continue
        frame = decode_image(path, ybias=0.2 if actual_source == "capsule" else 0.5)
        if frame is None:
            continue
        frame = sharpen(frame)
        if actual_source == "hero":
            frame = lift(frame)
        if style == "logo_dim" and position == "bottom" and actual_source == "hero":
            # Preserve the historical Lab 28 local Steam fallback exactly.
            logo = find_logo(appid)
            if logo is not None:
                frame = overlay_logo(frame, logo)
        else:
            from .artwork_layout import compose_frame, prepare_logo
            frame = compose_frame(frame, prepare_logo(appid), style, position)
        return frame, str(path), actual_source
    return None, "", ""


def frame_load(rgb):
    return sum(rgb) / (len(rgb) * 255.0) if rgb else 0.0
