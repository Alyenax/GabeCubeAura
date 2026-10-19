"""When each Home Assistant state area is worth publishing, and how coarse its numbers are.

Home Assistant's recorder stores a row for every state change and every
distinct set of attributes, and keeps them for weeks. By default the bridge
sends what automations need rather than a stream: the chatty areas get
deadbands and slow cadences on top of "only when it changed". A quiet machine
sends nothing.

Turbo mode turns all of that off. Every area then publishes whenever it
changes, at most once a second, with minutes to one decimal place.

The bridge passes its own clock's "now" in, so tests can drive the policy.
reset() makes every area due, for a full republish.
"""

from __future__ import annotations

import math

BASE_INTERVAL_S = 1.0
# The slow areas outside Turbo mode. Thermal protection tripping, a countdown
# starting or ending and a game starting or stopping are news and go at once.
AREA_INTERVAL_S = {"performance": 30.0, "countdown": 60.0, "status": 60.0}
# How far a performance reading must move from the last value sent:
# percentage points for load, degrees for temperature.
LOAD_DEADBAND = 5
TEMPERATURE_DEADBAND = 2.0
DEADBANDS = {"cpu_load": LOAD_DEADBAND, "gpu_load": LOAD_DEADBAND,
             "cpu_temperature": TEMPERATURE_DEADBAND, "gpu_temperature": TEMPERATURE_DEADBAND}
SESSION_STEP_MINUTES = 5
IMMEDIATE_KEYS = {
    "performance": ("thermal_protection",),
    "countdown": ("active", "source", "label"),  # a new label means a new countdown
    "game": ("running", "appid", "title"),
}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _moved(now, before, deadband) -> bool:
    if _is_number(now) and _is_number(before):
        return abs(now - before) >= deadband
    return now != before


def _whole(value, rounding):
    return int(rounding(value)) if _is_number(value) else value


class PublishingPolicy:
    def __init__(self):
        self._last = {}  # area -> (text, payload, published at)

    def reset(self):
        """Forget what was sent, so every area is due again."""
        self._last.clear()

    def shape(self, area, payload, turbo) -> dict:
        """Return the payload as published: whole minutes by default, as given in Turbo mode."""
        if turbo or not isinstance(payload, dict):
            return payload
        if area == "countdown":
            # Rounded up, so a running countdown never shows 0 before it ends.
            return {**payload,
                    "remaining_minutes": _whole(payload.get("remaining_minutes"), math.ceil),
                    "total_minutes": _whole(payload.get("total_minutes"), lambda v: math.floor(v + 0.5))}
        if area == "game":
            return {**payload, "session_minutes": _whole(
                payload.get("session_minutes"),
                lambda v: (v // SESSION_STEP_MINUTES) * SESSION_STEP_MINUTES)}
        if area == "performance" and area in self._last:
            # A reading inside its deadband keeps the value last sent, so one
            # moving sensor does not record a row for the other three.
            last = self._last[area][1]
            return {**payload, **{key: last.get(key) for key, deadband in DEADBANDS.items()
                                  if not _moved(payload.get(key), last.get(key), deadband)}}
        return payload

    def due(self, area, payload, text, now, turbo) -> bool:
        """Whether this (already shaped) payload should be published now."""
        last = self._last.get(area)
        if last is None:
            return True
        last_text, last_payload, last_at = last
        if text == last_text:
            return False
        elapsed = now - last_at
        if turbo:
            return elapsed >= BASE_INTERVAL_S
        if isinstance(payload, dict) and isinstance(last_payload, dict) and any(
                payload.get(key) != last_payload.get(key) for key in IMMEDIATE_KEYS.get(area, ())):
            return True
        # Performance readings that stayed inside their deadband were shaped
        # back to the last value sent, so any difference left is a real move.
        return elapsed >= AREA_INTERVAL_S.get(area, BASE_INTERVAL_S)

    def sent(self, area) -> bool:
        """Whether this area was published since the last reset()."""
        return area in self._last

    def published(self, area, payload, text, now):
        """Record a successful publish; deadbands and intervals count from it."""
        self._last[area] = (text, payload, now)
