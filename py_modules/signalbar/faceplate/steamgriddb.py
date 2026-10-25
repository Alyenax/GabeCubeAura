# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Faceplate-only SteamGridDB artwork library.

The personal API key and downloaded originals never enter GabeCubeAura's
exported settings.  Originals are compiled once into the panel's native GIF
format; game launches then reuse the local result without a network request.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import time
import threading
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

from . import gif, protocol
from .artwork import clean_environment, sharpen


API_BASE = "https://www.steamgriddb.com/api/v2"
API_KEY_URL = "https://www.steamgriddb.com/profile/preferences/api"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 256 * 1024
MAX_GIF_BYTES = 2 * 1024 * 1024
MAX_FRAMES = 80
FRAME_RATE = 10
DASHBOARD_PACK_MAX_FRAMES = MAX_FRAMES
DASHBOARD_PACK_REVISION = "artwork-dashboard-background-2"
TERMINAL_BLANK_MAX_FRAMES = 3
TERMINAL_BLANK_CHANNEL = 8
TERMINAL_BLANK_RATIO = 0.99
TERMINAL_EDGE_MAX_ROWS = 2
LOOP_CLEANUP_LEVELS = {"no", "soft", "medium", "aggressive"}
MAX_RESULTS_PER_KIND = 12
MAX_RESULTS_TOTAL = 24
PREFERENCES = {"animated", "animated_any", "static", "hero_pan", "both"}
SQUARE_DIMENSIONS = "512x512,1024x1024"
# Animated faceplate art is normally published as a hero, portrait or wide
# grid. Square grids remain available through the legacy explicit mode, but
# automatic discovery deliberately avoids them.
ALL_GRID_DIMENSIONS = "600x900,342x482,660x930,460x215,920x430"
HERO_DIMENSIONS = "1920x620,3840x1240,1600x650"
ALLOWED_HOSTS = {"www.steamgriddb.com", "steamgriddb.com"}
API_KEY = re.compile(r"^[A-Za-z0-9._~-]{16,512}$")


def prepared_compatibility(manifest):
    """Metadata-only: never infer the absence of a baked overlay from pixels."""
    components = manifest.get("matrix_components", [])
    components = components if isinstance(components, list) else []
    if (manifest.get("scene") == "performance" or manifest.get("bottom_mode") in {"performance", "cpu_gpu"}
            or any(value in {"performance", "cpu", "gpu", "cpu_gpu"} for value in components if isinstance(value, str))):
        return "retired-overlay"
    return "current" if manifest.get("matrix_policy") == "no-cpu-v2" else "legacy-unverified"
SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",  # Arch/SteamOS ca-certificates-utils
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/certs/ca-bundle.crt",
)


class SteamGridDBError(RuntimeError):
    def __init__(self, message, code="request_failed"):
        super().__init__(message)
        self.code = str(code)


def _certificate_failure(error):
    reason = getattr(error, "reason", error)
    return isinstance(reason, ssl.SSLCertVerificationError) or (
        isinstance(reason, ssl.SSLError)
        and "CERTIFICATE_VERIFY_FAILED" in str(reason)
    )


def default_root(user_home=None):
    home = Path(user_home or os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~"))
    return home / ".local/share/gabecubeaura/steamgriddb"


def _trusted_url(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host in ALLOWED_HOSTS or host.endswith(".steamgriddb.com"))


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _trusted_url(newurl):
            raise SteamGridDBError("SteamGridDB redirected to an untrusted host")
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected is not None and urlparse(request.full_url).hostname != urlparse(newurl).hostname:
            redirected.remove_header("Authorization")
        return redirected


def _atomic_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path, maximum=MAX_JSON_BYTES):
    try:
        if not path.is_file() or path.stat().st_size > maximum:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _source_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8"):
        return "jpg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    raise SteamGridDBError("SteamGridDB returned an unsupported image format")


def _palette_332():
    return [
        (round(red * 255 / 7), round(green * 255 / 7), round(blue * 255 / 3))
        for red in range(8) for green in range(8) for blue in range(4)
    ]


PALETTE_332 = _palette_332()


def _index_332(rgb):
    out = bytearray(len(rgb) // 3)
    for pixel, offset in enumerate(range(0, len(rgb), 3)):
        red = (rgb[offset] * 7 + 127) // 255
        green = (rgb[offset + 1] * 7 + 127) // 255
        blue = (rgb[offset + 2] * 3 + 127) // 255
        out[pixel] = (red << 5) | (green << 2) | blue
    return bytes(out)


def _adjust(rgb, saturation=100, brightness=100):
    saturation = max(0, min(200, int(saturation))) / 100.0
    brightness = max(50, min(150, int(brightness))) / 100.0
    out = bytearray(len(rgb))
    for offset in range(0, len(rgb), 3):
        red, green, blue = rgb[offset:offset + 3]
        luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        for channel, value in enumerate((red, green, blue)):
            out[offset + channel] = max(0, min(255, round(
                (luma + (value - luma) * saturation) * brightness
            )))
    return bytes(out)


def _cover_dimensions(source_width, source_height):
    try:
        width, height = int(source_width), int(source_height)
    except (TypeError, ValueError, OverflowError):
        width, height = 64, 64
    if width <= 0 or height <= 0:
        width, height = 64, 64
    source_ratio = width / height
    target_ratio = protocol.WIDTH / protocol.HEIGHT
    if source_ratio >= target_ratio:
        width, height = max(
            protocol.WIDTH, math.ceil(protocol.HEIGHT * source_ratio),
        ), protocol.HEIGHT
    else:
        width, height = protocol.WIDTH, max(
            protocol.HEIGHT, math.ceil(protocol.WIDTH / source_ratio),
        )
    # GStreamer raw RGB rows are commonly padded to a four-byte boundary.
    # Making the pixel width a multiple of four makes width*3 aligned too and
    # prevents a row of padding from slowly walking into later video frames.
    width = (width + 3) // 4 * 4
    return width, height


def _crop_cover(rgb, width, height, focus=50, focus_x=None):
    focus = max(0, min(100, int(focus)))
    horizontal = focus if focus_x is None else max(0, min(100, int(focus_x)))
    x0 = round(max(0, width - protocol.WIDTH) * horizontal / 100.0)
    y0 = round(max(0, height - protocol.HEIGHT) * focus / 100.0)
    return b"".join(
        rgb[((y0 + row) * width + x0) * 3:
            ((y0 + row) * width + x0 + protocol.WIDTH) * 3]
        for row in range(protocol.HEIGHT)
    )


def _black_pixel_ratio(rgb, threshold=TERMINAL_BLANK_CHANNEL):
    """Return the share of pixels whose three channels are nearly black."""
    pixels = len(rgb) // 3
    if not pixels:
        return 1.0
    black = sum(
        1 for offset in range(0, pixels * 3, 3)
        if max(rgb[offset:offset + 3]) <= threshold
    )
    return black / pixels


def _trim_terminal_decoder_blanks(frames):
    """Remove only a short, abrupt decoder-black tail from an animation.

    Some animated SteamGridDB sources end with one or two empty/transparent
    video buffers. Converting them to packed RGB turns those buffers black, so
    the faceplate flashes just before the GIF loops. A long or gradual dark
    ending can be authored content and must be kept; only a short nearly-black
    tail after a clearly visible frame is classified as a decoder artefact.
    """
    if len(frames) < 2:
        return frames
    trailing = 0
    for frame in reversed(frames):
        if _black_pixel_ratio(frame) < TERMINAL_BLANK_RATIO:
            break
        trailing += 1
    if trailing == 0 or trailing > TERMINAL_BLANK_MAX_FRAMES or trailing >= len(frames):
        return frames
    previous = frames[-trailing - 1]
    visible_pixels = sum(
        1 for offset in range(0, len(previous), 3)
        if max(previous[offset:offset + 3]) >= 24
    )
    if visible_pixels / max(1, len(previous) // 3) < 0.05:
        return frames
    return frames[:-trailing]


def _repair_terminal_black_edges(frames):
    """Restore a decoder-only black top/bottom edge on the final frame."""
    if len(frames) < 2:
        return frames
    previous, final = frames[-2], bytearray(frames[-1])
    row_bytes = protocol.WIDTH * 3
    repaired = False
    for rows in (
        range(TERMINAL_EDGE_MAX_ROWS),
        range(protocol.HEIGHT - 1, protocol.HEIGHT - 1 - TERMINAL_EDGE_MAX_ROWS, -1),
    ):
        for row in rows:
            start, end = row * row_bytes, (row + 1) * row_bytes
            current_ratio = _black_pixel_ratio(final[start:end])
            previous_ratio = _black_pixel_ratio(previous[start:end])
            if current_ratio < 0.95 or previous_ratio > 0.25:
                break
            final[start:end] = previous[start:end]
            repaired = True
    if not repaired:
        return frames
    return frames[:-1] + [bytes(final)]


def _repair_terminal_decoder_artifacts(frames):
    frames = _trim_terminal_decoder_blanks(frames)
    return _repair_terminal_black_edges(frames)


def _restore_terminal_decoder_artifacts(frames):
    """Repair proven decoder debris without removing a frame slot.

    ``No cleanup`` means that Pixel Studio must not shorten or retime authored
    motion. It must not mean that a decoder-generated empty RGB buffer is
    treated as authored content. Replace only a short abrupt black tail with
    the last visible frame, then apply the same narrow edge-row repair used by
    Lab 25. The returned list always has the original length.
    """
    restored = list(frames)
    if len(restored) < 2:
        return restored
    trailing = 0
    for frame in reversed(restored):
        if _black_pixel_ratio(frame) < TERMINAL_BLANK_RATIO:
            break
        trailing += 1
    if 0 < trailing <= TERMINAL_BLANK_MAX_FRAMES and trailing < len(restored):
        previous = restored[-trailing - 1]
        visible_pixels = sum(
            1 for offset in range(0, len(previous), 3)
            if max(previous[offset:offset + 3]) >= 24
        )
        if visible_pixels / max(1, len(previous) // 3) >= 0.05:
            restored[-trailing:] = [previous] * trailing
    return _repair_terminal_black_edges(restored)


def _normalize_loop_cleanup(value):
    value = str(value or "no").lower()
    return value if value in LOOP_CLEANUP_LEVELS else "no"


def _loop_seam_score(first, candidate):
    """Prefer an endpoint close to frame zero without choosing black debris."""
    if not first or len(first) != len(candidate):
        return float("inf")
    difference = sum(abs(left - right) for left, right in zip(first, candidate)) / len(first)
    return difference + 96.0 * _black_pixel_ratio(candidate)


def _apply_loop_cleanup(frames, level="no"):
    """Repair decoder debris, then optionally find a stronger loop endpoint."""
    level = _normalize_loop_cleanup(level)
    original_count = len(frames)
    # No cleanup disables authored-motion trimming, not technical decoder
    # sanitation. Preserve every timing slot while replacing only proven empty
    # terminal buffers or a decoder-only black edge. Soft retains the historic
    # Lab 25 behavior and may remove a short empty tail.
    cleaned = (
        _restore_terminal_decoder_artifacts(frames)
        if level == "no" else _repair_terminal_decoder_artifacts(frames)
    )
    automatic_trim = original_count - len(cleaned)
    user_trim = 0
    if level in {"medium", "aggressive"} and len(cleaned) > 2:
        minimum, maximum = ((1, 5) if level == "medium" else (4, 10))
        maximum = min(maximum, len(cleaned) - 2)
        minimum = min(minimum, maximum)
        if maximum >= 1:
            user_trim = min(
                range(minimum, maximum + 1),
                key=lambda trim: (_loop_seam_score(cleaned[0], cleaned[-trim - 1]), trim),
            )
            cleaned = cleaned[:-user_trim]
    trimmed = automatic_trim + user_trim
    return cleaned, {
        "loop_cleanup": level,
        "loop_original_frames": original_count,
        "loop_trimmed_frames": trimmed,
        "loop_trimmed_ms": round(trimmed * 1000 / FRAME_RATE),
    }


def _decoder_error(stderr):
    """Keep the useful codec/demuxer line instead of FFmpeg's final summary."""
    lines = [line.strip() for line in stderr.decode(
        "utf-8", "replace",
    ).splitlines() if line.strip()]
    generic = (
        "nothing was written into output file",
        "pipeline doesn't want to preroll",
        "pipeline doesn’t want to preroll",
        "conversion failed",
    )
    actionable = [
        line for line in lines
        if not any(marker in line.lower() for marker in generic)
    ]
    return (actionable[-1] if actionable else (lines[-1] if lines else "no video frames"))[:180]


def decode_frames(path, crop_y=50, saturation=100, brightness=100, timeout=20,
                  source_width=0, source_height=0, animation_style="source",
                  crop_x=50, loop_cleanup="no", cleanup_stats=None):
    """Decode at most eight seconds and cover-crop without distorting the source."""
    executable = shutil.which("gst-launch-1.0")
    ffmpeg = shutil.which("ffmpeg")
    if not executable and not ffmpeg:
        raise SteamGridDBError("Neither GStreamer nor FFmpeg is available")
    decode_width, decode_height = _cover_dimensions(source_width, source_height)
    # Explicit static use stays bounded even if a server mislabels an animated
    # source: decode exactly one frame, never the eight-second animation bank.
    max_frames = 1 if animation_style == "static" else MAX_FRAMES
    attempts = []
    if executable:
        attempts.append(("GStreamer", [
            executable, "-q", "filesrc", f"location={path}", "!", "decodebin", "!",
            "videoconvert", "!", "videoscale", "method=3", "add-borders=false", "!",
            "videorate", "!",
            (f"video/x-raw,format=RGB,width={decode_width},height={decode_height},"
             f"pixel-aspect-ratio=1/1,framerate={FRAME_RATE}/1"),
            "!", "identity", f"eos-after={2 if animation_style == 'static' else max_frames}", "!", "fdsink", "fd=1",
            "sync=false",
        ]))
    if ffmpeg:
        attempts.append(("FFmpeg", [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-vf", f"fps={FRAME_RATE},scale={decode_width}:{decode_height}:flags=lanczos",
            "-frames:v", str(max_frames), "-an", "-sn", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "pipe:1",
        ]))
        # Some community WebM uploads contain sparse, negative or malformed
        # timestamps. Steam/Chromium can still play them, while a strict
        # command can reach EOF without emitting a frame. This bounded retry
        # regenerates timestamps, ignores damaged packets and explicitly maps
        # the first video stream before we fall back to the SGDB preview.
        attempts.append(("FFmpeg recovery", [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-fflags", "+genpts+discardcorrupt", "-err_detect", "ignore_err",
            "-analyzeduration", "100M", "-probesize", "100M", "-i", str(path),
            "-map", "0:v:0", "-vf",
            (f"setpts=PTS-STARTPTS,fps={FRAME_RATE},"
             f"scale={decode_width}:{decode_height}:flags=lanczos"),
            "-frames:v", str(max_frames), "-an", "-sn", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "pipe:1",
        ]))
    result = None
    frame_bytes = decode_width * decode_height * 3
    failures = []
    for name, command in attempts:
        try:
            candidate = subprocess.run(
                command, capture_output=True, timeout=timeout, check=False,
                env=clean_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            failures.append(f"{name}: {type(error).__name__}")
            continue
        count = min(max_frames, len(candidate.stdout) // frame_bytes)
        if candidate.returncode == 0 and count >= 1:
            result = candidate
            break
        failures.append(f"{name}: {_decoder_error(candidate.stderr)}")
    if result is None:
        raise SteamGridDBError(
            "Could not decode the SteamGridDB artwork (" + "; ".join(failures)[:300] + ")"
        )
    count = min(max_frames, len(result.stdout) // frame_bytes)
    frames = []
    if animation_style == "pan":
        # A static wide hero becomes an eight-second hardware GIF. The triangle
        # path returns through the picture instead of jumping from the far edge
        # back to frame zero. Smoothstep gives both ends a natural brief dwell.
        raw = result.stdout[:frame_bytes]
        for index in range(MAX_FRAMES):
            phase = index / max(1, MAX_FRAMES)
            ping_pong = 1.0 - abs(1.0 - 2.0 * phase)
            eased = ping_pong * ping_pong * (3.0 - 2.0 * ping_pong)
            frame = _adjust(
                _crop_cover(raw, decode_width, decode_height, crop_y,
                            round(eased * 100)),
                saturation, brightness,
            )
            frames.append(sharpen(frame, 0.45))
        if isinstance(cleanup_stats, dict):
            cleanup_stats.update({
                "loop_cleanup": "no", "loop_original_frames": len(frames),
                "loop_trimmed_frames": 0, "loop_trimmed_ms": 0,
            })
        return frames
    for index in range(count):
        raw = result.stdout[index * frame_bytes:(index + 1) * frame_bytes]
        frame = _adjust(
            _crop_cover(raw, decode_width, decode_height, crop_y, crop_x),
            saturation, brightness,
        )
        frames.append(sharpen(frame, 0.45))
    frames, details = _apply_loop_cleanup(frames, loop_cleanup)
    if isinstance(cleanup_stats, dict):
        cleanup_stats.update(details)
    return frames


def _dashboard_pack_frames(frames):
    """Keep every prepared source frame for the Dashboard compositor."""
    frames = list(frames)
    if len(frames) <= DASHBOARD_PACK_MAX_FRAMES:
        return frames
    # Include both endpoints.  The source decoder has already removed short
    # terminal blanks and repaired decoder-only black edges.
    indexes = [
        round(index * (len(frames) - 1) / (DASHBOARD_PACK_MAX_FRAMES - 1))
        for index in range(DASHBOARD_PACK_MAX_FRAMES)
    ]
    return [frames[index] for index in indexes]


def compile_source(path, crop_y=50, saturation=100, brightness=100,
                   source_width=0, source_height=0, animation_style="source",
                   crop_x=50, include_frames=False, loop_cleanup="no",
                   cleanup_stats=None, appid=0, art_style="art",
                   logo_position="bottom", logo_scale=100):
    from .artwork_layout import compose_frame, prepare_logo, validate_layout, validate_logo_scale
    validate_layout(art_style, logo_position)
    validate_logo_scale(logo_scale)
    frames = decode_frames(
        path, crop_y, saturation, brightness,
        source_width=source_width, source_height=source_height,
        animation_style=animation_style, crop_x=crop_x,
        loop_cleanup=loop_cleanup, cleanup_stats=cleanup_stats,
    )
    # Static, pan and animated sources share the same one-time composition.
    # Transparent logos are decoded once, outside the game-launch path.
    if int(appid or 0) > 0 and art_style != "art":
        prepared_logo = prepare_logo(appid)
        if prepared_logo is not None:
            if art_style == "logo_only":
                frames = [compose_frame(frames[0], prepared_logo, art_style, logo_position, logo_scale)]
            else:
                frames = [
                    compose_frame(frame, prepared_logo, art_style, logo_position, logo_scale)
                    for frame in frames
                ]
    indexed = [_index_332(frame) for frame in frames]
    data = gif.encode(
        protocol.WIDTH, protocol.HEIGHT, PALETTE_332, indexed,
        delay_cs=round(100 / FRAME_RATE), loop=len(indexed) > 1,
    )
    if len(data) > MAX_GIF_BYTES:
        raise SteamGridDBError("Compiled faceplate GIF exceeds 2 MiB")
    peak_load = max(sum(frame) / (len(frame) * 255.0) for frame in frames)
    result = (data, peak_load, len(frames))
    if include_frames:
        return (*result, _dashboard_pack_frames(frames))
    return result


class SteamGridDBFaceplate:
    def __init__(self, root=None, logger=None, opener=None, clock=time.time):
        self.root = Path(root or default_root())
        self.auth_path = self.root / "auth.json"
        self.preferences_path = self.root / "preferences.json"
        self.artwork_root = self.root / "artwork"
        self.logger = logger
        self.opener = opener or build_opener(_Redirects())
        self.clock = clock
        self._results = {}
        self._auth_lock = threading.RLock()
        self._auth_generation = 0

    def _open_with_system_trust(self, request, first_error, timeout=10):
        """Retry verified HTTPS against SteamOS's explicit CA bundle.

        Decky's embedded Python can resolve a different default OpenSSL trust
        path from the host. Never disable certificate or hostname checks: use
        the same system-CA recovery already proven by GabeCubeAura Weather.
        """
        last_error = first_error
        attempted = set()
        for bundle in SYSTEM_CA_BUNDLES:
            if not os.path.isfile(bundle):
                continue
            resolved = os.path.realpath(bundle)
            if resolved in attempted:
                continue
            attempted.add(resolved)
            try:
                context = ssl.create_default_context(cafile=bundle)
            except OSError as error:
                last_error = error
                continue
            try:
                opener = build_opener(_Redirects(), HTTPSHandler(context=context))
                return opener.open(request, timeout=timeout)
            except (URLError, ssl.SSLError) as error:
                if not _certificate_failure(error):
                    raise
                last_error = error
        raise SteamGridDBError(
            "SteamGridDB HTTPS certificate could not be verified with the SteamOS system CA bundle",
            "tls",
        ) from last_error

    def _log(self, level, message):
        callback = getattr(self.logger, level, None)
        if callable(callback):
            callback("[GabeCubeAura SteamGridDB] " + message)

    def api_key(self):
        value = str(_read_json(self.auth_path).get("api_key", "")).strip()
        return value if API_KEY.fullmatch(value) else ""

    @staticmethod
    def _key_fingerprint(key):
        return hashlib.sha256(str(key).encode("utf-8")).hexdigest()

    def _auth_status(self):
        record = _read_json(self.auth_path)
        key = self.api_key()
        if not key:
            return "absent", 0.0, 0.0, "", ""
        fingerprint = self._key_fingerprint(key)
        if record.get("key_fingerprint") != fingerprint:
            return "detected_unverified", 0.0, 0.0, "", ""
        state = str(record.get("validation_state", "detected_unverified"))
        if state not in {"detected_unverified", "validated", "rejected", "offline"}:
            state = "detected_unverified"
        return (
            state,
            float(record.get("validation_checked_at", 0.0) or 0.0),
            float(record.get("validated_at", 0.0) or 0.0),
            str(record.get("validation_code", ""))[:48],
            str(record.get("validation_detail", ""))[:180],
        )

    def _write_auth(self, key, validation_state="detected_unverified",
                    checked_at=0.0, validated_at=0.0,
                    validation_code="", validation_detail=""):
        _atomic_json(self.auth_path, {
            "schema": 2,
            "api_key": key,
            "key_fingerprint": self._key_fingerprint(key),
            "validation_state": validation_state,
            "validation_checked_at": float(checked_at or 0.0),
            "validated_at": float(validated_at or 0.0),
            "validation_code": str(validation_code or "")[:48],
            "validation_detail": str(validation_detail or "")[:180],
        })

    def set_api_key(self, value, validate=False):
        key = str(value or "").strip()
        if not API_KEY.fullmatch(key):
            raise SteamGridDBError("Invalid SteamGridDB API key")
        with self._auth_lock:
            self._auth_generation += 1
            previous = _read_json(self.auth_path)
            if previous.get("api_key") == key:
                state, checked_at, validated_at, code, detail = self._auth_status()
            else:
                state, checked_at, validated_at, code, detail = (
                    "detected_unverified", 0.0, 0.0, "", "",
                )
            self._write_auth(key, state, checked_at, validated_at, code, detail)
        return self.validate_api_key() if validate else self.status()

    def validate_api_key(self):
        """Validate the stored secret without ever returning it to callers."""
        with self._auth_lock:
            generation = self._auth_generation
            key = self.api_key()
        if not key:
            return self.status()
        checked_at = float(self.clock())
        try:
            # Portal 2 is a stable, tiny game lookup.  A successful authenticated
            # response proves the key without downloading an artwork catalogue.
            self._json_request(f"{API_BASE}/games/steam/620")
        except SteamGridDBError as error:
            state = "rejected" if error.code == "unauthorized" else "offline"
            detail = str(error)[:180] or "SteamGridDB validation failed"
            with self._auth_lock:
                if generation != self._auth_generation:
                    return self.status()
                self._write_auth(key, state, checked_at, 0.0, error.code, detail)
            self._log("warning", f"API-key validation failed ({error.code}): {detail}")
            return self.status()
        with self._auth_lock:
            if generation != self._auth_generation:
                return self.status()
            self._write_auth(key, "validated", checked_at, checked_at)
        return self.status()

    def clear_api_key(self):
        with self._auth_lock:
            self._auth_generation += 1
            try:
                self.auth_path.unlink()
            except FileNotFoundError:
                pass
        return self.status()

    def preference(self):
        value = str(_read_json(self.preferences_path).get("preference", "animated_any"))
        # Lab 10 defaulted to animated square grids. Existing installs migrate
        # to the hero/portrait/wide search that better matches SGDB uploads.
        if value == "animated":
            return "animated_any"
        return value if value in PREFERENCES else "animated_any"

    def set_preference(self, value):
        preference = str(value or "")
        if preference not in PREFERENCES:
            raise SteamGridDBError("Invalid SteamGridDB artwork preference")
        _atomic_json(self.preferences_path, {"schema": 1, "preference": preference}, 0o644)
        return self.status()

    def configuration_snapshot(self):
        """Saved artwork choices and preparation controls, without media/auth."""
        keys=('schema','appid','asset_id','mode','source_variant','asset_kind',
              'crop_x','crop_y','saturation','brightness','art_style','logo_position','logo_scale',
              'animation_style','loop_cleanup','dashboard_treatment','dashboard_compression',
              'dashboard_show_clock','dashboard_clock_choice','dashboard_clock_size',
              'dashboard_show_status_rail','dashboard_show_session','dashboard_show_battery',
              'source_sha256','sha256')
        def read_saved(path):
            if path.stat().st_size>65536:
                raise ValueError('Artwork metadata exceeds the snapshot limit')
            value=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value,dict):
                raise ValueError('Artwork metadata is not an object')
            return value
        if self.preferences_path.is_symlink():
            raise ValueError('Cannot snapshot linked artwork preferences')
        if self.preferences_path.exists():
            read_saved(self.preferences_path)
        result=dict(preference=self.preference(), games={})
        if not self.artwork_root.exists():
            return result
        if self.artwork_root.is_symlink():
            raise ValueError('Cannot snapshot a linked artwork library')
        for app in sorted(self.artwork_root.iterdir()):
            if not app.name.isdigit() or not app.is_dir():
                continue
            if app.is_symlink():
                raise ValueError('Cannot snapshot a linked artwork entry')
            if len(result['games'])>=2000:
                raise ValueError('Artwork configuration exceeds the snapshot limit')
            entry=dict(selections={},prepared={})
            for context, filename in (('game','active.json'),('home','home.json')):
                path=app/filename
                if path.is_symlink():
                    raise ValueError('Cannot snapshot linked artwork preferences')
                if path.is_file():
                    selected=read_saved(path)
                    entry['selections'][context]={key:selected[key] for key in ('schema','appid','mode') if key in selected}
                for mode in ('static','animated','pan'):
                    path=self._prepared_root(int(app.name),mode,home=context=='home')/'manifest.json'
                    if any(p.is_symlink() for p in (path,*path.parents)
                           if p==self.artwork_root or self.artwork_root in p.parents):
                        raise ValueError('Cannot snapshot linked artwork metadata')
                    if path.is_file():
                        manifest=read_saved(path)
                        entry['prepared'][context+'/'+mode]={key:manifest[key] for key in keys if key in manifest}
            result['games'][app.name]=entry
            if len(json.dumps(result).encode('utf-8'))>768*1024:
                raise ValueError('Artwork configuration exceeds the snapshot limit')
        return result

    def status(self):
        validation_state, checked_at, validated_at, code, detail = self._auth_status()
        return {
            "configured": bool(self.api_key()),
            "validation_state": validation_state,
            "validation_checked_at": checked_at,
            "validated_at": validated_at,
            "validation_code": code,
            "validation_detail": detail,
            "preference": self.preference(),
            "api_key_url": API_KEY_URL,
        }

    def _json_request(self, url):
        key = self.api_key()
        if not key:
            raise SteamGridDBError("SteamGridDB API key is not configured")
        request = Request(url, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "GabeCubeAura/SteamGridDB-faceplate",
        })
        try:
            try:
                response = self.opener.open(request, timeout=10)
            except (URLError, ssl.SSLError) as error:
                if not _certificate_failure(error):
                    raise
                response = self._open_with_system_trust(request, error, timeout=10)
            with response:
                body = response.read(MAX_JSON_BYTES + 1)
        except HTTPError as error:
            if error.code == 401:
                raise SteamGridDBError(
                    "SteamGridDB rejected the API key", "unauthorized",
                ) from error
            if error.code == 403:
                raise SteamGridDBError(
                    "SteamGridDB denied the validation request (HTTP 403)", "forbidden",
                ) from error
            if error.code == 429:
                raise SteamGridDBError(
                    "SteamGridDB rate-limited validation (HTTP 429)", "rate_limited",
                ) from error
            if error.code >= 500:
                raise SteamGridDBError(
                    f"SteamGridDB service error (HTTP {error.code})", "server_error",
                ) from error
            raise SteamGridDBError(
                f"SteamGridDB request failed (HTTP {error.code})", "http_error",
            ) from error
        except (URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            if _certificate_failure(error):
                code, message = "tls", "SteamGridDB TLS certificate verification failed"
            elif isinstance(reason, (socket.timeout, TimeoutError)):
                code, message = "timeout", "SteamGridDB validation timed out"
            elif isinstance(reason, socket.gaierror):
                code, message = "dns", "SteamGridDB hostname could not be resolved"
            else:
                code, message = "network", "SteamGridDB could not be reached"
            raise SteamGridDBError(message, code) from error
        if len(body) > MAX_JSON_BYTES:
            raise SteamGridDBError("SteamGridDB response is too large")
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise SteamGridDBError(
                "SteamGridDB returned invalid JSON", "invalid_response",
            ) from error
        if not isinstance(value, dict) or not value.get("success"):
            errors = value.get("errors", []) if isinstance(value, dict) else []
            message = str(errors[0])[:160] if errors else "SteamGridDB request failed"
            code = "unauthorized" if "auth" in message.lower() else "api_error"
            raise SteamGridDBError(message, code)
        return value

    @staticmethod
    def _asset(raw, kind):
        if not isinstance(raw, dict) or not _trusted_url(raw.get("url")):
            return None
        thumb = str(raw.get("thumb", ""))
        source_url = str(raw.get("url", ""))
        animated = bool(raw.get("type") == "animated" or ".webm" in thumb.lower()
                        or ".webm" in source_url.lower())
        try:
            width, height = int(raw.get("width", 0) or 0), int(raw.get("height", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            width, height = 0, 0
        asset = {
            "id": int(raw.get("id", 0) or 0),
            "kind": kind,
            "score": int(raw.get("score", 0) or 0),
            "style": str(raw.get("style", ""))[:32],
            "url": str(raw["url"]),
            "thumb": thumb if _trusted_url(thumb) else str(raw["url"]),
            "animated": animated,
            "author": str((raw.get("author") or {}).get("name", ""))[:64],
            "width": max(0, width),
            "height": max(0, height),
        }
        return asset if asset["id"] > 0 else None

    def _search_kind(self, appid, kind, dimensions, types):
        query_values = {
            "dimensions": dimensions,
            "types": types,
            "nsfw": "false", "humor": "false", "epilepsy": "false",
            "limit": MAX_RESULTS_PER_KIND, "page": 0,
        }
        # SteamGridDB animated entries are commonly served as WebM.  Filtering
        # them to image/* silently removed the most useful candidates.
        if "animated" not in types:
            query_values["mimes"] = "image/png,image/jpeg,image/webp"
        query = urlencode(query_values)
        endpoint = "heroes" if kind == "hero" else "grids"
        value = self._json_request(f"{API_BASE}/{endpoint}/steam/{appid}?{query}")
        return [asset for raw in value.get("data", [])
                if (asset := self._asset(raw, kind)) is not None]

    def search(self, appid, preference=None):
        appid = int(appid)
        if appid <= 0:
            raise SteamGridDBError("A Steam app ID is required")
        preference = preference or self.preference()
        if preference not in PREFERENCES:
            raise SteamGridDBError("Invalid SteamGridDB artwork preference")
        if preference == "animated_any":
            assets = self._search_kind(appid, "grid", ALL_GRID_DIMENSIONS, "animated")
            assets += self._search_kind(appid, "hero", HERO_DIMENSIONS, "animated")
        elif preference == "hero_pan":
            assets = self._search_kind(appid, "hero", HERO_DIMENSIONS, "static")
        else:
            types = "animated,static" if preference == "both" else preference
            assets = self._search_kind(appid, "grid", SQUARE_DIMENSIONS, types)
        if preference == "animated":
            assets.sort(key=lambda item: (not item["animated"], -item["score"]))
        elif preference == "static":
            assets.sort(key=lambda item: (item["animated"], -item["score"]))
        if preference in {"animated_any", "hero_pan"}:
            assets.sort(key=lambda item: (item["kind"] != "hero", -item["score"]))
        assets = assets[:MAX_RESULTS_TOTAL]
        self._results[appid] = {
            f'{item["kind"]}:{item["id"]}': item for item in assets
        }
        return assets

    @staticmethod
    def _content_length(response):
        headers = getattr(response, "headers", None)
        try:
            raw = headers.get("Content-Length", "") if headers is not None else ""
            value = int(raw)
        except (AttributeError, TypeError, ValueError):
            return 0
        return max(0, value)

    def _download_to(self, url, temporary, progress=None):
        """Stream one bounded source to disk without holding it in Decky's RAM."""
        if not _trusted_url(url):
            raise SteamGridDBError("Untrusted SteamGridDB asset URL")
        request = Request(url, headers={"User-Agent": "GabeCubeAura/SteamGridDB-faceplate"})
        temporary = Path(temporary)
        temporary.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        downloaded = 0
        first = b""
        last_percent = 8
        try:
            with self.opener.open(request, timeout=20) as response:
                expected = self._content_length(response)
                if expected > MAX_SOURCE_BYTES:
                    raise SteamGridDBError(
                        "SteamGridDB artwork exceeds the 128 MiB source limit"
                    )
                with temporary.open("wb") as output:
                    while True:
                        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        if len(first) < 32:
                            first = (first + chunk)[:32]
                        downloaded += len(chunk)
                        if downloaded > MAX_SOURCE_BYTES:
                            raise SteamGridDBError(
                                "SteamGridDB artwork exceeds the 128 MiB source limit"
                            )
                        output.write(chunk)
                        if callable(progress) and expected > 0:
                            percent = min(35, 8 + int(downloaded * 27 / expected))
                            if percent > last_percent:
                                last_percent = percent
                                progress(
                                    percent, "download",
                                    f"Downloading source artwork · {downloaded // (1024 * 1024)} / "
                                    f"{max(1, expected // (1024 * 1024))} MiB",
                                )
        except (HTTPError, URLError, OSError) as error:
            temporary.unlink(missing_ok=True)
            raise SteamGridDBError("Could not download SteamGridDB artwork") from error
        except SteamGridDBError:
            temporary.unlink(missing_ok=True)
            raise
        if not downloaded or not first:
            temporary.unlink(missing_ok=True)
            raise SteamGridDBError("SteamGridDB artwork download was empty")
        if callable(progress) and last_percent < 35:
            progress(
                35, "download",
                f"Source downloaded · {max(1, downloaded // (1024 * 1024))} MiB",
            )
        try:
            extension = _source_extension(first)
        except SteamGridDBError:
            temporary.unlink(missing_ok=True)
            raise
        return extension, downloaded

    def _cached_asset(self, appid, asset_id, asset_kind=None):
        results = self._results.get(appid, {})
        if asset_kind:
            return results.get(f"{asset_kind}:{asset_id}")
        if asset_id in results:  # compatibility with tests and older in-process callers
            return results[asset_id]
        return next((asset for asset in results.values()
                     if int(asset.get("id", 0)) == asset_id), None)

    def select(self, appid, asset_id, crop_y=50, saturation=110, brightness=100,
               preference=None, asset_kind=None, loop_cleanup="no"):
        appid, asset_id = int(appid), int(asset_id)
        asset = self._cached_asset(appid, asset_id, asset_kind)
        if asset is None:
            self.search(appid, preference)
            asset = self._cached_asset(appid, asset_id, asset_kind)
        if asset is None:
            raise SteamGridDBError("The selected SteamGridDB artwork is no longer available")
        result = self.prepare_choice(
            appid, asset, "animated" if asset.get("animated") else "static",
            crop_y=crop_y, saturation=saturation, brightness=brightness,
            loop_cleanup=loop_cleanup,
        )
        self.activate_prepared(appid, result["mode"])
        return result

    def _prepared_root(self, appid, mode, draft=False, home=False):
        mode = str(mode)
        if mode not in {"static", "animated", "pan"}:
            raise SteamGridDBError("Invalid prepared artwork mode")
        return self.artwork_root / str(int(appid)) / ("draft" if draft else "home" if home else "prepared") / mode

    def prepare_choice(self, appid, asset, mode, crop_y=50, saturation=110,
                       brightness=100, progress=None, crop_x=50,
                       dashboard_treatment="none",
                       dashboard_show_clock=None,
                       dashboard_clock_size="large",
                       dashboard_show_session=True,
                       dashboard_show_battery=True,
                       dashboard_compression="compatible",
                       loop_cleanup="no", art_style="art",
                       logo_position="bottom", draft=False, logo_scale=100):
        """Compile a candidate without changing what game launches display."""
        from .artwork_layout import validate_logo_scale
        validate_logo_scale(logo_scale)
        appid = int(appid)
        mode = str(mode)
        if appid <= 0 or mode not in {"static", "animated", "pan"}:
            raise SteamGridDBError("Invalid faceplate preparation request")
        if not isinstance(asset, dict) or int(asset.get("id", 0) or 0) <= 0:
            raise SteamGridDBError("Invalid SteamGridDB artwork candidate")
        notify = progress if callable(progress) else lambda *_args, **_kwargs: None
        notify(8, "download", "Downloading source artwork")
        destination = self._prepared_root(appid, mode, draft=draft)
        destination.mkdir(parents=True, mode=0o755, exist_ok=True)
        source_download = destination / "source.download.tmp"
        extension, _source_bytes = self._download_to(
            asset["url"], source_download, progress=notify,
        )
        source = destination / f"source.{extension}"
        os.replace(source_download, source)
        notify(40, "decode", "Decoding source frames")
        source_variant = "original"
        loop_cleanup = (
            _normalize_loop_cleanup(loop_cleanup) if mode == "animated" else "no"
        )
        cleanup_stats = {}

        def compile_downloaded(path):
            cleanup_stats.clear()
            return compile_source(
                path, crop_y=crop_y, saturation=saturation, brightness=brightness,
                source_width=asset.get("width", 0), source_height=asset.get("height", 0),
                animation_style=mode if mode in {"pan", "static"} else "source",
                crop_x=crop_x, include_frames=True,
                loop_cleanup=loop_cleanup, cleanup_stats=cleanup_stats,
                appid=appid, art_style=art_style, logo_position=logo_position, logo_scale=logo_scale,
            )

        try:
            compiled_result = compile_downloaded(source)
            data, peak_load, frame_count = compiled_result[:3]
            dashboard_frames = list(compiled_result[3]) if len(compiled_result) > 3 else []
        except SteamGridDBError as original_error:
            preview_url = str(asset.get("thumb", ""))
            if (not asset.get("animated") or preview_url == str(asset.get("url", ""))
                    or not _trusted_url(preview_url)):
                raise
            notify(42, "fallback", "Original WebM failed; downloading optimized preview")
            preview_download = destination / "source.preview.download.tmp"

            def preview_progress(percent, _stage, detail):
                mapped = 42 + max(0, min(27, int(percent) - 8)) * 10 // 27
                notify(mapped, "fallback", detail.replace("source artwork", "preview"))

            preview_extension, _preview_bytes = self._download_to(
                preview_url, preview_download, progress=preview_progress,
            )
            preview_source = destination / f"source.{preview_extension}"
            source.unlink(missing_ok=True)
            os.replace(preview_download, preview_source)
            source = preview_source
            source_variant = "optimized_preview"
            notify(54, "decode", "Decoding optimized SteamGridDB preview")
            try:
                compiled_result = compile_downloaded(source)
                data, peak_load, frame_count = compiled_result[:3]
                dashboard_frames = list(compiled_result[3]) if len(compiled_result) > 3 else []
            except SteamGridDBError as preview_error:
                raise SteamGridDBError(
                    "Original and optimized SteamGridDB animations could not be decoded ("
                    f"original: {original_error}; preview: {preview_error})"
                ) from preview_error
        compiled = destination / "faceplate.gif"
        compiled_tmp = destination / "faceplate.gif.tmp"
        compiled_tmp.write_bytes(data)
        os.replace(compiled_tmp, compiled)
        dashboard_pack = destination / "artwork-dashboard.rgb"
        dashboard_pack_tmp = destination / "artwork-dashboard.rgb.tmp"
        if dashboard_frames:
            dashboard_pack_tmp.write_bytes(b"".join(dashboard_frames))
            os.replace(dashboard_pack_tmp, dashboard_pack)
        else:
            dashboard_pack.unlink(missing_ok=True)
        notify(94, "validate", "Validating hardware GIF")
        treatment = str(dashboard_treatment or "none").strip().lower()
        if treatment not in {"none", "cinema", "hero-cut", "palette-echo"}:
            treatment = "none"
        dashboard_compression = str(
            dashboard_compression or "compatible"
        ).strip().lower()
        if dashboard_compression not in {"compatible", "balanced", "fine"}:
            dashboard_compression = "compatible"
        clock_size = str(dashboard_clock_size or "large").strip().lower()
        if clock_size not in {"compact", "large"}:
            clock_size = "large"
        # The two exclusive anchors are persisted as resolved dashboard rules,
        # so a stale or older UI cannot accidentally create an overlap.
        clock_choice = "default-off" if dashboard_show_clock is None else "explicit"
        dashboard_show_clock = bool(dashboard_show_clock) and logo_position != "top"
        dashboard_show_status_rail = logo_position != "bottom_rail"
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        pack_sha256 = (
            hashlib.sha256(dashboard_pack.read_bytes()).hexdigest()
            if dashboard_frames else ""
        )
        manifest = {
            "matrix_policy": "no-cpu-v2", "matrix_components": ["artwork-background"],
            "schema": 2, "appid": appid, "asset_id": int(asset["id"]),
            "mode": mode, "ready": True,
            "animation_style": "pan" if mode == "pan" else "source",
            "source": source.name, "compiled": compiled.name,
            "source_variant": source_variant,
            "source_url": asset["url"], "thumb": asset["thumb"],
            "animated": asset["animated"], "author": asset["author"],
            "asset_kind": asset.get("kind", "grid"),
            "source_width": int(asset.get("width", 0) or 0),
            "source_height": int(asset.get("height", 0) or 0),
            "crop_axis": (
                "horizontal" if int(asset.get("width", 0) or 0) * protocol.HEIGHT
                >= int(asset.get("height", 0) or 0) * protocol.WIDTH else "vertical"
            ),
            "crop_y": max(0, min(100, int(crop_y))),
            "crop_x": max(0, min(100, int(crop_x))),
            "saturation": max(0, min(200, int(saturation))),
            "brightness": max(50, min(150, int(brightness))),
            "art_style": str(art_style),
            "logo_position": str(logo_position),
            "logo_scale": logo_scale,
            "loop_cleanup": cleanup_stats.get("loop_cleanup", loop_cleanup),
            "loop_original_frames": int(cleanup_stats.get("loop_original_frames", frame_count)),
            "loop_trimmed_frames": int(cleanup_stats.get("loop_trimmed_frames", 0)),
            "loop_trimmed_ms": int(cleanup_stats.get("loop_trimmed_ms", 0)),
            "frames": frame_count, "peak_load": round(peak_load, 6),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_sha256": source_sha256,
            "dashboard_pack": dashboard_pack.name if dashboard_frames else "",
            "dashboard_pack_frames": len(dashboard_frames),
            "dashboard_pack_sha256": pack_sha256,
            "dashboard_pack_revision": DASHBOARD_PACK_REVISION,
            "dashboard_treatment": treatment,
            "dashboard_compression": dashboard_compression,
            "dashboard_show_clock": bool(dashboard_show_clock),
            "dashboard_clock_choice": clock_choice,
            "dashboard_clock_size": clock_size,
            "dashboard_show_status_rail": dashboard_show_status_rail,
            "dashboard_show_session": bool(dashboard_show_session) and dashboard_show_status_rail,
            "dashboard_show_battery": bool(dashboard_show_battery) and dashboard_show_status_rail,
            "prepared_at": self.clock(),
        }
        _atomic_json(destination / "manifest.json", manifest, 0o644)
        trimmed = manifest["loop_trimmed_frames"]
        detail = "Ready to activate"
        if mode == "animated":
            detail += (
                f" · {trimmed} frames removed "
                f"({manifest['loop_trimmed_ms'] / 1000:.1f} s)"
                if trimmed else " · no terminal frames removed"
            )
        notify(100, "ready", detail)
        return {**manifest, "path": str(compiled), "size": len(data)}

    def prepared(self, appid, mode, draft=False, home=False):
        destination = self._prepared_root(appid, mode, draft=draft, home=home)
        manifest = _read_json(destination / "manifest.json")
        compiled = destination / "faceplate.gif"
        try:
            data = compiled.read_bytes()
        except OSError:
            return None
        if (manifest.get("schema") != 2 or manifest.get("appid") != int(appid)
                or manifest.get("mode") != mode or not manifest.get("ready")
                or prepared_compatibility(manifest) == "retired-overlay"
                or not data or len(data) > MAX_GIF_BYTES
                or hashlib.sha256(data).hexdigest() != manifest.get("sha256")):
            return None
        return data, manifest, compiled

    def prepared_manifest(self, appid, mode):
        prepared = self.prepared(appid, mode)
        return dict(prepared[1]) if prepared is not None else {}

    def prepared_dashboard_manifest(self, appid, mode, manifest=None, draft=False, home=False):
        """Validate one prepared Dashboard pack using JSON and stat only."""
        appid = int(appid)
        mode = str(mode)
        if mode not in {"static", "animated", "pan"}:
            return {}
        root = self._prepared_root(appid, mode, draft=draft, home=home)
        manifest = dict(manifest) if isinstance(manifest, dict) else _read_json(
            root / "manifest.json"
        )
        frame_count = int(manifest.get("dashboard_pack_frames", 0) or 0)
        pack = root / str(manifest.get("dashboard_pack", ""))
        expected = protocol.WIDTH * protocol.HEIGHT * 3 * frame_count
        try:
            valid_size = pack.is_file() and pack.stat().st_size == expected
        except OSError:
            valid_size = False
        if (manifest.get("schema") != 2 or manifest.get("appid") != appid
                or manifest.get("mode") != mode or not manifest.get("ready")
                or prepared_compatibility(manifest) == "retired-overlay"
                or manifest.get("dashboard_pack_revision") != DASHBOARD_PACK_REVISION
                or not 1 <= frame_count <= DASHBOARD_PACK_MAX_FRAMES
                or not valid_size):
            return {}
        return manifest

    def library_entries(self):
        """List prepared artwork without reading GIF payloads into Decky RAM."""
        entries = []
        try:
            roots = tuple(self.artwork_root.iterdir())
        except OSError:
            return entries
        for app_root in roots:
            if not app_root.is_dir() or not app_root.name.isdigit():
                continue
            appid = int(app_root.name)
            active = _read_json(app_root / "active.json")
            active_mode = str(active.get("mode", "")) if (
                active.get("schema") == 1 and active.get("appid") == appid
            ) else ""
            for mode in ("static", "animated", "pan"):
                root = app_root / "prepared" / mode
                manifest = _read_json(root / "manifest.json")
                compiled = root / "faceplate.gif"
                try:
                    size = compiled.stat().st_size
                except OSError:
                    continue
                if (manifest.get("schema") != 2 or manifest.get("appid") != appid
                        or manifest.get("mode") != mode or not manifest.get("ready")
                        or not 0 < size <= MAX_GIF_BYTES):
                    continue
                entries.append({
                    key: manifest.get(key) for key in (
                        "appid", "asset_id", "mode", "thumb", "animated", "sha256",
                        "author", "asset_kind", "source_width", "source_height",
                        "frames", "dashboard_pack_frames", "dashboard_treatment", "logo_scale",
                        "dashboard_compression",
                        "prepared_at",
                    )
                } | {
                    "matrix_compatibility": prepared_compatibility(manifest),
                    "repair_available": bool(manifest.get("source") and (root / Path(str(manifest.get("source"))).name).is_file()),
                    "active": mode == active_mode,
                    "dashboard_ready": bool(self.prepared_dashboard_manifest(
                        appid, mode, manifest,
                    )),
                    "size": size,
                })
        return sorted(
            entries,
            key=lambda item: (float(item.get("prepared_at", 0) or 0),
                              int(item.get("appid", 0) or 0)),
            reverse=True,
        )[:64]

    def reset_user_data(self):
        """Explicit factory reset of this library's own data, never Steam files."""
        if self.root.is_symlink():
            raise SteamGridDBError("Cannot reset a linked artwork library")
        with self._auth_lock:
            self.clear_api_key()  # Retire in-flight key validation generations too.
            for name in ("artwork", "jobs", "preferences.json"):
                path = self.root / name
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
            self._results.clear()

    def delete_prepared(self, appid, mode):
        """Delete one exact library variant and clear its active pointer."""
        appid = int(appid)
        root = self._prepared_root(appid, mode)
        try:
            resolved = root.resolve(strict=False)
            prepared_root = (self.artwork_root / str(appid) / "prepared").resolve()
        except (OSError, ValueError) as error:
            raise SteamGridDBError("Invalid prepared artwork path") from error
        if prepared_root not in resolved.parents:
            raise SteamGridDBError("Invalid prepared artwork path")
        existed = root.is_dir()
        if existed:
            shutil.rmtree(root)
        app_root = self.artwork_root / str(appid)
        active_path = app_root / "active.json"
        active = _read_json(active_path)
        if active.get("schema") == 1 and str(active.get("mode", "")) == str(mode):
            active_path.unlink(missing_ok=True)
        return existed

    @contextmanager
    def applying_prepared(self, appid, mode, draft=False, home=False):
        """Promote a verified candidate only on explicit Apply, retaining the old copy on failure."""
        prepared = self.prepared(appid, mode, draft=draft)
        if prepared is None:
            raise SteamGridDBError("This artwork has not finished preparing")
        source = prepared[2].parent
        target = self._prepared_root(appid, mode, home=home)
        if source == target:
            yield
            return
        temporary = target.with_name(target.name + ".applying")
        previous = target.with_name(target.name + ".previous")
        if temporary.exists() or previous.exists():
            raise SteamGridDBError("An interrupted artwork application needs recovery")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, temporary)
            if target.exists():
                os.replace(target, previous)
            try:
                os.replace(temporary, target)
                yield
            except Exception:
                if target.exists():
                    shutil.rmtree(target)
                if previous.exists():
                    os.replace(previous, target)
                raise
            if previous.exists():
                shutil.rmtree(previous)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def activate_prepared(self, appid, mode, draft=False):
        with self.applying_prepared(appid, mode, draft=draft):
            prepared = self.prepared(appid, mode)
            if prepared is None:
                raise SteamGridDBError("This artwork has not finished preparing")
            destination = self.artwork_root / str(int(appid))
            _atomic_json(destination / "active.json", {
                "schema": 1, "appid": int(appid), "mode": str(mode),
                "activated_at": self.clock(),
            }, 0o644)
        return {**prepared[1], "path": str(prepared[2]), "size": len(prepared[0])}

    def selected(self, appid):
        destination = self.artwork_root / str(int(appid))
        active = _read_json(destination / "active.json")
        if active.get("schema") == 1 and active.get("appid") == int(appid):
            mode = str(active.get("mode", ""))
            if mode in {"static", "animated", "pan"}:
                prepared = self.prepared(appid, mode)
                if prepared is not None:
                    return prepared
        # Lab 10-12 compatibility: an already compiled selection remains valid
        # until the user explicitly activates a prepared replacement.
        manifest = _read_json(destination / "manifest.json")
        compiled = destination / "faceplate.gif"
        try:
            data = compiled.read_bytes()
        except OSError:
            return None
        if (manifest.get("schema") != 1 or manifest.get("appid") != int(appid)
                or prepared_compatibility(manifest) == "retired-overlay"
                or not data or len(data) > MAX_GIF_BYTES
                or hashlib.sha256(data).hexdigest() != manifest.get("sha256")):
            return None
        return data, manifest, compiled

    def selected_manifest(self, appid):
        selected = self.selected(appid)
        return dict(selected[1]) if selected is not None else {}

    def selected_source(self, appid):
        selected = self.selected(appid)
        if selected is None:
            return None
        manifest, root = selected[1], selected[2].parent
        source_name = str(manifest.get("source", ""))
        if not re.fullmatch(r"source\.(png|jpg|gif|webp|webm)", source_name):
            return None
        path = root / source_name
        try:
            resolved = path.resolve(strict=True)
            resolved_root = root.resolve(strict=True)
            if resolved_root not in resolved.parents or not resolved.is_file():
                return None
            return resolved
        except (OSError, ValueError):
            return None

    def selected_dashboard_pack(self, appid):
        """Return the active predecoded background pack, never decoding at launch."""
        reference = self.selected_dashboard_pack_reference(appid)
        if reference is None:
            return None
        manifest, path = reference
        frame_count = int(manifest["dashboard_pack_frames"])
        expected_bytes = protocol.WIDTH * protocol.HEIGHT * 3 * frame_count
        try:
            payload = path.read_bytes()
        except OSError:
            return None
        if (len(payload) != expected_bytes
                or hashlib.sha256(payload).hexdigest()
                != manifest.get("dashboard_pack_sha256")):
            return None
        frame_bytes = protocol.WIDTH * protocol.HEIGHT * 3
        frames = tuple(
            payload[offset:offset + frame_bytes]
            for offset in range(0, len(payload), frame_bytes)
        )
        return frames, dict(manifest), path

    def selected_dashboard_pack_reference(self, appid, mode=None, draft=False, home=False):
        """Return a validated lightweight pack reference for an isolated renderer."""
        if home and not _read_json(self.artwork_root / str(int(appid)) / "home.json"):
            home = False
        manifest = (self.prepared_dashboard_manifest(appid, mode, draft=draft, home=home)
                    if mode is not None else self.selected_dashboard_manifest(appid, home=home))
        if not manifest:
            return None
        root = self._prepared_root(appid, manifest["mode"], draft=draft, home=home)
        filename = str(manifest.get("dashboard_pack", ""))
        frame_count = int(manifest.get("dashboard_pack_frames", 0) or 0)
        if (filename != "artwork-dashboard.rgb" or frame_count <= 0
                or frame_count > DASHBOARD_PACK_MAX_FRAMES
                or manifest.get("dashboard_pack_revision") != DASHBOARD_PACK_REVISION):
            return None
        path = root / filename
        expected_bytes = protocol.WIDTH * protocol.HEIGHT * 3 * frame_count
        try:
            resolved = path.resolve(strict=True)
            resolved_root = root.resolve(strict=True)
            if (resolved_root not in resolved.parents or not resolved.is_file()
                    or resolved.stat().st_size != expected_bytes):
                return None
        except (OSError, ValueError):
            return None
        return dict(manifest), resolved

    def selected_dashboard_manifest(self, appid, home=False):
        """Cheap launch-time readiness check: small JSON/stat reads only."""
        destination = self.artwork_root / str(int(appid))
        active = _read_json(destination / ("home.json" if home else "active.json"))
        if home and not active:
            return self.selected_dashboard_manifest(appid)
        if active.get("schema") != 1 or active.get("appid") != int(appid):
            return {}
        mode = str(active.get("mode", ""))
        return dict(self.prepared_dashboard_manifest(appid, mode, home=home))

    def assign_home(self, appid, mode, draft=False):
        if not self.prepared_dashboard_manifest(appid, mode, draft=draft):
            raise SteamGridDBError("Prepare this artwork for Dashboard first")
        with self.applying_prepared(appid, mode, draft=draft, home=True):
            _atomic_json(self.artwork_root / str(int(appid)) / "home.json", {
                "schema": 1, "appid": int(appid), "mode": str(mode),
                "activated_at": self.clock(),
            }, 0o644)
        return self.prepared_dashboard_manifest(appid, mode, home=True)

    def home_selected(self, appid):
        active = _read_json(self.artwork_root / str(int(appid)) / "home.json")
        if not active:
            return self.selected(appid)
        if active.get("schema") != 1 or active.get("appid") != int(appid):
            return None
        mode = str(active.get("mode", ""))
        return self.prepared(appid, mode, home=True) if mode in {"static", "animated", "pan"} else None

    def home_dashboard_manifest(self, appid):
        return self.selected_dashboard_manifest(appid, home=True)

    def home_dashboard_pack_reference(self, appid):
        return self.selected_dashboard_pack_reference(appid, home=True)
