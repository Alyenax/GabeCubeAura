"""Minimal sysfs adapter for the official Steam Machine light bar.

This module performs raw I/O but never decides when to write. Only Renderer
owns an instance in production.
"""

from __future__ import annotations

import glob
import os
import re
import threading
from typing import Optional

from signalbar.models import Frame, LED_COUNT, normalize_frame

LED_GLOB = "/sys/class/leds/valve-leds[[]*[]]"
VALVE_ANIMATED_EFFECTS = {"patrol", "breath", "factory", "rainbow", "demo"}


def _index(path: str) -> int:
    match = re.search(r"\[(\d+)\]$", path)
    return int(match.group(1)) if match else -1


def discover_paths(pattern: str = LED_GLOB):
    return sorted(glob.glob(pattern), key=_index)


class ValveLedHardware:
    def __init__(self, paths=None):
        self.paths = list(paths) if paths is not None else discover_paths()
        if len(self.paths) != LED_COUNT:
            raise RuntimeError(f"expected {LED_COUNT} valve-leds devices, found {len(self.paths)}")
        self._io_lock = threading.RLock()
        self._reverse = False

    @property
    def device_path(self) -> str:
        if not self.paths:
            return LED_GLOB
        return os.path.commonpath(self.paths)

    @property
    def reverse(self) -> bool:
        return self._reverse

    def set_reverse(self, reverse: bool):
        with self._io_lock:
            changed = self._reverse != bool(reverse)
            self._reverse = bool(reverse)
            return changed

    def _logical_paths(self):
        return list(reversed(self.paths)) if self._reverse else self.paths

    @staticmethod
    def _read(path: str, name: str) -> str:
        with open(os.path.join(path, name), encoding="ascii") as handle:
            return handle.read().strip()

    @staticmethod
    def _write(path: str, name: str, value: str):
        with open(os.path.join(path, name), "w", encoding="ascii") as handle:
            handle.write(value)

    def _control_path(self, name: str) -> str:
        return os.path.join(self.paths[0], name)

    def _read_control(self, name: str) -> Optional[str]:
        path = self._control_path(name)
        if not os.path.exists(path):
            return None
        return self._read(self.paths[0], name)

    def _write_control(self, name: str, value: str) -> bool:
        path = self._control_path(name)
        if not os.path.exists(path):
            return False
        self._write(self.paths[0], name, value)
        return True

    def read_frame(self) -> Frame:
        with self._io_lock:
            values = []
            for path in self._logical_paths():
                raw = self._read(path, "multi_intensity")
                parts = raw.split()
                if len(parts) != 3:
                    raise OSError(f"unexpected multi_intensity value at {path}")
                values.append(tuple(int(part) for part in parts))
            return normalize_frame(values)

    def read_signature(self):
        """Include Valve's global mode as well as every visible LED input."""
        with self._io_lock:
            controls = (
                self._read_control("effect"),
                self._read_control("enabled"),
                self._read_control("brightness_scale"),
            )
            pixels = tuple(
                (self._read(path, "multi_intensity"), self._read(path, "brightness"))
                for path in self.paths
            )
            return controls, pixels

    @staticmethod
    def stability_signature(signature):
        """Ignore brightness-only churn while waiting for the initial claim.

        The global effect and RGB targets still have to remain stable. Once
        GabeCubeAura owns the bar, the full signature is used so a Valve
        brightness or mode change immediately yields ownership.
        """
        controls, pixels = signature
        effect, enabled, _brightness_scale = controls
        return (effect, enabled), tuple(pixel[0] for pixel in pixels)

    @staticmethod
    def native_priority_state(signature):
        """Recognize native states that must never be replaced by a plugin.

        Steam's explicit download lease remains the primary signal. Hardware
        effects provide a local fallback if that private Steam callback is not
        available. Fixed colours are never interpreted semantically: thermal
        protection uses CPU/GPU sensors instead of guessing from red pixels.
        """
        controls, pixels = signature
        effect, enabled, _brightness_scale = controls
        if str(enabled or "1").strip().lower() in {"0", "false", "off"}:
            return "", ""
        effect = str(effect or "").strip().lower()
        if effect in VALVE_ANIMATED_EFFECTS:
            return "effect", f"Valve {effect} hardware effect"
        return "", ""

    @staticmethod
    def native_priority_reason(signature) -> str:
        return ValveLedHardware.native_priority_state(signature)[1]

    def capture_state(self):
        with self._io_lock:
            return {
                "frame": self.read_frame(),
                "effect": self._read_control("effect"),
                "enabled": self._read_control("enabled"),
                "brightness_scale": self._read_control("brightness_scale"),
            }

    def read_brightness_scale(self) -> Optional[int]:
        """Return Valve's global LED gain when this driver exposes it."""
        with self._io_lock:
            raw = self._read_control("brightness_scale")
            if raw is None:
                return None
            try:
                return max(0, min(255, int(str(raw), 0)))
            except (TypeError, ValueError):
                return None

    def set_brightness_scale(self, value: int) -> bool:
        """Set the global gain without changing effect ownership or RGB data."""
        with self._io_lock:
            clean = max(0, min(255, int(value)))
            return self._write_control("brightness_scale", str(clean))

    def restore_brightness_scale_if(self, expected: int, saved: int) -> bool:
        """Restore a saved gain only if no external actor changed our value."""
        with self._io_lock:
            current = self.read_brightness_scale()
            if current is None or current != max(0, min(255, int(expected))):
                return False
            return self.set_brightness_scale(saved)

    def claim_manual_control(self):
        """Select the hardware mode required for direct per-pixel writes."""
        with self._io_lock:
            self._write_control("effect", "manual")
            self._write_control("enabled", "1")

    def write_frame(self, frame: Frame):
        frame = normalize_frame(frame)
        with self._io_lock:
            for path, (red, green, blue) in zip(self._logical_paths(), frame):
                self._write(path, "multi_intensity", f"{red} {green} {blue}")

    def try_restore(self, frame: Optional[Frame]):
        if frame is not None:
            self.write_frame(frame)

    def try_restore_state(self, state):
        if not state:
            return
        with self._io_lock:
            frame = state.get("frame")
            if frame is not None:
                self.write_frame(frame)
            brightness_scale = state.get("brightness_scale")
            if brightness_scale is not None:
                self._write_control("brightness_scale", brightness_scale)
            effect = state.get("effect")
            if effect is not None:
                self._write_control("effect", effect)
            enabled = state.get("enabled")
            if enabled is not None:
                self._write_control("enabled", enabled)
