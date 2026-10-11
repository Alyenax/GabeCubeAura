"""Short, full-bar Steam event signals and Home Assistant alerts. No hardware I/O lives here."""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame


BLACK = (0, 0, 0)
CYAN = (67, 214, 225)
GOLD = (255, 196, 73)
CHAMPAGNE = (255, 238, 170)
ICE = (215, 240, 250)
RED = (229, 54, 70)
WHITE = (246, 249, 255)
BLUE = (55, 132, 205)
PINK = (245, 98, 166)
LIME = (154, 230, 88)
VIOLET = (170, 122, 243)
DURATIONS = {
    "notification": 1.4,
    "achievement": 2.7,
    "screenshot": 1.25,
    "record-start": 1.35,
    "record-stop": 1.2,
}
VARIANT_DURATIONS = {
    "notification-original": 1.4,
    "notification-return": 2.5,
    "notification-echo": 2.3,
    "notification-ample": 3.6,
    "notification-double": 4.05,
    "notification-beacon": 3.8,
    "achievement-original": 2.7,
    "achievement-confetti": 3.8,
    "achievement-rebound": 3.65,
    "achievement-constellation": 3.45,
    "achievement-twoway": 4.85,
    "achievement-supernova": 4.3,
    "screenshot-original": 1.25,
    "screenshot-double": 2.45,
    "screenshot-scan": 2.25,
    "screenshot-bloom": 3.25,
    "screenshot-ripple": 3.5,
    "record-start": 1.35,
    "record-stop": 1.2,
}
# Home Assistant alerts (kind "ha"), whose variant and colour the automation
# picks. These are the default lengths; an alert may ask for anything from
# half a second to the longest Steam event.
HA_ALERT_DURATIONS = {"ha-flash": 1.2, "ha-pulse": 2.0, "ha-sweep": 1.6}
HA_ALERT_MIN_S = 0.5
HA_ALERT_MAX_S = max(VARIANT_DURATIONS.values())


def _duration(kind, variant):
    original = kind if kind.startswith("record-") else f"{kind}-original"
    return DURATIONS[kind] if variant == original else VARIANT_DURATIONS[variant]


def _blend(a, b, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(round(x * (1 - amount) + y * amount) for x, y in zip(a, b))


def _glow(frame, centre, width, colour, strength):
    for index in range(LED_COUNT):
        weight = max(0.0, 1.0 - abs(index - centre) / width) * strength
        if weight:
            frame[index] = _blend(frame[index], colour, weight)


def _band(frame, centre, radius, colour, strength):
    for index in range(LED_COUNT):
        if abs(index - centre) <= radius:
            frame[index] = _blend(frame[index], colour, strength)


def _ring(frame, radius, width, colour, strength):
    _glow(frame, 8 - radius, width, colour, strength)
    _glow(frame, 8 + radius, width, colour, strength)


def _pulse(t, start, end):
    return math.sin(math.pi * (t - start) / (end - start)) if start < t < end else 0.0


def _confetti(frame, t, intensity):
    palette = (GOLD, ICE, PINK, LIME, VIOLET, CHAMPAGNE)
    beat = int(t * 18)
    for index in range(LED_COUNT):
        score = (index * 11 + beat * 7 + index * beat // 3) % 13
        if score < 5:
            _glow(frame, index, 1.12, palette[(index * 3 + beat) % len(palette)],
                  intensity * (1 if score < 2 else .6))


def _variant_frame(variant, t):
    frame = [BLACK] * LED_COUNT
    if t >= 1:
        return normalize_frame(frame)
    if variant == "notification-return":
        x = 16 * (1 - t / .46) if t < .46 else 0 if t < .56 else 16 * (t - .56) / .44
        _glow(frame, x, 2.3, CYAN, min(1, t * 18, (1 - t) * 18))
        _glow(frame, x + (2 if t < .5 else -2), 2.5, BLUE, .22)
    elif variant == "notification-echo":
        if t < .21:
            _glow(frame, 8, 2.2, CYAN, math.sin(t / .21 * math.pi))
        radius = min(8, max(0, (t - .16) / .62 * 8))
        _ring(frame, radius, 1.8, CYAN, min(1, (1 - t) * 2))
        if t > .45:
            _ring(frame, min(8, (t - .45) / .55 * 8), 1.5, ICE, (1 - t) * .55)
    elif variant == "notification-ample":
        _glow(frame, 8, 3, WHITE, _pulse(t, 0, .22) * .82)
        if .16 <= t < .67:
            radius = 8 * (t - .16) / .51
            _ring(frame, radius, 3.2, CYAN, .99)
            _ring(frame, max(0, radius - 2), 3.1, BLUE, .33)
        if .49 <= t < .98:
            _ring(frame, 8 * (t - .49) / .49, 2.7, ICE, .78 * min(1, (1 - t) * 5))
    elif variant == "notification-double":
        _glow(frame, 8, 2.8, WHITE, _pulse(t, 0, .17) * .85)
        if .11 <= t < .39:
            _ring(frame, 8 * (t - .11) / .28, 2.5, CYAN, .86)
        _glow(frame, 8, 3.5, WHITE, _pulse(t, .45, .61))
        if .51 <= t < .83:
            radius = 8 * (t - .51) / .32
            _ring(frame, radius, 3.4, CYAN, 1)
            _ring(frame, max(0, radius - 2.5), 3.6, BLUE, .4)
        if t >= .83:
            _ring(frame, 8, 3, ICE, min(1, (1 - t) * 6))
    elif variant == "notification-beacon":
        _glow(frame, 8, 3.8, WHITE, _pulse(t, 0, .23))
        if .15 <= t < .57:
            _ring(frame, 8 * (t - .15) / .42, 3, CYAN, 1)
        if .55 <= t < .70:
            _ring(frame, 8, 2.9, ICE, _pulse(t, .55, .70))
        if t >= .68:
            _ring(frame, max(0, 8 * (1 - (t - .68) / .32)), 2.7, CYAN, min(.94, (1 - t) * 4))
    elif variant in {"screenshot-double", "screenshot-scan", "screenshot-bloom", "screenshot-ripple"}:
        close_end = {"screenshot-double": .41, "screenshot-scan": 0,
                     "screenshot-bloom": .31, "screenshot-ripple": .29}[variant]
        if variant == "screenshot-scan":
            if t < .57:
                _glow(frame, 16 * t / .57, 1.5, ICE, .88)
            elif t < .69:
                _band(frame, 8, 8, WHITE, min(1, (t - .57) * 40, (.69 - t) * 35))
            else:
                for index in range(LED_COUNT):
                    _glow(frame, index, .9, BLUE, (1 - t) * .85 * (1 - index / 23))
        else:
            if t < close_end:
                x = 8 * t / close_end
                _glow(frame, x, 1.8, ICE, .94)
                _glow(frame, 16 - x, 1.8, ICE, .94)
            if variant == "screenshot-double":
                if .41 <= t < .54:
                    _band(frame, 8, 2, WHITE, min(1, (t - .41) * 30, (.54 - t) * 30))
                if .64 <= t < .83:
                    _band(frame, 8, 5, WHITE, min(1, (t - .64) * 22, (.83 - t) * 14))
            elif variant == "screenshot-bloom":
                _band(frame, 8, 2, WHITE, _pulse(t, .33, .42))
                if .39 <= t < .62:
                    radius = 2 + 3 * (t - .39) / .23
                    _ring(frame, radius, 2.1, ICE, (1 - (t - .39) / .23) * .8)
                _band(frame, 8, 5, WHITE, _pulse(t, .63, .73))
                if .70 <= t < .99:
                    radius = 5 + 3 * (t - .70) / .29
                    _ring(frame, radius, 2.7, ICE, (1 - (t - .70) / .29) * .86)
            else:
                _band(frame, 8, 2, WHITE, _pulse(t, .30, .39))
                if .37 <= t < .59:
                    _ring(frame, 2 + 5 * (t - .37) / .22, 1.7, ICE, .84)
                _band(frame, 8, 5, WHITE, _pulse(t, .60, .70))
                if .68 <= t < .83:
                    _ring(frame, 5 + 3 * (t - .68) / .15, 2, ICE, .92)
                if t >= .83:
                    _ring(frame, 8 - 4 * (t - .83) / .17, 1.9, BLUE, (1 - t) * 4)
    elif variant in {"achievement-confetti", "achievement-rebound"}:
        if variant == "achievement-confetti":
            if t < .19:
                _glow(frame, 8, 2.8, GOLD, .5 + .5 * math.sin(t / .19 * math.pi * 3) ** 2)
            elif t < .51:
                radius = 8 * (t - .19) / .32
                _ring(frame, radius, 2.2, CHAMPAGNE, .97)
                _band(frame, 8, radius, GOLD, .22)
            elif t < .70:
                _ring(frame, 8 * (1 - (t - .51) / .19), 2.2, GOLD, 1)
            else:
                _glow(frame, 8, 3.4, WHITE, max(0, 1 - (t - .70) / .13))
                _confetti(frame, t, min(1, (t - .70) * 11, (1 - t) * 8))
        else:
            if t < .18:
                _glow(frame, 8, 2.6, GOLD, .6 + .4 * math.sin(t / .18 * math.pi * 2) ** 2)
            elif t < .45:
                _ring(frame, 8 * (t - .18) / .27, 2.3, GOLD, 1)
            elif t < .72:
                radius = 8 * (1 - (t - .45) / .27)
                _glow(frame, 8 - radius, 2.6, PINK, .9)
                _glow(frame, 8 + radius, 2.6, ICE, .9)
                _glow(frame, 8 - radius - 2, 2.3, GOLD, .35)
                _glow(frame, 8 + radius + 2, 2.3, GOLD, .35)
            else:
                _glow(frame, 8, 4.5, WHITE, max(0, 1 - (t - .72) * 8))
                _confetti(frame, t + .18, min(1, (1 - t) * 8))
    elif variant in {"achievement-constellation", "achievement-twoway", "achievement-supernova"}:
        stars = (1, 5, 11, 15, 8, 3, 13)
        if variant == "achievement-constellation":
            if t < .38:
                for j, x in enumerate(stars[:math.ceil(t / .38 * len(stars))]):
                    _glow(frame, x, 1.25, CHAMPAGNE if j % 2 else GOLD, .85)
            elif t < .68:
                for x in stars:
                    _glow(frame, x, 1, GOLD, .35)
                _glow(frame, 16 * (t - .38) / .30, 3, CHAMPAGNE, 1)
            else:
                _band(frame, 8, 8, GOLD, min(.82, (1 - t) * 2.5))
                for x in stars:
                    _glow(frame, x, 1.1, WHITE, min(.8, (1 - t) * 2))
        elif variant == "achievement-twoway":
            count = min(len(stars), math.ceil(t / .21 * len(stars)))
            for j, x in enumerate(stars[:count]):
                _glow(frame, x, 1.2, CHAMPAGNE if j % 2 else GOLD, .83 if t < .21 else .32)
            if .21 <= t < .43:
                _glow(frame, 16 * (t - .21) / .22, 3.2, CHAMPAGNE, 1)
            if .43 <= t < .58:
                _band(frame, 8, min(8, 8 * (t - .43) / .08), GOLD, .67)
                _band(frame, 8, 8, WHITE, _pulse(t, .48, .57) * .93)
            if .58 <= t < .78:
                _glow(frame, 16 * (1 - (t - .58) / .20), 3.2, CHAMPAGNE, 1)
            if t >= .78:
                _band(frame, 8, min(8, 8 * (t - .78) / .10), GOLD, .75 * min(1, (1 - t) * 7))
                _band(frame, 8, 8, WHITE, _pulse(t, .84, .96))
        else:
            if t < .30:
                for j, x in enumerate(stars[:math.ceil(t / .30 * len(stars))]):
                    _glow(frame, x, 1.25, CHAMPAGNE if j % 2 else GOLD, .88)
            elif t < .57:
                gather = (t - .30) / .27
                for x in stars:
                    _glow(frame, x + (8 - x) * gather, 1.55, GOLD, .85)
                _glow(frame, 8, 2.6, WHITE, gather * .9)
            elif t < .74:
                radius = 8 * (t - .57) / .17
                _ring(frame, radius, 3, CHAMPAGNE, 1)
                _glow(frame, 8, 3, WHITE, max(0, 1 - radius / 5))
            else:
                _confetti(frame, t, min(1, (1 - t) * 4))
                for x in stars:
                    _glow(frame, x, 1, GOLD, (1 - t) * .9)
    else:
        raise ValueError(f"unknown event variant: {variant}")
    return normalize_frame(frame)


def ha_alert_frame(variant, colour, t):
    """One frame of a Home Assistant alert at progress t (0-1), drawn only in the alert's colour."""
    colour = tuple(colour)
    frame = [BLACK] * LED_COUNT
    if variant not in HA_ALERT_DURATIONS:
        raise ValueError(f"unknown Home Assistant alert: {variant}")
    if t >= 1:
        return normalize_frame(frame)
    if variant == "ha-flash":
        # Three hard blinks, each lit for the first 60 % of its third.
        if (t * 3) % 1 < .6:
            frame = [colour] * LED_COUNT
    elif variant == "ha-pulse":
        frame = [_blend(BLACK, colour, math.sin(math.pi * t))] * LED_COUNT
    else:  # ha-sweep: one glow from the left end to the right end
        _glow(frame, 16 * t, 2.4, colour, min(1.0, t * 12, (1 - t) * 12))
    return normalize_frame(frame)


def event_frame(kind, elapsed_seconds, variant=None):
    """Render the mockup's 17 logical pixels on a dark, exclusive canvas."""
    if kind not in DURATIONS:
        raise ValueError(f"unknown event: {kind}")
    variant = variant or (kind if kind.startswith("record-") else f"{kind}-original")
    if variant not in VARIANT_DURATIONS or not (variant == kind or variant.startswith(kind + "-")):
        raise ValueError(f"invalid {kind} variant: {variant}")
    t = max(0.0, min(1.0, float(elapsed_seconds) / _duration(kind, variant)))
    if variant not in {"notification-original", "achievement-original", "screenshot-original", "record-start", "record-stop"}:
        return _variant_frame(variant, t)
    frame = [BLACK] * LED_COUNT

    if kind == "notification":
        strength = min(1.0, t * 9, (1 - t) * 9)
        _glow(frame, 16 - 16 * t, 2.15, CYAN, strength)
    elif kind == "achievement":
        if t < .26:
            build = t / .26
            beat = math.sin(build * math.pi * 3) ** 2
            _glow(frame, 8, 1.5 + build * 2.5, GOLD, .4 + .6 * beat)
            _glow(frame, 8, .9, CHAMPAGNE, .3 + .65 * build)
        elif t < .72:
            sweep = (t - .26) / .46
            radius = sweep * 8
            for index in range(LED_COUNT):
                reached = max(0.0, min(1.0, radius - abs(index - 8) + 1))
                if reached:
                    frame[index] = _blend(frame[index], GOLD, reached * .7)
            _glow(frame, 8, 3.4, CHAMPAGNE, max(0.0, 1 - sweep * 2.5))
            _glow(frame, 8 - radius, 2.1, CHAMPAGNE, .96)
            _glow(frame, 8 + radius, 2.1, CHAMPAGNE, .96)
        else:
            finale = (t - .72) / .28
            fade = min(1.0, (1 - finale) * 4)
            frame = [_blend(pixel, GOLD, .82 * fade) for pixel in frame]
            for point in (2, 8, 14):
                _glow(frame, point, 1.3, CHAMPAGNE,
                      (.2 + .14 * math.sin(finale * 13 + point)) * fade)
    elif kind == "screenshot":
        inward = min(1.0, t / .47)
        fade = 1.0 if t < .72 else (1 - t) / .28
        _glow(frame, inward * 8, 1.8, ICE, fade)
        _glow(frame, 16 - inward * 8, 1.8, ICE, fade)
    elif kind == "record-start":
        travel = min(1.0, t / .72)
        fade = max(0.0, 1 - t)
        _glow(frame, travel * 8, 1.7, RED, fade)
        _glow(frame, 16 - travel * 8, 1.7, RED, fade)
        _glow(frame, 8, .74, RED, min(1.0, t / .72) * .96)
    elif kind == "record-stop":
        _glow(frame, 8, .8, RED, 1 - t)
        _glow(frame, 8 - t * 8, 1.6, RED, (1 - t) * .65)
        _glow(frame, 8 + t * 8, 1.6, RED, (1 - t) * .65)
    return normalize_frame(frame)


class EventProvider:
    name = "event"

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        # (kind, variant, colour, seconds): colour is None for Steam events, which draw their own.
        self._queue = deque(maxlen=3)
        self._active = None
        self._active_variant = ""
        self._active_colour = None
        self._active_duration = 0.0
        self._variants = {
            "notification": "notification-original",
            "achievement": "achievement-original",
            "screenshot": "screenshot-original",
        }
        self._started_at = 0.0
        self._recording = False
        self._last_kind = ""
        self._last_trigger_at = 0.0
        self._last_ha_at = float("-inf")

    @property
    def recording(self):
        with self._lock:
            return self._recording

    def set_recording(self, active):
        with self._lock:
            self._recording = bool(active)

    def set_variants(self, values):
        with self._lock:
            for kind in ("notification", "achievement", "screenshot"):
                candidate = values.get(f"event_{kind}_variant", f"{kind}-original")
                if candidate in VARIANT_DURATIONS and candidate.startswith(kind + "-"):
                    self._variants[kind] = candidate

    def trigger(self, kind, *, preview=False, variant=""):
        if kind not in DURATIONS:
            return False
        now = self._clock()
        with self._lock:
            selected = variant or self._variants.get(kind, kind)
            if selected not in VARIANT_DURATIONS or not (
                selected == kind or selected.startswith(kind + "-")
            ):
                return False
            if variant and not preview:
                return False
            if not preview:
                if kind == self._last_kind and now - self._last_trigger_at < .8:
                    return False
                self._last_kind, self._last_trigger_at = kind, now
                if kind == "record-start":
                    self._recording = True
                elif kind == "record-stop":
                    self._recording = False
            else:
                # A deliberate preview should be immediate, not wait behind
                # a real notification or a previous preview.
                self._active = None
                self._active_variant = ""
                self._queue.clear()
            self._start_or_queue((kind, selected, None, _duration(kind, selected)), now)
            return True

    def trigger_home_assistant(self, variant, colour, duration=None):
        """Queue a Home Assistant alert; False if it is not one or repeats within 0.8 s.

        A bad colour or duration raises ValueError with a fixed reason. Steam
        events keep their own repeat rule.
        """
        if variant not in HA_ALERT_DURATIONS:
            return False
        try:
            seconds = HA_ALERT_DURATIONS[variant] if duration is None else float(duration)
            if math.isnan(seconds):
                raise ValueError
            seconds = max(HA_ALERT_MIN_S, min(HA_ALERT_MAX_S, seconds))
            colour = normalize_frame([colour] * LED_COUNT)[0]
        except (ValueError, TypeError, OverflowError):
            raise ValueError("invalid Home Assistant alert colour or duration") from None
        now = self._clock()
        with self._lock:
            if now - self._last_ha_at < .8:
                return False
            self._last_ha_at = now
            self._start_or_queue(("ha", variant, colour, seconds), now)
            return True

    def _start_or_queue(self, item, now):
        if self._active is None:
            self._activate(item, now)
        else:
            self._queue.append(item)

    def _activate(self, item, now):
        self._active, self._active_variant, self._active_colour, self._active_duration = item
        self._started_at = now

    def _deactivate(self):
        self._active, self._active_variant, self._active_colour, self._active_duration = None, "", None, 0.0

    def clear_transients(self):
        with self._lock:
            self._deactivate()
            self._queue.clear()

    def cancel_kinds(self, kinds):
        kinds = set(kinds)
        with self._lock:
            self._queue = deque((item for item in self._queue if item[0] not in kinds), maxlen=3)
            if self._active in kinds:
                if self._queue:
                    self._activate(self._queue.popleft(), self._clock())
                else:
                    self._deactivate()

    def holds(self, kind):
        """Whether an event of this kind is playing or waiting."""
        now = self._clock()
        with self._lock:
            playing = self._active == kind and now - self._started_at < self._active_duration
            return playing or any(item[0] == kind for item in self._queue)

    def clear_recording(self):
        with self._lock:
            self._recording = False

    def output(self):
        now = self._clock()
        with self._lock:
            while self._active is not None and now - self._started_at >= self._active_duration:
                if self._queue:
                    self._activate(self._queue.popleft(), now)
                else:
                    self._deactivate()
            if self._active is None:
                return ProviderOutput(self.name, None, "no active event")
            kind = self._active
            variant = self._active_variant
            colour, duration = self._active_colour, self._active_duration
            elapsed = now - self._started_at
        frame = (ha_alert_frame(variant, colour, elapsed / duration) if kind == "ha"
                 else event_frame(kind, elapsed, variant))
        return ProviderOutput(f"event:{kind}", frame, f"{variant} animation")

    def status(self):
        output = self.output()
        with self._lock:
            return {
                "active": output.frame is not None,
                "kind": self._active or "",
                "variant": self._active_variant,
                "recording": self._recording,
                "queued": len(self._queue),
                "colors": [list(pixel) for pixel in output.frame] if output.frame else [],
            }
