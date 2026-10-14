"""Philips Hue, sketched from the docs. UNTESTED: I don't own a Hue bridge anymore.

Nothing calls this yet. It's here to show the shape of a Hue backend and to
answer the question of whether a third-party app can get at the Entertainment
area without jumping through hoops. Per the Hue docs, yes:

  1. Find the bridge. mDNS `_hue._tcp.local`, or ask
     https://discovery.meethue.com which bridges share your public IP.
  2. Pair. POST /api with {"devicetype": ..., "generateclientkey": true}
     while someone presses the bridge's link button. You get back a
     `username` (the app key) and a `clientkey` (for streaming). No developer
     account involved; this is all on the LAN.
  3. Read the Entertainment areas the user already set up in the Hue app:
     GET /clip/v2/resource/entertainment_configuration with the
     `hue-application-key` header. Each one lists its channels with x/y/z
     positions (-1..1, TV at the front), so "left edge", "right edge" etc.
     fall straight out of the positions. That's the bit I asked about.
  4. Start it: PUT that configuration with {"action": "start"}.
  5. Stream: DTLS 1.2 with a pre-shared key (identity = app key, key =
     clientkey) to UDP 2100, sending HueStream v2 packets of up to 20
     channels each, ideally 50-60 a second.
  6. Stop: PUT {"action": "stop"} when the game ends.

Step 5 is why this stops at a sketch. Python's ssl module can't do DTLS, so a
real version needs something like mbedtls or a small helper binary, and I
didn't want to add a native dependency for a feature I can't test.

Docs: https://developers.meethue.com/develop/hue-entertainment/
(the docs themselves sit behind a free login).
"""

from __future__ import annotations

import json
import ssl
import urllib.request

DISCOVERY_URL = "https://discovery.meethue.com"
APP_NAME = "gabecubeaura#steam-machine"

# Hue bridges use a self-signed certificate. The docs say to pin Signify's CA;
# skipping verification keeps the sketch short and is fine on a home LAN.
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


def find_bridges():
    """[{"id": ..., "internalipaddress": ...}, ...] via Hue's discovery service."""
    try:
        return _request("GET", DISCOVERY_URL)
    except OSError:
        return []


def pair(bridge_ip):
    """Call this after the user presses the link button. Returns (app_key, client_key)
    or None if the button hasn't been pressed yet."""
    reply = _request("POST", f"https://{bridge_ip}/api",
                     {"devicetype": APP_NAME, "generateclientkey": True})
    success = (reply or [{}])[0].get("success")
    if not success:
        return None
    return success["username"], success["clientkey"]


def entertainment_areas(bridge_ip, app_key):
    """The user's Entertainment areas with each channel's position."""
    reply = _request("GET", f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration",
                     key=app_key)
    areas = []
    for area in reply.get("data", []):
        areas.append({
            "id": area["id"],
            "name": area.get("metadata", {}).get("name", "Entertainment area"),
            "channels": [
                {"id": channel["channel_id"], "position": channel["position"]}
                for channel in area.get("channels", [])
            ],
        })
    return areas


def side_for(position):
    """Which screen edge a channel should follow, from its x/y position."""
    x, y = position["x"], position["y"]
    if abs(x) >= abs(y):
        return "right" if x > 0 else "left"
    return "top" if y > 0 else "bottom"


def set_streaming(bridge_ip, app_key, area_id, on):
    return _request("PUT",
                    f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{area_id}",
                    {"action": "start" if on else "stop"}, key=app_key)


def huestream_packet(area_id, colours):
    """One HueStream v2 packet. `colours` is [(channel_id, (r, g, b)), ...], 8-bit."""
    packet = bytearray(b"HueStream")
    packet += bytes((0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00))  # v2.0, seq, reserved, RGB, reserved
    packet += area_id.encode("ascii")
    for channel, (r, g, b) in colours[:20]:
        packet.append(channel)
        for value in (r, g, b):
            packet += int(value * 257).to_bytes(2, "big")  # 16-bit per colour
    return bytes(packet)


def stream(*_args, **_kwargs):
    raise NotImplementedError(
        "Hue streaming needs DTLS (PSK) and Python's ssl module doesn't do DTLS. See the notes at the top."
    )
