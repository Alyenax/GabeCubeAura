"""When each Home Assistant state area is worth publishing, and how coarse its numbers are.

Home Assistant's recorder stores a row for every state change and every distinct attribute blob, and
keeps them for weeks. By default the bridge therefore sends what automations and control need, not a
second-by-second stream: deadbands and slow cadences for the chatty areas, on top of "only when the
payload changed". Identical payloads are never resent, so a quiet machine costs nothing.

Turbo mode (an MQTT setting) turns all of that off: every area publishes whenever it changes, at most
once a second, with countdown and session minutes to 0.1.

The policy keeps no clock of its own: the bridge passes its injected clock's "now" in, so tests drive
it exactly. A full republish (connect, Home Assistant birth) calls reset(), which makes every area due.
"""

from __future__ import annotations

import math

# Every area, Turbo or not: on change, at most once a second (the bridge's snapshot cadence).
BASE_INTERVAL_S = 1.0
# Slow areas in the default mode. A thermal-protection flip, a countdown starting or ending, and a game
# starting or stopping are news for automations and bypass these.
AREA_INTERVAL_S = {"performance": 30.0, "countdown": 60.0, "status": 60.0}
# Performance only publishes once a reading has moved this far from the last value sent.
LOAD_DEADBAND = 5          # percentage points (cpu_load, gpu_load)
TEMPERATURE_DEADBAND = 2.0  # °C (cpu_temperature, gpu_temperature)
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
    return now != before  # a reading appearing or vanishing (None) is always worth sending


def _whole(value, rounding):
    return int(rounding(value)) if _is_number(value) else value


class PublishingPolicy:
    def __init__(self):
        self._last = {}  # area -> (text, payload, published at)

    def reset(self):
        """Forget what was sent: the next offer of every area is due (full republish, new connection)."""
        self._last.clear()

    def shape(self, area, payload, turbo) -> dict:
        """The payload as it should be published: whole minutes by default, as given in Turbo mode."""
        if turbo or not isinstance(payload, dict):
            return payload
        if area == "countdown":
            # Remaining rounds up so a running countdown never shows 0 before it ends.
            return {**payload,
                    "remaining_minutes": _whole(payload.get("remaining_minutes"), math.ceil),
                    "total_minutes": _whole(payload.get("total_minutes"), lambda v: math.floor(v + 0.5))}
        if area == "game":
            return {**payload, "session_minutes": _whole(
                payload.get("session_minutes"),
                lambda v: (v // SESSION_STEP_MINUTES) * SESSION_STEP_MINUTES)}
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
        if elapsed < AREA_INTERVAL_S.get(area, BASE_INTERVAL_S):
            return False
        if area == "performance":
            return self._performance_moved(payload, last_payload)
        return True

    def sent(self, area) -> bool:
        """Whether this area was published since the last reset()."""
        return area in self._last

    def published(self, area, payload, text, now):
        """Record a successful publish; deadbands and intervals are measured from here."""
        self._last[area] = (text, payload, now)

    @staticmethod
    def _performance_moved(payload, last) -> bool:
        if not isinstance(payload, dict) or not isinstance(last, dict):
            return True
        return any(_moved(payload.get(key), last.get(key), LOAD_DEADBAND)
                   for key in ("cpu_load", "gpu_load")) or any(
            _moved(payload.get(key), last.get(key), TEMPERATURE_DEADBAND)
            for key in ("cpu_temperature", "gpu_temperature"))
