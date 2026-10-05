"""Fail-safe CPU/GPU thermal interlock for LED ownership."""

from __future__ import annotations

import math
import threading
import time


THERMAL_TRIP_C = 94.0
THERMAL_RESET_C = 90.0
THERMAL_RESET_HOLD_S = 30.0
THERMAL_MIN_PLAUSIBLE_C = -40.0
THERMAL_MAX_PLAUSIBLE_C = 150.0
THERMAL_SUSPENSION_MESSAGE = "Désactivé temporairement : protection thermique"


class ThermalProtection:
    """Latch at the thermal limit and recover only after a stable cool period.

    Missing or incoherent readings do not create an alert by themselves, but
    they can never clear an active alert. This preserves Valve's native warning
    path when GabeCubeAura can no longer prove that both processors are cool.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._active = False
        self._triggered_at = 0.0
        self._recovery_started_at = 0.0
        self._trigger_sensor = ""
        self._cpu_temperature = None
        self._gpu_temperature = None
        self._sensor_state = "waiting"

    @staticmethod
    def _temperature(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            clean = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if (not math.isfinite(clean)
                or clean < THERMAL_MIN_PLAUSIBLE_C
                or clean > THERMAL_MAX_PLAUSIBLE_C):
            return None
        return clean

    @property
    def active(self):
        with self._lock:
            return self._active

    def update(self, sample, now=None):
        now = self._clock() if now is None else float(now)
        cpu = self._temperature(getattr(sample, "cpu_temp_c", None))
        gpu = self._temperature(getattr(sample, "gpu_temp_c", None))
        with self._lock:
            self._cpu_temperature = cpu
            self._gpu_temperature = gpu
            hot = [name for name, value in (("CPU", cpu), ("GPU", gpu))
                   if value is not None and value >= THERMAL_TRIP_C]
            if hot:
                if not self._active:
                    self._triggered_at = now
                    self._trigger_sensor = "+".join(hot)
                self._active = True
                self._recovery_started_at = 0.0
                self._sensor_state = "hot"
                return True

            if not self._active:
                self._recovery_started_at = 0.0
                self._sensor_state = "ok" if cpu is not None or gpu is not None else "unavailable"
                return False

            # During an active alert, both readings must remain coherent. A
            # missing/stale/bogus value keeps Valve in control and restarts the
            # full 30-second recovery proof.
            if cpu is None or gpu is None:
                self._recovery_started_at = 0.0
                self._sensor_state = "fail-safe"
                return True
            if cpu >= THERMAL_RESET_C or gpu >= THERMAL_RESET_C:
                self._recovery_started_at = 0.0
                self._sensor_state = "cooling"
                return True
            if not self._recovery_started_at:
                self._recovery_started_at = now
                self._sensor_state = "recovering"
                return True
            if now - self._recovery_started_at < THERMAL_RESET_HOLD_S:
                self._sensor_state = "recovering"
                return True

            self._active = False
            self._recovery_started_at = 0.0
            self._sensor_state = "ok"
            return False

    def status(self, now=None):
        now = self._clock() if now is None else float(now)
        with self._lock:
            elapsed = (
                max(0.0, now - self._recovery_started_at)
                if self._active and self._recovery_started_at else 0.0
            )
            return {
                "active": self._active,
                "message": THERMAL_SUSPENSION_MESSAGE if self._active else "",
                "trip_temperature_c": THERMAL_TRIP_C,
                "reset_temperature_c": THERMAL_RESET_C,
                "reset_hold_seconds": THERMAL_RESET_HOLD_S,
                "recovery_remaining_s": (
                    max(0.0, THERMAL_RESET_HOLD_S - elapsed)
                    if self._active and self._recovery_started_at else None
                ),
                "trigger_sensor": self._trigger_sensor,
                "triggered_at": self._triggered_at,
                "cpu_temperature": self._cpu_temperature,
                "gpu_temperature": self._gpu_temperature,
                "sensor_state": self._sensor_state,
            }
