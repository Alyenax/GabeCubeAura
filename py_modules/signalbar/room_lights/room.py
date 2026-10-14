"""Room lights: drive lights around the room from what's on screen.

Each light gets one role:

  off         left alone
  key-art     slow ambient. The game's artwork palette is laid around all the
              key-art lights like a ring and turns slowly, so the room has
              some movement without pulling your eye off the TV.
  screen-*    real time. The light follows one edge of the picture (left,
              right, top, bottom) or the whole thing.

Roles mix freely: a couple of lamps behind the TV on screen edges and the rest
of the room on key art is the setup I run at home.

Settings live in their own small JSON file so this whole feature can be
pulled out by deleting this folder and a handful of lines in the engine.
"""

from __future__ import annotations

import json
import os
import threading
import time

from signalbar.room_lights import govee

ROLES = ("off", "key-art", "screen-left", "screen-right", "screen-top",
         "screen-bottom", "screen-whole")

# A light is told the stream ended after this long without a fresh frame, so a
# closed game or a sleeping Steam Machine hands the light back.
SCREEN_TIMEOUT = 1.5
# One lap of the key-art ring. Slow on purpose.
RING_LAP_SECONDS = 180.0
# Key-art lights only get a new colour when it has moved this much (0-255 per
# channel), and never more than once a second. Bulbs don't need more.
RING_MIN_CHANGE = 6
RING_MIN_INTERVAL = 1.0
# Screen lights: 20 updates a second is plenty and keeps the network quiet.
SCREEN_MIN_INTERVAL = 0.05
SCREEN_KEEPALIVE = 0.5


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def ring_colour(palette, position):
    """Colour at `position` (0..1) around a ring made from the palette."""
    n = len(palette)
    spot = (position % 1.0) * n
    i = int(spot)
    return _mix(palette[i % n], palette[(i + 1) % n], spot - i)


class RoomLights:
    def __init__(self, path, clock=time.monotonic, light_factory=govee.GoveeLight):
        self.path = path
        self.clock = clock
        self.light_factory = light_factory
        self._lock = threading.Lock()
        self._lights = {}        # id -> GoveeLight, made on first use
        self._sent = {}          # id -> (colours, at)
        self._last_frame_at = 0.0
        self._found = []
        self.config = {"enabled": False, "brightness": 80, "lights": {}}
        try:
            with open(path) as handle:
                saved = json.load(handle)
            self.config.update({k: saved[k] for k in self.config if k in saved})
        except (OSError, ValueError):
            pass

    # -- settings ---------------------------------------------------------

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(self.config, handle, indent=2)
        os.replace(tmp, self.path)

    def scan(self, extra_ips=()):
        found = govee.scan()
        known = {light["id"] for light in found}
        # Lights on another VLAN never hear the multicast scan, so anything
        # added by IP stays in the list even when the scan can't see it.
        for light_id, light in self.config["lights"].items():
            if light_id not in known:
                found.append({"id": light_id, "ip": light["ip"], "model": light.get("model", "?")})
        for ip in extra_ips:
            if ip and ip not in {light["ip"] for light in found}:
                found.append({"id": ip, "ip": ip, "model": "added by IP"})
        with self._lock:
            self._found = found
        return self.status()

    def set_enabled(self, enabled):
        with self._lock:
            self.config["enabled"] = bool(enabled)
            if not enabled:
                self._release_all()
            self._save()
        return self.status()

    def set_brightness(self, percent):
        with self._lock:
            self.config["brightness"] = max(1, min(100, int(percent)))
            for light in self._lights.values():
                light.streaming = False  # re-sends brightness on the next frame
            self._save()
        return self.status()

    def set_role(self, light_id, ip, model, role):
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        with self._lock:
            if role == "off":
                self._release(light_id)
                self.config["lights"].pop(light_id, None)
            else:
                old = self.config["lights"].get(light_id, {}).get("role")
                if old != role:
                    self._release(light_id)
                self.config["lights"][light_id] = {"ip": ip, "model": model, "role": role}
            self._save()
        return self.status()

    def status(self):
        with self._lock:
            return {
                "enabled": self.config["enabled"],
                "brightness": self.config["brightness"],
                "lights": dict(self.config["lights"]),
                "found": list(self._found),
                "roles": list(ROLES),
            }

    def wants_screen(self):
        """True when some light needs the live picture, so capture should run."""
        return self.config["enabled"] and any(
            light["role"].startswith("screen-") for light in self.config["lights"].values()
        )

    # -- output -----------------------------------------------------------

    def _light(self, light_id):
        light = self._lights.get(light_id)
        ip = self.config["lights"][light_id]["ip"]
        if light is None or light.ip != ip:
            light = self._lights[light_id] = self.light_factory(ip)
        return light

    def _release(self, light_id):
        light = self._lights.pop(light_id, None)
        if light is not None and light.streaming:
            light.stop_stream()
        self._sent.pop(light_id, None)

    def _release_all(self):
        for light_id in list(self._lights):
            self._release(light_id)

    def update(self, edges=None, palette=()):
        """Called from the engine loop, about ten times a second.

        edges: {"left": [rgb...], "right": [...], "top": [...], "bottom": [...],
                "whole": [rgb]} from the latest screen frame, or None.
        palette: the current game's artwork colours, or empty.
        """
        with self._lock:
            if not self.config["enabled"]:
                return
            now = self.clock()
            if edges:
                self._last_frame_at = now
            screen_live = now - self._last_frame_at < SCREEN_TIMEOUT

            lights = self.config["lights"]
            ring = sorted(i for i, light in lights.items() if light["role"] == "key-art")
            for light_id, light_cfg in lights.items():
                role = light_cfg["role"]
                if role.startswith("screen-"):
                    if screen_live and edges:
                        self._stream(light_id, edges[role[len("screen-"):]], now)
                    elif not screen_live and light_id in self._sent:
                        self._release(light_id)
                elif role == "key-art" and palette:
                    spot = ring.index(light_id) / len(ring) + now / RING_LAP_SECONDS
                    self._paint(light_id, ring_colour(list(palette), spot), now)

    def _stream(self, light_id, colours, now):
        light = self._light(light_id)
        last, at = self._sent.get(light_id, (None, 0.0))
        if now - at < SCREEN_MIN_INTERVAL:
            return
        if colours == last and now - at < SCREEN_KEEPALIVE:
            return
        if not light.streaming:
            light.start_stream(self.config["brightness"])
        if not light.frame(colours):
            light.streaming = False  # try the enable again next time
        self._sent[light_id] = (colours, now)

    def _paint(self, light_id, colour, now):
        light = self._light(light_id)
        last, at = self._sent.get(light_id, (None, 0.0))
        if now - at < RING_MIN_INTERVAL:
            return
        if last and max(abs(a - b) for a, b in zip(last, colour)) < RING_MIN_CHANGE:
            return
        if last is None:
            light.power(True)
            light.brightness(self.config["brightness"])
        light.colour(colour)
        self._sent[light_id] = (colour, now)

    def stop(self):
        with self._lock:
            self._release_all()
