"""Temporary playtime countdown signals for the 17-pixel light bar."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from signalbar.models import LED_COUNT, ProviderOutput, normalize_frame
from .timer_end_action import TimerEndAction, VALID_ACTIONS


COUNTDOWN_COLOURS = {
    "cyan": (25, 195, 235),
    "green": (45, 205, 105),
    "amber": (245, 165, 35),
    "violet": (165, 85, 235),
    "white": (225, 235, 245),
}

COUNTDOWN_WARNING_COLOUR = COUNTDOWN_COLOURS["amber"]
COUNTDOWN_URGENT_COLOUR = (255, 0, 0)
COUNTDOWN_ALERT_COLOUR = (255, 255, 255)
COUNTDOWN_FINAL_ALERT_SECONDS = 8.0
COUNTDOWN_DARK_EDGE_COMPENSATION = 3


def _scaled(colour, amount):
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(int(round(channel * amount)) for channel in colour)


def _countdown_lit_count(remaining_seconds, total_seconds, dark_edge_compensation):
    remaining = max(0.0, float(remaining_seconds))
    total = max(1.0, float(total_seconds))
    fraction = max(0.0, min(1.0, remaining / total))
    nominal_lit = min(LED_COUNT, int(math.ceil(LED_COUNT * fraction)))
    if remaining <= 0:
        return 0
    if nominal_lit >= LED_COUNT:
        return LED_COUNT
    compensation = max(0, min(LED_COUNT - 1, int(dark_edge_compensation)))
    return max(1, nominal_lit - compensation)


def countdown_frame(
    remaining_seconds,
    total_seconds,
    colour="cyan",
    elapsed_seconds=0.0,
    dark_edge_compensation=COUNTDOWN_DARK_EDGE_COMPENSATION,
):
    """Render a shrinking bar with a right-to-left travelling highlight.

    Lit pixels always occupy the logical left side, so the disappearing edge
    moves from right to left. A brighter comet also travels in that direction.
    The selected colour changes to amber below 15 minutes, then pure red below
    five minutes while the travelling highlight remains the only animation.
    """
    remaining = max(0.0, float(remaining_seconds))
    total = max(1.0, float(total_seconds))
    # The Steam Machine's diffuser makes nearby dark pixels look lit. The
    # configurable physical-only compensation is skipped for a completely full
    # bar and always leaves one visible pixel while time remains.
    lit = _countdown_lit_count(remaining, total, dark_edge_compensation)
    base = COUNTDOWN_COLOURS.get(str(colour), COUNTDOWN_COLOURS["cyan"])
    if 0 < remaining <= 300.0:
        base = COUNTDOWN_URGENT_COLOUR
    elif remaining <= 900.0:
        base = COUNTDOWN_WARNING_COLOUR
    elapsed = max(0.0, float(elapsed_seconds))

    pixels = [(0, 0, 0)] * LED_COUNT
    for index in range(lit):
        pixels[index] = _scaled(base, 0.34)

    if lit:
        # One pixel every 0.20 s. The reset happens at the current right edge,
        # making both the fill boundary and the animation read right-to-left.
        head = lit - 1 - (int(elapsed / 0.20) % lit)
        pixels[head] = base
        for distance, strength in ((1, 0.72), (2, 0.52)):
            tail = head + distance
            if tail < lit:
                pixels[tail] = _scaled(base, strength)

    return normalize_frame(pixels)


def countdown_final_alert_frame(elapsed_seconds):
    """Repeat three short full-white flashes during the final eight seconds."""
    elapsed = max(0.0, float(elapsed_seconds))
    phase = elapsed % 1.8
    lit = any(start <= phase < start + 0.15 for start in (0.0, 0.30, 0.60))
    colour = COUNTDOWN_ALERT_COLOUR if lit else (0, 0, 0)
    return normalize_frame([colour] * LED_COUNT)


@dataclass
class _Countdown:
    source: str
    label: str
    total_seconds: float
    ends_at: float
    started_at: float
    power_generation: int = 0


class CountdownProvider:
    """Own independent parental, free and preview countdown deadlines."""

    name = "countdown"

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._states = {}
        self._faceplate_completed = None
        self.end_action = TimerEndAction(clock)

    def start(
        self, source, seconds, total_seconds=None, label="", end_action='none',
    ):
        source = str(source or "free")
        if not isinstance(end_action, str) or end_action not in VALID_ACTIONS or source != 'free' and end_action != 'none':
            raise ValueError('Only a personal timer can request a power action')
        seconds = max(0.0, float(seconds))
        if seconds <= 0:
            self.stop(source)
            return
        now = self._clock()
        with self._lock:
            self._faceplate_completed = None
            previous = self._states.get(source)
            total = max(seconds, float(total_seconds or 0.0))
            if previous is not None:
                total = max(total, previous.total_seconds)
                started_at = previous.started_at
            else:
                started_at = now
            self._states[source] = _Countdown(
                source=source,
                label=str(label or source.title()),
                total_seconds=max(1.0, total),
                ends_at=now + seconds,
                started_at=started_at,
                power_generation=self.end_action.arm(end_action, now+seconds) if source == 'free' else 0,
            )

    def stop(self, source=None):
        with self._lock:
            if source is None or source == 'free':
                self.end_action.cancel('timer-stopped')
            if (self._faceplate_completed is not None
                    and (source is None or self._faceplate_completed.source == str(source))):
                self._faceplate_completed = None
            if source is None:
                self._states.clear()
            else:
                self._states.pop(str(source), None)

    def personal_status(self):
        """Free timer only, even when a Families deadline currently has priority."""
        _, now = self._current()
        with self._lock:
            state = self._states.get('free')
            if state is None or state.ends_at <= now:
                self._states.pop('free', None)
                return {'active': False, 'remaining_seconds': 0}
            return {'active': True, 'remaining_seconds': math.ceil(state.ends_at-now)}

    def claim_end_action(self):
        self._current()
        return self.end_action.claim()

    def extend_personal(self, seconds):
        _, now = self._current()
        with self._lock:
            state = self._states.get('free')
            seconds = int(seconds)
            if seconds <= 0 or seconds > 14400:
                raise ValueError('Timer extension must be 1..14400 seconds')
            if state is None or state.ends_at <= now:
                self._states.pop('free', None)
                return False
            if state.ends_at-now+seconds > 14400:
                raise RuntimeError('Le timer personnel ne peut pas dépasser quatre heures.')
            state.ends_at += seconds
            state.total_seconds += seconds
            self.end_action.extend(state.power_generation, state.ends_at)
            return True

    def _current(self, allow_parental=True):
        now = self._clock()
        with self._lock:
            # Remember natural expiry separately from LED activity. Cancellation
            # never invents TIME'S UP, and an expired preview cannot mask a timer.
            priority = {"preview": 0, "parental": 1, "free": 2}
            visible = [state for state in self._states.values()
                       if allow_parental or state.source != "parental"]
            previous = min(visible, key=lambda state: (
                priority.get(state.source, 3), state.ends_at,
            )) if visible else None
            if previous is not None and previous.ends_at <= now:
                self._faceplate_completed = previous
            expired = [
                source for source, state in self._states.items()
                if state.ends_at <= now
            ]
            for source in expired:
                if source == 'free':
                    self.end_action.expire(self._states[source].power_generation)
                self._states.pop(source, None)
            candidates = [
                state for state in self._states.values()
                if allow_parental or state.source != "parental"
            ]
            if not candidates:
                return None, now
            # Explicit preview wins briefly. Steam Families is authoritative
            # over a personal timer; neither can be displaced by Artwork or
            # Performance in the arbiter.
            priority = {"preview": 0, "parental": 1, "free": 2}
            state = min(
                candidates,
                key=lambda item: (priority.get(item.source, 3), item.ends_at),
            )
            return state, now

    def faceplate_snapshot(self, allow_parental=True):
        """Bounded semantic snapshot, sharing the existing timer priority/clock.

        Completion is available for 60 seconds to let a slow serial transfer
        finish. The engine displays it eight seconds after the upload ACK.
        """
        state, now = self._current(allow_parental=allow_parental)
        if state is not None:
            return {"active": True, "source": state.source,
                    "remaining_seconds": max(0, state.ends_at - now)}
        with self._lock:
            completed = self._faceplate_completed
            if (completed is not None and 0 <= now - completed.ends_at < 60
                    and (allow_parental or completed.source != "parental")):
                return {"active": False, "source": completed.source,
                        "completion_id": f"{completed.source}:{completed.ends_at:.6f}"}
        return {"active": False}

    @staticmethod
    def _render_total(state, full_bar_seconds):
        # Preview must always demonstrate the full animation. Real timers can
        # instead use a fixed time-to-17-LED scale; values above that scale stay
        # full until they enter the configured window.
        if state.source == "preview" or float(full_bar_seconds or 0.0) <= 0:
            return state.total_seconds
        return max(1.0, float(full_bar_seconds))

    def output(
        self, colour="cyan", allow_parental=True, enabled=True,
        dark_edge_compensation=COUNTDOWN_DARK_EDGE_COMPENSATION,
        full_bar_seconds=0.0,
    ):
        if not enabled:
            return ProviderOutput(self.name, None, "countdown disabled")
        state, now = self._current(allow_parental=allow_parental)
        if state is None:
            return ProviderOutput(self.name, None, "no active countdown")
        remaining = max(0.0, state.ends_at - now)
        render_total = self._render_total(state, full_bar_seconds)
        if remaining <= COUNTDOWN_FINAL_ALERT_SECONDS:
            frame = countdown_final_alert_frame(
                COUNTDOWN_FINAL_ALERT_SECONDS - remaining,
            )
            reason = f"{state.label}: {int(math.ceil(remaining))}s final alert"
        else:
            frame = countdown_frame(
                remaining,
                render_total,
                colour=colour,
                elapsed_seconds=now - state.started_at,
                dark_edge_compensation=dark_edge_compensation,
            )
            reason = f"{state.label}: {int(math.ceil(remaining))}s remaining"
        return ProviderOutput(self.name, frame, reason)

    def status(
        self, colour="cyan", allow_parental=True,
        dark_edge_compensation=COUNTDOWN_DARK_EDGE_COMPENSATION,
        full_bar_seconds=0.0,
    ):
        state, now = self._current(allow_parental=allow_parental)
        if state is None:
            return {
                "active": False,
                "source": "",
                "label": "",
                "remaining_seconds": 0,
                "total_seconds": 0,
                "scale_seconds": 0,
                "alerting": False,
                "logical_lit": 0,
                "physical_lit": 0,
                "colors": [],
            }
        remaining = max(0.0, state.ends_at - now)
        render_total = self._render_total(state, full_bar_seconds)
        alerting = remaining <= COUNTDOWN_FINAL_ALERT_SECONDS
        if alerting:
            frame = countdown_final_alert_frame(
                COUNTDOWN_FINAL_ALERT_SECONDS - remaining,
            )
            logical_lit = sum(pixel != (0, 0, 0) for pixel in frame)
            physical_lit = logical_lit
        else:
            # The Decky preview stays logical. Compensation is a calibration
            # applied only to the frame written to the physical light bar.
            frame = countdown_frame(
                remaining,
                render_total,
                colour=colour,
                elapsed_seconds=now - state.started_at,
                dark_edge_compensation=0,
            )
            logical_lit = _countdown_lit_count(remaining, render_total, 0)
            physical_lit = _countdown_lit_count(
                remaining, render_total, dark_edge_compensation,
            )
        return {
            "active": True,
            "source": state.source,
            "label": state.label,
            "remaining_seconds": int(math.ceil(remaining)),
            "total_seconds": int(math.ceil(state.total_seconds)),
            "scale_seconds": int(math.ceil(render_total)),
            "alerting": alerting,
            "logical_lit": logical_lit,
            "physical_lit": physical_lit,
            "colors": [list(pixel) for pixel in frame],
        }
