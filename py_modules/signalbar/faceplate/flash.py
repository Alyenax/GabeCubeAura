# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""GIF accounting and deduplication; no transfer quotas.

One process-wide gate at Link.send_gif; the coordinator supplies its persisted
instance. The existing sole worker remains the only queue. Never sleep here.
Reservations precede body transmission and survive crashes; receipts do not
claim sector erasures. Power and brightness commands do not use this budget.
"""
from __future__ import annotations

from collections import deque
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import tempfile
import time
import zlib

CAPACITY = 8
SCREENSAVER_CONTINUITY_SECONDS = 5.0
REFILL_SECONDS = 30.0
HOUR_LIMIT = 120
WINDOW_SECONDS = 3600.0
DAY_SECONDS = 86400.0
DAY_LIMIT = 128
BACKGROUND_DAY_LIMIT = 24
COUNTER_FLUSH_SECONDS = 60.0
PRIORITIES = {"background", "interactive", "assistant", "restore", "player-city", "player-city-restore"}


class UploadDeferred(RuntimeError):
    def __init__(self, retry_after, reason="Transfer temporarily deferred"):
        super().__init__(reason)
        self.retry_after = max(1.0, float(retry_after))


class ContentCollision(ValueError):
    pass


def identity(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "crc32": zlib.crc32(data) & 0xffffffff}


class FlashWearProtection:
    def __init__(self, path=None, *, monotonic=time.monotonic, wall_clock=time.time,
                 prior_usage=False):
        self.path = Path(path) if path is not None else None
        self.monotonic, self.wall_clock = monotonic, wall_clock
        self.lock = threading.RLock()
        self.enabled = True
        self.performance_unlimited = False
        self.performance_attempts_session = 0
        self.ordinary_attempts_session = 0
        self.tokens = float(CAPACITY)
        self.tick = self.monotonic()
        self.attempts = deque(maxlen=HOUR_LIMIT)
        self.daily_attempts = deque(maxlen=DAY_LIMIT)
        self.background_attempts = deque(maxlen=BACKGROUND_DAY_LIMIT)
        self.history_state = "new" if not prior_usage else "unknown"
        self.marker = self.path.with_name(self.path.name + ".initialized") if self.path else None
        self.total = dict(confirmed=0, reused=0, deferred=0, uncertain=0)
        self.commands = dict(brightness=0, power=0, native_clock=0)
        self.session = dict(self.total)
        self.events = deque(maxlen=32)
        self.fingerprint = None
        self.hardware_state = "unknown"
        self.pending = None
        self.screensaver_next_at = 0.0
        self.persistence_error = ""
        self.last_flush = self.tick
        self.dirty = False
        self._status_cache = {}
        self._load()
        if (self.path is not None and not self.path.exists()
                and (prior_usage or self.marker.exists())):
            # Preferences and downloaded modules may be reset; usage history may
            # not. Missing evidence on a known install is never a fresh device.
            self.history_state = "lost"
            self.tokens = 0.0
            self.dirty = True
        if self.dirty:
            self.flush(force=True)
        self.status()

    def _load(self):
        if self.path is None or not self.path.exists():
            return
        try:
            if self.path.is_symlink():
                raise ValueError("symlink protection state")
            if self.path.stat().st_size > 65536:
                raise ValueError("oversized protection state")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("schema") not in (1, 2):
                raise ValueError("unsupported protection state")
            saved = float(raw["saved_at"])
            elapsed = self.wall_clock() - saved
            # Backwards/implausible clocks cannot create a fresh allowance.
            elapsed = max(0.0, min(DAY_SECONDS, elapsed))
            screensaver_remaining = float(raw.get("screensaver_remaining", 0))
            if not math.isfinite(screensaver_remaining) or not 0 <= screensaver_remaining <= 600:
                raise ValueError("invalid screensaver attempt window")
            self.screensaver_next_at = self.tick + min(SCREENSAVER_CONTINUITY_SECONDS,max(0.0, screensaver_remaining-elapsed))
            tokens = float(raw["tokens"])
            if not math.isfinite(tokens) or not math.isfinite(saved):
                raise ValueError("invalid protection clock")
            self.tokens = max(0.0, min(CAPACITY, tokens + elapsed / REFILL_SECONDS))
            ages = raw["attempt_ages"]
            if not isinstance(ages, list) or len(ages) > HOUR_LIMIT:
                raise ValueError("invalid protection window")
            for age in ages:
                age = float(age) + elapsed
                if not math.isfinite(age) or age < 0:
                    raise ValueError("invalid reservation age")
                if age < WINDOW_SECONDS:
                    self.attempts.append(self.tick - age)
            daily = raw.get("daily_attempt_ages", ages)
            background = raw.get("background_attempt_ages", [])
            for source, target, maximum in ((daily, self.daily_attempts, DAY_LIMIT),
                                             (background, self.background_attempts, BACKGROUND_DAY_LIMIT)):
                if not isinstance(source, list) or len(source) > maximum:
                    raise ValueError("invalid daily protection window")
                for age in source:
                    age = float(age) + elapsed
                    if not math.isfinite(age) or age < 0:
                        raise ValueError("invalid daily reservation age")
                    if age < DAY_SECONDS:
                        target.append(self.tick - age)
            self.history_state = str(raw.get("history_state", "partial-upgrade" if raw["schema"] == 1 else "known"))
            for key in self.total:
                self.total[key] = max(0, int(raw.get("total", {}).get(key, 0)))
            for key in self.commands:
                self.commands[key] = max(0, int(raw.get("commands", {}).get(key, 0)))
            self.fingerprint = raw.get("fingerprint")
            if self.fingerprint is not None and (
                    not isinstance(self.fingerprint, dict)
                    or set(self.fingerprint) != {"sha256", "size", "crc32"}
                    or len(str(self.fingerprint["sha256"])) != 64):
                raise ValueError("invalid content identity")
            if raw.get("pending"):
                # The process may have died before or after the commit ACK.
                self.total["uncertain"] += 1
                self.dirty = True
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
            # Do not invent a full day of transfers or a day-long lock.
            # Preserve the diagnostic and rebuild accounting when writable.
            self.tokens = 0.0
            self.attempts = deque(maxlen=HOUR_LIMIT)
            self.daily_attempts = deque(maxlen=DAY_LIMIT)
            self.background_attempts = deque(maxlen=BACKGROUND_DAY_LIMIT)
            self.history_state = "corrupt"
            self.persistence_error = "Transfer history unreadable; accounting continues in memory: " + str(error)[:100]

    def _refresh(self):
        now = self.monotonic()
        self.tokens = min(CAPACITY, self.tokens + max(0.0, now - self.tick) / REFILL_SECONDS)
        self.tick = now
        while self.attempts and now - self.attempts[0] >= WINDOW_SECONDS:
            self.attempts.popleft()
        for queue in (self.daily_attempts, self.background_attempts):
            while queue and now - queue[0] >= DAY_SECONDS:
                queue.popleft()

    def _delay(self, priority):
        # All scenes, including City, use accounting/deduplication only.
        # Hourly City refresh belongs to its scheduler, never this journal.
        self._refresh()
        return 0.0

    def configure(self, enabled):
        with self.lock:
            self.enabled = bool(enabled)

    def configure_performance(self, consented):
        with self.lock:
            # Legacy callers cannot reopen the retired unlimited path.
            self.performance_unlimited = False

    def delay(self, priority="background"):
        with self.lock:
            return self._delay(priority)

    def screensaver_delay(self):
        """Short continuity guard, not an hourly/daily screensaver allowance."""
        with self.lock:
            return max(0.0, self.screensaver_next_at-self.monotonic())

    def reserve_screensaver_attempt(self):
        """Persist before USB, including reuse/uncertain or interrupted attempts.

        This is not another token allowance: ordinary preflight/reserve_body
        still applies. A restart cannot turn an uncertain attempt into a retry.
        """
        with self.lock:
            delay = self.screensaver_delay()
            if delay > 0:
                raise UploadDeferred(delay)
            self.screensaver_next_at = self.monotonic()+SCREENSAVER_CONTINUITY_SECONDS
            self.dirty = True
            self.flush(force=True)

    def preflight(self, data, priority):
        """Best-effort accounting; the device CRC decides whether a body is needed."""
        with self.lock:
            wanted = identity(data)
            if self.path is not None and (self.persistence_error or not self.path.exists()):
                self.dirty = True
                self.flush(force=True)
            return wanted

    def reserve_body(self, wanted, priority):
        with self.lock:
            self._refresh()
            priority = priority if priority in PRIORITIES else "background"
            self.ordinary_attempts_session += 1
            self.tokens = max(0.0, self.tokens - 1)
            self.attempts.append(self.tick)
            self.daily_attempts.append(self.tick)
            if priority in ("background", "player-city"):
                self.background_attempts.append(self.tick)
            self.pending = wanted
            self.hardware_state = "unknown"
            if self.history_state == "new":
                self.history_state = "known"
            self.dirty = True
            # Accounting failure is diagnostic only, never an upload lock.
            if not self.flush(force=True):
                self.pending = None

    def check_reuse(self, wanted):
        with self.lock:
            prior = self.fingerprint
            if (prior and prior["size"] == wanted["size"]
                    and prior["crc32"] == wanted["crc32"] and prior != wanted):
                self.hardware_state = "unknown"
                raise ContentCollision("Stored GIF CRC collision; refusing to claim identical content")

    def receipt(self, wanted, *, wrote=False, error=False, scene="scene"):
        with self.lock:
            key = "uncertain" if error else "confirmed" if wrote else "reused"
            self.total[key] += 1
            self.session[key] += 1
            self.hardware_state = "unknown" if error else "acknowledged"
            if not error:
                self.fingerprint = wanted
            self.pending = None
            self.events.append({"at": self.wall_clock(), "outcome": key,
                                "scene": str(scene)[:32], "bytes": wanted["size"]})
            self.dirty = True
            self.flush()

    def invalidate(self):
        with self.lock:
            self.hardware_state = "unknown"

    def record_command(self, name):
        """A drained control packet, not a measured settings-sector erase."""
        with self.lock:
            if name in self.commands:
                self.commands[name] += 1
                self.dirty = True
                self.flush()

    def flush(self, force=False):
        with self.lock:
            self._refresh()
            if not self.dirty or (not force and self.monotonic() - self.last_flush < COUNTER_FLUSH_SECONDS):
                return not self.persistence_error
            if self.path is None:
                self.dirty = False
                return True
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = {"schema": 2, "saved_at": self.wall_clock(), "tokens": self.tokens,
                           "attempt_ages": [max(0, self.tick - t) for t in self.attempts],
                           "daily_attempt_ages": [max(0, self.tick-t) for t in self.daily_attempts],
                           "background_attempt_ages": [max(0, self.tick-t) for t in self.background_attempts],
                           "history_state": self.history_state,
                           "screensaver_remaining": max(0.0, min(600.0, self.screensaver_next_at-self.tick)),
                           "total": self.total, "commands": self.commands,
                           "fingerprint": self.fingerprint, "pending": self.pending}
                descriptor, temporary = tempfile.mkstemp(prefix=".flash-protection-", suffix=".tmp", dir=self.path.parent)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                if self.marker is not None and not self.marker.exists():
                    descriptor = os.open(self.marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    with os.fdopen(descriptor, "w") as marker:
                        marker.write("usage-history-initialized-v2\n")
                        marker.flush()
                        os.fsync(marker.fileno())
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                self.last_flush = self.monotonic()
                self.dirty = False
                self.persistence_error = ""
                return True
            except OSError as error:
                if "temporary" in locals():
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                self.persistence_error = "Transfer accounting could not be saved: " + str(error)[:100]
                return False

    def status(self):
        if not self.lock.acquire(blocking=False):
            return copy.deepcopy(self._status_cache)
        try:
            self._refresh()
            result = {"enabled": self.enabled, "hard_limit_enabled": False, "policy": "dedup-no-quotas-v3", "capacity": 0,
                    "refill_seconds": 0, "hour_limit": 0,
                    "attempts_last_hour": len(self.attempts),
                    "player_city": {"enabled": False, "policy": "hourly-no-quotas",
                        "retry_after_seconds": 0},
                    "day_limit": 0, "day_reserved_returns": 0,
                    "background_day_limit": 0, "window_counters_bounded": True,
                    "attempts_last_day": len(self.daily_attempts),
                    "background_attempts_last_day": len(self.background_attempts),
                    "history_state": self.history_state,
                    "control_commands": dict(self.commands),
                    "tokens": 0, "reserved_tokens": {},
                    "performance_unlimited": self.performance_unlimited,
                    "performance_attempts_session": self.performance_attempts_session,
                    "ordinary_attempts_session": self.ordinary_attempts_session,
                    "screensaver_retry_after_seconds": self.screensaver_delay(),
                    "session": dict(self.session), "total": dict(self.total),
                    "hardware_state": self.hardware_state, "recent": list(self.events),
                    "persistence_error": self.persistence_error,
                    "counter_flush_seconds": COUNTER_FLUSH_SECONDS,
                    "endurance": "unknown", "performance_faceplate_enabled": False}
            self._status_cache = result
            return copy.deepcopy(result)
        finally:
            self.lock.release()


_DEFAULT = FlashWearProtection()


def default_manager():
    return _DEFAULT


def install_manager(manager):
    """Bind direct Link callers to the engine's same persisted gate."""
    global _DEFAULT
    _DEFAULT = manager
