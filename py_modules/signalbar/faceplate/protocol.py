"""Frame layout, both directions:

    'D' 'Y' | type | cmd | len (u16 BE) | payload | CRC16/KERMIT (u16 BE)

The CRC covers everything before it, magic included. Type 0x01 is a control
command; type 0x02 carries GIF data chunks. The panel answers every frame
with a frame of the same type and cmd whose first payload byte is a status.
"""

from __future__ import annotations

import zlib

MAGIC = b"DY"

TYPE_CONTROL = 0x01
TYPE_DATA = 0x02

CMD_POWER = 0x01
CMD_BRIGHTNESS = 0x02
CMD_GIF_BEGIN = 0x04
CMD_GIF_END = 0x0B
CMD_BUILTIN = 0x21
CMD_FACTORY_TEST = 0xF0
CMD_GIF_CHUNK = 0x02  # with TYPE_DATA

# The stock daemon sends 498-byte chunks (500 with the sequence number).
CHUNK_SIZE = 498

WIDTH = 64
HEIGHT = 54


def crc16_kermit(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def frame(kind, cmd, payload=b""):
    body = MAGIC + bytes([kind & 0xFF, cmd & 0xFF]) + len(payload).to_bytes(2, "big") + bytes(payload)
    return body + crc16_kermit(body).to_bytes(2, "big")


def power(on):
    return frame(TYPE_CONTROL, CMD_POWER, b"\x01" if on else b"\x00")


def brightness(percent):
    return frame(TYPE_CONTROL, CMD_BRIGHTNESS, bytes([max(0, min(100, int(percent)))]))


def builtin(mode):
    return frame(TYPE_CONTROL, CMD_BUILTIN, bytes([mode & 0xFF]))


def gif_begin(gif):
    payload = len(gif).to_bytes(4, "big") + (zlib.crc32(gif) & 0xFFFFFFFF).to_bytes(4, "big")
    return frame(TYPE_CONTROL, CMD_GIF_BEGIN, payload)


def gif_chunks(gif, size=CHUNK_SIZE):
    for seq, offset in enumerate(range(0, len(gif), size)):
        yield frame(TYPE_DATA, CMD_GIF_CHUNK, (seq & 0xFFFF).to_bytes(2, "big") + gif[offset:offset + size])


def gif_end():
    return frame(TYPE_CONTROL, CMD_GIF_END, b"\x01")


class Reply:
    __slots__ = ("kind", "cmd", "payload")

    def __init__(self, kind, cmd, payload):
        self.kind, self.cmd, self.payload = kind, cmd, payload

    @property
    def status(self):
        return self.payload[0] if self.payload else None

    def __repr__(self):
        return "Reply(type=0x%02X cmd=0x%02X payload=%s)" % (self.kind, self.cmd, self.payload.hex(" "))


def parse(buffer):
    """Pull complete, CRC-valid frames out of a bytearray (consumed in place).

    Returns (replies, junk) where junk is any bytes skipped while resyncing.
    """
    replies, junk = [], bytearray()
    while True:
        start = buffer.find(MAGIC)
        if start < 0:
            # Keep a trailing 'D' in case the 'Y' is still on the wire.
            keep = 1 if buffer[-1:] == b"D" else 0
            junk += buffer[:len(buffer) - keep]
            del buffer[:len(buffer) - keep]
            return replies, bytes(junk)
        junk += buffer[:start]
        del buffer[:start]
        if len(buffer) < 6:
            return replies, bytes(junk)
        length = int.from_bytes(buffer[4:6], "big")
        total = 6 + length + 2
        if len(buffer) < total:
            return replies, bytes(junk)
        body = bytes(buffer[:6 + length])
        crc = int.from_bytes(buffer[6 + length:total], "big")
        if crc16_kermit(body) != crc:
            junk += buffer[:2]
            del buffer[:2]
            continue
        replies.append(Reply(body[2], body[3], body[6:]))
        del buffer[:total]
