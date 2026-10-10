"""MQTT 3.1.1 packet encoding and decoding, limited to what GabeCubeAura uses (QoS 0)."""

from __future__ import annotations

import struct

CONNECT, CONNACK, PUBLISH, PUBACK, SUBSCRIBE, SUBACK = 1, 2, 3, 4, 8, 9
PINGREQ, PINGRESP, DISCONNECT = 12, 13, 14
CONNACK_ERRORS = {
    1: "broker refused the protocol version",
    2: "broker rejected the client id",
    3: "broker unavailable",
    4: "bad username or password",
    5: "not authorised",
}
PINGREQ_PACKET = bytes([PINGREQ << 4, 0])
DISCONNECT_PACKET = bytes([DISCONNECT << 4, 0])
MAX_LENGTH = 268_435_455


class PacketError(ValueError):
    pass


def _bytes(value) -> bytes:
    return value.encode("utf-8") if isinstance(value, str) else bytes(value)


def _string(value) -> bytes:
    data = _bytes(value)
    if len(data) > 0xFFFF:
        raise PacketError("string too long for MQTT")
    return struct.pack(">H", len(data)) + data


def encode_length(length: int) -> bytes:
    if length < 0 or length > MAX_LENGTH:
        raise PacketError("packet too large")
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length:
            byte |= 0x80
        out.append(byte)
        if not length:
            return bytes(out)


def _packet(first: int, body: bytes) -> bytes:
    return bytes([first]) + encode_length(len(body)) + body


def connect(client_id, keepalive, username="", password="", will=None, clean=True) -> bytes:
    flags = 0x02 if clean else 0
    payload = _string(client_id)
    if will:
        topic, message, retain = will
        flags |= 0x04 | (0x20 if retain else 0)
        payload += _string(topic) + _string(message)
    if username:
        flags |= 0x80
        payload += _string(username)
        if password:
            flags |= 0x40
            payload += _string(password)
    body = _string("MQTT") + bytes([4, flags]) + struct.pack(">H", int(keepalive)) + payload
    return _packet(CONNECT << 4, body)


def publish(topic, payload, retain=False) -> bytes:
    return _packet((PUBLISH << 4) | (1 if retain else 0), _string(topic) + _bytes(payload))


def subscribe(packet_id: int, topics) -> bytes:
    body = struct.pack(">H", packet_id) + b"".join(_string(topic) + b"\x00" for topic in topics)
    return _packet((SUBSCRIBE << 4) | 0x02, body)


def puback(packet_id: int) -> bytes:
    return _packet(PUBACK << 4, struct.pack(">H", packet_id))


class Reader:
    """Collects received bytes and returns every complete packet as (type, flags, body)."""

    def __init__(self, limit: int = 4 * 1024 * 1024):
        self.buffer = bytearray()
        self.limit = limit

    def feed(self, data: bytes):
        self.buffer += data
        packets = []
        while len(self.buffer) >= 2:
            multiplier, length, index = 1, 0, 1
            while True:
                if index >= len(self.buffer):
                    return packets
                byte = self.buffer[index]
                length += (byte & 0x7F) * multiplier
                index += 1
                if not byte & 0x80:
                    break
                multiplier *= 128
                if multiplier > 128 ** 3:
                    raise PacketError("malformed remaining length")
            if length > self.limit:
                raise PacketError("packet over the size limit")
            if len(self.buffer) < index + length:
                return packets
            first = self.buffer[0]
            body = bytes(self.buffer[index:index + length])
            del self.buffer[:index + length]
            packets.append((first >> 4, first & 0x0F, body))
        return packets


def parse_publish(flags: int, body: bytes):
    """Return (topic, payload, retain, qos, packet_id or None) for a PUBLISH body."""
    try:
        size = struct.unpack(">H", body[:2])[0]
        if len(body) < 2 + size:
            raise PacketError("truncated topic")
        topic = body[2:2 + size].decode("utf-8")
        qos = (flags >> 1) & 0x03
        position = 2 + size
        packet_id = None
        if qos:
            packet_id = struct.unpack(">H", body[position:position + 2])[0]
            position += 2
    except (struct.error, UnicodeDecodeError) as error:
        raise PacketError(f"bad PUBLISH: {error}") from error
    return topic, body[position:], bool(flags & 0x01), qos, packet_id
