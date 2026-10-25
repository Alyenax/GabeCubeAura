# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Approved architectural RGB banks; no drawing dependencies on SteamOS.

Each bank contains scene rows 0--44 only. The live Steam count is composed
separately, so a preview's demonstration count can never reach the device.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import zlib

ROOT = Path(__file__).resolve().parents[3] / 'assets/faceplate/player-city/animated'
MANIFEST_SHA256 = 'dc1c979118f9234f80c1878775fa4a1ed065512481ecce11b650439643564943'
FRAME_COUNT = 192
ART_BYTES = 64 * 45 * 3
# Keep the existing native timing contract: 192 frames / 24 s = 8 fps average.
# The manifest's historical speed=2 field identifies this playback cadence.
DELAYS_CS = (12, 13) * 96


@lru_cache(maxsize=1)
def animation_manifest():
    data = (ROOT / 'manifest.json').read_bytes()
    if len(data) > 131072 or hashlib.sha256(data).hexdigest() != MANIFEST_SHA256:
        raise ValueError('Player City animation manifest integrity failure')
    return json.loads(data)


@lru_cache(maxsize=2)
def animated_rgb(code, phase, tier):
    row = next((r for r in animation_manifest()['images']
                if (r['weather'], r['phase'], r['tier']) == (code, phase, tier)), None)
    if row is None:
        raise ValueError('Invalid Player City animation variant')
    packed = (ROOT / row['file']).read_bytes()
    if len(packed) != row['bytes'] or hashlib.sha256(packed).hexdigest() != row['sha256']:
        raise ValueError('Player City animation pack integrity failure')
    expected = FRAME_COUNT * ART_BYTES
    decoder = zlib.decompressobj()
    raw = decoder.decompress(packed, expected + 1)
    if (len(raw) != expected or not decoder.eof or decoder.unused_data
            or hashlib.sha256(raw).hexdigest() != row['rgb_sha256']):
        raise ValueError('Player City animation RGB integrity failure')
    return tuple(raw[p:p + ART_BYTES] for p in range(0, expected, ART_BYTES))


def projection_source(code, phase, tier):
    """Immutable original artwork identity, without the live count rail."""
    row = next((r for r in animation_manifest()['images']
                if (r['weather'], r['phase'], r['tier']) == (code, phase, tier)), None)
    if row is None:
        raise ValueError('Invalid Player City projection source')
    return dict(kind='player-city', weather=code, phase=phase, tier=tier, height=45,
                sha256=row['rgb_sha256'], revision=MANIFEST_SHA256)
