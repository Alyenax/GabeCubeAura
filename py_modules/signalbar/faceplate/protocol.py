"""JSAUX PIXEL 64x54 serial framing.

Adapted from hodapp/pixel-faceplate 0.1.9 (BSD-3-Clause), copyright
2026 Eli Hodapp. See licenses/Pixel-Faceplate-BSD-3-Clause.txt.
"""

from __future__ import annotations

import zlib
from datetime import datetime

MAGIC = b"DY"
TYPE_CONTROL = 0x01
TYPE_DATA = 0x02
CMD_POWER = 0x01
CMD_BRIGHTNESS = 0x02
CMD_GIF_BEGIN = 0x04
CMD_NATIVE_CLOCK = 0x05
CMD_GIF_END = 0x0B
CMD_GIF_CHUNK = 0x02
CMD_FACTORY_TEST = 0xF0
CHUNK_SIZE = 498
# Conservative common transfer profile, below the observed 200 KiB gap
# between the live GIF and upload buffer. Flash chip capacity is not slot size.
MAX_GIF_BYTES = 192 * 1024
WIDTH = 64
HEIGHT = 54


def crc16_kermit(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def frame(kind: int, command: int, payload: bytes = b"") -> bytes:
    body = MAGIC + bytes((kind & 0xFF, command & 0xFF)) \
        + len(payload).to_bytes(2, "big") + bytes(payload)
    return body + crc16_kermit(body).to_bytes(2, "big")


def power(enabled: bool) -> bytes:
    return frame(TYPE_CONTROL, CMD_POWER, b"\x01" if enabled else b"\x00")


def brightness(percent: int) -> bytes:
    return frame(TYPE_CONTROL, CMD_BRIGHTNESS, bytes((max(0, min(100, int(percent))),)))


def factory_test(mode: int = 0) -> bytes:
    """Select a factory test pattern; mode 0 returns to normal display mode."""
    return frame(TYPE_CONTROL, CMD_FACTORY_TEST, bytes((mode & 0xFF,)))


def native_clock(when: datetime) -> bytes:
    """Set and activate the MCU clock. Local wall fields, no weekday/offset.

    Always send all seven bytes: short payloads use stale firmware memory.
    RAM time storage does not establish the flash effects of mode activation.
    """
    if not isinstance(when, datetime):
        raise TypeError("native clock requires a datetime")
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("native clock requires a timezone-aware datetime")
    # Revalidate calendar fields, including datetime subclasses supplied by callers.
    datetime(when.year, when.month, when.day, when.hour, when.minute, when.second)
    payload = when.year.to_bytes(2, "big", signed=False) + bytes((
        when.month - 1, when.day - 1, when.hour, when.minute, when.second,
    ))
    if len(payload) != 7:
        raise ValueError("native clock payload must contain exactly seven bytes")
    return frame(TYPE_CONTROL, CMD_NATIVE_CLOCK, payload)


def gif_begin(data: bytes) -> bytes:
    payload = len(data).to_bytes(4, "big") \
        + (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "big")
    return frame(TYPE_CONTROL, CMD_GIF_BEGIN, payload)


def gif_chunks(data: bytes, size: int = CHUNK_SIZE):
    for sequence, offset in enumerate(range(0, len(data), size)):
        payload = (sequence & 0xFFFF).to_bytes(2, "big") + data[offset:offset + size]
        yield frame(TYPE_DATA, CMD_GIF_CHUNK, payload)


def gif_end() -> bytes:
    return frame(TYPE_CONTROL, CMD_GIF_END, b"\x01")


class Reply:
    __slots__ = ("kind", "command", "payload")

    def __init__(self, kind: int, command: int, payload: bytes):
        self.kind = kind
        self.command = command
        self.payload = payload

    @property
    def status(self):
        return self.payload[0] if self.payload else None


def parse(buffer: bytearray):
    replies = []
    junk = bytearray()
    while True:
        start = buffer.find(MAGIC)
        if start < 0:
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
        received_crc = int.from_bytes(buffer[6 + length:total], "big")
        if crc16_kermit(body) != received_crc:
            junk += buffer[:2]
            del buffer[:2]
            continue
        replies.append(Reply(body[2], body[3], body[6:]))
        del buffer[:total]
