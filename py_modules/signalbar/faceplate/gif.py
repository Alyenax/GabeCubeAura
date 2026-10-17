"""Small stdlib-only GIF89a encoder; the faceplate only accepts GIFs."""

from __future__ import annotations

def _lzw(indices, min_code_size):
    clear = 1 << min_code_size
    end = clear + 1
    out = bytearray()
    acc = 0
    nbits = 0
    size = min_code_size + 1

    def emit(code):
        nonlocal acc, nbits
        acc |= code << nbits
        nbits += size
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8

    table = {}
    next_code = end + 1
    emit(clear)
    prefix = None
    for value in indices:
        if prefix is None:
            prefix = value
            continue
        key = (prefix << 8) | value
        code = table.get(key)
        if code is not None:
            prefix = code
            continue
        emit(prefix)
        if next_code < 4096:
            table[key] = next_code
            next_code += 1
            # The decoder widens one code late, so widen once the table
            # has filled the current width.
            if next_code > (1 << size) and size < 12:
                size += 1
        else:
            emit(clear)
            table.clear()
            next_code = end + 1
            size = min_code_size + 1
        prefix = value
    if prefix is not None:
        emit(prefix)
    emit(end)
    if nbits:
        out.append(acc & 0xFF)
    return bytes(out)


def _sub_blocks(data):
    out = bytearray()
    for offset in range(0, len(data), 255):
        chunk = data[offset:offset + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def encode(width, height, palette, frames, delay_cs=10, loop=True):
    """palette: list of (r, g, b), up to 256. frames: iterables of palette indices."""
    bits = 1
    while (1 << bits) < max(2, len(palette)):
        bits += 1
    table = bytearray()
    for r, g, b in palette:
        table += bytes((r, g, b))
    table += bytes(3 * ((1 << bits) - len(palette)))

    out = bytearray(b"GIF89a")
    out += width.to_bytes(2, "little") + height.to_bytes(2, "little")
    out += bytes((0x80 | (bits - 1), 0, 0))
    out += table
    frames = list(frames)
    if loop and len(frames) > 1:
        out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"
    min_code = max(2, bits)
    for indices in frames:
        if len(frames) > 1:
            # Graphic control: dispose "do not dispose", no transparency.
            out += b"\x21\xF9\x04\x04" + int(delay_cs).to_bytes(2, "little") + b"\x00\x00"
        out += b"\x2C" + bytes(4) + width.to_bytes(2, "little") + height.to_bytes(2, "little") + b"\x00"
        out.append(min_code)
        out += _sub_blocks(_lzw(bytes(indices), min_code))
    out.append(0x3B)
    return bytes(out)


# A fixed 3-3-2 palette (256 colours) for test patterns and the tools.
# Real pictures get their own palette from quantize().
PALETTE_332 = [
    ((i >> 5) * 255 // 7, ((i >> 2) & 7) * 255 // 7, (i & 3) * 255 // 3) for i in range(256)
]


def quantize(rgb, colours=256):
    """Per-picture palette: exact when the frame has few colours, median cut otherwise.

    The panel shows smooth 64-step ramps (seen), so a fixed cube would add
    banding the hardware doesn't have. Returns (palette, indices).
    """
    rgb = bytes(rgb)
    pixels = [rgb[i:i + 3] for i in range(0, len(rgb), 3)]
    unique = list(dict.fromkeys(pixels))
    if len(unique) <= colours:
        lookup = {c: i for i, c in enumerate(unique)}
        return [tuple(c) for c in unique], bytes(lookup[p] for p in pixels)

    boxes = [unique]
    while len(boxes) < colours:
        # Split the box with the widest channel range at its median.
        best, best_range, best_axis = None, -1, 0
        for index, box in enumerate(boxes):
            if len(box) < 2:
                continue
            for axis in range(3):
                values = [c[axis] for c in box]
                spread = max(values) - min(values)
                if spread > best_range:
                    best, best_range, best_axis = index, spread, axis
        if best is None or best_range == 0:
            break
        box = sorted(boxes.pop(best), key=lambda c: c[best_axis])
        middle = len(box) // 2
        boxes += [box[:middle], box[middle:]]

    palette = []
    lookup = {}
    for index, box in enumerate(boxes):
        n = len(box)
        palette.append(tuple(sum(c[k] for c in box) // n for k in range(3)))
        for c in box:
            lookup[c] = index
    return palette, bytes(lookup[p] for p in pixels)
