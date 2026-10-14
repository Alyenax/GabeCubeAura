"""Govee LAN API: find lights on the network and stream colour to them.

No account, no cloud, no keys. The only thing the user has to do is flip
"LAN Control" on for each light in the Govee app, which is a one-time toggle.
"""

from __future__ import annotations

import base64
import json
import socket
import time

SCAN_GROUP = "239.255.255.250"
SCAN_PORT = 4001      # lights listen here for the scan
REPLY_PORT = 4002     # and answer here
CONTROL_PORT = 4003   # everything else goes to the light's IP on this port

# The "razer" command is the real-time mode the Govee HDMI sync box uses. I
# went with it over ptReal (the per-segment command the app uses) because
# ptReal writes settings the light stores, and after a few hours of 10+ a
# second my strip dropped off LAN Control twice. Razer frames aren't stored.
# Every razer payload ends with an XOR of all its bytes.
RAZER_ON = bytes((0xBB, 0x00, 0x01, 0xB1, 0x01))
RAZER_OFF = bytes((0xBB, 0x00, 0x01, 0xB1, 0x00))


def scan(timeout=2.0):
    """Ask every Govee light on the LAN to say hi. Returns a list of dicts."""
    listener = _reply_socket(0.2)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    ask = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}})

    found = {}
    try:
        # UDP multicast gets dropped sometimes, so ask a few times.
        deadline = time.monotonic() + timeout
        next_ask = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_ask:
                sender.sendto(ask.encode(), (SCAN_GROUP, SCAN_PORT))
                next_ask = time.monotonic() + 0.6
            try:
                data, _ = listener.recvfrom(4096)
            except socket.timeout:
                continue
            try:
                info = json.loads(data)["msg"]["data"]
            except (ValueError, KeyError, TypeError):
                continue
            if info.get("device") and info.get("ip"):
                found[info["device"]] = {
                    "id": info["device"],
                    "ip": info["ip"],
                    "model": info.get("sku", "?"),
                }
    finally:
        listener.close()
        sender.close()
    return sorted(found.values(), key=lambda light: (light["model"], light["ip"]))


def _reply_socket(timeout):
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    listener.bind(("", REPLY_PORT))
    listener.settimeout(timeout)
    return listener


def identify(ip):
    """Blink a light three times so you can tell which one it is, then put it
    back how it was. If the light doesn't say how it was, it's left on."""
    light = GoveeLight(ip)
    before = light.state()
    for _ in range(3):
        light.power(True)
        light.brightness(100)
        light.white(6500)
        time.sleep(0.4)
        light.brightness(1)
        time.sleep(0.4)
    if not before:
        light.brightness(100)
        return
    if not before.get("onOff"):
        light.power(False)
        return
    light.brightness(before.get("brightness", 100))
    if before.get("colorTemInKelvin"):
        light.white(before["colorTemInKelvin"])
    elif before.get("color"):
        c = before["color"]
        light.colour((c.get("r", 0), c.get("g", 0), c.get("b", 0)))


class GoveeLight:
    """One light, addressed by IP. Fire and forget UDP, so nothing here blocks."""

    def __init__(self, ip, sock=None):
        self.ip = ip
        self.sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.streaming = False

    def _send(self, cmd, data):
        message = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
        try:
            self.sock.sendto(message, (self.ip, CONTROL_PORT))
            return True
        except OSError:
            return False

    def _razer(self, raw):
        checksum = 0
        for byte in raw:
            checksum ^= byte
        payload = base64.b64encode(bytes(raw) + bytes((checksum,))).decode("ascii")
        return self._send("razer", {"pt": payload})

    def state(self, timeout=1.0):
        """Ask the light what it's doing: onOff, brightness, color,
        colorTemInKelvin. None if it doesn't answer in time."""
        try:
            listener = _reply_socket(0.2)
        except OSError:
            return None
        try:
            self._send("devStatus", {})
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, (sender, _) = listener.recvfrom(4096)
                except socket.timeout:
                    continue
                if sender != self.ip:
                    continue
                try:
                    message = json.loads(data)["msg"]
                except (ValueError, KeyError, TypeError):
                    continue
                if message.get("cmd") == "devStatus":
                    return message.get("data")
        finally:
            listener.close()
        return None

    def power(self, on):
        return self._send("turn", {"value": 1 if on else 0})

    def brightness(self, percent):
        return self._send("brightness", {"value": max(1, min(100, int(percent)))})

    def colour(self, rgb):
        """Whole-light colour. Fine for slow changes, too chatty for real time."""
        r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
        return self._send("colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})

    def white(self, kelvin):
        """Plain white at a colour temperature, e.g. 3000 for warm."""
        return self._send("colorwc", {"color": {"r": 0, "g": 0, "b": 0},
                                      "colorTemInKelvin": int(kelvin)})

    def start_stream(self, brightness=100):
        # Power and brightness first, then a beat before real-time mode. Sent
        # back to back, the enable sometimes lands before the light is awake.
        self.power(True)
        self.brightness(brightness)
        time.sleep(0.05)
        self._razer(RAZER_ON)
        self.streaming = True

    def frame(self, colours):
        """Send a list of colours. The light stretches them across its length,
        so a bulb can take one colour and a lamp or strip can take several."""
        colours = list(colours)[:255]
        n = len(colours)
        if not n:
            return False
        raw = bytearray((0xBB, 0x00, (3 * n + 2) & 0xFF, 0xB0, 0x01, n))
        for rgb in colours:
            raw.extend(max(0, min(255, int(round(c)))) for c in rgb)
        return self._razer(raw)

    def stop_stream(self):
        self._razer(RAZER_OFF)
        self.streaming = False
