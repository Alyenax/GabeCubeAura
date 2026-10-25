# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Optional non-blocking worker for faceplate scene transfers.

The LED runtime must never wait for a slow serial commit.  This worker keeps a
single pending scene, replaces it when a newer scene arrives, and performs the
hardware operation on its own thread.  Serial ownership and process IPC can be
added behind the injected handler without changing the queue contract.
"""

from __future__ import annotations

import threading
import time

from .transport import PROFILE_BASELINE, TRANSPORT_PROFILES

PERFORMANCE_MIN_UPLOAD_INTERVAL_SECONDS = 1.0
STATISTICS_IDLE_SECONDS = 60.0

DEFAULT_CAPABILITIES = {
    "protocol": "jsaux-pixel-gif-v1",
    "profiles": list(TRANSPORT_PROFILES),
    "configured_profile": PROFILE_BASELINE,
    "active_profile": "",
    "factory_test": "optional-fire-and-forget",
    "gif_end_timeout": "adaptive",
    "native_clock": True,
    "native_clock_flash_effect": "unverified",
    "raw_pixels": False,
    "single_serial_owner": True,
    "panel_crc_deduplication": True,
    "long_gif_delays": True,
    "long_gif_delay_state": "unused-dashboard-uses-standard-delays",
    "performance_live_updates": False,
    "performance_policy": "removed-from-faceplate",
    "performance_min_upload_interval_seconds": PERFORMANCE_MIN_UPLOAD_INTERVAL_SECONDS,
}


class FaceplateWorker:
    """Run the latest requested faceplate operation outside the LED thread."""

    def __init__(self, handler, *, enabled: bool = False, logger=None,
                 monotonic=time.monotonic, on_complete=None, on_idle=None):
        if not callable(handler):
            raise TypeError("faceplate worker handler must be callable")
        self.handler = handler
        self.logger = logger
        self.monotonic = monotonic
        self.on_complete = on_complete
        self.on_idle = on_idle
        self.condition = threading.Condition()
        self.enabled = bool(enabled)
        self.stopping = False
        self.thread = None
        self.pending = None
        self.active_request = None
        self.busy = False
        self.generation = 0
        self.completed_generation = 0
        self.completed = 0
        # Bounded receipts let a waiter observe its own ACK even if another
        # scene starts/completes before it wakes. Never retain GIF payloads.
        self.completion_receipts = {}
        self.dropped = 0
        self.last_scene = ""
        self.last_result = None
        self.last_error = ""
        self.last_completed_at = 0.0
        self.last_queue_age_ms = 0
        self.ack_ema_ms = 0.0
        self.handler_ema_ms = 0.0
        self.superseded_active = 0
        self.rejected = 0
        self.last_rejection = ""
        self.capability_state = dict(DEFAULT_CAPABILITIES)

    def _log(self, level: str, message: str):
        if self.logger:
            getattr(self.logger, level)("[GabeCubeAura Faceplate Worker] " + message)

    def _start_locked(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.stopping = False
        self.thread = threading.Thread(
            target=self._run, name="gabecubeaura-faceplate", daemon=True,
        )
        self.thread.start()

    def start(self):
        with self.condition:
            self._start_locked()

    def configure(self, enabled: bool):
        with self.condition:
            self.enabled = bool(enabled)
            if self.enabled:
                self._start_locked()
            elif self.pending is not None:
                self.pending = None
                self.dropped += 1
            if not self.enabled and self.active_request is not None:
                cancelled = self.active_request.get("_cancelled")
                if cancelled is not None:
                    cancelled.set()
            self.condition.notify_all()

    def submit(self, scene: str, payload, metadata=None):
        """Queue one scene and return its generation, or zero when disabled."""
        with self.condition:
            if not self.enabled or self.stopping:
                return 0
            metadata = dict(metadata or {})
            rejection = self._gate_request(str(scene or ""), metadata)
            if rejection:
                self.rejected += 1
                self.last_rejection = rejection
                return 0
            self._start_locked()
            self.generation += 1
            request = {
                "generation": self.generation,
                "scene": str(scene or "")[:96],
                "payload": payload,
                "metadata": metadata,
                "queued_at": self.monotonic(),
            }
            if self.pending is not None:
                self.dropped += 1
            self.pending = request
            if self.active_request is not None:
                active_metadata = self.active_request.get("metadata") or {}
                active_class = self._scene_class(
                    self.active_request.get("scene", ""), active_metadata,
                )
                next_class = self._scene_class(request["scene"], metadata)
                if metadata.get("cancel_active") or active_class != next_class:
                    cancelled = self.active_request.get("_cancelled")
                    if cancelled is not None and not cancelled.is_set():
                        cancelled.set()
                        self.superseded_active += 1
            self.condition.notify()
            return self.generation

    @staticmethod
    def _scene_class(scene: str, metadata: dict) -> str:
        value = str(metadata.get("scene_class") or scene.partition(":")[0])
        return value.strip().lower()[:32]

    def cancel_scene_class(self, scene_class: str):
        """Release one owner without dropping a newer normal/power request."""
        wanted = str(scene_class).strip().lower()
        with self.condition:
            if self.pending is not None and self._scene_class(
                self.pending["scene"], self.pending["metadata"],
            ) == wanted:
                self.pending = None
                self.dropped += 1
            if self.active_request is not None and self._scene_class(
                self.active_request["scene"], self.active_request["metadata"],
            ) == wanted:
                cancelled = self.active_request.get("_cancelled")
                if cancelled is not None and not cancelled.is_set():
                    cancelled.set()
                    self.superseded_active += 1
            self.condition.notify_all()

    def wait_for_completion(self, generation: int, cancelled, timeout: float):
        """Wake on the exact completion; cancellation remains bounded to 50 ms.

        Serial commit itself is not interrupted here. Only the waiting caller
        is released; the sole worker must finish/cancel at safe boundaries.
        """
        deadline = self.monotonic() + max(0.0, float(timeout))
        with self.condition:
            while True:
                if cancelled.is_set():
                    return None
                receipt = self.completion_receipts.get(generation)
                if receipt is not None:
                    return {**receipt, "result": dict(receipt["result"])}
                pending = self.pending and self.pending["generation"] == generation
                active = self.active_request and self.active_request["generation"] == generation
                if self.stopping or (not pending and not active):
                    raise RuntimeError("Faceplate request was superseded before confirmation")
                remaining = deadline - self.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Faceplate completion timed out")
                self.condition.wait(min(0.05, remaining))

    def _gate_request(self, scene: str, metadata: dict) -> str:
        """Reject capabilities that have not been proven safe on hardware."""
        if (metadata.get("requires_long_gif_delays")
                and not self.capability_state.get("long_gif_delays", False)):
            return "long GIF frame delays require physical faceplate validation"
        if self._scene_class(scene, metadata) != "performance":
            return ""
        return "CPU/GPU display has been removed from the Faceplate"

    def set_capabilities(self, values):
        """Publish only known, JSON-safe transport capability fields."""
        allowed = set(DEFAULT_CAPABILITIES)
        clean = {key: values[key] for key in allowed if key in values}
        clean["performance_live_updates"] = False
        clean["performance_policy"] = "removed-from-faceplate"
        if "performance_min_upload_interval_seconds" in clean:
            try:
                clean["performance_min_upload_interval_seconds"] = max(
                    0.25,
                    float(clean["performance_min_upload_interval_seconds"]),
                )
            except (TypeError, ValueError, OverflowError):
                clean.pop("performance_min_upload_interval_seconds")
        with self.condition:
            self.capability_state.update(clean)

    def status(self):
        with self.condition:
            result = self.last_result if isinstance(self.last_result, dict) else {}
            return {
                "enabled": self.enabled,
                "running": bool(self.thread and self.thread.is_alive()),
                "busy": self.busy,
                "queued": self.pending is not None,
                "generation": self.generation,
                "completed_generation": self.completed_generation,
                "completed": self.completed,
                "dropped": self.dropped,
                "last_scene": self.last_scene,
                "last_error": self.last_error,
                "last_completed_at": self.last_completed_at,
                "last_queue_age_ms": self.last_queue_age_ms,
                "ack_ema_ms": round(self.ack_ema_ms),
                "handler_ema_ms": round(self.handler_ema_ms),
                "active_generation": (
                    self.active_request["generation"] if self.active_request else 0
                ),
                "active_scene": self.active_request['scene'] if self.active_request else '',
                "superseded_active": self.superseded_active,
                "rejected": self.rejected,
                "last_rejection": self.last_rejection,
                "last_result": {
                    key: result.get(key) for key in (
                        "fallback", "frames", "refresh_policy", "wrote", "automatic_background",
                        "identical", "synchronized", "size_bytes",
                        'sent_unconfirmed', 'error',
                    ) if key in result
                },
                "capabilities": dict(self.capability_state),
            }

    def stop(self, timeout: float = 2.0):
        with self.condition:
            self.enabled = False
            self.stopping = True
            if self.pending is not None:
                self.pending = None
                self.dropped += 1
            if self.active_request is not None:
                cancelled = self.active_request.get("_cancelled")
                if cancelled is not None:
                    cancelled.set()
            thread = self.thread
            self.condition.notify_all()
        if thread is not None:
            thread.join(max(0.0, float(timeout)))
        stopped = thread is None or not thread.is_alive()
        if stopped:
            with self.condition:
                if self.thread is thread:
                    self.thread = None
        return stopped

    def _run(self):
        while True:
            maintenance = False
            with self.condition:
                while not self.stopping and (not self.enabled or self.pending is None):
                    timeout = STATISTICS_IDLE_SECONDS if self.enabled and callable(self.on_idle) else None
                    notified = self.condition.wait(timeout)
                    if (not notified and timeout is not None and self.enabled
                            and self.pending is None and not self.stopping):
                        maintenance = True
                        break
                if self.stopping:
                    return
                if maintenance:
                    request = None
                else:
                    request = self.pending
                    self.pending = None
                    request["_cancelled"] = threading.Event()
                    self.active_request = request
                    self.busy = True
                    self.last_error = ""
                    self.last_queue_age_ms = round(max(
                        0.0, self.monotonic() - request["queued_at"],
                    ) * 1000)
            if maintenance:
                try:
                    self.on_idle()
                except Exception as caught:
                    self._log("warning", "statistics maintenance failed: " + str(caught)[:120])
                continue
            started = self.monotonic()
            result = None
            error = ""
            try:
                result = self.handler(request)
            except Exception as caught:  # isolate hardware failures from Aura Core
                error = f"{type(caught).__name__}: {caught}"[:180]
                self._log("warning", error)
            finally:
                with self.condition:
                    self.busy = False
                    self.completed += 1
                    self.completed_generation = request["generation"]
                    self.last_scene = request["scene"]
                    self.last_result = result
                    self.last_error = error
                    self.completion_receipts[request["generation"]] = {
                        "generation": request["generation"], "scene": request["scene"],
                        "error": error, "result": {
                            key: result[key] for key in ("synchronized", "error", "superseded")
                            if isinstance(result, dict) and key in result
                        },
                    }
                    while len(self.completion_receipts) > 8:
                        self.completion_receipts.pop(next(iter(self.completion_receipts)))
                    self.last_completed_at = self.monotonic()
                    duration_ms = max(0.0, (self.last_completed_at - started) * 1000)
                    self.handler_ema_ms = (
                        duration_ms if not self.handler_ema_ms
                        else self.handler_ema_ms * 0.7 + duration_ms * 0.3
                    )
                    if isinstance(result, dict) and not result.get('sent_unconfirmed'):
                        try:
                            ack_ms = float(
                                result.get("ack_ms")
                                or (result.get("transfer") or {}).get("total_ms")
                                or result.get("upload_ms") or 0
                            )
                        except (TypeError, ValueError, OverflowError):
                            ack_ms = 0.0
                        if ack_ms > 0:
                            self.ack_ema_ms = (
                                ack_ms if not self.ack_ema_ms
                                else self.ack_ema_ms * 0.7 + ack_ms * 0.3
                            )
                    if self.active_request is request:
                        self.active_request = None
                    self.condition.notify_all()
                if self.on_complete is not None:
                    try:
                        self.on_complete()
                    except Exception as caught:
                        self._log('warning', 'completion snapshot failed: ' + str(caught)[:180])
