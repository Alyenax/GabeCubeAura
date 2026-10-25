# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Safe, bounded GIF89a 180-degree rotation without PIL or source media decode.

Accepts only native full-frame GIFs with a single global palette, as emitted by
GabeCubeAura's own GIF encoder. No flash transfer, network, or external process.
Preserves animation frame count, order and per-frame delays.
"""
from __future__ import annotations

from . import gif, protocol

MAX_BYTES = 2 * 1024 * 1024
MAX_FRAMES = 192


class GifTransformError(ValueError):
    pass


def repack_for_restore(data):
    """Change only GIF image subblock boundaries, not a single LZW bit.

    One deterministic recovery representation for an uncertain delegated
    handoff. No nonce, extra frame, palette change, timing change or decode.
    Strictly bounded parsing rejects truncated/non-native source structures.
    This is NOT a firmware slot selector: a fresh BEGIN/body/END is required.
    """
    data = bytes(data)
    if not 13 <= len(data) <= MAX_BYTES or data[:6] not in (b'GIF87a', b'GIF89a'):
        raise GifTransformError('not a bounded native GIF')
    if data[6:10] != b'\x40\x00\x36\x00' or not data[10] & 0x80:
        raise GifTransformError('unexpected Faceplate GIF dimensions/palette')
    offset = 13 + 3 * (1 << ((data[10] & 7) + 1))
    if offset > len(data):
        raise GifTransformError('truncated GIF palette')
    replacement = None
    frames = 0
    while offset < len(data):
        block = data[offset]
        if block == 0x3B:
            if offset != len(data) - 1 or not frames or replacement is None:
                raise GifTransformError('invalid GIF trailer')
            start, end, packed = replacement
            # 127 or 126 bytes, choosing a representation different from the
            # source. Short streams are split in two instead of padded.
            for size in (min(127, max(1, len(packed)//2)),
                         min(126, max(1, len(packed)//3)), 1):
                out = bytearray()
                for pos in range(0, len(packed), size):
                    chunk = packed[pos:pos + size]
                    out.append(len(chunk))
                    out.extend(chunk)
                out.append(0)
                if out != data[start:end]:
                    result = data[:start] + out + data[end:]
                    if len(result) > MAX_BYTES:
                        raise GifTransformError('repacked GIF exceeds the limit')
                    return bytes(result)
            raise GifTransformError('no distinct recovery representation')
        if block == 0x21:
            if offset + 2 >= len(data):
                raise GifTransformError('truncated GIF extension')
            _, offset = _subblocks(data, offset + 2)
            continue
        if block != 0x2C or offset + 11 > len(data):
            raise GifTransformError('unsupported GIF frame data')
        if data[offset + 1:offset + 10] != b'\x00\x00\x00\x00\x40\x00\x36\x00\x00':
            raise GifTransformError('unsupported partial/interlaced/local-palette GIF')
        if not 2 <= data[offset + 10] <= 8:
            raise GifTransformError('unsupported GIF LZW code size')
        start = offset + 11
        packed, offset = _subblocks(data, start)
        if not packed:
            raise GifTransformError('empty GIF image data')
        if replacement is None:
            replacement = (start, offset, packed)
        frames += 1
        if frames > 4096:
            raise GifTransformError('too many GIF frames')
    raise GifTransformError('missing GIF trailer')


def _subblocks(source, offset):
    chunks = bytearray()
    while offset < len(source):
        size = source[offset]
        offset += 1
        if not size:
            return bytes(chunks), offset
        if offset + size > len(source):
            raise GifTransformError("truncated GIF subblock")
        chunks += source[offset:offset + size]
        offset += size
        if len(chunks) > MAX_BYTES:
            raise GifTransformError("GIF image data exceeds the limit")
    raise GifTransformError("unterminated GIF subblocks")


def _decode_lzw(packed, minimum, expected):
    if not 2 <= minimum <= 8:
        raise GifTransformError("unsupported GIF LZW code size")
    clear = 1 << minimum
    end = clear + 1
    table = [bytes((i,)) for i in range(clear)] + [b"", b""]
    width = minimum + 1
    last = None
    position = 0
    buffer = 0
    bits = 0
    output = bytearray()
    while True:
        while bits < width:
            if position >= len(packed):
                # Legacy native encoder: a final dictionary-width increase
                # can leave END encoded at the previous width. Accept only
                # the explicit terminal token after exactly one full frame,
                # with no remaining bytes or nonzero padding (Pillow agrees).
                if (len(output) == expected and width > minimum + 1
                        and len(table) == 1 << (width - 1)
                        and minimum + 1 <= bits == width - 1 and buffer == end):
                    return bytes(output)
                raise GifTransformError("truncated GIF LZW stream")
            buffer |= packed[position] << bits
            position += 1
            bits += 8
        code = buffer & ((1 << width) - 1)
        buffer >>= width
        bits -= width
        if code == clear:
            table = [bytes((i,)) for i in range(clear)] + [b"", b""]
            width = minimum + 1
            last = None
            continue
        if code == end:
            break
        if code < len(table) and table[code]:
            entry = table[code]
        elif code == len(table) and last:
            entry = last + last[:1]
        else:
            raise GifTransformError("invalid GIF LZW reference")
        output.extend(entry)
        if len(output) > expected:
            raise GifTransformError("GIF frame expands beyond 64 x 54")
        if last is not None and len(table) < 4096:
            table.append(last + entry[:1])
            if len(table) == (1 << width) and width < 12:
                width += 1
        last = entry
    if len(output) != expected:
        raise GifTransformError("GIF frame has unexpected pixel count")
    return bytes(output)


def rotate_gif(data):
    """Rotate every RGB-indexed frame, including all animated GIF frames."""
    data = bytes(data)
    if not 13 <= len(data) <= MAX_BYTES or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise GifTransformError("not a bounded GIF file")
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    if (width, height) != (protocol.WIDTH, protocol.HEIGHT):
        raise GifTransformError("unexpected Faceplate GIF dimensions")
    packed = data[10]
    if not packed & 0x80:
        raise GifTransformError("GIF requires a global colour table")
    colours = 1 << ((packed & 7) + 1)
    offset = 13
    length = 3 * colours
    if offset + length > len(data):
        raise GifTransformError("truncated GIF palette")
    palette = tuple(
        tuple(data[p:p + 3]) for p in range(offset, offset + length, 3)
    )
    offset += length
    frames = []
    delays = []
    next_delay = 10
    next_transparent = None
    transparency = []
    loop = False
    while offset < len(data):
        block = data[offset]
        if block == 0x3B:
            break
        if block == 0x21:
            if offset + 2 >= len(data):
                raise GifTransformError("truncated GIF extension")
            label = data[offset + 1]
            head_length = data[offset + 2]
            first = offset + 3
            last = first + head_length
            if last > len(data):
                raise GifTransformError("truncated GIF extension body")
            if label == 0xF9:
                if head_length != 4 or last >= len(data) or data[last] != 0:
                    raise GifTransformError("invalid GIF graphics control block")
                control = data[first]
                if ((control >> 2) & 7) not in (0, 1):
                    raise GifTransformError("unsupported GIF disposal method")
                next_transparent = data[first + 3] if control & 1 else None
                if next_transparent is not None and next_transparent >= colours:
                    raise GifTransformError("GIF transparency index out of range")
                next_delay = int.from_bytes(data[first + 1:first + 3], "little")
                offset = last + 1
                continue
            if label == 0xFF and data[first:last] == b"NETSCAPE2.0":
                loop = True
            _, offset = _subblocks(data, last)
            continue
        if block != 0x2C or offset + 10 > len(data):
            raise GifTransformError("unsupported GIF frame data")
        left = int.from_bytes(data[offset + 1:offset + 3], "little")
        top = int.from_bytes(data[offset + 3:offset + 5], "little")
        fw = int.from_bytes(data[offset + 5:offset + 7], "little")
        fh = int.from_bytes(data[offset + 7:offset + 9], "little")
        flags = data[offset + 9]
        if (left, top, fw, fh) != (0, 0, width, height) or flags & 0xC0:
            raise GifTransformError("unsupported partial/interlaced/local-palette GIF")
        offset += 10
        if offset >= len(data):
            raise GifTransformError("truncated GIF frame")
        minimum = data[offset]
        compressed, offset = _subblocks(data, offset + 1)
        indices = _decode_lzw(compressed, minimum, width * height)
        if any(index >= colours for index in indices):
            raise GifTransformError("GIF palette index out of range")
        if not frames and next_transparent is not None and next_transparent in indices:
            raise GifTransformError("first GIF frame must draw every pixel")
        frames.append(indices[::-1])
        delays.append(next_delay)
        transparency.append(next_transparent)
        next_delay = 10
        next_transparent = None
        if len(frames) > MAX_FRAMES:
            raise GifTransformError("too many GIF frames")
    if not frames or offset >= len(data) or data[offset] != 0x3B:
        raise GifTransformError("missing GIF trailer")
    return gif.encode(width, height, palette, frames, delay_cs=delays, loop=loop,
                      transparent_index=transparency[0] if len(set(transparency)) == 1 else transparency)
