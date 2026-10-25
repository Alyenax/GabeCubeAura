"""Persistent, bounded and privacy-safe diagnostics for SteamOS Lab builds."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4
from .distribution import supports_private_tools


MAX_JOURNAL_BYTES = 256 * 1024
MAX_REPORT_BYTES = 48 * 1024
MAX_FIELD_CHARS = 720
SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|cookie|password|refresh[_-]?token|access[_-]?token|secret)",
    re.IGNORECASE,
)
TOKEN_VALUE = re.compile(r"(?:gh[ur]_[A-Za-z0-9_]{12,}|Bearer\s+[A-Za-z0-9._~-]{12,})")
CREDENTIAL_ASSIGNMENT = re.compile(
    r'''\b(?:token|api[_-]?key|password|secret)\s*[=:]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
    re.IGNORECASE,
)
STEAMGRIDDB_KEY = re.compile(r"\b[A-Za-z0-9_-]{28,}\b")
HOME_PATH = re.compile(r"/(?:home|Users)/[^/\s]+")
EVENT_NAME = re.compile(r"[^A-Za-z0-9_.:-]+")


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _read_json(path: Path):
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


class DiagnosticJournal:
    """Write crash-surviving events and build one redacted GitHub report."""

    def __init__(self, state_dir, version: str, logger=None, *, clock=time.time):
        self.state_dir = Path(state_dir).resolve()
        self.version = str(version)
        self.private_tools = supports_private_tools(self.version)
        self.logger = logger
        self.clock = clock
        self.journal_path = self.state_dir / "diagnostics.jsonl"
        self.previous_path = self.state_dir / "diagnostics.previous.jsonl"
        self.marker_path = self.state_dir / "diagnostics-session.json"
        self.state_path = self.state_dir / "diagnostics-state.json"
        self.pixel_studio_log = self.state_dir / "pixel-studio.log"
        self.pixel_studio_previous_log = self.state_dir / "pixel-studio.previous.log"
        self.faceplate_runtime_path = self.state_dir / "faceplate-runtime.json"
        self._lock = threading.RLock()
        self.session_id = uuid4().hex
        self.previous_unclean_session = ""
        self.previous_session_id = ""
        self.previous_activity_at=0
        self._state = self._load_state()
        from .voice_incidents import VoiceIncidents
        self.voice_incidents_path = self.state_dir / 'voice-incidents.json'
        try:
            self.voice_incidents = VoiceIncidents(_read_json(self.voice_incidents_path),
                                                  self.session_id, self.clock)
        except (ValueError, TypeError, AttributeError):
            self.voice_incidents = VoiceIncidents(backend=self.session_id, clock=self.clock)

    def _load_state(self):
        state = _read_json(self.state_path)
        state.setdefault("schema", 1)
        # The user explicitly requested automatic private Lab diagnostics.
        state.setdefault("automatic_upload", self.private_tools)
        state.setdefault("pending_session", "")
        state.setdefault("uploaded_session", "")
        state.setdefault("last_upload_at", 0)
        state.setdefault("last_upload_url", "")
        state.setdefault("last_error", "")
        return state

    def _save_state(self):
        _atomic_json(self.state_path, self._state)

    def _clean_text(self, value):
        text = str(value).replace(str(self.state_dir.parent.parent.parent), "$DECKY_USER_HOME")
        text = HOME_PATH.sub("$DECKY_USER_HOME", text)
        text = TOKEN_VALUE.sub("[redacted-token]", text)
        text = CREDENTIAL_ASSIGNMENT.sub("[redacted-credential]", text)
        # Long opaque strings are never useful in a crash report and can be API keys.
        text = STEAMGRIDDB_KEY.sub("[redacted-credential]", text)
        return text[:MAX_FIELD_CHARS]

    @staticmethod
    def _clean_event(value):
        # Event identifiers are controlled vocabulary, not opaque secrets.
        # Treating their long snake_case names as API keys made crash reports
        # lose the exact operation that preceded a failure.
        event = EVENT_NAME.sub("_", str(value)).strip("_")[:96]
        return event or "unknown"

    def _sanitize(self, value, key=""):
        if SENSITIVE_KEY.search(str(key)):
            return "[redacted]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._clean_text(value)
        if isinstance(value, dict):
            return {
                self._clean_text(name)[:80]: self._sanitize(item, name)
                for name, item in list(value.items())[:32]
            }
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in list(value)[:32]]
        return self._clean_text(type(value).__name__)

    def begin_session(self):
        with self._lock:
            previous = _read_json(self.marker_path)
            previous_id = str(previous.get("session_id", self._state.get("last_finished_session", "")))
            self.previous_session_id=previous_id
            if previous_id:
                try:self.previous_activity_at=min(int(self.clock()),int(self.journal_path.stat().st_mtime))
                except OSError:self.previous_activity_at=int(self.clock())
            if previous_id and previous and not bool(previous.get("clean")):
                self.previous_unclean_session = previous_id
                if previous_id != self._state.get("uploaded_session"):
                    self._state["pending_session"] = previous_id
            self.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            _atomic_json(self.marker_path, {
                "schema": 1,
                "session_id": self.session_id,
                "version": self.version,
                "started_at": int(self.clock()),
                "clean": False,
            })
            self._save_state()
            if self.voice_incidents.recovered:
                _atomic_json(self.voice_incidents_path, self.voice_incidents.snapshot())
            self.record(
                "plugin_session_started",
                previous_session_unclean=bool(self.previous_unclean_session),
            )
            return self.status()

    def finish_session(self):
        with self._lock:
            self.record("plugin_session_finished", clean=True)
            marker = _read_json(self.marker_path)
            if marker.get("session_id") == self.session_id:
                self._state['last_finished_session']=self.session_id
                self._save_state()
                self.marker_path.unlink(missing_ok=True)

    def _rotate_if_needed(self, incoming: int):
        try:
            current = self.journal_path.stat().st_size
        except OSError:
            current = 0
        if current + incoming <= MAX_JOURNAL_BYTES:
            return
        self.previous_path.unlink(missing_ok=True)
        if self.journal_path.exists():
            os.replace(self.journal_path, self.previous_path)
            os.chmod(self.previous_path, 0o600)

    def record(self, event: str, **fields):
        try:
            item = {
                "time": int(self.clock()),
                "session": self.session_id,
                "version": self.version,
                "event": self._clean_event(event),
                "fields": self._sanitize(fields),
            }
            payload = (json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
            with self._lock:
                self.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
                self._rotate_if_needed(len(payload))
                with self.journal_path.open("ab", buffering=0) as handle:
                    handle.write(payload)
                    os.fsync(handle.fileno())
                os.chmod(self.journal_path, 0o600)
                if self.voice_incidents.observe(item):
                    _atomic_json(self.voice_incidents_path, self.voice_incidents.snapshot())
        except Exception as error:
            callback = getattr(self.logger, "warning", None)
            if callable(callback):
                callback(f"[GabeCubeAura] diagnostic write failed: {type(error).__name__}")

    def status(self):
        with self._lock:
            return {
                "schema": 1,
                "automatic_upload": self.private_tools and bool(self._state.get("automatic_upload", True)),
                "private_tools": self.private_tools,
                "pending": bool(self._state.get("pending_session")),
                "previous_session_unclean": bool(self.previous_unclean_session),
                "last_upload_at": int(self._state.get("last_upload_at", 0) or 0),
                "last_upload_url": self._clean_text(self._state.get("last_upload_url", "")),
                "last_error": self._clean_text(self._state.get("last_error", "")),
            }

    def set_automatic_upload(self, enabled: bool):
        with self._lock:
            self._state["automatic_upload"] = self.private_tools and bool(enabled)
            self._save_state()
            self.record("diagnostic_upload_preference", enabled=bool(enabled))
            return self.status()

    @staticmethod
    def _tail(path: Path, maximum: int):
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                if size > maximum:
                    handle.seek(size - maximum)
                data = handle.read(maximum)
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""

    def build_report(self, *, reason="manual", faceplate_artwork_job=None, cinema=None):
        with self._lock:
            journal = self._tail(self.previous_path, 10 * 1024) + self._tail(
                self.journal_path, 24 * 1024,
            )
            companion = self._tail(self.pixel_studio_previous_log, 4 * 1024) + self._tail(
                self.pixel_studio_log, 10 * 1024,
            )
            clean_companion = self._sanitize_blob(companion)
            events = []
            for line in journal.splitlines()[-256:]:
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(item, dict):
                    events.append({
                        "backend_session": self._clean_event(item.get("session", "unknown")),
                        "time": int(item.get("time", 0) or 0),
                        "version": self._clean_text(item.get("version", "")),
                        "event": self._clean_event(item.get("event", "")),
                        "fields": self._sanitize(item.get("fields", {})),
                    })
            report_session = str(self._state.get("pending_session") or self.session_id)
            trigger = "unclean_restart" if self._state.get("pending_session") else str(reason)[:32]
            report = {
                "schema": "gabecubeaura-lab-diagnostic-v1",
                "created_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds"),
                "product": "GabeCubeAura",
                "version": self.version,
                "trigger": trigger,
                "previous_session_unclean": bool(self._state.get("pending_session")),
                "events": events,
                "voice_incidents": self.voice_incidents.snapshot(),
                "pixel_studio_log_tail": clean_companion.splitlines()[-160:],
                "faceplate_runtime": self._faceplate_runtime_snapshot(),
                "faceplate_artwork_job": self._faceplate_artwork_job_snapshot(
                    faceplate_artwork_job,
                ),
                "cinema": self._sanitize(cinema or {}),
                "privacy": {
                    "api_keys_included": False,
                    "authorization_tokens_included": False,
                    "usernames_included": False,
                    "personal_paths_included": False,
                    "process_arguments_included": False,
                    "raw_device_paths_included": False,
                },
            }
            payload = json.dumps(report, separators=(",", ":"), sort_keys=True).encode("utf-8")
            if len(payload) > MAX_REPORT_BYTES:
                report["events"] = events[-96:]
                report["pixel_studio_log_tail"] = clean_companion.splitlines()[-48:]
            return {"report": report, "session": report_session}

    def _faceplate_runtime_snapshot(self):
        """Keep useful routing/worker state without exposing the serial path."""
        value = _read_json(self.faceplate_runtime_path)
        routing = value.get("routing", {}) if isinstance(value.get("routing"), dict) else {}
        worker = value.get("worker", {}) if isinstance(value.get("worker"), dict) else {}
        weather = value.get("weather", {}) if isinstance(value.get("weather"), dict) else {}
        device = value.get("device", {}) if isinstance(value.get("device"), dict) else {}
        brightness = device.get("brightness_control", {})
        brightness = brightness if isinstance(brightness, dict) else {}
        uploads = value.get("uploads", {}) if isinstance(value.get("uploads"), dict) else {}
        preparation = routing.get("preparation", {})
        if not isinstance(preparation, dict):
            preparation = {}
        return self._sanitize({
            "running": bool(value.get("running")),
            "routing": {
                "context": routing.get("context", ""),
                "desired_scene": routing.get("desired_scene", ""),
                "effective_scene": routing.get("effective_scene", ""),
                "generation": routing.get("generation", 0),
                "preparation": {
                    "state": preparation.get("state", ""),
                    "scene": preparation.get("scene", ""),
                    "reason": preparation.get("reason", ""),
                    "error": preparation.get("error", ""),
                },
            },
            "worker": {
                name: worker.get(name)
                for name in (
                    "enabled", "running", "busy", "queued", "generation",
                    "completed_generation", "completed", "dropped", "last_scene",
                    "last_error", "rejected", "last_rejection", "capabilities",
                    "last_queue_age_ms", "ack_ema_ms", "handler_ema_ms",
                    "active_generation", 'active_scene', "superseded_active", "last_completed_at",
                )
            },
            "weather": {
                name: weather.get(name)
                for name in ("phase", "condition", "age_s", "error")
            },
            "player_city": self._player_city_snapshot(value.get("player_city")),
            "device": {
                "available": bool(device.get("available")),
                "busy": bool(device.get("busy")),
                "phase": device.get("phase", ""),
                "brightness_control": {
                    **self._numeric_fields(brightness, (
                        "requested_percent", "target_percent", "last_commanded_percent",
                        "peak_rgb_load", "power_budget",
                    )),
                    "limit_reason": brightness.get("limit_reason")
                        if brightness.get("limit_reason") in ("none", "content-power-budget", "content-unmeasured", "native-unmeasured") else "unknown",
                    "command_acknowledged": False,
                    "estimate_source": brightness.get("estimate_source")
                        if brightness.get("estimate_source") in ("encoded-gif", "content-unmeasured", "native-unmeasured", "not-used") else "unknown",
                },
            },
            "uploads": self._upload_observability_snapshot(uploads),
            "flash_protection": self._flash_protection_snapshot(value.get("flash_protection")),
        })

    def _player_city_snapshot(self, value):
        """Only public game/count/state data; no URLs, paths or exceptions."""
        value = value if isinstance(value, dict) else {}
        result = self._numeric_fields(value, ('appid', 'display_age_s', 'count_refresh_seconds', 'next_refresh_s'))
        for key in ('reason', 'weather', 'phase', 'tier', 'storage_error'):
            if isinstance(value.get(key), str):
                result[key] = value[key][:48]
        sample = value.get('sample')
        sample = sample if isinstance(sample, dict) else {}
        result['sample'] = self._numeric_fields(sample, ('appid', 'players', 'sampled_at', 'sample_age_s', 'next_poll_s'))
        result['sample'].update(state=str(sample.get('state', 'inactive'))[:32],
                                error_code=str(sample.get('error_code', ''))[:48],
                                transport=str(sample.get('transport', ''))[:16],
                                usable=sample.get('usable') is True,
                                in_flight=sample.get('in_flight') is True)
        for key in ('displayed', 'last_attempt'):
            row = value.get(key)
            if not isinstance(row, dict):
                result[key] = None
                continue
            safe = self._numeric_fields(row, ('appid', 'players', 'sampled_at', 'at', 'last_ack_at'))
            for field in ('weather', 'phase', 'outcome'):
                if isinstance(row.get(field), str):
                    safe[field] = row[field][:32]
            result[key] = safe
        return result

    def _flash_protection_snapshot(self, value):
        value = value if isinstance(value, dict) else {}
        names = ("confirmed", "reused", "deferred", "uncertain")
        recent = value.get("recent", [])
        return {
            "enabled": value.get("enabled") is True,
            "policy": str(value.get("policy", ""))[:48],
            "hardware_state": str(value.get("hardware_state", "unknown"))[:32],
            "rate": self._numeric_fields(value, ("capacity", "refill_seconds", "hour_limit", "attempts_last_hour", "tokens", "performance_attempts_session")),
            "performance_unlimited": value.get("performance_unlimited") is True,
            "session": self._numeric_fields(value.get("session"), names),
            "total": self._numeric_fields(value.get("total"), names),
            "persistence_error": str(value.get("persistence_error", ""))[:180],
            "player_city": self._numeric_fields(value.get("player_city"), (
                "shared_background_day_limit", "shared_day_limit", "reserved_returns",
                "hour_limit", "burst_capacity", "retry_after_seconds")),
            "recent": [{key: event.get(key) for key in ("at", "outcome", "scene", "bytes")}
                       for event in recent[-8:] if isinstance(event, dict)] if isinstance(recent, list) else [],
        }

    @staticmethod
    def _numeric_fields(value, names):
        value = value if isinstance(value, dict) else {}
        return {
            name: value.get(name)
            for name in names
            if isinstance(value.get(name), (int, float))
            and not isinstance(value.get(name), bool)
        }

    def _upload_observability_snapshot(self, uploads):
        """Whitelist bounded flash-write telemetry; never include hashes or paths."""
        uploads = uploads if isinstance(uploads, dict) else {}
        counter_names = (
            'unconfirmed',
            "attempts", "writes", "writes_measured", "identical", "failed",
            "payload_bytes_written", "unmeasured_legacy_writes",
        )
        estimate = uploads.get("estimate", {})
        estimate = estimate if isinstance(estimate, dict) else {}
        journal = uploads.get("journal", [])
        safe_journal = []
        if isinstance(journal, list):
            for item in journal[-8:]:
                if not isinstance(item, dict):
                    continue
                safe_journal.append({
                    name: item.get(name)
                    for name in (
                        "timestamp_utc", "reason", "scene", "size_bytes",
                        "failed_chunk", "chunk_status", "payload_bytes_confirmed",
                        "ack_ms", "duration_ms", "outcome", "error",
                    )
                    if item.get(name) is not None
                })
        return {
            "session": self._numeric_fields(uploads.get("session"), counter_names),
            "today_utc": {
                **self._numeric_fields(uploads.get("today_utc"), counter_names),
                "date_utc": (
                    uploads.get("today_utc", {}).get("date_utc", "")
                    if isinstance(uploads.get("today_utc"), dict) else ""
                ),
            },
            "total": self._numeric_fields(uploads.get("total"), counter_names),
            "estimate": {
                **self._numeric_fields(estimate, (
                    "assumed_flash_bytes", "logical_flash_equivalents",
                    "unmeasured_legacy_writes",
                )),
                "method": estimate.get("method", ""),
                "confidence": estimate.get("confidence", ""),
            },
            "journal": safe_journal,
        }

    def _faceplate_artwork_job_snapshot(self, value):
        """Keep the last compiler outcome without source URLs or local paths."""
        value = value if isinstance(value, dict) else {}
        return self._sanitize({
            name: value.get(name)
            for name in (
                "state", "stage", "percent", "detail", "appid", "mode",
                "updated_at",
            )
            if value.get(name) is not None
        })

    def _sanitize_blob(self, value: str):
        lines = []
        for line in str(value).splitlines()[-512:]:
            lines.append(self._clean_text(line))
        return "\n".join(lines)

    def upload_succeeded(self, session: str, url: str):
        with self._lock:
            self._state.update({
                "uploaded_session": str(session),
                "pending_session": "" if self._state.get("pending_session") == session else self._state.get("pending_session", ""),
                "last_upload_at": int(self.clock()),
                "last_upload_url": self._clean_text(url),
                "last_error": "",
            })
            self._save_state()
            self.record("diagnostic_upload_succeeded")
            return self.status()

    def upload_failed(self, error):
        with self._lock:
            self._state["last_error"] = self._clean_text(error)
            self._save_state()
            self.record("diagnostic_upload_failed", error=self._clean_text(error))
            return self.status()

    def automatic_upload_due(self):
        with self._lock:
            pending = str(self._state.get("pending_session", ""))
            return bool(
                self.private_tools
                and self._state.get("automatic_upload", True)
                and pending
                and pending != self._state.get("uploaded_session")
            )
