"""Draw 64x54 RGB frames: clock, light bar glow, images and Steam artwork via GStreamer."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

from signalbar.steam import find_library_artwork, find_library_logo

from .protocol import HEIGHT, WIDTH

FRAME_BYTES = WIDTH * HEIGHT * 3


def clean_environment():
    """Environment for system binaries: drop the library paths Decky's bundled Python sets."""
    env = dict(os.environ)
    for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    return env

# 3x5 digits for the date line and 5x7 digits drawn at 2x for the time.
SMALL = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
    "/": ["001", "001", "010", "100", "100"], " ": ["000"] * 5, ":": ["0", "1", "0", "1", "0"],
    "A": ["010", "101", "111", "101", "101"], "P": ["110", "101", "110", "100", "100"],
    "M": ["10001", "11011", "10101", "10001", "10001"],
}
BIG = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["0", "1", "1", "0", "1", "1", "0"],
}


class Canvas:
    def __init__(self, fill=(0, 0, 0)):
        self.px = bytearray(bytes(fill) * (WIDTH * HEIGHT))

    def set(self, x, y, colour):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            i = 3 * (y * WIDTH + x)
            self.px[i:i + 3] = bytes(colour)

    def rect(self, x, y, w, h, colour):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, colour)

    def text(self, x, y, string, colour, font=SMALL, scale=1, gap=1):
        for ch in string:
            glyph = font.get(ch, font.get(" ", ["0"]))
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1":
                        self.rect(x + gx * scale, y + gy * scale, scale, scale, colour)
            x += (len(glyph[0]) + gap) * scale
        return x

    @staticmethod
    def text_width(string, font=SMALL, scale=1, gap=1):
        return sum((len(font.get(ch, font.get(" ", ["0"]))[0]) + gap) * scale for ch in string) - gap * scale

    def bytes(self):
        return bytes(self.px)


def clock(now=None, colour=(255, 140, 20), use_24h=False):
    now = time.localtime(now)
    canvas = Canvas()
    hour = now.tm_hour if use_24h else (now.tm_hour % 12 or 12)
    hhmm = "%d:%02d" % (hour, now.tm_min) if not use_24h else "%02d:%02d" % (hour, now.tm_min)
    width = Canvas.text_width(hhmm, BIG, 2)
    canvas.text((WIDTH - width) // 2, 12, hhmm, colour, BIG, 2)
    line = "%d/%d" % (now.tm_mon, now.tm_mday)
    if not use_24h:
        line += " " + ("AM" if now.tm_hour < 12 else "PM")
    dim = tuple(c // 3 for c in colour)
    canvas.text((WIDTH - Canvas.text_width(line)) // 2, 34, line, dim)
    return canvas.bytes()


def read_lightbar(root="/sys/class/leds"):
    """Colours of the Steam Machine light bar, left to right, scaled by brightness."""
    leds = []
    for path in glob.glob(os.path.join(root, "valve-leds[[]*[]]")):
        try:
            index = int(path.rsplit("[", 1)[1].rstrip("]"))
            with open(os.path.join(path, "multi_intensity")) as handle:
                rgb = [int(v) for v in handle.read().split()[:3]]
            with open(os.path.join(path, "brightness")) as handle:
                level = int(handle.read().strip() or 0)
            with open(os.path.join(path, "max_brightness")) as handle:
                top = int(handle.read().strip() or 255) or 255
        except (OSError, ValueError, IndexError):
            continue
        leds.append((index, tuple(min(255, c * level // top) for c in rgb)))
    return [c for _, c in sorted(leds)]


def aura(colours):
    """A soft glow: light bar colours spread across the width, fading toward the top."""
    if not colours:
        return bytes(FRAME_BYTES)
    out = bytearray(FRAME_BYTES)
    n = len(colours)
    row = []
    for x in range(WIDTH):
        pos = x * (n - 1) / (WIDTH - 1) if n > 1 else 0
        a = int(pos)
        b = min(n - 1, a + 1)
        t = pos - a
        row.append(tuple(int(colours[a][k] * (1 - t) + colours[b][k] * t) for k in range(3)))
    for y in range(HEIGHT):
        # Brightest along the bottom edge, where the light bar sits below the faceplate.
        fade = ((y + 1) / HEIGHT) ** 1.6
        for x, (r, g, b) in enumerate(row):
            i = 3 * (y * WIDTH + x)
            out[i] = int(r * fade)
            out[i + 1] = int(g * fade)
            out[i + 2] = int(b * fade)
    return bytes(out)


def image_size(path):
    """(width, height) from a PNG or JPEG header, or None."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(64 * 1024)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                i += 1
                continue
            marker = head[i + 1]
            length = int.from_bytes(head[i + 2:i + 4], "big")
            # SOF0-SOF15 carry the size, except DHT (C4), JPG (C8) and DAC (CC).
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(head[i + 7:i + 9], "big"), int.from_bytes(head[i + 5:i + 7], "big")
            i += 2 + length
    return None


def _gst_decode(path, width, height, alpha=False, timeout=5.0):
    """Decode and Lanczos-scale an image with GStreamer; raw RGB or RGBA bytes, or None."""
    gst = shutil.which("gst-launch-1.0")
    if not gst or not os.path.isfile(path):
        return None
    fmt = "RGBA" if alpha else "RGB"
    argv = [
        gst, "-q", "filesrc", "location=%s" % path, "!", "decodebin", "!", "videoconvert",
        # method=3 is Lanczos: much crisper than bilinear at this size (seen).
        "!", "videoscale", "method=3", "add-borders=false",
        "!", "video/x-raw,format=%s,width=%d,height=%d,pixel-aspect-ratio=1/1" % (fmt, width, height),
        "!", "imagefreeze", "num-buffers=1", "!", "fdsink", "fd=1",
    ]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False,
                                env=clean_environment())
    except (OSError, subprocess.SubprocessError):
        return None
    # GStreamer pads every raw video row to a multiple of 4 bytes. RGB rows of
    # odd widths would shear diagonally if read as packed (seen on hero art).
    row = width * (4 if alpha else 3)
    stride = (row + 3) & ~3
    if result.returncode or len(result.stdout) < stride * height:
        return None
    data = result.stdout
    if stride == row:
        return data[:row * height]
    return b"".join(data[y * stride:y * stride + row] for y in range(height))


def _crop(rgb, width, height, x0, y0):
    out = bytearray()
    for y in range(y0, y0 + HEIGHT):
        start = 3 * (y * width + x0)
        out += rgb[start:start + 3 * WIDTH]
    return bytes(out)


def decode_image(path, fill=True, ybias=0.5):
    """Any image GStreamer can open, as one 64x54 RGB frame (or None).

    fill crops to the panel's shape (ybias picks how far down a tall image
    the crop sits: 0 top, 0.5 middle); otherwise the image is letterboxed.
    """
    size = image_size(path)
    if not size or not all(size):
        size = (WIDTH, HEIGHT)  # unknown format: just squeeze it
    w, h = size
    wide = w * HEIGHT > h * WIDTH
    if fill:
        tw, th = (max(WIDTH, round(w * HEIGHT / h)), HEIGHT) if wide else (WIDTH, max(HEIGHT, round(h * WIDTH / w)))
    else:
        tw, th = (WIDTH, max(1, round(h * WIDTH / w))) if wide else (max(1, round(w * HEIGHT / h)), HEIGHT)
    rgb = _gst_decode(path, tw, th)
    if rgb is None:
        return None
    if fill:
        return _crop(rgb, tw, th, (tw - WIDTH) // 2, int((th - HEIGHT) * ybias))
    canvas = bytearray(FRAME_BYTES)
    x0, y0 = (WIDTH - tw) // 2, (HEIGHT - th) // 2
    for y in range(th):
        start = 3 * ((y0 + y) * WIDTH + x0)
        canvas[start:start + 3 * tw] = rgb[3 * y * tw:3 * (y + 1) * tw]
    return bytes(canvas)


def sharpen(rgb, amount=0.8):
    """Light unsharp mask (3x3 box blur); downscaled art reads better with it."""
    out = bytearray(rgb)
    for y in range(1, HEIGHT - 1):
        for x in range(1, WIDTH - 1):
            i = 3 * (y * WIDTH + x)
            for k in range(3):
                total = 0
                for dy in (-WIDTH * 3, 0, WIDTH * 3):
                    j = i + dy + k
                    total += rgb[j - 3] + rgb[j] + rgb[j + 3]
                v = rgb[i + k] + amount * (rgb[i + k] - total / 9)
                out[i + k] = 0 if v < 0 else 255 if v > 255 else int(v)
    return bytes(out)


def dim(rgb, factor):
    return bytes(int(v * factor) for v in rgb)


def lift(rgb, gamma):
    """Brighten midtones (gamma < 1) while black stays black and white stays white."""
    table = bytes(int(round(255 * (v / 255.0) ** gamma)) for v in range(256))
    return bytes(rgb).translate(table)


def rotate(rgb):
    """Turn a frame 180 degrees, for a faceplate mounted with its cable on the right."""
    out = bytearray(len(rgb))
    last = len(rgb) - 3
    for i in range(0, len(rgb), 3):
        out[last - i:last - i + 3] = rgb[i:i + 3]
    return bytes(out)


def load_logo(path, max_width=WIDTH - 6, max_height=HEIGHT // 2):
    """A transparent logo PNG trimmed and box-averaged to fit the box.

    Returns (width, height, pixels) with pixels as (x, y, coverage, colour),
    or None if it can't be read or is empty.
    """
    size = image_size(path)
    if not size or not all(size):
        return None
    w, h = size
    # Decode at 4x the target width so trimming and box-averaging stay sharp.
    dw = 4 * max_width
    dh = max(1, round(h * dw / w))
    if dh > 4 * HEIGHT:
        dh = 4 * HEIGHT
        dw = max(1, round(w * dh / h))
    rgba = _gst_decode(path, dw, dh, alpha=True)
    if rgba is None:
        return None
    return fit_logo(rgba, dw, dh, max_width, max_height)


def fit_logo(rgba, dw, dh, max_width, max_height):
    # Trim fully transparent margins (logos ship with lots of padding).
    xs = [x for x in range(dw) if any(rgba[4 * (y * dw + x) + 3] > 8 for y in range(dh))]
    ys = [y for y in range(dh) if any(rgba[4 * (y * dw + x) + 3] > 8 for x in range(dw))]
    if not xs or not ys:
        return None
    bx0, bx1, by0, by1 = xs[0], xs[-1] + 1, ys[0], ys[-1] + 1
    bw, bh = bx1 - bx0, by1 - by0
    scale = min(max_width / bw, max_height / bh)
    lw, lh = max(1, int(bw * scale)), max(1, int(bh * scale))
    pixels = []
    for ty in range(lh):
        sy0, sy1 = by0 + int(ty / scale), by0 + max(int(ty / scale) + 1, int((ty + 1) / scale))
        for tx in range(lw):
            sx0, sx1 = bx0 + int(tx / scale), bx0 + max(int(tx / scale) + 1, int((tx + 1) / scale))
            r = g = b = a = 0
            n = 0
            for sy in range(sy0, min(sy1, dh)):
                for sx in range(sx0, min(sx1, dw)):
                    j = 4 * (sy * dw + sx)
                    alpha = rgba[j + 3]
                    r += rgba[j] * alpha
                    g += rgba[j + 1] * alpha
                    b += rgba[j + 2] * alpha
                    a += alpha
                    n += 1
            if a:
                pixels.append((tx, ty, a / (255 * n), (r / a, g / a, b / a)))
    return lw, lh, pixels


def place_logo(rgb, logo, position="bottom", band=True, margin=3):
    """Blend a fitted logo onto a frame at the top, bottom or centre.

    With band on, the art fades to half brightness behind the logo so the
    title stands out. It covers the logo plus a short fade, running out to
    the edge the logo sits against (both fades for a centred logo).
    """
    lw, lh, pixels = logo
    out = bytearray(rgb)
    ox = (WIDTH - lw) // 2
    if position == "top":
        oy = margin
    elif position == "centre":
        oy = (HEIGHT - lh) // 2
    else:
        oy = HEIGHT - lh - margin
    if band:
        fade = 6
        for y in range(HEIGHT):
            below, above = y - (oy - fade), (oy + lh + fade) - y  # rows inside each fade edge
            if position == "top":
                into = above
            elif position == "centre":
                into = min(below, above)
            else:
                into = below
            if into <= 0:
                continue
            keep = 1.0 - 0.5 * min(1.0, into / fade)
            row = 3 * y * WIDTH
            for i in range(row, row + 3 * WIDTH):
                out[i] = int(out[i] * keep)
    # Bright logo on dim art reads brighter than bright art, and the logo is
    # a small area, so it costs little power. Lift the logo until its brightest
    # channel is at full, at most doubling it.
    peak = max((max(c) for _, _, cov, c in pixels if cov > 0.5), default=255)
    gain = min(2.0, 255.0 / peak) if peak else 1.0
    for tx, ty, coverage, colour in pixels:
        i = 3 * ((oy + ty) * WIDTH + ox + tx)
        for k in range(3):
            lifted = min(255.0, colour[k] * gain)
            out[i + k] = int(out[i + k] * (1 - coverage) + lifted * coverage)
    return bytes(out)


# Midtone lift for game art. Even at full brightness the panel is much dimmer
# than the Steam Machine's light bar, so midtones get pushed up. The power cap
# in service.py still trims any frame that would draw too much.
ART_GAMMA = 0.7


def find_art(appid, kind):
    """Path of a game's art of one kind (hero, header, capsule, logo), or None.

    Same lookup as the light bar's Artwork, so both pick the same picture:
    custom grid art first (SteamGridDB writes there), then the library cache.
    """
    path = find_library_logo(appid) if kind == "logo" else find_library_artwork(appid, kind)
    return str(path) if path else None


def running_appid(proc_root="/proc"):
    """App ID of the game Steam is running, from its `reaper SteamLaunch AppId=N` process (0 if none)."""
    best = (0, 0)
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, "cmdline"), "rb") as handle:
                args = handle.read(4096).split(b"\0")
        except OSError:
            continue
        if b"SteamLaunch" not in args:
            continue
        for arg in args:
            if arg.startswith(b"AppId="):
                try:
                    appid = int(arg[6:])
                except ValueError:
                    break
                # Newest launch wins if two are up (e.g. a game started from another).
                if appid and int(entry) > best[0]:
                    best = (int(entry), appid)
                break
    return best[1]


def artwork(appid, style="logo_dim", position="bottom"):
    """The best 64x54 picture for a game, or None if nothing usable is cached.

    Side by side on five games, wide hero art with the transparent logo over
    the bottom beat the portrait cover: centred subject, readable title. The
    portrait cover cropped near the top is the fallback, then the header.

    style: logo_dim (art, logo, dark band behind it), logo (no band), art
    (no logo) or logo_only (the logo big on black; art if there's no logo).
    """
    if not appid:
        return None
    if style == "logo_only":
        path = find_art(appid, "logo")
        logo = load_logo(path, max_height=HEIGHT - 6) if path else None
        if logo:
            return place_logo(bytes(FRAME_BYTES), logo, position, band=False)
        style = "logo_dim"
    hero = find_art(appid, "hero")
    if hero:
        frame = decode_image(hero)
        if frame:
            frame = lift(sharpen(frame), ART_GAMMA)
            if style == "art":
                return frame
            path = find_art(appid, "logo")
            logo = load_logo(path) if path else None
            return place_logo(frame, logo, position, band=style == "logo_dim") if logo else frame
    for kind, bias in (("capsule", 0.2), ("header", 0.5)):
        path = find_art(appid, kind)
        if path:
            frame = decode_image(path, ybias=bias)
            if frame:
                return sharpen(frame)
    return None


# Steam's own icon, drawn from the copy SteamOS installs rather than shipped
# with the plugin (it's Valve's logo).
STEAM_ICONS = (
    "/usr/share/icons/hicolor/256x256/apps/steam.png",
    "/usr/share/icons/hicolor/48x48/apps/steam.png",
)


def steam_logo(size=46, paths=STEAM_ICONS):
    """The Steam logo centred on black, or None if SteamOS's icon isn't there."""
    for path in paths:
        if not os.path.isfile(path):
            continue
        dims = image_size(path) or (size, size)
        w = max(1, round(size * dims[0] / max(dims)))
        h = max(1, round(size * dims[1] / max(dims)))
        rgba = _gst_decode(path, w, h, alpha=True)
        if rgba is None:
            continue
        out = bytearray(FRAME_BYTES)
        ox, oy = (WIDTH - w) // 2, (HEIGHT - h) // 2
        for y in range(h):
            for x in range(w):
                j = 4 * (y * w + x)
                a = rgba[j + 3]
                if a:
                    i = 3 * ((oy + y) * WIDTH + ox + x)
                    for k in range(3):
                        out[i + k] = rgba[j + k] * a // 255
        return bytes(out)
    return None
