"""Philips Hue for Smart lighting. UNTESTED: written from the Hue docs, never run.

I don't own a Hue bridge anymore, so this is a stub for whoever picks it up.
HueArea has the same method names as govee.GoveeLight (power, brightness,
colour, white, start_stream, frame, stop_stream). It doesn't drop into room.py
as is: drivers there are built from an IP alone, and Hue needs the bridge,
keys and an area id, so wiring it in means a Hue entry in DRIVERS whose Light
knows where to find those. Nothing calls anything in this file yet, and the
Hue toggle in the UI is disabled.

How Hue works, per the docs (https://developers.meethue.com, free login):

  1. Find the bridge: mDNS `_hue._tcp.local`, or GET
     https://discovery.meethue.com (lists bridges behind your public IP).
  2. Pair: POST /api {"devicetype": ..., "generateclientkey": true} after the
     user presses the round link button on the bridge. Returns `username`
     (the app key) and `clientkey` (the streaming key). Save both. This is all
     local; no developer account or cloud involved.
  3. Read the user's Entertainment areas (set up in the Hue app with each
     light's position): GET /clip/v2/resource/entertainment_configuration.
     Every channel has x/y/z from -1 to 1, TV at the front.
  4. Start: PUT the area with {"action": "start"}.
  5. Stream: DTLS 1.2, PSK, UDP 2100, HueStream v2 packets, 50-60 a second.
  6. Stop: PUT {"action": "stop"} when the game ends.

Look for "CHECK" and "TRY" in the comments below: those are the spots I'd
expect to need fixing on a real bridge.
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.request

DISCOVERY_URL = "https://discovery.meethue.com"
APP_NAME = "gabecubeaura#steam-machine"  # CHECK: max 40 chars, "app#device" format
STREAM_PORT = 2100

# Hue bridges serve a self-signed cert. The docs say to pin Signify's root CA
# and check the bridge ID as the hostname. Skipping verification keeps the
# stub short and is OK on a home LAN. TRY: pin the CA before shipping this.
_INSECURE = ssl.create_default_context()
_INSECURE.check_hostname = False
_INSECURE.verify_mode = ssl.CERT_NONE


def _request(method, url, body=None, key=None, timeout=4.0):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["hue-application-key"] = key
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout, context=_INSECURE) as response:
        return json.loads(response.read() or b"null")


# --- setup -------------------------------------------------------------------

def find_bridges():
    """[{"id": ..., "internalipaddress": ...}, ...]

    This asks Signify's discovery service, which is a cloud call. If that
    doesn't sit right with GabeCubeAura's privacy posture, TRY mDNS instead
    (`_hue._tcp.local`); python-zeroconf does it in a few lines but it's a new
    dependency. The service is also rate limited (roughly one call per 15
    minutes per IP), so CHECK you only call it when the user taps Scan.
    """
    try:
        return _request("GET", DISCOVERY_URL)
    except OSError:
        return []


def pair(bridge_ip):
    """Call after the user presses the link button. Returns (app_key, client_key),
    or None if the button wasn't pressed (the bridge answers with error type 101).

    The button stays "pressed" for about 30 seconds. TRY: poll this once a
    second for 30 s while the UI says "Press the button on your Hue bridge".
    """
    reply = _request("POST", f"https://{bridge_ip}/api",
                     {"devicetype": APP_NAME, "generateclientkey": True})
    success = (reply or [{}])[0].get("success")
    if not success:
        return None
    return success["username"], success["clientkey"]


def entertainment_areas(bridge_ip, app_key):
    """The user's Entertainment areas, with each channel's position."""
    reply = _request("GET", f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration",
                     key=app_key)
    areas = []
    for area in reply.get("data", []):
        areas.append({
            "id": area["id"],
            "name": area.get("metadata", {}).get("name", "Entertainment area"),
            # CHECK: channel_id should be a small int (0-19) and position a
            # dict with x/y/z. If the shape differs, this is where it breaks.
            "channels": [
                {"id": channel["channel_id"], "position": channel["position"]}
                for channel in area.get("channels", [])
            ],
        })
    return areas


def zone_for(position, across=4, down=3):
    """Pick the screen cell a channel should show, from its x/y position.

    Hue positions: x -1 (left) to 1 (right), y -1 (back, behind you) to 1
    (front, at the TV), z -1 (floor) to 1 (ceiling). For a TV setup the
    useful axes are x for left/right and z for top/bottom. CHECK the sign of
    z on a real bridge: I'm going from the docs' diagram.

    This means Hue users wouldn't need the zone picker at all: the positions
    they set in the Hue app already say where each light is.
    """
    x, z = position.get("x", 0.0), position.get("z", 0.0)
    if abs(x) >= 0.6 and abs(z) >= 0.6:
        return ("top-" if z > 0 else "bottom-") + ("right" if x > 0 else "left")
    if abs(x) >= abs(z):
        row = min(down, max(1, round((1 - z) / 2 * (down - 1)) + 1))
        return f"{'right' if x > 0 else 'left'}-{row}"
    column = min(across, max(1, round((x + 1) / 2 * (across - 1)) + 1))
    return f"{'top' if z > 0 else 'bottom'}-{column}"


# --- streaming ---------------------------------------------------------------

def huestream_packet(area_id, colours, sequence=0):
    """One HueStream v2 packet. `colours` is [(channel_id, (r, g, b)), ...] in 0-255.

    Layout per the docs: "HueStream", version 2.0, sequence, 2 reserved bytes,
    colour space (0 = RGB), 1 reserved byte, the 36-char area id, then up to
    20 channels of channel id + 16-bit R, G, B.
    """
    packet = bytearray(b"HueStream")
    packet += bytes((0x02, 0x00, sequence & 0xFF, 0x00, 0x00, 0x00, 0x00))
    packet += area_id.encode("ascii")
    for channel, (r, g, b) in colours[:20]:
        packet.append(channel)
        for value in (r, g, b):
            packet += (max(0, min(255, int(value))) * 257).to_bytes(2, "big")
    return bytes(packet)


class HueArea:
    """One Entertainment area, driven like a Govee light: frame() takes the
    colours for each channel. Same method names as govee.GoveeLight.

    The catch is DTLS. Python's ssl module only does TLS over TCP, and Hue
    streaming needs DTLS 1.2 with PSK over UDP. Options I'd TRY, in order:
      - `python-mbedtls` (pip, has DTLS + PSK; wheels exist for x86_64 Linux,
        which is what the Steam Machine runs)
      - shelling out to `openssl s_client -dtls1_2 -psk ...` and writing
        packets to its stdin (no new Python deps, but fiddly)
    Until then start_stream() raises, so nothing half-works.
    """

    def __init__(self, bridge_ip, app_key, client_key, area_id, channels):
        self.ip = bridge_ip
        self.app_key = app_key
        self.client_key = client_key  # hex string; the PSK is bytes.fromhex(client_key)
        self.area_id = area_id
        self.channels = channels      # [{"id": 0, "position": {...}}, ...]
        self.streaming = False
        self._sequence = 0
        self._dtls = None

    def _area_url(self):
        return f"https://{self.ip}/clip/v2/resource/entertainment_configuration/{self.area_id}"

    # Plain (non-streaming) control for the key-art ring and idle looks.
    # Entertainment areas don't take colour commands directly; you'd send
    # these to each light or to the area's grouped_light. TRY:
    # PUT /clip/v2/resource/grouped_light/<id> {"on": {"on": true}}, and
    # {"color": {"xy": {...}}} for colour (Hue wants CIE xy, not RGB, so a
    # small RGB -> xy conversion goes here). Left as stubs on purpose.
    def power(self, on):
        raise NotImplementedError("Hue: PUT grouped_light {'on': {'on': on}}")

    def brightness(self, percent):
        raise NotImplementedError("Hue: PUT grouped_light {'dimming': {'brightness': percent}}")

    def colour(self, rgb):
        raise NotImplementedError("Hue: convert RGB to CIE xy, then PUT {'color': {'xy': ...}}")

    def white(self, kelvin):
        raise NotImplementedError("Hue: PUT {'color_temperature': {'mirek': 1000000 // kelvin}}")

    def start_stream(self, brightness=100):
        # This part should work as written: it's a plain HTTPS PUT.
        _request("PUT", self._area_url(), {"action": "start"}, key=self.app_key)
        # This part doesn't exist yet. The handshake: DTLS 1.2, cipher
        # TLS_PSK_WITH_AES_128_GCM_SHA256, PSK identity = app_key,
        # PSK = bytes.fromhex(client_key), to (bridge_ip, 2100). CHECK: the
        # bridge drops the session after ~10 s with no packets, so keep
        # sending even when colours don't change.
        raise NotImplementedError("Hue streaming needs DTLS; see the class docstring")

    def frame(self, colours):
        """colours: one (r, g, b) per channel, in self.channels order.

        room.py sends one colour per picked cell. For Hue, TRY: ignore the
        picked cells and map each channel to zone_for(channel position)
        instead, so the Hue app's layout drives it.
        """
        if not self._dtls:
            return False
        packet = huestream_packet(self.area_id, [
            (channel["id"], colour) for channel, colour in zip(self.channels, colours)
        ], self._sequence)
        self._sequence += 1
        try:
            self._dtls.send(packet)
            return True
        except (OSError, socket.error):
            return False

    def stop_stream(self):
        self.streaming = False
        if self._dtls:
            self._dtls.close()
            self._dtls = None
        try:
            _request("PUT", self._area_url(), {"action": "stop"}, key=self.app_key)
        except OSError:
            pass  # the bridge stops on its own ~10 s after packets stop
