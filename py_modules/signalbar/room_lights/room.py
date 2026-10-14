"""Room lights: drive lights around the room from what's on screen.

Each light gets one role:

  off      left alone
  key-art  slow ambient. The game's artwork palette is laid around all the
           key-art lights like a ring and turns slowly, so the room has some
           movement without pulling your eye off the TV.
  screen   real time. The light shows the screen zones picked for it: cells
           along the top, bottom, left and right edges, or the whole picture.
           A light with several cells (a strip under the TV) gets them in
           order, one colour per cell, and stretches them along its length.

Roles mix freely: a couple of lamps behind the TV on screen zones and the rest
of the room on key art is the setup I run at home.

When no game is running the lights do whatever "idle" says: nothing, warm
white, or off.

Lights are remembered by their Govee device ID, not their IP, and the IPs get
refreshed with a quick scan at startup and whenever a game starts, so DHCP
moving a light around doesn't break anything.

Settings live in their own small JSON file so this whole feature can be
pulled out by deleting this folder and a handful of lines in the engine.
"""

from __future__ import annotations

import json
import os
import threading
import time

from signalbar.room_lights import govee

ROLES = ("off", "key-art", "screen")
IDLE_MODES = ("leave", "warm", "off")
ACROSS, DOWN = 4, 3  # screen cells along the top/bottom and down each side
# The cells around the edge of the screen, clockwise from the top-left corner.
RING = (["top-left"] + [f"top-{i}" for i in range(1, ACROSS + 1)] + ["top-right"]
        + [f"right-{i}" for i in range(1, DOWN + 1)] + ["bottom-right"]
        + [f"bottom-{i}" for i in range(ACROSS, 0, -1)] + ["bottom-left"]
        + [f"left-{i}" for i in range(DOWN, 0, -1)])
ZONES = ("whole",) + tuple(RING)


def _spot(zone):
    """(row, column) of a cell on the screen grid, for working out which end is lowest."""
    edge, _, n = zone.partition("-")
    if n in ("left", "right"):
        return (0 if edge == "top" else DOWN + 1, 0 if n == "left" else ACROSS + 1)
    n = int(n)
    return {"top": (0, n), "bottom": (DOWN + 1, n), "left": (n, 0), "right": (n, ACROSS + 1)}[edge]


def send_order(zones, reverse=False):
    """The order a light's cells are sent in.

    Picked cells are walked around the edge of the screen, starting from the
    lowest end (left-most if both ends are level). That matches Govee, where
    the first colour lands at the bottom of a lamp and the left end of a strip,
    so a lamp on either side or a strip under the TV comes out right without
    touching anything. "Reverse" flips it for lights mounted the other way.
    """
    picked = [z for z in RING if z in zones]
    if not picked:
        return ["whole"]
    if len(picked) < len(RING):
        # Rotate the ring so the run of picked cells doesn't wrap around.
        start = next(i for i, z in enumerate(RING)
                     if z in zones and RING[i - 1] not in zones)
        picked = [z for z in RING[start:] + RING[:start] if z in zones]
    first, last = _spot(picked[0]), _spot(picked[-1])
    if (last[0], -last[1]) > (first[0], -first[1]):
        picked.reverse()
    if reverse:
        picked.reverse()
    return picked


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
# Idle state is sent once, then again now and then in case a light missed it
# (UDP has no delivery receipt) or was switched back on at the wall.
IDLE_RESEND = 120.0

DEFAULTS = {
    "enabled": False,
    "brightness": 80,
    "idle": "leave",
    "idle_kelvin": 3000,
    "idle_brightness": 40,
    "lights": {},
}


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def ring_colour(palette, position):
    """Colour at `position` (0..1) around a ring made from the palette."""
    n = len(palette)
    spot = (position % 1.0) * n
    i = int(spot)
    return _mix(palette[i % n], palette[(i + 1) % n], spot - i)


def _upgrade(light):
    """Configs from the first test build used screen-left etc. as roles."""
    role = light.get("role", "off")
    if role.startswith("screen-"):
        edge = role[len("screen-"):]
        light["role"] = "screen"
        light["zones"] = ["whole"] if edge == "whole" else [
            z for z in ZONES if z.startswith(edge + "-") and z.count("-") == 1 and z[-1].isdigit()]
    light.setdefault("zones", ["whole"])
    light.setdefault("reverse", False)
    return light


class RoomLights:
    def __init__(self, path, clock=time.monotonic, light_factory=govee.GoveeLight,
                 scanner=govee.scan):
        self.path = path
        self.clock = clock
        self.light_factory = light_factory
        self.scanner = scanner
        self._lock = threading.Lock()
        self._lights = {}        # id -> GoveeLight, made on first use
        self._sent = {}          # id -> (colours, at)
        self._last_frame_at = 0.0
        self._was_running = False
        self._idle_sent_at = None
        self._found = []
        self._quiet_until = {}   # ip -> time; leave a light alone while it blinks
        self.config = json.loads(json.dumps(DEFAULTS))
        try:
            with open(path) as handle:
                saved = json.load(handle)
            self.config.update({k: saved[k] for k in DEFAULTS if k in saved})
        except (OSError, ValueError):
            pass
        for light in self.config["lights"].values():
            _upgrade(light)
        # Saved lights show up straight away; a scan only adds to the list.
        self._found = [{"id": i, "ip": l["ip"], "model": l.get("model", "?")}
                       for i, l in self.config["lights"].items()]

    # -- settings ---------------------------------------------------------

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(self.config, handle, indent=2)
        os.replace(tmp, self.path)

    def _learn_addresses(self, found):
        """Point saved lights at the IP the scan just saw them on."""
        changed = False
        for light in found:
            saved = self.config["lights"].get(light["id"])
            if saved and saved["ip"] != light["ip"]:
                saved["ip"] = light["ip"]
                self._lights.pop(light["id"], None)
                changed = True
        if changed:
            self._save()

    def refresh_addresses(self):
        """Rescan in the background and fix up any IPs DHCP has moved."""
        if not self.config["enabled"] or not self.config["lights"]:
            return

        def run():
            found = self.scanner()
            with self._lock:
                self._learn_addresses(found)
        threading.Thread(target=run, name="room-lights-scan", daemon=True).start()

    def scan(self, extra_ips=()):
        found = self.scanner()
        known = {light["id"] for light in found}
        # Keep anything an earlier scan found too, so a light that misses one
        # multicast round doesn't drop out of the list.
        for light in self._found:
            if light["id"] not in known and light["id"] not in self.config["lights"]:
                found.append(light)
                known.add(light["id"])
        # Lights on another VLAN never hear the multicast scan, so anything
        # added by IP stays in the list even when the scan can't see it.
        for light_id, light in self.config["lights"].items():
            if light_id not in known:
                found.append({"id": light_id, "ip": light["ip"], "model": light.get("model", "?")})
        for ip in extra_ips:
            if ip and ip not in {light["ip"] for light in found}:
                found.append({"id": ip, "ip": ip, "model": "added by IP"})
        with self._lock:
            self._learn_addresses(found)
            self._found = found
        return self.status()

    def identify(self, ip):
        """Blink one light so the user can tell which one it is."""
        with self._lock:
            # Don't fight a light we're streaming to: hand it back first.
            self._quiet_until[ip] = self.clock() + 10.0
            for light_id, light in list(self.config["lights"].items()):
                if light["ip"] == ip:
                    self._release(light_id)
        try:
            govee.identify(ip)
        finally:
            with self._lock:
                self._quiet_until.pop(ip, None)
        return self.status()

    def set_options(self, changes):
        """enabled, brightness, idle, idle_kelvin, idle_brightness."""
        with self._lock:
            if "enabled" in changes:
                self.config["enabled"] = bool(changes["enabled"])
                if not self.config["enabled"]:
                    self._release_all()
            if "brightness" in changes:
                self.config["brightness"] = max(1, min(100, int(changes["brightness"])))
                for light in self._lights.values():
                    light.streaming = False  # re-sends brightness on the next frame
            if changes.get("idle") in IDLE_MODES:
                self.config["idle"] = changes["idle"]
            if "idle_kelvin" in changes:
                self.config["idle_kelvin"] = max(2000, min(9000, int(changes["idle_kelvin"])))
            if "idle_brightness" in changes:
                self.config["idle_brightness"] = max(1, min(100, int(changes["idle_brightness"])))
            self._idle_sent_at = None  # apply the new idle look straight away
            self._save()
        if changes.get("enabled"):
            self.refresh_addresses()
        return self.status()

    def set_light(self, light_id, ip, model, role, zones=None, reverse=None):
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        with self._lock:
            if role == "off":
                self._release(light_id)
                self.config["lights"].pop(light_id, None)
            else:
                light = self.config["lights"].get(light_id) or _upgrade({"role": role})
                if light["role"] != role:
                    self._release(light_id)
                light.update({"ip": ip, "model": model, "role": role})
                if zones is not None:
                    light["zones"] = [z for z in zones if z in ZONES] or ["whole"]
                if reverse is not None:
                    light["reverse"] = bool(reverse)
                self.config["lights"][light_id] = light
            self._idle_sent_at = None
            self._save()
        return self.status()

    def status(self):
        with self._lock:
            return {
                **{k: self.config[k] for k in DEFAULTS if k != "lights"},
                "lights": json.loads(json.dumps(self.config["lights"])),
                "found": list(self._found),
                "roles": list(ROLES),
                "idle_modes": list(IDLE_MODES),
                "across": ACROSS,
                "down": DOWN,
            }

    def wants_screen(self):
        """True when some light needs the live picture, so capture should run."""
        return self.config["enabled"] and any(
            light["role"] == "screen" for light in self.config["lights"].values()
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

    def update(self, zones=None, palette=(), game_running=False):
        """Called from the engine loop, about ten times a second.

        zones: {"top-1": rgb, ..., "whole": rgb} from the latest screen frame,
               or None when there's no fresh frame.
        palette: the current game's artwork colours, or empty.
        """
        if game_running and not self._was_running:
            self.refresh_addresses()  # a game just started: catch DHCP moves
        self._was_running = game_running
        with self._lock:
            if not self.config["enabled"]:
                return
            now = self.clock()
            if zones:
                self._last_frame_at = now
            screen_live = now - self._last_frame_at < SCREEN_TIMEOUT

            if not game_running and not screen_live:
                self._idle(now)
                return
            self._idle_sent_at = None

            lights = self.config["lights"]
            ring = sorted(i for i, light in lights.items() if light["role"] == "key-art")
            for light_id, light in lights.items():
                if self._quiet_until.get(light["ip"], 0) > now:
                    continue
                if light["role"] == "screen":
                    if screen_live and zones:
                        cells = send_order(light["zones"], light["reverse"])
                        self._stream(light_id, [zones[z] for z in cells], now)
                    elif not screen_live and light_id in self._sent:
                        self._release(light_id)
                elif light["role"] == "key-art" and palette:
                    spot = ring.index(light_id) / len(ring) + now / RING_LAP_SECONDS
                    self._paint(light_id, ring_colour(list(palette), spot), now)

    def _idle(self, now):
        if self._idle_sent_at is not None and now - self._idle_sent_at < IDLE_RESEND:
            return
        self._release_all()
        mode = self.config["idle"]
        for light_id, light_cfg in self.config["lights"].items():
            if self._quiet_until.get(light_cfg["ip"], 0) > now:
                continue
            if mode == "warm":
                light = self._light(light_id)
                light.power(True)
                light.brightness(self.config["idle_brightness"])
                light.white(self.config["idle_kelvin"])
            elif mode == "off":
                self._light(light_id).power(False)
        self._idle_sent_at = now

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
