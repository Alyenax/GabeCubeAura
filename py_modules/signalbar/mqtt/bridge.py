"""Publish GabeCubeAura to Home Assistant over MQTT (Phase 1: report only, no commands)."""

from __future__ import annotations

import collections
import json
import os
import socket
import stat
import threading
import time
from datetime import datetime, timezone

from .client import MqttClient
from .discovery import (
    BASE_EVENT_TYPES,
    DEFAULT_KEY_ART_TYPE,
    Topics,
    discovery_messages,
    event_area,
    faceplate_discovery,
    key_art_discovery,
    node_id_for,
)
from .policy import PublishingPolicy
from .snapshot import _json_safe, build_snapshot, frontend_connected, is_redacted

# Areas are offered once a second; policy.py decides which are worth publishing (deadbands, slow
# cadences for performance, countdown and the large status blob, or everything in Turbo mode).
SNAPSHOT_INTERVAL_S = 1.0
KEY_ART_LIMIT = 2 * 1024 * 1024
KEY_ART_RETRY_S = 30.0
# Events queued while the broker was away are history, not news: firing automations for an
# achievement from hours ago on reconnect would be wrong.
EVENT_MAX_AGE_S = 60.0
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def image_type(data) -> str | None:
    """Content type from the file's magic bytes; custom (non-Steam) grid art is often PNG or WebP."""
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _clean_event(value, depth=0):
    """Drop redacted keys (any depth) from hub event data; the bridge never trusts event payloads."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        return {key: _clean_event(child, depth + 1) for key, child in value.items() if not is_redacted(key)}
    if isinstance(value, (list, tuple)):
        return [_clean_event(child, depth + 1) for child in value]
    return value


class MqttBridge:
    def __init__(self, config, engine, faceplate_status, update_status, logger=None, hostname=None,
                 client_factory=MqttClient, clock=time.monotonic, wall=time.time, run_thread=True):
        self.config = config
        self._run_thread = run_thread
        self.engine = engine
        self._faceplate_status = faceplate_status
        self._update_status = update_status
        self.log = logger
        self.hostname = hostname or socket.gethostname()
        self._client_factory = client_factory
        self._clock, self._wall = clock, wall
        self.client = None
        self._unsubscribe = None
        self._lock = threading.Lock()
        self._events = collections.deque(maxlen=128)
        self._needs_full = False
        self._policy = PublishingPolicy()  # what each area last sent, and when
        self._turbo = False           # the Turbo setting the policy last ran with
        self._last_snapshot_at = None
        self._connected_key = None
        self._event_types = {area: list(types) for area, types in BASE_EVENT_TYPES.items()}
        self._previous = {}
        self._stale_dropped = 0
        self._generation = 0          # bumped by start(); the worker resets its state when it sees a change
        self._seen_generation = 0
        self._step_lock = threading.Lock()  # serialises step() so a slow old worker cannot race a new one
        self._lifecycle_lock = threading.RLock()  # start/stop/reconfigure; never taken by the worker
        self._key_art_state = None    # which appid the retained image shows: None unknown / appid / "empty"
        self._key_art_retry = (None, 0.0)
        self._key_art_type = DEFAULT_KEY_ART_TYPE  # content_type the image entity's discovery declares
        self._faceplate_described = False  # whether the Faceplate sensor's discovery config is published
        self._version = None
        self._game = (0, None)        # (appid, started wall time)
        self._download_active = False
        self._frontend_published = None
        self._stop_event = threading.Event()
        self._thread = None
        self.join_timeout_s = 3.0
        self.topics = None

    # ---- lifecycle -----------------------------------------------------
    # Settings saves run reconfigure() on executor threads; two overlapping saves must not interleave
    # stop() and start() (two clients, two workers). Reentrant: reconfigure() holds it across both.
    def start(self):
        with self._lifecycle_lock:
            self._start()

    def stop(self):
        with self._lifecycle_lock:
            self._stop()

    def reconfigure(self):
        with self._lifecycle_lock:
            self._stop()
            self._start()  # start() bumps the generation; the worker resets its own state

    def _start(self):
        if self.client is not None:
            return
        settings = self.config.public()
        if not settings["enabled"] or not settings["host"]:
            return
        self.topics = Topics(settings["base_topic"], node_id_for(self.hostname), settings["discovery_prefix"])
        self._connected_key = None
        self._key = self.config.connection_key()
        with self._lock:
            self._generation += 1
            self._needs_full = True
        self.client = self._client_factory(
            settings["host"], settings["port"], f"gabecubeaura-{self.topics.node_id}",
            username=settings["username"], password=self.config.password(), tls=settings["tls"],
            will=(self.topics.availability, "offline", True),
            on_connect=self._on_connect, on_message=self._on_message, logger=self.log,
        )
        self.client.subscribe(self.topics.ha_status)
        self._unsubscribe = self.engine.subscribe(self._on_event)
        self.client.start()
        # A fresh Event per start: an old worker stuck in a slow publish keeps its own, already-set one.
        self._stop_event = threading.Event()
        if self._run_thread:
            self._thread = threading.Thread(target=self._run, args=(self._stop_event,),
                                            name="gabecubeaura-mqtt-bridge", daemon=True)
            self._thread.start()

    def _stop(self):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self.join_timeout_s)
        self._thread = None
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        client, self.client = self.client, None
        if client is not None:
            if client.connected and self.topics:
                client.publish(self.topics.availability, "offline", retain=True)
            client.stop()

    def status(self) -> dict:
        client = self.client
        return {
            "enabled": bool(self.config.public()["enabled"]),
            "connected": bool(client and client.connected),
            "connected_with_current_settings": bool(
                client and client.connected_once and self._connected_key == self.config.connection_key()),
            # last_error means "why the previous connection ended"; the client keeps it across reconnects.
            "last_error": (client.last_error if client and not client.connected else "") or "",
            "messages_out": client.messages_out if client else 0,
            "events_dropped": self._events_dropped(),
        }

    def _events_dropped(self) -> int:
        return int(getattr(self.engine.hub, "dropped", 0) or 0) + self._stale_dropped

    # ---- callbacks (client and hub threads; keep them tiny) -------------
    def _on_connect(self):
        with self._lock:
            self._needs_full = True
            self._connected_key = self._key

    def _on_message(self, topic, payload, retain):
        if self.topics and topic == self.topics.ha_status and payload == b"online":
            with self._lock:
                self._needs_full = True

    def _on_event(self, kind, data):
        with self._lock:
            if kind == "steam.download":
                self._download_active = bool((data or {}).get("active"))
            self._events.append((self._clock(), kind, dict(data or {})))

    # ---- worker --------------------------------------------------------
    def _run(self, stop_event):
        failures = 0
        while not stop_event.wait(0.25):
            try:
                self.step()
                failures = 0
            except Exception as error:  # noqa: BLE001 - never let the bridge thread die silently
                failures += 1
                if self.log:
                    self.log.warning(f"[GabeCubeAura] MQTT bridge step failed: {error}")
                if failures >= 3:
                    stop_event.wait(min(60.0, 5.0 * failures))

    def step(self):
        with self._step_lock:
            self._step()

    def _step(self):
        client = self.client
        if client is None:
            return
        with self._lock:
            generation = self._generation
        if generation != self._seen_generation:
            self._seen_generation = generation
            self._policy.reset()
            self._key_art_state = None
            self._key_art_retry = (None, 0.0)
            self._frontend_published = None
            self._faceplate_described = False  # new topics or broker: described again by discovery
        if not client.connected:
            with self._lock:
                self._needs_full = True
            return
        with self._lock:
            full, self._needs_full = self._needs_full, False
            queued = list(self._events)
            self._events.clear()
        now = self._clock()
        events = []
        for stamped, kind, data in queued:
            if now - stamped > EVENT_MAX_AGE_S:
                self._stale_dropped += 1
                continue
            try:
                area, event_type = event_area(kind, data)
                payload = {**_json_safe(_clean_event(data)), "event_type": event_type}
            except Exception:  # noqa: BLE001 - one malformed event must not lose the batch
                self._stale_dropped += 1
                continue
            events.append((area, event_type, payload))
        new_types = False
        for area, event_type, _ in events:
            if event_type not in self._event_types.setdefault(area, []):
                self._event_types[area].append(event_type)
                new_types = True
        if full or new_types:
            self._publish_discovery(client)
        if full:
            client.publish(self.topics.availability, "online", retain=True)
            self._policy.reset()  # a full republish sends every area now, whatever its cadence
            self._frontend_published = None
            self._key_art_state = None
            self._key_art_retry = (None, 0.0)
        for area, _, payload in events:
            try:
                client.publish(self.topics.event(area), _json(payload))
            except Exception:  # noqa: BLE001 - e.g. unserialisable payload; keep the rest of the batch
                self._stale_dropped += 1
        if full or self._last_snapshot_at is None or now - self._last_snapshot_at >= SNAPSHOT_INTERVAL_S:
            self._last_snapshot_at = now
            self._publish_snapshot(client, full, now)

    def _publish_discovery(self, client):
        version = self.engine.status().get("version") if hasattr(self.engine, "status") else None
        self._version = version
        # The Faceplate sensor exists only while a faceplate service reports status. Without one (this
        # plugin has no faceplate support, or it failed to start) Home Assistant gets no entity at all.
        faceplate = isinstance(self._safe(self._faceplate_status), dict)
        published = True
        for topic, payload in discovery_messages(self.topics, version, self.hostname, self._event_types,
                                                 self._key_art_type, faceplate=faceplate):
            ok = client.publish(topic, _json(payload), retain=True)
            if payload["unique_id"].endswith("_faceplate"):
                published = ok
        self._faceplate_described = faceplate and bool(published)

    def _publish_faceplate_discovery(self, client):
        """Describe the Faceplate sensor once a faceplate service appears after discovery ran."""
        topic, payload = faceplate_discovery(self.topics, self._version, self.hostname)
        if client.publish(topic, _json(payload), retain=True):
            self._faceplate_described = True

    def _publish_snapshot(self, client, full=False, now=None):
        now = self._clock() if now is None else now
        status = self.engine.status()
        appid = int((status.get("game") or {}).get("appid") or 0)
        if appid != self._game[0]:
            self._game = (appid, self._wall() if appid else None)
        started = self._game[1]
        frontend_up = frontend_connected(status)
        if not frontend_up:
            # The Decky frontend may die without sending active=False; the flag must not return stale.
            with self._lock:
                self._download_active = False
        facts = {
            "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat() if started else "",
            "session_minutes": round((self._wall() - started) / 60.0, 1) if started else 0.0,
            "download_active": self._download_active and frontend_up,
            "events_dropped": self._events_dropped(),
            "frontend_connected": frontend_up,
        }
        snapshot = build_snapshot(status, self._safe(self._faceplate_status), self._safe(self._update_status), facts)
        if snapshot["faceplate"]["available"] and not self._faceplate_described:
            # Before its state, so Home Assistant has the entity when the state arrives.
            self._publish_faceplate_discovery(client)
        frontend = "online" if facts["frontend_connected"] else "offline"
        if frontend != self._frontend_published:
            client.publish(self.topics.frontend, frontend, retain=True)
            self._frontend_published = frontend
        # Read every step, so switching Turbo mode needs no reconnect.
        turbo = bool(self.config.public().get("turbo"))
        if turbo != self._turbo:
            # Either direction: resend every area now in the new mode, rather than wait out the old
            # mode's deadbands and cadences.
            self._turbo = turbo
            self._policy.reset()
        for area, payload in snapshot.items():
            shaped = self._policy.shape(area, payload, turbo)
            text = _json(shaped)
            if self._policy.due(area, shaped, text, now, turbo) and client.publish(
                    self.topics.state(area), text, retain=True):
                self._policy.published(area, shaped, text, now)
        self._derive_events(client, snapshot)
        self._publish_key_art(client, snapshot["game"], now)

    def _derive_events(self, client, snapshot):
        current = {
            "thermal": snapshot["performance"]["thermal_protection"],
            "light_bar": snapshot["light_bar"]["owner"],
            "countdown": snapshot["countdown"]["active"],
        }
        previous, self._previous = self._previous, current
        if not previous:
            return
        if current["thermal"] != previous["thermal"]:
            client.publish(self.topics.event("thermal"),
                           _json({"event_type": "tripped" if current["thermal"] else "recovered"}))
        if current["light_bar"] != previous["light_bar"]:
            client.publish(self.topics.event("light_bar"),
                           _json({"event_type": "owner_changed", "owner": current["light_bar"]}))
        if current["countdown"] != previous["countdown"]:
            client.publish(self.topics.event("countdown"), _json({
                "event_type": "started" if current["countdown"] else "ended",
                "source": snapshot["countdown"]["source"]}))

    def _publish_key_art(self, client, game, now):
        appid = game["appid"]
        if not appid:
            # Game stopped: clear the retained image so HA does not show the last game forever.
            if self._key_art_state != "empty" and client.publish(self.topics.key_art_image, b"", retain=True):
                self._key_art_state = "empty"
            return
        if self._key_art_state == appid:
            return
        retry_appid, retry_at = self._key_art_retry
        if retry_appid == appid and now < retry_at:
            return
        art = self._read_key_art(appid)
        if art is not None:
            data, content_type = art
            if self._publish_key_art_type(client, content_type) and client.publish(
                    self.topics.key_art_image, data, retain=True):
                self._key_art_state = appid
                self._key_art_retry = (None, 0.0)
                return
        elif self._key_art_state != "empty":
            # The retained image still shows another game (or one from before a restart): clear it now
            # rather than leave the wrong art up while the retry waits.
            if client.publish(self.topics.key_art_image, b"", retain=True):
                self._key_art_state = "empty"
        self._key_art_retry = (appid, now + KEY_ART_RETRY_S)

    def _publish_key_art_type(self, client, content_type) -> bool:
        """Home Assistant decodes the image by its discovery content_type: update it before new bytes."""
        if content_type == self._key_art_type:
            return True
        topic, payload = key_art_discovery(self.topics, self._version, self.hostname, content_type)
        if not client.publish(topic, _json(payload), retain=True):
            return False
        self._key_art_type = content_type
        return True

    @staticmethod
    def _read_key_art(appid):
        """(bytes, content type) or None. The grid folder is user-writable and we run as root: no symlinks,
        regular files only (O_NONBLOCK so a FIFO swapped in cannot block the open), JPEG/PNG/WebP only."""
        try:
            from signalbar.steam import find_library_artwork
            path = find_library_artwork(appid, "hero")
            if path is None:
                return None
            fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > KEY_ART_LIMIT:
                    return None
                data = handle.read(KEY_ART_LIMIT + 1)
        except OSError:
            return None
        if not data or len(data) > KEY_ART_LIMIT:
            return None
        content_type = image_type(data)
        return None if content_type is None else (data, content_type)

    @staticmethod
    def _safe(getter):
        try:
            return getter()
        except Exception:  # noqa: BLE001 - a missing service just means no data for that area
            return None
