# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Truthful, transport-independent Steam state for Faceplate composition.

SteamUI owns the notification callbacks.  This small state holder deliberately
does not query Steam, render pixels, or touch the serial link.  Renderers only
receive immutable snapshots whose recording state is tri-state: an old
callback must never leave a convincing but stale REC indicator on the panel.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


RECORDING_STATES = ("active", "inactive", "unknown")
RECENT_EVENT_KINDS = ("notification", "achievement", "screenshot")
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 8.0
DEFAULT_RECENT_EVENT_SECONDS = 60.0


@dataclass(frozen=True)
class FaceplateStatusSnapshot:
    recording: str
    recording_sequence: int
    recording_age_s: float | None
    observer_fresh: bool
    heartbeat_age_s: float | None
    recent_event: str
    event_sequence: int
    event_age_s: float | None

    def render_payload(self, recent_event=""):
        """Return only stable pixels inputs; ages never enter GIF identities."""
        selected = str(recent_event or "")
        if selected not in RECENT_EVENT_KINDS:
            selected = ""
        return {
            "recording": self.recording,
            "recording_sequence": self.recording_sequence,
            "recent_event": selected,
            "event_sequence": self.event_sequence if selected else 0,
        }

    def as_dict(self):
        return {
            "recording": self.recording,
            "recording_sequence": self.recording_sequence,
            "recording_age_s": self.recording_age_s,
            "observer_fresh": self.observer_fresh,
            "heartbeat_age_s": self.heartbeat_age_s,
            "recent_event": self.recent_event,
            "event_sequence": self.event_sequence,
            "event_age_s": self.event_age_s,
        }


class FaceplateSteamState:
    """Thread-safe callback state shared by LED events and Faceplate routes."""

    def __init__(self, clock=time.monotonic,
                 heartbeat_timeout=DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
                 recent_event_seconds=DEFAULT_RECENT_EVENT_SECONDS):
        self._clock = clock
        self._heartbeat_timeout = max(1.0, float(heartbeat_timeout))
        self._recent_event_seconds = max(1.0, float(recent_event_seconds))
        self._lock = threading.RLock()
        self._recording = "unknown"
        self._recording_sequence = 0
        self._recording_updated_at = 0.0
        self._heartbeat_at = 0.0
        self._recent_event = ""
        self._event_sequence = 0
        self._event_at = 0.0

    def heartbeat(self):
        with self._lock:
            self._heartbeat_at = self._clock()

    def mark_unknown(self):
        """Invalidate recording knowledge without inventing an inactive state."""
        with self._lock:
            if self._recording == "unknown":
                return False
            self._recording = "unknown"
            self._recording_sequence += 1
            self._recording_updated_at = self._clock()
            return True

    def observe_event(self, kind):
        """Record one real Steam callback and report a REC state transition."""
        kind = str(kind or "")
        now = self._clock()
        with self._lock:
            # Any real callback proves that the observer is alive at this
            # instant, including callbacks received between periodic heartbeats.
            self._heartbeat_at = now
            recording_changed = False
            if kind in {"record-start", "record-stop"}:
                desired = "active" if kind == "record-start" else "inactive"
                if desired != self._recording:
                    self._recording = desired
                    self._recording_sequence += 1
                    self._recording_updated_at = now
                    recording_changed = True
            elif kind in RECENT_EVENT_KINDS:
                self._recent_event = kind
                self._event_sequence += 1
                self._event_at = now
            return recording_changed

    def snapshot(self):
        now = self._clock()
        with self._lock:
            heartbeat_age = (
                max(0.0, now - self._heartbeat_at) if self._heartbeat_at else None
            )
            observer_fresh = bool(
                heartbeat_age is not None
                and heartbeat_age <= self._heartbeat_timeout
            )
            if not observer_fresh and self._recording != "unknown":
                # Once the callback lease expires, a later heartbeat alone
                # cannot prove whether recording continued while disconnected.
                self._recording = "unknown"
                self._recording_sequence += 1
                self._recording_updated_at = now
            recording = self._recording
            recording_age = (
                max(0.0, now - self._recording_updated_at)
                if self._recording_updated_at else None
            )
            event_age = (
                max(0.0, now - self._event_at) if self._event_at else None
            )
            recent_event = (
                self._recent_event
                if event_age is not None and event_age <= self._recent_event_seconds
                else ""
            )
            return FaceplateStatusSnapshot(
                recording=recording,
                recording_sequence=self._recording_sequence,
                recording_age_s=recording_age,
                observer_fresh=observer_fresh,
                heartbeat_age_s=heartbeat_age,
                recent_event=recent_event,
                event_sequence=self._event_sequence,
                event_age_s=event_age,
            )
