# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Generate a dim, opaque, synthetic GIF for the manual USB size test."""
from functools import lru_cache
from random import Random

from . import gif, protocol

SIZES_KIB = (1, 4, 32, 56, 64, 80)


@lru_cache(maxsize=len(SIZES_KIB))
def build(size_kib):
    if type(size_kib) is not int or size_kib not in SIZES_KIB:
        raise ValueError("unsupported GIF test size")
    # Symmetric under 180-degree rotation, so the payload size is independent
    # of mounting orientation. No comment padding or alternate GIF format.
    rng = Random(16103)
    half = bytes(rng.getrandbits(2) for _ in range(protocol.WIDTH * protocol.HEIGHT // 2))
    frame = half + half[::-1]
    palette = tuple((0, index * 5, index * 10) for index in range(4))
    one = gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, (frame,), loop=False)
    if size_kib == 1:
        return one, 1
    two = gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, (frame, frame), loop=False)
    step = len(two) - len(one) - 8  # first GCE appears only in multi-frame GIFs
    count = max(2, round((size_kib * 1024 - len(one) - 8) / step) + 1)
    return gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, (frame,) * count,
                      delay_cs=10, loop=False), count


def outcome(result):
    """Classify only the receipt belonging to this particular probe."""
    if result.get("test_state"):
        return result["test_state"]
    if result.get("synchronized"):
        return "confirmed" if result.get("wrote") else "already-stored"
    if result.get("deferred"):
        return "flash-protection"
    if result.get("sent_unconfirmed"):
        return "unconfirmed"
    if result.get("superseded"):
        return "cancelled"
    transfer = result.get("transfer", {})
    if transfer.get("failure_stage") == "begin":
        if transfer.get("failure_kind") == "rejected":
            return "begin-refused"
        if transfer.get("failure_kind") == "timeout":
            return "begin-timeout"
    return "failed"
