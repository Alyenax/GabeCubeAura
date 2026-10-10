"""Publish GabeCubeAura to Home Assistant over MQTT, and apply the settings Home Assistant may change.

Report only (the default) publishes state and events and refuses every command. A device whose level
is "settings" gets a switch, select or number per controllable setting (schema.py) and accepts
commands on <root>/set/<key>: checked here, coalesced per key, applied through the UI's own
set_setting on Decky's event loop (the apply_setting callable from main.py), then read back.
"""

from __future__ import annotations

import collections
import json
import os
import re
import socket
import stat
import threading
import time
from datetime import datetime, timezone

from .advertised import AdvertisedTopics
from .client import MqttClient
from .discovery import (
    BASE_EVENT_TYPES,
    DEFAULT_KEY_ART_TYPE,
    PRESET_NOTE,
    Topics,
    discovery_messages,
    event_area,
    faceplate_discovery,
    key_art_discovery,
    node_id_for,
    setting_discovery,
)
from .policy import PublishingPolicy
from .schema import DEVICES, build_schema
from .snapshot import _json_safe, build_snapshot, frontend_connected, is_redacted

# Areas are offered once a second; policy.py decides which are worth publishing (deadbands, slow
# cadences for performance, countdown and the large status blob, or everything in Turbo mode).
SNAPSHOT_INTERVAL_S = 1.0
KEY_ART_LIMIT = 2 * 1024 * 1024
KEY_ART_RETRY_S = 30.0
# Events queued while the broker was away are history, not news: firing automations for an
# achievement from hours ago on reconnect would be wrong.
EVENT_MAX_AGE_S = 60.0
# A dragged slider sends a stream of values: apply the newest once a second per setting, not each one.
COALESCE_S = 1.0
# CPU load needs two /proc/stat samples, so the engine's first status has none. The first performance
# publish waits up to this long for a reading rather than record "unknown" in Home Assistant (the
# 30-second cadence would then keep it there). Past it, a machine that never has one publishes as is.
PERFORMANCE_HOLD_S = 10.0
ERROR_LIMIT = 200
DEVICE_NAMES = {"light_bar": "Light bar", "faceplate": "Faceplate"}
_KEY = re.compile(r"[a-z0-9_]{1,64}")  # fullmatch only
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


def _same(current, value) -> bool:
    """Whether a command would change nothing (True is not 1 here; 45 equals 45.0)."""
    if isinstance(current, bool) or isinstance(value, bool):
        return current is value
    if isinstance(current, (int, float)) and isinstance(value, (int, float)):
        return float(current) == float(value)
    return current == value


def _shown(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:40]


class MqttBridge:
    def __init__(self, config, engine, faceplate_status, update_status, logger=None, hostname=None,
                 client_factory=MqttClient, clock=time.monotonic, wall=time.time, run_thread=True,
                 read_settings=None, apply_setting=None, schema=None, advertised=None):
        self.config = config
        # read_settings() -> the settings store's current values; apply_setting(key, value) runs the UI's
        # set_setting on Decky's loop and raises ValueError/TimeoutError. Without both, commands are refused.
        self._read_settings = read_settings
        self._apply_setting = apply_setting
        self.schema = schema if schema is not None else build_schema()
        # Retained settings topics on the broker (main.py: persisted next to mqtt.json; else memory only).
        self._advertised = advertised if advertised is not None else AdvertisedTopics()
        self._advertised_logged = ""  # the advertised.json problem last logged, so each is logged once
        self._described = None        # devices whose setting entities Home Assistant has; None = unknown
        self._settings_text = None    # the settings state JSON last published
        self._commands = {}           # key -> (value, apply at): Home Assistant commands waiting to apply
        self._last_error = ""         # the last refusal; cleared when that same setting later applies
        self._last_error_key = None   # the command key _last_error belongs to
        self._last_logged = ""        # the refusal last logged; reset when a command applies, so a recurrence logs again
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
        self._performance_held_at = None  # when the first performance publish began waiting for CPU load
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
            # A late message from the old client thread can queue after stop() cleared; drop it here.
            self._commands.clear()
        self._log_advertised_error()  # e.g. advertised.json unreadable when it was loaded
        self.client = self._client_factory(
            settings["host"], settings["port"], f"gabecubeaura-{self.topics.node_id}",
            username=settings["username"], password=self.config.password(), tls=settings["tls"],
            will=(self.topics.availability, "offline", True),
            on_connect=self._on_connect, on_message=self._on_message, logger=self.log,
        )
        self.client.subscribe(self.topics.ha_status)
        # Always subscribed, even at Report only: a refused command then says why in Last command error.
        self.client.subscribe(self.topics.commands)
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
        with self._lock:
            self._commands.clear()  # never apply a command after the bridge stopped
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
        settings = self.config.public()
        # The settings page's step-by-step line (home_assistant_status.ts). Off: no client running.
        phase, reason, retry_in = "off", "", None
        if client is not None:
            if client.connected:
                phase = "connected"
            else:
                reason = getattr(client, "last_reason", "") or ""
                retry = getattr(client, "retry_in", None)
                retry_in = retry() if callable(retry) else None
                phase = "waiting_retry" if retry_in is not None else "connecting"
        host = settings["host"] if client is not None else ""
        return {
            "phase": phase,
            "reason": reason[:ERROR_LIMIT],
            "retry_in_s": None if retry_in is None else round(retry_in, 1),
            # Typed by the user on that page; never the password.
            "broker": (f"[{host}]:{settings['port']}" if ":" in host else f"{host}:{settings['port']}") if host else "",
            "username": settings["username"] if client is not None else "",
            "topic_root": self.topics.root if client is not None and self.topics else "",
            "enabled": bool(self.config.public()["enabled"]),
            "connected": bool(client and client.connected),
            "connected_with_current_settings": bool(
                client and client.connected_once and self._connected_key == self.config.connection_key()),
            # last_error means "why the previous connection ended"; the client keeps it across reconnects.
            "last_error": (client.last_error if client and not client.connected else "") or "",
            "messages_out": client.messages_out if client else 0,
            "events_dropped": self._events_dropped(),
            # The settings page shows the faceplate's level only when the faceplate has settings to offer.
            "faceplate_controls": bool(self.schema.for_device("faceplate")),
            "command_error": self._last_error,
        }

    def _events_dropped(self) -> int:
        return int(getattr(self.engine.hub, "dropped", 0) or 0) + self._stale_dropped

    # ---- callbacks (client and hub threads; keep them tiny) -------------
    def _on_connect(self):
        with self._lock:
            self._needs_full = True
            self._connected_key = self._key

    def _on_message(self, topic, payload, retain):
        topics = self.topics
        if topics is None:
            return
        if topic == topics.ha_status:
            if payload == b"online":
                with self._lock:
                    self._needs_full = True
            return
        if topic.startswith(topics.command_prefix):
            self._on_command(topic[len(topics.command_prefix):], payload, retain)

    def _on_command(self, key, payload, retain):
        """Client thread: check the command and queue it; the worker applies it (never this thread)."""
        name = key if _KEY.fullmatch(key) else "(unreadable)"
        if retain:
            # A retained command would replay on every reconnect and snap the setting back.
            if self.log:
                self.log.info(f"[GabeCubeAura] ignored a retained Home Assistant command for {name}")
            return
        if payload in (b"", ""):
            # How MQTT tools clear a retained topic (it arrives live, retain=0): not a command, not an error.
            if self.log:
                self.log.debug(f"[GabeCubeAura] ignored an empty Home Assistant command for {name}")
            return
        if key in self.schema.local_only:
            # GabeCubeAura's own list (store.LOCAL_ONLY_SETTINGS), whatever the level.
            self._reject(key, f"{name}: can only be changed on the Steam Machine")
            return
        control = self.schema.controls.get(key)
        if control is None:
            self._reject(key, f"{name}: not a setting Home Assistant can change")
            return
        if not self._level_allows(control):
            self._reject(key, f"{name}: {DEVICE_NAMES[control.device]} is set to Report only")
            return
        try:
            value = control.parse(payload)
        except ValueError as error:
            self._reject(key, f"{name}: {error}")
            return
        with self._lock:
            pending = self._commands.get(key)
            # Keep the first command's deadline: a stream of values applies once a second, newest wins.
            apply_at = pending[1] if pending else self._clock() + COALESCE_S
            self._commands[key] = (value, apply_at)

    def _level_allows(self, control) -> bool:
        return self.config.public().get(f"{control.device}_level") == "settings"

    def _reject(self, key, message):
        message = message[:ERROR_LIMIT]
        with self._lock:
            repeated, self._last_error = message == self._last_logged, message
            self._last_error_key = key  # only this setting applying later clears the refusal
            self._last_logged = message
        # A misbehaving automation can send the same refused command many times a second: log it once.
        if self.log and not repeated:
            self.log.warning(f"[GabeCubeAura] Home Assistant command refused: {message}")

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
                self.step(stop_event)
                failures = 0
            except Exception as error:  # noqa: BLE001 - never let the bridge thread die silently
                failures += 1
                if self.log:
                    self.log.warning(f"[GabeCubeAura] MQTT bridge step failed: {error}")
                if failures >= 3:
                    stop_event.wait(min(60.0, 5.0 * failures))

    def step(self, stop_event=None):
        """One worker pass. stop_event is the calling worker's own (tests and direct calls: the current)."""
        with self._step_lock:
            self._step(self._stop_event if stop_event is None else stop_event)

    def _step(self, stop_event):
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
            self._described = None
            self._settings_text = None
        # Before the connection check: a command Home Assistant already sent applies even if the
        # connection dropped meanwhile.
        self._apply_due_commands(stop_event)
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
            self._described = None     # describe (or clear) setting entities again
            self._settings_text = None
        for area, _, payload in events:
            try:
                client.publish(self.topics.event(area), _json(payload))
            except Exception:  # noqa: BLE001 - e.g. unserialisable payload; keep the rest of the batch
                self._stale_dropped += 1
        if full or self._last_snapshot_at is None or now - self._last_snapshot_at >= SNAPSHOT_INTERVAL_S:
            self._last_snapshot_at = now
            self._publish_snapshot(client, full, now)
        # Every step (a dict copy and a string compare): a level change or an applied command shows in
        # Home Assistant within a quarter second; an unchanged state is never resent.
        self._sync_settings(client)

    # ---- settings (level "settings") ------------------------------------
    def _controlled_devices(self) -> frozenset:
        settings = self.config.public()
        return frozenset(device for device in DEVICES if settings.get(f"{device}_level") == "settings")

    def _sync_settings(self, client):
        """Describe or clear setting entities when a level changes (live), then publish their state."""
        active = self._controlled_devices()
        if active != self._described:
            if not self._describe_settings(client, active):
                return  # retried on the next step; retained configs make repeats harmless
            self._described = active
            self._settings_text = None
        if not active:
            return
        values = self._safe(self._read_settings) if self._read_settings else None
        values = values if isinstance(values, dict) else {}
        state = {key: values[key] for key in self.schema.reported(active) if key in values}
        text = _json(_json_safe(state))
        if text != self._settings_text and client.publish(self.topics.state("settings"), text, retain=True):
            self._settings_text = text

    def _describe_settings(self, client, active) -> bool:
        """Advertise the active devices' entities; clear exactly what was advertised and is no longer
        wanted (recorded in AdvertisedTopics, so also what an earlier run left behind). Nothing
        recorded and nothing active: nothing is sent."""
        previous = self._described
        wanted, new = set(), []
        for control in self.schema.controls.values():
            if control.device in active:
                topic, payload = setting_discovery(self.topics, self._version, self.hostname, control)
                wanted.add(topic)
                # Previous None (connect, Home Assistant restart): describe every active entity again.
                if previous is None or control.device not in previous:
                    new.append((topic, payload))
        if active:
            wanted |= {self.topics.state("settings"), self.topics.preset_note}
        # Recorded before publishing: a crash in between still gets these cleared on a later start.
        self._advertised.add(wanted)
        self._log_advertised_error()
        ok = True
        if active:
            ok = client.publish(self.topics.preset_note, _json(PRESET_NOTE), retain=True) and ok
        for topic, payload in new:
            ok = client.publish(topic, _json(payload), retain=True) and ok
        # An empty retained config deletes the entity; an empty state or note deletes the topic. Every
        # config goes before the state and note, in this same pass (a later pass would let the level
        # return first and leave the entities unadvertised): an empty state while the entities still
        # exist makes Home Assistant render every template against nothing.
        stale = sorted(self._advertised.topics() - wanted, key=lambda topic: (not topic.endswith("/config"), topic))
        cleared = [topic for topic in stale if client.publish(topic, "", retain=True)]
        self._advertised.discard(cleared)
        self._log_advertised_error()
        done = ok and len(cleared) == len(stale)
        if not done and cleared:
            # Some entities are gone but _described still names their device: if the level returns to
            # that set before the retry, nothing would advertise them again. Unknown: describe afresh.
            self._described = None
        return done

    def _log_advertised_error(self):
        """One warning per new advertised.json problem (unreadable at start, or a failed save)."""
        error = self._advertised.error
        if error != self._advertised_logged:
            self._advertised_logged = error
            if error and self.log:
                self.log.warning(f"[GabeCubeAura] {error}")

    def _apply_due_commands(self, stop_event):
        now = self._clock()
        with self._lock:
            due = sorted((at, key, value) for key, (value, at) in self._commands.items() if at <= now)
            for _, key, _ in due:
                del self._commands[key]
        for _, key, value in due:
            # This worker's own event, never self._stop_event: after a join timed out, start() has replaced
            # that with the new worker's unset one, and this old worker would carry on applying.
            if stop_event.is_set():  # unloading: stop() is joining this worker, so apply nothing more
                break
            self._apply_command(key, value)

    def _apply_command(self, key, value):
        control = self.schema.controls[key]
        if not self._level_allows(control):  # the level may have dropped while the command waited
            self._reject(key, f"{key}: {DEVICE_NAMES[control.device]} is set to Report only")
            return
        if self._read_settings is None or self._apply_setting is None:
            self._reject(key, f"{key}: settings control is not available")
            return
        values = self._safe(self._read_settings)
        if not isinstance(values, dict):
            # Without the current value the no-op guard below cannot work: refuse rather than write.
            self._reject(key, f"{key}: settings control is not available")
            return
        current = values.get(key)
        if _same(current, value):
            # Never write an unchanged value: the store treats any write of a preset-controlled key as
            # an edit and leaves the display preset (store.update), even when nothing changes.
            return
        try:
            self._apply_setting(key, value)
        except ValueError as error:
            self._reject(key, f"{key}: {error}")  # GabeCubeAura's own words, e.g. choose a city first
            return
        except TimeoutError:
            self._reject(key, f"{key}: GabeCubeAura did not apply the change in time")
            return
        except Exception as error:  # noqa: BLE001 - type only: a message could carry paths
            self._reject(key, f"{key}: not applied ({type(error).__name__})")
            return
        stored = (self._safe(self._read_settings) or {}).get(key)
        if not _same(stored, value):
            # The store changed it silently (a dependent clamp); the state publish shows the real value.
            self._reject(key, f"{key}: GabeCubeAura kept {_shown(stored)} instead of {_shown(value)}")
            return
        with self._lock:
            self._last_logged = ""  # applied: the same refusal recurring later is news again
            # The refused setting itself now took: the sensor and the settings page stop showing its
            # refusal. Another setting applying must not wipe it (state/bridge may not have sent it yet).
            if self._last_error_key == key:
                self._last_error, self._last_error_key = "", None

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
            "last_error": self._last_error,
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
            if area == "performance" and self._hold_performance(payload, now):
                continue
            shaped = self._policy.shape(area, payload, turbo)
            text = _json(shaped)
            if self._policy.due(area, shaped, text, now, turbo) and client.publish(
                    self.topics.state(area), text, retain=True):
                self._policy.published(area, shaped, text, now)
        self._derive_events(client, snapshot)
        self._publish_key_art(client, snapshot["game"], now)

    def _hold_performance(self, payload, now) -> bool:
        """Whether to skip the performance area now: only before its first publish since a reset, while
        CPU load has no reading yet, for at most PERFORMANCE_HOLD_S. Held, not published without the
        field: the sensors' templates render a missing field as unknown too. Thermal protection is
        news and is never held; a retained reading from an earlier run stays shown meanwhile."""
        if (self._policy.sent("performance") or payload.get("cpu_load") is not None
                or payload.get("thermal_protection")):
            self._performance_held_at = None
            return False
        if self._performance_held_at is None:
            self._performance_held_at = now
        return now - self._performance_held_at < PERFORMANCE_HOLD_S

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
