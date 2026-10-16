"""Check the commands Home Assistant sends to drive the light bar.

Topics under <root>/drive/:
- light: Home Assistant's JSON light schema, {"state": "ON" | "OFF",
  "brightness": 0-255, "color": {"r", "g", "b"}}. "transition" is accepted
  and ignored, "color_mode" may only be "rgb", and brightness 0 means off.
- frame: a JSON list of 17 [r, g, b] values, left to right.
- alert: {"variant": "flash" | "pulse" | "sweep", "color": {"r", "g", "b"},
  "duration": 0.5-4.85 seconds}. Colour defaults to white and duration to
  the variant's own length.

Keys use Home Assistant's spelling ("color") so an automation can pass a
light's colour straight through. Everything is checked here, on the client
thread, so the engine never meets a malformed value. Reasons never quote the
payload.
"""

from __future__ import annotations

import json
from typing import NamedTuple, Optional, Tuple

from signalbar.models import LED_COUNT
from signalbar.providers.events import HA_ALERT_MAX_S, HA_ALERT_MIN_S

LIGHT_LIMIT = 256
FRAME_LIMIT = 1024
ALERT_LIMIT = 256
ALERT_VARIANTS = ("flash", "pulse", "sweep")
WHITE = (255, 255, 255)
_LIGHT_FIELDS = frozenset({"state", "brightness", "color", "color_mode", "transition"})
_ALERT_FIELDS = frozenset({"variant", "color", "duration"})


class LightCommand(NamedTuple):
    # None keeps the current colour or brightness.
    on: bool
    colour: Optional[Tuple[int, int, int]] = None
    brightness: Optional[int] = None


class AlertCommand(NamedTuple):
    variant: str  # as EventProvider names it: "ha-flash", "ha-pulse" or "ha-sweep"
    colour: Tuple[int, int, int]
    duration: Optional[float]  # None plays the variant's own length


def _no_constant(_name):
    # Python's json accepts NaN and Infinity; JSON itself does not.
    raise ValueError("not a number")


def _load(payload, limit):
    if isinstance(payload, str):
        try:
            payload = payload.encode("utf-8")
        except UnicodeEncodeError:  # a lone surrogate; the error's own text would quote it
            raise ValueError("value is not text") from None
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError("value is not text")
    if len(payload) > limit:
        raise ValueError(f"longer than {limit} bytes")
    try:
        return json.loads(bytes(payload).decode("utf-8"), parse_constant=_no_constant)
    except ValueError:  # UnicodeDecodeError is a ValueError too
        raise ValueError("not valid JSON") from None


def _byte(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError(f"{what} must be a whole number 0-255")
    return value


def _colour(value):
    if not isinstance(value, dict) or set(value) != {"r", "g", "b"}:
        raise ValueError('color must be {"r", "g", "b"}')
    return tuple(_byte(value[channel], "each colour value") for channel in "rgb")


def _object(payload, limit, fields):
    data = _load(payload, limit)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    if set(data) - fields:
        raise ValueError("unsupported field")
    return data


def parse_light(payload) -> LightCommand:
    data = _object(payload, LIGHT_LIMIT, _LIGHT_FIELDS)
    state = data.get("state")
    if state not in ("ON", "OFF"):
        raise ValueError('state must be "ON" or "OFF"')
    if data.get("color_mode", "rgb") != "rgb":
        raise ValueError("only rgb colours are supported")
    transition = data.get("transition", 0)
    if isinstance(transition, bool) or not isinstance(transition, (int, float)):
        raise ValueError("transition must be a number")
    colour = _colour(data["color"]) if "color" in data else None
    brightness = _byte(data["brightness"], "brightness") if "brightness" in data else None
    if state == "OFF" or brightness == 0:
        return LightCommand(False)
    return LightCommand(True, colour, brightness)


def parse_frame(payload) -> tuple:
    data = _load(payload, FRAME_LIMIT)
    if not isinstance(data, list) or len(data) != LED_COUNT:
        raise ValueError(f"expected a list of {LED_COUNT} [r, g, b] pixels")
    frame = []
    for pixel in data:
        if not isinstance(pixel, list) or len(pixel) != 3:
            raise ValueError("each pixel must be [r, g, b]")
        frame.append(tuple(_byte(channel, "each colour value") for channel in pixel))
    return tuple(frame)


def parse_alert(payload) -> AlertCommand:
    data = _object(payload, ALERT_LIMIT, _ALERT_FIELDS)
    variant = data.get("variant")
    if not isinstance(variant, str) or variant not in ALERT_VARIANTS:
        raise ValueError("variant must be flash, pulse or sweep")
    colour = _colour(data["color"]) if "color" in data else WHITE
    duration = None
    if "duration" in data:
        value = data["duration"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not HA_ALERT_MIN_S <= value <= HA_ALERT_MAX_S:
            raise ValueError(f"duration must be {HA_ALERT_MIN_S}-{HA_ALERT_MAX_S} seconds")
        duration = float(value)
    return AlertCommand(f"ha-{variant}", colour, duration)


def light_state(light) -> dict:
    """Return Home Assistant's JSON light state for HomeAssistantProvider.light().

    Frames are left out: they can arrive four times a second and
    the recorder would store every one.
    """
    red, green, blue = light["colour"]
    return {"state": "ON" if light["on"] else "OFF", "brightness": light["brightness"],
            "color_mode": "rgb", "color": {"r": red, "g": green, "b": blue}}
