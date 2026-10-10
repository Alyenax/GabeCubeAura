"""Controller-battery gauges and short, exclusive 17-pixel signals."""

from __future__ import annotations

import math
import threading
import time

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame

BLACK = (0, 0, 0)
CYAN = (67, 214, 225)
GREEN = (124, 224, 174)
AMBER = (255, 198, 110)
RED = (255, 92, 108)
WHITE = (246, 249, 255)

VARIANTS = {
    "connect": ("welcome", "orbit", "handshake"),
    "persistent": ("clean", "tip", "horizon"),
    "low": ("beacon", "drain", "heartbeat"),
    "charging": ("current", "breath", "spark"),
    "duo": ("twin", "focus", "double-welcome"),
}
DURATIONS = {"connect": 3.2, "low": 3.2, "charging": 2.8, "persistent": 3.0, "duo": 6.0}


def effective_controller_colour_mode(values=None, controller_count=1):
    """Resolve the colour meaning without mutating saved settings."""
    values = values or {}
    if values.get("controller_colour_preset", "automatic") == "automatic":
        return "players" if max(1, int(controller_count)) >= 2 else "battery"
    mode = values.get("controller_colour_mode", "battery")
    return mode if mode in {"battery", "players"} else "battery"


def _resolved_colour_values(values, controller_count):
    resolved = dict(values or {})
    resolved["controller_colour_mode"] = effective_controller_colour_mode(
        resolved, controller_count
    )
    return resolved


def _colour(percent, values=None, player=0):
    values = values or {}
    if values.get("controller_colour_mode") == "players":
        key = f"controller_player_colour_{max(1, min(4, int(player) + 1))}"
        fallback = ((36, 199, 245), (255, 167, 26), (106, 26, 255), (70, 210, 136))[max(0, min(3, int(player)))]
        return tuple(values.get(key, fallback))
    threshold = values.get("controller_low_threshold", 20)
    key, fallback = ("low", RED) if percent <= threshold else ("medium", AMBER) if percent <= max(35, threshold + 5) else ("normal", GREEN)
    return tuple(values.get(f"controller_colour_{key}", fallback))


def _render_percent(item):
    """Coarse Steam levels drive a gauge, never a displayed exact percent."""
    if item["percent"] is not None:
        return item["percent"]
    if item["level"] is not None:
        return item["level"] * 25
    return None


def _fill(frame, start, end, colour):
    for index in range(max(0, start), min(LED_COUNT - 1, end) + 1):
        frame[index] = colour


def _scaled(colour, factor):
    return tuple(round(channel * factor) for channel in colour)


def _gauge(percent, *, width=17, start=0, from_right=False, colour=None, values=None, player=0):
    frame = [BLACK] * LED_COUNT
    if percent is None:
        return frame
    count = min(width, max(1 if percent > 0 else 0, round(percent * width / 100)))
    chosen = colour or _colour(percent, values, player)
    if from_right:
        _fill(frame, start + width - count, start + width - 1, chosen)
    else:
        _fill(frame, start, start + count - 1, chosen)
    return frame


def controller_zones(count):
    """Fixed player seats. Two and four mirror; three always fills left to right."""
    count = max(1, min(4, int(count)))
    if count == 1:
        return (tuple(range(17)),)
    if count == 2:
        return (tuple(range(0, 8)), tuple(range(16, 8, -1)))
    if count == 3:
        return (tuple(range(0, 5)), tuple(range(6, 11)), tuple(range(12, 17)))
    return (
        tuple(range(0, 4)), tuple(range(7, 3, -1)),
        tuple(range(9, 13)), tuple(range(16, 12, -1)),
    )


def _seat_gauge(frame, zone, percent, *, colour=None, values=None, player=0):
    if percent is None:
        return []
    count = min(len(zone), max(1 if percent > 0 else 0, round(percent * len(zone) / 100)))
    chosen = colour or _colour(percent, values, player)
    lit = list(zone[:count])
    for index in lit:
        frame[index] = chosen
    return lit


def _duo(first, second, variant, elapsed, intro_age=None, values=None):
    frame = _gauge(first, width=8, start=0, values=values, player=0)
    right = _gauge(second, width=8, start=9, from_right=True, values=values, player=1)
    for index in range(9, 17):
        frame[index] = right[index]
    frame[8] = BLACK
    left_lit = [index for index in range(8) if frame[index] != BLACK]
    right_lit = [index for index in range(9, 17) if frame[index] != BLACK]
    left_tip = left_lit[-1] if left_lit else None
    right_tip = right_lit[0] if right_lit else None
    # None means a settled, always-on gauge, not the start of an intro.
    age = float("inf") if intro_age is None else max(0.0, intro_age)
    reveal_end = {"twin": 1.45, "focus": 3.3, "double-welcome": 3.4}[variant]
    if variant == "twin" and age < reveal_end:
        fraction = age / reveal_end
        left_count = round(sum(pixel != BLACK for pixel in frame[:8]) * fraction)
        right_count = round(sum(pixel != BLACK for pixel in frame[9:]) * fraction)
        for index in range(left_count, 8):
            frame[index] = BLACK
        for index in range(9, 17 - right_count):
            frame[index] = BLACK
    elif variant == "focus" and age < reveal_end:
        if age < 1.7 and first is not None:
            index = min(7, int(age / 1.7 * 8))
            if index == left_tip:
                index -= 1
            if index >= 0:
                frame[index] = WHITE
        elif second is not None:
            count = min(8, int((age - 1.7) / 1.6 * 8) + 1)
            index = 17 - count
            if index == right_tip:
                index += 1
            if index < LED_COUNT:
                frame[index] = WHITE
    elif variant == "double-welcome" and age < reveal_end:
        if age < 1.45:
            step = min(7, int(age / 1.45 * 8))
        elif age < 1.9:
            step = 7
        else:
            step = max(0, min(7, int((3.4 - age) / 1.5 * 8)))
        left_index = step - 1 if step == left_tip else step
        right_index = 17 - step if 16 - step == right_tip else 16 - step
        if first is not None and left_index >= 0:
            frame[left_index] = WHITE
        if second is not None and right_index < LED_COUNT:
            frame[right_index] = WHITE
    if age >= reveal_end:
        if left_tip is not None:
            frame[left_tip] = WHITE
        if right_tip is not None:
            frame[right_tip] = WHITE
    frame[8] = BLACK
    return frame


def _multi(percents, variant, elapsed, intro_age=None, values=None):
    """Extend the official multiplayer choreography to three and four seats."""
    percents = list(percents or [])[:4]
    if len(percents) <= 2:
        first = percents[0] if percents else None
        second = percents[1] if len(percents) > 1 else None
        return _duo(first, second, variant, elapsed, intro_age, values)
    zones = controller_zones(len(percents))
    frame = [BLACK] * LED_COUNT
    tips = []
    for player, (zone, percent) in enumerate(zip(zones, percents)):
        lit = _seat_gauge(frame, zone, percent, values=values, player=player)
        tips.append(lit[-1] if lit else None)
    age = float("inf") if intro_age is None else max(0.0, intro_age)
    reveal_end = {"twin": 1.45, "focus": 3.3, "double-welcome": 3.4}[variant]
    if variant == "twin" and age < reveal_end:
        for zone in zones:
            visible = round(sum(frame[index] != BLACK for index in zone) * age / reveal_end)
            for index in zone[visible:]:
                frame[index] = BLACK
    elif variant == "focus" and age < reveal_end:
        slot = reveal_end / len(zones)
        player = min(len(zones) - 1, int(age / slot))
        zone = zones[player]
        local_age = age - player * slot
        position = min(len(zone) - 1, int(local_age / slot * len(zone)))
        if zone[position] == tips[player]:
            position = max(0, position - 1)
        frame[zone[position]] = WHITE
    elif variant == "double-welcome" and age < reveal_end:
        for player, zone in enumerate(zones):
            if age < 1.45:
                step = min(len(zone) - 1, int(age / 1.45 * len(zone)))
            elif age < 1.9:
                step = len(zone) - 1
            else:
                step = max(0, min(len(zone) - 1, int((3.4 - age) / 1.5 * len(zone))))
            if zone[step] == tips[player]:
                step = max(0, step - 1)
            frame[zone[step]] = WHITE
    if age >= reveal_end:
        for tip in tips:
            if tip is not None:
                frame[tip] = WHITE
    return frame


def _tint_multi_charging(frame, controllers, values):
    """Keep each charging seat blue while preserving white motion and endpoints."""
    frame = list(frame)
    brightness = values.get("controller_gauge_brightness", 100) / 100.0
    white = _scaled(WHITE, brightness)
    blue = _scaled(tuple(values.get("controller_colour_charging", CYAN)), brightness)
    zones = controller_zones(len(controllers))
    for player, item in enumerate(controllers[:4]):
        percent = _render_percent(item)
        if item["charging"] is not True or percent is None or percent >= 100:
            continue
        charge_gauge = [BLACK] * LED_COUNT
        lit = _seat_gauge(charge_gauge, zones[player], percent, colour=blue)
        for index in lit:
            if frame[index] not in (BLACK, white):
                frame[index] = blue
    return frame


def _tint_duo_charging(frame, controllers, values):
    """Compatibility alias for existing callers and third-party tests."""
    return _tint_multi_charging(frame, controllers, values)


def _animate_charging_seat(frame, zone, percent, variant, elapsed, values):
    """Animate one controller inside its fixed seat without touching its neighbours."""
    frame = list(frame)
    brightness = values.get("controller_gauge_brightness", 100) / 100.0
    white = _scaled(WHITE, brightness)
    blue = _scaled(tuple(values.get("controller_colour_charging", CYAN)), brightness)
    seat = [BLACK] * LED_COUNT
    charged = _seat_gauge(seat, zone, percent, colour=blue)
    lit = [index for index in charged if frame[index] != BLACK]
    for index in lit:
        if frame[index] != white:
            frame[index] = blue
    if not lit:
        return frame
    phase = max(0.0, float(elapsed)) % 2.55
    if len(lit) == 1:
        white_window = (
            phase < .35 if variant == "current"
            else phase < .45 if variant == "breath"
            else phase % .85 < .18
        )
        frame[lit[0]] = white if white_window else blue
        return frame
    if variant == "current":
        position = min(len(lit) - 1, int(min(1.0, phase / 1.95) * len(lit)))
        frame[lit[position]] = white
    elif variant == "breath":
        centre = phase / 2.55 * (len(lit) + 3) - 2
        for position, index in enumerate(lit):
            if abs(position - centre) < 2.2:
                frame[index] = white
    else:
        for offset in range(3):
            frame[lit[int(((phase / 2.55 + offset / 3) % 1) * len(lit))]] = white
    # A short gauge must still read as charging blue, not become solid white.
    frame[lit[0]] = blue
    return frame


def controller_frame(kind, variant, elapsed, percent=74, second_percent=25, *, intro_age=None,
                     values=None, continuous=False, percents=None, player=0,
                     controller_count=None):
    """Pure renderer. Unknown battery levels never become invented percentages."""
    if kind not in VARIANTS or variant not in VARIANTS[kind]:
        raise ValueError("unknown controller signal variant")
    t = max(0.0, float(elapsed))
    if controller_count is None:
        controller_count = len(percents) if kind == "duo" and percents is not None else (
            2 if kind == "duo" else 1
        )
    values = _resolved_colour_values(values, controller_count)
    cyan = tuple(values.get("controller_colour_charging", CYAN))
    red = tuple(values.get("controller_colour_low", RED))
    brightness = values.get("controller_gauge_brightness", 100) / 100.0

    def finish(pixels):
        return normalize_frame([_scaled(pixel, brightness) for pixel in pixels])

    frame = [BLACK] * LED_COUNT
    if kind == "duo":
        levels = list(percents) if percents is not None else [percent, second_percent]
        return finish(_multi(levels, variant, t, intro_age, values))
    if kind == "persistent":
        frame = _gauge(percent, values=values, player=player)
        if variant == "tip" and any(pixel != BLACK for pixel in frame):
            frame[max(index for index, pixel in enumerate(frame) if pixel != BLACK)] = WHITE
        elif variant == "horizon":
            frame = [_scaled(pixel, .58) for pixel in frame]
        return finish(frame)
    if kind == "charging" and continuous:
        t %= {"current": 2.55, "breath": 3.2, "spark": 2.55}[variant]
    elif t >= DURATIONS[kind]:
        return finish(frame)
    if kind == "connect":
        intro_end = {"welcome": 1.3, "orbit": 2.3, "handshake": 1.65}[variant]
        if t < intro_end:
            if variant == "welcome":
                step = min(7, int(t / 1.3 * 8))
                frame[step] = cyan
                frame[16 - step] = cyan
                if step:
                    frame[step - 1] = _scaled(cyan, .45)
                    frame[17 - step] = _scaled(cyan, .45)
            elif variant == "orbit":
                phase = t / 1.15 if t < 1.15 else 2 - t / 1.15
                index = min(16, max(0, int(phase * 16)))
                frame[index] = WHITE
                if index:
                    frame[index - 1] = cyan
                if index < 16:
                    frame[index + 1] = cyan
            else:
                step = min(8, int(t / 1.65 * 9))
                frame[8 - step] = WHITE
                frame[8 + step] = WHITE
        elif t < 1.75 and variant == "welcome":
            _fill(frame, 6, 10, WHITE)
        else:
            frame = _gauge(percent, values=values, player=player)
            if percent is not None and percent > 0:
                frame[max(index for index, pixel in enumerate(frame) if pixel != BLACK)] = WHITE
    elif kind == "low":
        if variant == "beacon":
            if t < 1.25:
                count = max(round((1 - t / 1.25) * 17), round((percent or 0) / 100 * 17))
                _fill(frame, 0, count - 1, tuple(values.get("controller_colour_medium", AMBER)))
            else:
                frame = _gauge(percent, colour=red)
                if (1.5 < t < 1.73 or 1.91 < t < 2.15) and any(pixel != BLACK for pixel in frame):
                    frame[max(index for index, pixel in enumerate(frame) if pixel != BLACK)] = WHITE
        elif variant == "drain":
            frame = _gauge(percent, colour=red)
            if t < 2.4:
                phase = t / 1.2 if t < 1.2 else 2 - t / 1.2
                frame[min(16, max(0, int(phase * 16)))] = WHITE
        else:
            beat = t < 2.2 and (t % .92 < .24 or .38 < t % .92 < .58)
            frame = _gauge(percent, colour=WHITE if beat else _scaled(red, .7))
            if beat:
                frame[8] = red
    elif kind == "charging":
        frame = _gauge(percent, colour=cyan)
        lit = [index for index, pixel in enumerate(frame) if pixel != BLACK]
        if lit and variant == "current":
            if t < 1.95:
                index = lit[min(len(lit) - 1, int(t / 1.95 * len(lit)))]
                frame[index] = WHITE
                if index:
                    frame[index - 1] = _scaled(WHITE, .65)
            else:
                frame[lit[-1]] = WHITE
        elif lit and variant == "breath":
            centre = t / 2.75 * (len(lit) + 3) - 2
            for index in lit:
                distance = abs(index - centre)
                if distance < 2.8:
                    frame[index] = WHITE if distance < 1 else _scaled(WHITE, .7)
            frame[lit[-1]] = WHITE
        elif lit and variant == "spark":
            for offset in range(3):
                index = lit[int(((t / 2.15 + offset / 3) % 1) * len(lit))]
                frame[index] = WHITE if offset == 0 else _scaled(WHITE, .68)
            frame[lit[-1]] = WHITE
    return finish(frame)


def _normalise_controllers(raw):
    result = {}
    if not isinstance(raw, list):
        return result
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id", ""))[:96]
        if not identifier or identifier in result:
            continue
        percent = item.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not math.isfinite(percent) or not 0 <= percent <= 100:
            percent = None
        else:
            percent = round(percent)
        charging = item.get("charging")
        level = item.get("level")
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 4:
            level = None
        result[identifier] = {
            "id": identifier,
            "name": str(item.get("name") or "Controller")[:64],
            "percent": percent,
            "level": level,
            "charging": charging if isinstance(charging, bool) else None,
        }
    return result


class ControllerProvider:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._controllers = {}
        self._initialized = False
        self._active = None
        self._started_at = 0.0
        self._roster_changed_at = 0.0
        self._warned = {}
        self._charging_since = {}
        self._charge_completed_at = {}
        self._last_update_at = None
        self._style = {}
        self._preview_count = 1
        self._preview_target = 0

    def clear_transients(self):
        with self._lock:
            self._active = None

    def cancel_alerts_except_low(self):
        """Drop a playing connect, charging or preview alert; a low-battery one stays."""
        with self._lock:
            if self._active and self._active[0] != "low":
                self._active = None

    def clear(self):
        with self._lock:
            self._controllers.clear()
            self._warned.clear()
            self._charging_since.clear()
            self._charge_completed_at.clear()
            self._active = None
            self._initialized = False
            self._last_update_at = None

    def _expire(self):
        # The frontend renews this lease on every successful two-second query.
        # A stopped collector must not leave an old battery gauge on forever.
        if self._last_update_at is not None and self._clock() - self._last_update_at > 10:
            self._controllers.clear()
            self._warned.clear()
            self._charging_since.clear()
            self._charge_completed_at.clear()
            self._initialized = False
            self._last_update_at = None
            if self._active and not self._active[3]:
                self._active = None

    def _start(self, kind, controller, values, preview=False, variant=""):
        if values.get("mode") == "disabled":
            return False
        if not preview and not values.get("controller_alerts_enabled", False):
            return False
        selected = variant or values.get(f"controller_{kind}_variant", VARIANTS[kind][0])
        if selected not in VARIANTS[kind]:
            return False
        self._active = (kind, selected, controller, preview)
        self._started_at = self._clock()
        return True

    def update(self, raw, values, game_running=False):
        fresh = _normalise_controllers(raw)
        started_kind = None
        with self._lock:
            self._expire()
            self._style = dict(values)
            self._last_update_at = self._clock()
            previous = self._controllers
            # Steam may reorder its list between polls; do not swap player sides.
            fresh = {**{identifier: fresh[identifier] for identifier in previous if identifier in fresh},
                     **{identifier: item for identifier, item in fresh.items() if identifier not in previous}}
            self._controllers = fresh
            if set(previous) != set(fresh):
                self._roster_changed_at = self._clock()
            for identifier in set(previous) - set(fresh):
                self._warned.pop(identifier, None)
                self._charging_since.pop(identifier, None)
                self._charge_completed_at.pop(identifier, None)
                if self._active and self._active[2].get("id") == identifier and not self._active[3]:
                    self._active = None
            initial = not self._initialized
            self._initialized = True
            for identifier, item in fresh.items():
                before = previous.get(identifier)
                if (before and before["charging"] is True and _render_percent(before) is not None
                        and _render_percent(before) < 100 and _render_percent(item) == 100):
                    self._charge_completed_at[identifier] = self._clock()
                if (self._active and not self._active[3] and self._active[0] == "charging"
                        and self._active[2]["id"] == identifier
                        and (item["charging"] is not True or _render_percent(item) is None
                             or _render_percent(item) == 100)):
                    self._active = None
                if item["charging"] is True and _render_percent(item) is not None and _render_percent(item) < 100:
                    self._charging_since.setdefault(identifier, self._clock())
                else:
                    self._charging_since.pop(identifier, None)
            policy = values.get("controller_alert_context", "both")
            allowed = policy == "both" or policy == ("game" if game_running else "home")
            if not allowed:
                return None
            threshold = values.get("controller_low_threshold", 20)
            for identifier, item in fresh.items():
                before = previous.get(identifier)
                percent = item["percent"]
                level = item["level"] if percent is None else None
                if item["charging"] is True or (percent is not None and percent >= threshold + 5):
                    self._warned.pop(identifier, None)
                elif level is not None and level >= 2:
                    self._warned.pop(identifier, None)
                low = ((percent is not None and percent <= threshold) or level == 1) and item["charging"] is not True
                if low and identifier not in self._warned and values.get("controller_low_enabled", True):
                    if self._start("low", item, values):
                        self._warned[identifier] = True
                        started_kind = "low"
                elif not initial and before is None and started_kind != "low" and values.get("controller_connect_enabled", True):
                    if len(fresh) >= 2 and len(previous) == len(fresh) - 1:
                        if self._start("duo", next(iter(fresh.values())), values):
                            started_kind = "duo"
                    else:
                        if self._start("connect", item, values):
                            started_kind = "connect"
                elif (before is not None and started_kind != "low" and before["charging"] is not True
                      and item["charging"] is True and _render_percent(item) is not None
                      and values.get("controller_charging_enabled", True)):
                    if self._start("charging", item, values):
                        started_kind = "charging"
        return started_kind

    def preview(self, kind, values, variant="", count=1, target=0):
        if kind not in VARIANTS:
            return False
        with self._lock:
            self._style = dict(values)
            try:
                count = int(count)
            except (TypeError, ValueError, OverflowError):
                count = 2 if kind == "duo" else 1
            try:
                target = int(target)
            except (TypeError, ValueError, OverflowError):
                target = 0
            self._preview_count = max(2 if kind == "duo" else 1, min(4, count))
            self._preview_target = max(0, min(self._preview_count - 1, target))
            samples = (96, 41, 73, 28)
            percent = 14 if kind == "low" else 38 if kind == "charging" else samples[self._preview_target]
            sample = {"id": "preview", "name": f"Controller {self._preview_target + 1}",
                      "percent": percent, "level": None, "charging": kind == "charging"}
            return self._start(kind, sample, values, preview=True, variant=variant)

    def cancel_for_settings(self, values, game_running=False):
        with self._lock:
            self._style = dict(values)
            if self._active and not self._active[3]:
                kind = self._active[0]
                policy = values["controller_alert_context"]
                context_allowed = policy == "both" or policy == ("game" if game_running else "home")
                if (not values["controller_alerts_enabled"] or values["mode"] == "disabled"
                        or not context_allowed or not values.get(f"controller_{kind}_enabled", True)):
                    self._active = None

    def event_output(self):
        now = self._clock()
        with self._lock:
            self._expire()
            if self._active is None:
                return ProviderOutput("controller", None, "no controller alert")
            kind, variant, item, preview = self._active
            if not preview:
                item = self._controllers.get(item["id"], item)
                if kind == "charging" and (item["charging"] is not True or _render_percent(item) is None
                                           or _render_percent(item) == 100):
                    self._active = None
                    return ProviderOutput("controller", None, "charging ended")
            elapsed = now - self._started_at
            if elapsed >= DURATIONS[kind]:
                self._active = None
                return ProviderOutput("controller", None, "controller alert ended")
            current = list(self._controllers.values())[:4]
            player = next((index for index, controller in enumerate(current)
                           if controller["id"] == item["id"]), self._preview_target if preview else 0)
            levels = None
            if kind == "duo":
                levels = ([96, 41, 73, 28][:self._preview_count] if preview
                          else [_render_percent(controller) for controller in current])
            seat_count = self._preview_count if preview else len(current)
            if kind == "charging" and seat_count > 1:
                samples = ([96, 41, 73, 28][:seat_count] if preview
                           else [_render_percent(controller) for controller in current])
                samples[player] = _render_percent(item)
                frame = controller_frame(
                    "duo", self._style.get("controller_duo_variant", "twin"), elapsed,
                    intro_age=None, values=self._style, percents=samples,
                    controller_count=seat_count,
                )
                frame = normalize_frame(_animate_charging_seat(
                    frame, controller_zones(seat_count)[player],
                    _render_percent(item), variant, elapsed, self._style,
                ))
            else:
                frame = controller_frame(
                    kind, variant, elapsed, _render_percent(item),
                    intro_age=elapsed if kind == "duo" else None,
                    values=self._style, percents=levels, player=player,
                    controller_count=seat_count,
                )
            if kind == "duo" and not preview:
                frame = normalize_frame(_tint_multi_charging(frame, current, self._style))
            return ProviderOutput(f"controller:{kind}", frame, f"{variant} animation")

    def persistent_output(self, values, game_running=False):
        policy = values.get("controller_battery_display", "off")
        charging_policy = values.get("controller_charging_display", "off")
        gauge_allowed = (policy == "everywhere" or (policy == "home" and not game_running)
                         or (policy == "game" and game_running))
        charging_allowed = charging_policy == "everywhere" or (charging_policy == "home" and not game_running)
        if not gauge_allowed and not charging_allowed:
            return ProviderOutput("controller-battery", None, "battery display disabled here")
        with self._lock:
            self._expire()
            current = list(self._controllers.values())[:4]
            known = [item for item in current if _render_percent(item) is not None]
            if not known:
                return ProviderOutput("controller-battery", None, "battery level unavailable")
            now = self._clock()
            colour_values = _resolved_colour_values(values, len(current))
            completed = next((item for item in known if 0 <= now - self._charge_completed_at.get(item["id"], -100) < .9), None)
            if charging_allowed and completed is not None:
                progress = (now - self._charge_completed_at[completed["id"]]) / .9
                player = current.index(completed)
                if len(current) >= 2:
                    frame = list(controller_frame(
                        "duo", values.get("controller_duo_variant", "twin"), now,
                        intro_age=None, values=values,
                        percents=[_render_percent(item) for item in current],
                    ))
                    zone = controller_zones(len(current))[player]
                else:
                    frame = list(controller_frame("persistent", "clean", now, 100,
                                                  values=values, player=player))
                    zone = controller_zones(1)[0]
                spread = min(8, int(progress * 9))
                cue = _scaled(WHITE if progress < .5 else _colour(100, colour_values, player),
                              values.get("controller_gauge_brightness", 100) / 100.0)
                centre = (len(zone) - 1) / 2
                radius = min(len(zone), max(1, round(spread * len(zone) / 9)))
                for position, index in enumerate(zone):
                    if abs(position - centre) <= radius:
                        frame[index] = cue
                return ProviderOutput("controller-charge-complete", normalize_frame(frame), "controller fully charged")
            charging = next((item for item in known if item["charging"] is True and _render_percent(item) < 100), None)
            if charging_allowed and charging is not None:
                variant = values.get("controller_charging_variant", "current")
                elapsed = now - self._charging_since.get(charging["id"], now)
                if len(current) >= 2:
                    frame = list(controller_frame(
                        "duo", values.get("controller_duo_variant", "twin"), now,
                        intro_age=now - self._roster_changed_at, values=values,
                        percents=[_render_percent(item) for item in current],
                    ))
                    frame = _tint_multi_charging(frame, current, values)
                    intro_age = now - self._roster_changed_at
                    reveal_end = {"twin": 1.45, "focus": 3.3, "double-welcome": 3.4}[
                        values.get("controller_duo_variant", "twin")]
                    zones = controller_zones(len(current))
                    for player, item in enumerate(current):
                        if (item["charging"] is not True or _render_percent(item) is None
                                or _render_percent(item) >= 100):
                            continue
                        if intro_age >= reveal_end:
                            frame = _animate_charging_seat(
                                frame, zones[player], _render_percent(item), variant,
                                now - self._charging_since.get(item["id"], now), values,
                            )
                else:
                    frame = controller_frame("charging", variant, elapsed, _render_percent(charging),
                                             values=values, continuous=True, player=0)
                return ProviderOutput("controller-charging", normalize_frame(frame), "controller charging continuously")
            if not gauge_allowed:
                return ProviderOutput("controller-battery", None, "permanent battery gauge disabled here")
            if len(current) >= 2:
                variant = values.get("controller_duo_variant", "twin")
                frame = controller_frame(
                    "duo", variant, now, intro_age=now - self._roster_changed_at,
                    values=values, percents=[_render_percent(item) for item in current],
                )
            else:
                variant = values.get("controller_persistent_variant", "clean")
                frame = controller_frame("persistent", variant, now, _render_percent(current[0]),
                                         values=values, player=0)
            return ProviderOutput("controller-battery", frame, "controller battery gauge")

    def roster(self):
        """Copies of the current controllers (id, name, percent, level, charging)."""
        with self._lock:
            return [dict(item) for item in self._controllers.values()]

    def status(self, values, game_running=False):
        with self._lock:
            self._expire()
            current = list(self._controllers.values())
            active = self._active
        transient = self.event_output()
        persistent = self.persistent_output(values, game_running)
        display = transient if transient.frame is not None else persistent
        return {
            "controllers": current,
            "active": transient.frame is not None,
            "kind": active[0] if active and transient.frame is not None else "",
            "variant": active[1] if active and transient.frame is not None else "",
            "colors": [list(pixel) for pixel in display.frame] if display.frame else [],
            "persistent_available": persistent.frame is not None,
            "charging_active": persistent.provider == "controller-charging" and persistent.frame is not None,
        }
