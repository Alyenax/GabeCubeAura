"""Small stdlib-only GIF89a encoder for the JSAUX 64 x 54 panel.

Adapted from hodapp/pixel-faceplate (BSD-3-Clause), copyright 2026
Eli Hodapp. See licenses/Pixel-Faceplate-BSD-3-Clause.txt.
"""


def _lzw(indices, min_code_size):
    clear = 1 << min_code_size
    end = clear + 1
    out = bytearray()
    accumulator = 0
    bit_count = 0
    code_size = min_code_size + 1

    def emit(code):
        nonlocal accumulator, bit_count
        accumulator |= code << bit_count
        bit_count += code_size
        while bit_count >= 8:
            out.append(accumulator & 0xFF)
            accumulator >>= 8
            bit_count -= 8

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
            if next_code > (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            emit(clear)
            table.clear()
            next_code = end + 1
            code_size = min_code_size + 1
        prefix = value
    if prefix is not None:
        emit(prefix)
    emit(end)
    if bit_count:
        out.append(accumulator & 0xFF)
    return bytes(out)


def _sub_blocks(data):
    out = bytearray()
    for offset in range(0, len(data), 255):
        chunk = data[offset:offset + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def encode(width, height, palette, frames, delay_cs=10, loop=True, transparent_index=None):
    """Encode full indexed frames with a global palette and keep-frame disposal.

    A transparent index can reuse unchanged pixels from the preceding frame.
    A per-frame list can borrow indices absent from each frame's changed pixels.
    Callers must draw the complete first frame, including on each loop.
    """
    frames = list(frames)
    transparency = list(transparent_index) if isinstance(transparent_index, (list, tuple)) else [transparent_index]*len(frames)
    if len(transparency) != len(frames):
        raise ValueError('GIF transparency indices must match frame count')
    if not 1 <= len(palette) <= 256 or any(index is not None and not 0 <= index < len(palette) for index in transparency):
        raise ValueError("GIF transparency requires a valid global palette index")
    bits = 1
    while (1 << bits) < max(2, len(palette)):
        bits += 1
    table = bytearray()
    for red, green, blue in palette:
        table += bytes((red, green, blue))
    table += bytes(3 * ((1 << bits) - len(palette)))

    out = bytearray(b"GIF89a")
    out += width.to_bytes(2, "little") + height.to_bytes(2, "little")
    out += bytes((0x80 | (bits - 1), 0, 0))
    out += table
    if isinstance(delay_cs, (list, tuple)):
        delays = [int(value) for value in delay_cs]
        if len(delays) != len(frames):
            raise ValueError("GIF frame delays must match frame count")
    else:
        delays = [int(delay_cs)] * len(frames)
    if loop and len(frames) > 1:
        out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"
    minimum_code_size = max(2, bits)
    for frame_index, indices in enumerate(frames):
        transparent = transparency[frame_index]
        if len(frames) > 1 or transparent is not None:
            flags = 4 if transparent is None else 5
            out += (b"\x21\xF9\x04" + bytes((flags,))
                    + delays[frame_index].to_bytes(2, "little")
                    + bytes((transparent or 0, 0)))
        out += (
            b"\x2C" + bytes(4) + width.to_bytes(2, "little")
            + height.to_bytes(2, "little") + b"\x00"
        )
        out.append(minimum_code_size)
        out += _sub_blocks(_lzw(bytes(indices), minimum_code_size))
    out.append(0x3B)
    data = bytes(out)
    return data


def quantize(rgb, colours=256):
    """Return a per-picture median-cut palette and indexed pixels."""
    rgb = bytes(rgb)
    pixels = [rgb[index:index + 3] for index in range(0, len(rgb), 3)]
    unique = list(dict.fromkeys(pixels))
    if len(unique) <= colours:
        lookup = {colour: index for index, colour in enumerate(unique)}
        return [tuple(colour) for colour in unique], bytes(lookup[pixel] for pixel in pixels)

    boxes = [unique]
    while len(boxes) < colours:
        best = None
        best_range = -1
        best_axis = 0
        for index, box in enumerate(boxes):
            if len(box) < 2:
                continue
            for axis in range(3):
                values = [colour[axis] for colour in box]
                spread = max(values) - min(values)
                if spread > best_range:
                    best, best_range, best_axis = index, spread, axis
        if best is None or best_range == 0:
            break
        box = sorted(boxes.pop(best), key=lambda colour: colour[best_axis])
        middle = len(box) // 2
        boxes += [box[:middle], box[middle:]]

    palette = []
    lookup = {}
    for index, box in enumerate(boxes):
        palette.append(tuple(sum(colour[channel] for colour in box) // len(box) for channel in range(3)))
        for colour in box:
            lookup[colour] = index
    return palette, bytes(lookup[pixel] for pixel in pixels)
