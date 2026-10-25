# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Offline RGB profile utilities, never electrical or optical measurements.

Lab185 does not call these utilities from the encoder, renderer or delivery
worker. Normal brightness is manual. POWER_BUDGET is retained for the separate
prepared-content admission contract of delegated clients.
"""
from collections import Counter, OrderedDict
import hashlib
import math
import threading

REVISION = "encoded-rgb-peak-1"
POWER_BUDGET = .50
_cache = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 256


def indexed_peak(palette, frames):
    weights = tuple(sum(rgb) for rgb in palette)
    return max(sum(weights[index] * count for index, count in Counter(frame).items())
               / (len(frame) * 765) for frame in frames)


def _put(value):
    with _lock:
        _cache[value["sha256"]] = dict(value)
        _cache.move_to_end(value["sha256"])
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)
    return dict(value)


def record_encoded(data, palette, frames):
    """Called by the trusted encoder after quantisation, without LZW decode."""
    return _put({"revision": REVISION, "sha256": hashlib.sha256(data).hexdigest(),
                 "peak_load": indexed_peak(palette, frames), "frames": len(frames)})


def valid_profile(data, value):
    return bool(isinstance(value, dict) and value.get("revision") == REVISION
                and value.get("sha256") == hashlib.sha256(data).hexdigest()
                and type(value.get("frames")) is int and 1 <= value["frames"] <= 4096
                and type(value.get("peak_load")) in (int, float)
                and math.isfinite(value["peak_load"]) and 0 <= value["peak_load"] <= 1)


def profile(data, prepared=None):
    """Use a trusted local prepared profile only for its exact GIF bytes."""
    digest = hashlib.sha256(data).hexdigest()
    with _lock:
        cached = _cache.get(digest)
        if cached is not None:
            _cache.move_to_end(digest)
            return dict(cached)
    if valid_profile(data, prepared):
        return _put({key: prepared[key] for key in ("revision", "sha256", "peak_load", "frames")})
    return _put(_decode_profile(bytes(data), digest))


def _decode_profile(data, digest):
    # Shared bounded decoder; one displayed native frame at a time.
    from .gif_transform import _subblocks, _decode_lzw, GifTransformError
    if (not 13 <= len(data) <= 2 * 1024 * 1024 or data[:6] not in (b"GIF87a", b"GIF89a")
            or data[6:10] != b"\x40\x00\x36\x00" or not data[10] & 0x80):
        raise GifTransformError("power estimate requires a native GIF")
    count = 1 << ((data[10] & 7) + 1)
    end = 13 + count * 3
    if end > len(data):
        raise GifTransformError("truncated power palette")
    palette = tuple(tuple(data[i:i+3]) for i in range(13, end, 3))
    offset, frames, peak = end, 0, 0.
    previous = None
    transparent = None
    while offset < len(data):
        block = data[offset]
        if block == 0x3b:
            if offset != len(data)-1 or not frames:
                raise GifTransformError("invalid power GIF trailer")
            return {"revision": REVISION, "sha256": digest, "frames": frames, "peak_load": peak}
        if block == 0x21:
            if offset + 3 >= len(data):
                raise GifTransformError("truncated power extension")
            if data[offset+1] == 0xf9:
                if (offset+7 >= len(data) or data[offset+2] != 4 or data[offset+7] != 0):
                    raise GifTransformError("invalid GIF graphics control block")
                control = data[offset+3]
                if ((control >> 2) & 7) not in (0, 1):
                    raise GifTransformError("unsupported GIF disposal method")
                transparent = data[offset+6] if control & 1 else None
                if transparent is not None and transparent >= count:
                    raise GifTransformError("GIF transparency index out of range")
            _, offset = _subblocks(data, offset+2)
            continue
        if (block != 0x2c or offset+11 > len(data)
                or data[offset+1:offset+10] != b"\x00\x00\x00\x00\x40\x00\x36\x00\x00"):
            raise GifTransformError("power estimate requires full native frames")
        minimum = data[offset+10]
        packed, offset = _subblocks(data, offset+11)
        indices = _decode_lzw(packed, minimum, 3456)
        if transparent is not None:
            if previous is None and transparent in indices:
                raise GifTransformError("first GIF frame must draw every pixel")
            if previous is not None:
                indices = bytes(old if value == transparent else value
                                for value, old in zip(indices, previous))
        previous = indices
        transparent = None
        try:
            peak = max(peak, indexed_peak(palette, (indices,)))
        except IndexError as error:
            raise GifTransformError("GIF power palette index out of range") from error
        frames += 1
        if frames > 4096:
            raise GifTransformError("too many power frames")
    raise GifTransformError("missing power GIF trailer")
