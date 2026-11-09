# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Generate a dim, opaque, synthetic GIF for the manual USB size test."""
from functools import lru_cache
from random import Random

from . import gif, protocol

SIZES_KIB = (1, 4, 32, 56, 64, 80)
EXACT_SIZES_BYTES = (32_768, 32_769)


def _split_first_image_block(data, target):
    # The generated GIF has a global palette, then an 8-byte graphic control
    # extension, a 10-byte image descriptor and the one-byte LZW code size.
    palette_end = 13 + 3 * (1 << ((data[10] & 7) + 1))
    offset = palette_end + 8 + 10 + 1
    extra_blocks = target - len(data)
    block_length = data[offset]
    if (data[palette_end:palette_end + 3] != b"\x21\xf9\x04"
            or data[palette_end + 8] != 0x2C or not 0 <= extra_blocks < block_length):
        raise ValueError("cannot encode the requested exact GIF size")

    # Each extra GIF sub-block adds one length byte. Preserve all LZW bytes
    # and add no metadata, frames or bytes after the GIF trailer.
    block = data[offset + 1:offset + 1 + block_length]
    part_length, remainder = divmod(block_length, extra_blocks + 1)
    split = bytearray()
    start = 0
    for index in range(extra_blocks + 1):
        length = part_length + (index < remainder)
        split.append(length)
        split.extend(block[start:start + length])
        start += length
    return data[:offset] + split + data[offset + 1 + block_length:]


@lru_cache(maxsize=len(SIZES_KIB) + len(EXACT_SIZES_BYTES))
def build(size):
    if type(size) is not int or size not in SIZES_KIB + EXACT_SIZES_BYTES:
        raise ValueError("unsupported GIF test size")
    exact = size in EXACT_SIZES_BYTES
    # Both motifs are invariant under a 180-degree rotation. The exact pair
    # uses a seed that yields 32,762 bytes before splitting one image block.
    rng = Random(16138 if exact else 16103)
    half = bytes(rng.getrandbits(2) for _ in range(protocol.WIDTH * protocol.HEIGHT // 2))
    frame = half + half[::-1]
    palette = tuple((0, index * 5, index * 10) for index in range(4))
    if exact:
        count = 31
        data = gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, (frame,) * count,
                          delay_cs=10, loop=False)
        return _split_first_image_block(data, size), count
    one = gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, (frame,), loop=False)
    if size == 1:
        return one, 1
    two = gif.encode(protocol.WIDTH, protocol.HEIGHT, palette, (frame, frame), loop=False)
    step = len(two) - len(one) - 8  # first GCE appears only in multi-frame GIFs
    count = max(2, round((size * 1024 - len(one) - 8) / step) + 1)
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
