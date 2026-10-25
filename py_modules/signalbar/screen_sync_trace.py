"""Bounded, redacted capture metadata; file I/O never runs on the capture loop."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from uuid import uuid4

from .diagnostics import HOME_PATH, TOKEN_VALUE, CREDENTIAL_ASSIGNMENT, STEAMGRIDDB_KEY, SENSITIVE_KEY

MAX_TRACE_FILE_BYTES = 256 * 1024
MAX_TRACE_REPORT_BYTES = 24 * 1024
TRACE_GST_DEBUG = "2,pipewiresrc:5,GST_STATES:4,GST_CAPS:4,videorate:4"


def _sanitize(value, key=""):
    if SENSITIVE_KEY.search(str(key)):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k)[:64]: _sanitize(v, k) for k, v in list(value.items())[:16]}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value[:16]]
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(value))
    for pattern, replacement in ((HOME_PATH, "$DECKY_USER_HOME"),
            (TOKEN_VALUE, "[redacted-token]"), (CREDENTIAL_ASSIGNMENT, "[redacted-credential]"),
            (STEAMGRIDDB_KEY, "[redacted-credential]")):
        text = pattern.sub(replacement, text)
    return text[:720]


class ScreenSyncTrace:
    def __init__(self, directory=None, *, clock=time.monotonic, wall_clock=time.time):
        self.directory = Path(directory).resolve() if directory is not None else None
        self.clock, self.wall_clock = clock, wall_clock
        self.session = uuid4().hex[:12]
        self._lock = threading.RLock()
        self._rows = deque(maxlen=256)
        self._landmarks = deque(maxlen=64)
        self._preview_rows = deque(maxlen=256)
        self._preview_landmarks = deque(maxlen=64)
        self._preview_id = ""
        self._preview_until = 0.0
        self._preview_open = False
        self._sequence = 0
        self._dropped = 0
        self._disk_error = ""
        self._queue = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._thread = None
        self._detail_until = 0.0
        self._rate_second = -1
        self._rate_count = 0
        self._restored_preview = self._load_preview()

    def enable_detail(self, seconds=300):
        with self._lock:
            self._detail_until = self.clock() + max(0, min(300, float(seconds)))

    def detailed(self):
        with self._lock: return self.clock() < self._detail_until

    def _load_preview(self):
        if self.directory is None:
            return None
        try:
            path = self.directory / "screen-sync-preview.json"
            if path.is_symlink() or path.stat().st_size > MAX_TRACE_REPORT_BYTES * 2:
                return None
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or value.get("schema") != "screen-sync-trace-v1":
                return None
            # Sanitize each record separately; generic report list truncation
            # must not silently discard the end of a 15-second preview.
            records = value.get("records", [])
            return {"schema": "screen-sync-trace-v1", "scope": "previous-backend-preview",
                    "records": [_sanitize(row) for row in records[-96:] if isinstance(row, dict)]}
        except (OSError, ValueError, TypeError):
            return None

    def _enqueue(self, item):
        if self.directory is None:
            return
        # A blocked/failed disk must not stop PipeWire stdout/stderr draining.
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._write_loop, name="gca-capture-log", daemon=True)
            self._thread.start()
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._dropped += 1

    def record(self, event, *, important=True, **fields):
        fields = _sanitize(fields)
        with self._lock:
            second = int(self.clock())
            if second != self._rate_second:
                self._rate_second, self._rate_count = second, 0
            if not important:
                self._rate_count += 1
                if self._rate_count > 40:
                    self._dropped += 1
                    return
            self._sequence += 1
            row = {"session": self.session, "seq": self._sequence,
                   "time_ms": round(self.wall_clock() * 1000),
                   "mono_ms": round(self.clock() * 1000), "event": str(event)[:64], "fields": fields}
            in_preview = bool(self._preview_id and self.clock() <= self._preview_until + 3.0)
            if in_preview:
                row["preview"] = self._preview_id
                self._preview_rows.append(row)
                if important:
                    self._preview_landmarks.append(row)
            self._rows.append(row)
            if important:
                self._landmarks.append(row)
            self._enqueue(("event", row))
            if in_preview and not self._preview_open:
                self._enqueue(("preview", self.snapshot()))

    def begin_preview(self, seconds, **fields):
        with self._lock:
            self._preview_id = uuid4().hex[:12]
            self._preview_until = self.clock() + seconds
            self._preview_open = True
            self._preview_rows.clear()
            # Retain the connection milestones of an already-running capture.
            self._preview_landmarks = deque(list(self._landmarks)[-8:], maxlen=64)
            self.record("preview-request", seconds=seconds, **fields)
            self._enqueue(("preview", self.snapshot()))

    def end_preview(self, reason="expired"):
        with self._lock:
            if not self._preview_open:
                return
            self.record("preview-end", reason=reason)
            self._preview_open = False
            self._enqueue(("preview", self.snapshot()))

    @property
    def previewing(self):
        with self._lock:
            return self._preview_open and self.clock() < self._preview_until

    def snapshot(self):
        with self._lock:
            if not self._preview_id and not self._rows and self._restored_preview is not None:
                return json.loads(json.dumps(self._restored_preview))
            landmarks = list(self._preview_landmarks if self._preview_id else self._landmarks)
            rows = list(self._preview_rows if self._preview_id else self._rows)
            selected = {(r["session"], r["seq"]): r for r in landmarks[:8] + landmarks[-48:] + rows[-24:]}
            records = sorted(selected.values(), key=lambda r: (r["time_ms"], r["seq"]))
            value = {"schema": "screen-sync-trace-v1", "scope": "latest-preview" if self._preview_id else "capture",
                     "preview_id": self._preview_id, "dropped_records": self._dropped,
                     "writer_error": self._disk_error, "records": records}
            if not self._preview_id and self._restored_preview is not None:
                previous = self._restored_preview['records']
                value['previous_preview'] = {"scope":"previous-backend-preview",
                    "records":previous[:3] + previous[-9:] if len(previous)>12 else previous}
            # Preserve the beginning and end even under a pathological log flood.
            while len(json.dumps(value).encode()) > MAX_TRACE_REPORT_BYTES:
                previous = value.get('previous_preview', {}).get('records', [])
                if len(records) > 2:
                    records.pop(len(records) // 2)
                elif len(previous) > 2:
                    previous.pop(len(previous) // 2)
                elif records:
                    records.pop()
                elif previous:
                    previous.pop()
                else:
                    break
            return json.loads(json.dumps(value))

    def _append(self, rows):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / "screen-sync-trace.jsonl"
        payload = b"".join((json.dumps(row, separators=(",", ":")) + "\n").encode() for row in rows)
        # Never follow a substituted log-file link.
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        if os.fstat(descriptor).st_size + len(payload) > MAX_TRACE_FILE_BYTES:
            os.close(descriptor)
            os.replace(path, self.directory / "screen-sync-trace.previous.jsonl")
            descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "ab") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)

    def _write_loop(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                kind, value = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if kind == "event":
                    self._append([value])
                else:
                    from .diagnostics import _atomic_json
                    self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    _atomic_json(self.directory / "screen-sync-preview.json", value)
            except (OSError, ValueError) as error:
                # Controlled class name only, never a sensitive filesystem path.
                self._disk_error = type(error).__name__
            finally:
                self._queue.task_done()

    def close(self, timeout=0.5):
        self.end_preview("engine-stopped")
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
