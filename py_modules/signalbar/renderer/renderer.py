"""The sole production writer for the LED hardware."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

from signalbar.models import Frame, normalize_frame


class Renderer:
    def __init__(self, hardware, min_interval_s: float = 0.05, clock=time.monotonic,
                 brightness_recovery_path: Optional[str] = None):
        self.hardware = hardware
        self.min_interval_s = max(0.05, float(min_interval_s))
        self._clock = clock
        self._lock = threading.RLock()
        self._last_frame: Optional[Frame] = None
        self._last_signature = None
        self._last_write_at = 0.0
        self._last_successful_write_at = 0.0
        self._saved_frame: Optional[Frame] = None
        self._saved_state = None
        self._failed = False
        self._writes = 0
        self._output_brightness_scale: Optional[int] = None
        self._applied_brightness_scale: Optional[int] = None
        self._saved_brightness_scale: Optional[int] = None
        self._brightness_override_active = False
        self._brightness_recovery_path = brightness_recovery_path
        self._startup_brightness_recovered = False
        self._recover_interrupted_brightness_override()

    @property
    def failed(self):
        return self._failed

    @property
    def last_frame(self):
        return self._last_frame

    @property
    def last_signature(self):
        return self._last_signature

    @property
    def last_write_at(self):
        return self._last_write_at

    @property
    def last_successful_write_at(self):
        return self._last_successful_write_at

    @property
    def writes(self):
        return self._writes

    @property
    def output_brightness_scale(self):
        return self._output_brightness_scale

    def _read_brightness_scale(self):
        reader = getattr(self.hardware, "read_brightness_scale", None)
        if not callable(reader):
            return None
        return reader()

    def _write_recovery(self, saved: int, *expected: int):
        if not self._brightness_recovery_path:
            return
        path = os.path.abspath(self._brightness_recovery_path)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({
                "protocol": 2,
                "saved_brightness_scale": int(saved),
                "expected_brightness_scales": sorted({int(value) for value in expected}),
            }, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)

    def _clear_recovery(self):
        if not self._brightness_recovery_path:
            return
        try:
            os.unlink(self._brightness_recovery_path)
        except FileNotFoundError:
            pass

    def _recover_interrupted_brightness_override(self):
        path = self._brightness_recovery_path
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict) or payload.get("protocol") not in {1, 2}:
                self._clear_recovery()
                return
            saved = max(0, min(255, int(payload["saved_brightness_scale"])))
            if payload.get("protocol") == 1:
                expected = [max(0, min(255, int(payload["reference_brightness_scale"])))]
            else:
                expected = [
                    max(0, min(255, int(value)))
                    for value in payload["expected_brightness_scales"]
                ]
                if not expected:
                    raise ValueError("empty expected brightness set")
            current = self._read_brightness_scale()
            restorer = getattr(self.hardware, "restore_brightness_scale_if", None)
            if current in expected and callable(restorer):
                self._startup_brightness_recovered = bool(restorer(current, saved))
            # A different current value means Steam or the user already took
            # over. Never replace it with stale recovery data.
            if current not in expected or self._startup_brightness_recovered:
                self._clear_recovery()
        except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
            # Keep a valid-looking recovery file for the next startup if the
            # sysfs write itself failed. Malformed files are harmless because
            # applying a reference always rewrites them atomically.
            return

    def set_output_brightness_scale(self, value: Optional[int]):
        """Select a temporary global gain while this renderer owns the bar."""
        clean = None if value is None else max(0, min(255, int(value)))
        with self._lock:
            if clean == self._output_brightness_scale:
                return False
            previous = self._output_brightness_scale
            self._output_brightness_scale = clean
            if previous is not None and clean is None:
                self._release_brightness_override(previous)
                if self._last_signature is not None:
                    try:
                        self._last_signature = self.hardware.read_signature()
                    except OSError:
                        self._failed = True
            # Force the next frame through claim_manual_control so a newly
            # selected reference is applied even if RGB did not change.
            self._last_frame = None
            return True

    def _apply_brightness_override(self):
        reference = self._output_brightness_scale
        setter = getattr(self.hardware, "set_brightness_scale", None)
        if reference is None or not callable(setter):
            return
        if not self._brightness_override_active:
            current = self._read_brightness_scale()
            if current is None:
                return
            self._saved_brightness_scale = current
            self._write_recovery(current, reference)
        elif self._applied_brightness_scale != reference and self._saved_brightness_scale is not None:
            # Either side of a sysfs transition can survive a sudden stop.
            # Both are therefore safe recovery sentinels until the write is
            # confirmed, after which the record is collapsed to the new one.
            self._write_recovery(
                self._saved_brightness_scale,
                self._applied_brightness_scale,
                reference,
            )
        if setter(reference):
            self._brightness_override_active = True
            self._applied_brightness_scale = reference
            if self._saved_brightness_scale is not None:
                self._write_recovery(self._saved_brightness_scale, reference)

    def _release_brightness_override(self, expected: Optional[int] = None):
        if not self._brightness_override_active and self._saved_brightness_scale is None:
            return False
        reference = self._applied_brightness_scale
        if reference is None:
            reference = self._output_brightness_scale if expected is None else expected
        saved = self._saved_brightness_scale
        current = self._read_brightness_scale()
        restored = False
        if reference is not None and saved is not None:
            restorer = getattr(self.hardware, "restore_brightness_scale_if", None)
            if callable(restorer):
                restored = bool(restorer(reference, saved))
        # If another actor already changed the gain, its value is authoritative
        # and the stale recovery record must not overwrite it on next startup.
        if restored or current is None or current != reference:
            self._clear_recovery()
        self._saved_brightness_scale = None
        self._applied_brightness_scale = None
        self._brightness_override_active = False
        return restored

    def calibration_status(self):
        with self._lock:
            current = self._read_brightness_scale()
            return {
                "supported": current is not None,
                "detected_brightness": current,
                "reference_brightness": self._output_brightness_scale,
                "applied_brightness": self._applied_brightness_scale,
                "saved_steam_brightness": self._saved_brightness_scale,
                "override_active": self._brightness_override_active,
                "startup_recovered": self._startup_brightness_recovered,
            }

    def render(self, frame, *, force=False) -> bool:
        clean = normalize_frame(frame)
        with self._lock:
            if self._failed or clean == self._last_frame and not force:
                return False
            now = self._clock()
            if self._last_write_at and now - self._last_write_at < self.min_interval_s:
                return False
            try:
                if self._saved_frame is None:
                    capture_state = getattr(self.hardware, "capture_state", None)
                    if callable(capture_state):
                        self._saved_state = capture_state()
                        self._saved_frame = self._saved_state["frame"]
                    else:
                        self._saved_frame = self.hardware.read_frame()
                claim_manual_control = getattr(self.hardware, "claim_manual_control", None)
                if callable(claim_manual_control) and (
                    self._last_frame is None or self._saved_frame is not None and force
                ):
                    # Protected ownership must restore manual mode after a
                    # competing Valve write, even when the desired RGB frame
                    # itself has not changed.
                    claim_manual_control()
                self._apply_brightness_override()
                self.hardware.write_frame(clean)
                self._last_signature = self.hardware.read_signature()
            except OSError:
                self._failed = True
                self._last_frame = None
                self._last_signature = None
                raise
            self._last_frame = clean
            self._last_write_at = now
            self._last_successful_write_at = now
            self._writes += 1
            return True

    def relinquish(self, restore_if_owned: bool = True) -> bool:
        """Stop owning the bar; restore only when nobody changed our frame."""
        with self._lock:
            restored = False
            if restore_if_owned and self._saved_frame is not None and self._last_signature is not None:
                try:
                    if self.hardware.read_signature() == self._last_signature:
                        restore_state = getattr(self.hardware, "try_restore_state", None)
                        if self._saved_state is not None and callable(restore_state):
                            restore_state(self._saved_state)
                        else:
                            self.hardware.try_restore(self._saved_frame)
                        restored = True
                except OSError:
                    self._failed = True
            if self._brightness_override_active or self._saved_brightness_scale is not None:
                if restored:
                    self._clear_recovery()
                    self._saved_brightness_scale = None
                    self._applied_brightness_scale = None
                    self._brightness_override_active = False
                else:
                    self._release_brightness_override()
            self._last_frame = None
            self._last_signature = None
            self._saved_frame = None
            self._saved_state = None
            self._last_write_at = 0.0
            return restored
