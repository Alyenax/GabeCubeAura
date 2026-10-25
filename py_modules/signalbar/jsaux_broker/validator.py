# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Strict bounded parser for the one GIF profile accepted by the broker.

Runs in a disposable resource-limited child. It imports no network clients and
never interprets extensions, images or metadata as executable instructions.
Only one decoded frame and a bounded 4096-entry LZW dictionary are retained.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

if __package__:
    from .limits import LIMITS
else:
    # -I deliberately removes the script directory from sys.path; add only this
    # bundled trusted module directory, never the caller's cwd/PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from limits import LIMITS


class InvalidGIF(ValueError):
    def __init__(self, code="CONTENT_INVALID"):
        super().__init__(code)
        self.code = code


def _lzw(data, pixels=None):
    """Decode and validate one 3456-pixel frame, without an image library."""
    offset = 0
    size = 9
    table = [bytes((i,)) for i in range(256)] + [None, None]
    previous = None
    count = 0
    brightness = 0
    load = tuple(sum((round(r * 255 / 7), round(g * 255 / 7), round(b * 255 / 3)))
                 for r in range(8) for g in range(8) for b in range(4))
    cleared = False
    while offset + size <= len(data) * 8:
        code = (int.from_bytes(data[offset // 8:offset // 8 + 3], "little") >> (offset % 8)) & ((1 << size) - 1)
        offset += size
        if code == 256:
            table = [bytes((i,)) for i in range(256)] + [None, None]
            size, previous, cleared = 9, None, True
            continue
        if not cleared:
            raise InvalidGIF()
        if code == 257:
            if count != 3456 or any(data[offset // 8 + bool(offset % 8):]):
                raise InvalidGIF()
            if offset % 8 and (data[offset // 8] >> (offset % 8)):
                raise InvalidGIF()
            return brightness / (3456 * 765)
        if code < len(table) and table[code] is not None:
            value = table[code]
        elif code == len(table) and previous is not None:
            value = previous + previous[:1]
        else:
            raise InvalidGIF()
        count += len(value)
        if pixels is not None:pixels.extend(value)
        brightness += sum(load[index] for index in value)
        if count > 3456:
            raise InvalidGIF()
        if previous is not None and len(table) < 4096:
            table.append(previous + value[:1])
            if len(table) == 1 << size and size < 12:
                size += 1
        previous = value
    raise InvalidGIF()


def validate_bytes(data, on_frame=None):
    if len(data) > LIMITS["max_content_bytes"]:
        raise InvalidGIF("CONTENT_TOO_LARGE")
    if data[:6] != b"GIF89a":
        raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
    if len(data) < 782:
        raise InvalidGIF()
    if data[6:13] != b"\x40\x00\x36\x00\x87\x00\x00":
        raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
    palette = bytes(c for r in range(8) for g in range(8) for b in range(4)
                    for c in (round(r * 255 / 7), round(g * 255 / 7), round(b * 255 / 3)))
    if data[13:781] != palette:
        raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
    pos, frames, duration = 781, 0, 0
    loop, gce, peak_load = False, None, 0.
    while pos < len(data):
        kind = data[pos]
        if kind == 0x3b:
            if pos != len(data) - 1 or not frames or gce is not None:
                raise InvalidGIF()
            if frames == 1 and (loop or duration):
                raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
            if frames > 1 and (not loop or not duration):
                raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
            return dict(frames=frames, duration_cs=duration, width=64, height=54,
                        static=frames == 1, timed_loop=frames > 1, peak_load=peak_load)
        if kind == 0x21:
            if data[pos:pos + 19] == b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00":
                if frames or loop or gce is not None:
                    raise InvalidGIF()
                loop = True
                pos += 19
                continue
            if data[pos:pos + 4] == b"\x21\xf9\x04\x04" and pos + 8 <= len(data):
                if gce is not None or data[pos + 6:pos + 8] != b"\x00\x00":
                    raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
                gce = int.from_bytes(data[pos + 4:pos + 6], "little")
                if not 1 <= gce <= 65535:
                    raise InvalidGIF()
                pos += 8
                continue
            raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
        if kind != 0x2c or pos + 11 > len(data):
            raise InvalidGIF()
        if data[pos + 1:pos + 10] != b"\x00\x00\x00\x00\x40\x00\x36\x00\x00" or data[pos + 10] != 8:
            raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
        if loop != (gce is not None):
            raise InvalidGIF("CONTENT_PROFILE_UNSUPPORTED")
        pos += 11
        compressed = bytearray()
        while True:
            if pos >= len(data):
                raise InvalidGIF()
            length = data[pos]
            pos += 1
            if not length:
                break
            if pos + length > len(data):
                raise InvalidGIF()
            compressed.extend(data[pos:pos + length])
            pos += length
        pixels=bytearray() if on_frame is not None else None
        peak_load = max(peak_load, _lzw(compressed,pixels))
        if on_frame is not None:on_frame(pixels,gce or 0)
        frames += 1
        duration += gce or 0
        gce = None
        if frames > LIMITS["max_frames"] or duration > LIMITS["max_loop_duration_cs"]:
            raise InvalidGIF("VALIDATION_LIMIT")
    raise InvalidGIF()


def validate_file(path, digest):
    """Child entry: bounded file, digest, canonical parse. No hardware access."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        data = source.read(LIMITS["max_content_bytes"] + 1)
    if hashlib.sha256(data).hexdigest() != digest:
        raise InvalidGIF("HASH_MISMATCH")
    return validate_bytes(data)


def validate_isolated(path, digest):
    """Subprocess has fixed argv, no stdin, no inherited descriptors or secrets."""
    try:
        # Decky's embedded interpreter can report the plugin-loader ELF itself
        # as sys.executable; executing it would recursively start another loader.
        candidates = ["/usr/bin/python3", "/usr/local/bin/python3"]
        if Path(sys.executable).name.startswith("python"):
            candidates.insert(0, sys.executable)
        interpreter = next((value for value in candidates if Path(value).is_file() and os.access(value, os.X_OK)), None)
        if interpreter is None:
            return dict(error="VALIDATION_LIMIT")
        result = subprocess.run([interpreter, "-I", str(Path(__file__).resolve()), str(path), digest],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True,
                                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                timeout=LIMITS["validator_wall_ms"] / 1000)
        if result.returncode or len(result.stdout) > 2048:
            return dict(error="VALIDATION_LIMIT")
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else dict(error="CONTENT_INVALID")
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return dict(error="VALIDATION_LIMIT")


if __name__ == "__main__":
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    # Linux target: hard address-space cap. Darwin's Python/managed test host
    # rejects lowering these limits; it is NOT evidence of the Linux memory cap.
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (LIMITS["validator_memory_bytes"],) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    try:
        print(json.dumps(validate_file(sys.argv[1], sys.argv[2]), separators=(",", ":")))
    except InvalidGIF as error:
        print(json.dumps(dict(error=error.code)))
    except Exception:
        print('{"error":"CONTENT_INVALID"}')
