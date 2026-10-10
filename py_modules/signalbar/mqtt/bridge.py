"""Publish GabeCubeAura to Home Assistant over MQTT and apply what it may change.

At Report only (the default) the bridge publishes state and events and
refuses every command. At "settings" a device also gets a switch, select or
number for each setting schema.py allows; commands arrive on <root>/set/<key>
and are checked here, coalesced per key and applied through the UI's own
set_setting on Decky's event loop.

"drive" (light bar only) adds a Home Assistant light and alert buttons on
top. Their commands arrive on <root>/drive/<name>, are checked on the client
thread and applied by the worker: colours and frames to the engine's Home
Assistant display slot, alerts through the light event queue.
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
from .config import CONTROL_LEVELS
from .discovery import (
    BASE_EVENT_TYPES,
    DEFAULT_KEY_ART_TYPE,
    GAME_ART,
    art_discovery,
    PRESET_NOTE,
    Topics,
    discovery_messages,
    drive_discovery,
    event_area,
    faceplate_discovery,
    key_art_discovery,
    node_id_for,
    setting_discovery,
)
from .drive import light_state, parse_alert, parse_frame, parse_light
from .policy import PublishingPolicy
from .routed import RoutedDisplays
from .schema import DEVICES, build_schema
from .snapshot import _json_safe, build_snapshot, frontend_connected, is_redacted

SNAPSHOT_INTERVAL_S = 1.0
KEY_ART_LIMIT = 2 * 1024 * 1024
KEY_ART_RETRY_S = 30.0
# Events queued while the broker was away are history, not news. Replaying an
# achievement from hours ago would fire automations for nothing.
EVENT_MAX_AGE_S = 60.0
COALESCE_S = 1.0
# CPU load needs two /proc/stat samples, so the first status has none. Waiting
# a little keeps Home Assistant from recording "unknown" for the next 30 s.
PERFORMANCE_HOLD_S = 10.0
ERROR_LIMIT = 200
DRIVE_INTERVAL_S = 0.25
UPDATE_BUSY_PHASES = frozenset({"installing", "swap_started", "swapped", "restart_pending"})
DRIVE_PARSERS = {"light": parse_light, "frame": parse_frame, "alert": parse_alert}
ALERT_BACKLOG = 3
DEVICE_NAMES = {"light_bar": "Light bar", "faceplate": "Faceplate"}
_KEY = re.compile(r"[a-z0-9_]{1,64}")  # used with fullmatch
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def image_type(data) -> str | None:
    """Return the content type of JPEG, PNG or WebP bytes, else None."""
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
    """Drop private keys at any depth from hub event data."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        return {key: _clean_event(child, depth + 1) for key, child in value.items() if not is_redacted(key)}
    if isinstance(value, (list, tuple)):
        return [_clean_event(child, depth + 1) for child in value]
    return value


def _same(current, value) -> bool:
    """Whether writing value would change nothing. True is not 1; 45 is 45.0."""
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
                 read_settings=None, apply_setting=None, schema=None, advertised=None, routed=None):
        self.config = config
        self._read_settings = read_settings
        self._apply_setting = apply_setting
        self.schema = schema if schema is not None else build_schema()
        self._advertised = advertised if advertised is not None else AdvertisedTopics()
        self._advertised_logged = ""
        self._described = None
        self._settings_text = None
        self._commands = {}
        self._last_error = ""
        self._last_error_key = None
        self._last_logged = ""
        self._drive_attached = False
        self._drive_text = None
        self._drive_light = None
        self._drive_applied_at = None
        self._routed = routed if routed is not None else RoutedDisplays()
        self._routed_logged = self._routed.error
        self._drive_alerts = []
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
        self._policy = PublishingPolicy()
        self._turbo = False
        self._performance_held_at = None
        self._last_snapshot_at = None
        self._connected_key = None
        self._event_types = {area: list(types) for area, types in BASE_EVENT_TYPES.items()}
        self._previous = {}
        self._stale_dropped = 0
        self._generation = 0
        self._seen_generation = 0
        # step() is serialised so a slow old worker cannot race a new one. The
        # lifecycle lock is for start, stop and reconfigure only.
        self._step_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._key_art_state = None
        self._key_art_retry = (None, 0.0)
        self._key_art_type = DEFAULT_KEY_ART_TYPE
        self._art_state, self._art_retry = {}, {}
        self._art_type = {kind: DEFAULT_KEY_ART_TYPE for kind in GAME_ART}
        self._faceplate_described = False
        self._version = None
        self._game = (0, None)  # (appid, wall time it started)
        self._download_active = False
        self._frontend_published = None
        self._stop_event = threading.Event()
        self._thread = None
        self.join_timeout_s = 3.0
        self.topics = None

    # Settings saves call reconfigure() on executor threads. Two overlapping
    # saves must not interleave stop() and start(), or two clients and two
    # workers would run.
    def start(self):
        with self._lifecycle_lock:
            self._start()

    def stop(self):
        with self._lifecycle_lock:
            self._stop()

    def reconfigure(self):
        with self._lifecycle_lock:
            self._stop()
            self._start()

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
            self._commands.clear()
            self._drive_light = None
            self._drive_alerts.clear()
        self._log_advertised_error()
        self.client = self._client_factory(
            settings["host"], settings["port"], f"gabecubeaura-{self.topics.node_id}",
            username=settings["username"], password=self.config.password(), tls=settings["tls"],
            will=(self.topics.availability, "offline", True),
            on_connect=self._on_connect, on_message=self._on_message, logger=self.log,
        )
        self.client.subscribe(self.topics.ha_status)
        # Subscribed even at Report only, so a refused command can say why.
        self.client.subscribe(self.topics.commands)
        self.client.subscribe(self.topics.drive_commands)
        self._unsubscribe = self.engine.subscribe(self._on_event)
        self.client.start()
        # A new event for each worker: an old one stuck in a slow publish keeps
        # its own, already set.
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
            self._commands.clear()
            self._drive_light = None
            self._drive_alerts.clear()
        self._detach_drive()
        # Put back the displays the light replaced. Reconfigure runs on an
        # executor thread, so Decky's loop is free to apply them; at unload
        # main.py has already let go of the loop, apply_setting raises
        # RuntimeError and the record waits for the next start.
        try:
            self._restore_routes(threading.Event())
        except Exception as error:
            if self.log:
                self.log.warning("[GabeCubeAura] Could not put back the display Home Assistant "
                                 f"replaced ({type(error).__name__})")
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
            "broker": ((f"[{host}]:{settings['port']}" if ":" in host else f"{host}:{settings['port']}")
                       if host else ""),
            "username": settings["username"] if client is not None else "",
            "topic_root": self.topics.root if client is not None and self.topics else "",
            "enabled": bool(self.config.public()["enabled"]),
            "connected": bool(client and client.connected),
            "connected_with_current_settings": bool(
                client and client.connected_once and self._connected_key == self.config.connection_key()),
            "last_error": (client.last_error if client and not client.connected else "") or "",
            "messages_out": client.messages_out if client else 0,
            "events_dropped": self._events_dropped(),
            "faceplate_controls": bool(self.schema.for_device("faceplate")),
            "command_error": self._last_error,
        }

    def _events_dropped(self) -> int:
        return int(getattr(self.engine.hub, "dropped", 0) or 0) + self._stale_dropped

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
        elif topic.startswith(topics.drive_prefix):
            self._on_drive(topic[len(topics.drive_prefix):], payload, retain)

    def _on_command(self, key, payload, retain):
        """Check a settings command and queue it for the worker."""
        name = key if _KEY.fullmatch(key) else "(unreadable)"
        if retain:
            # A retained command would replay on every reconnect and snap the
            # setting back.
            if self.log:
                self.log.info(f"[GabeCubeAura] ignored a retained Home Assistant command for {name}")
            return
        if payload in (b"", ""):
            if self.log:
                self.log.debug(f"[GabeCubeAura] ignored an empty Home Assistant command for {name}")
            return
        if key in self.schema.local_only:
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
            apply_at = pending[1] if pending else self._clock() + COALESCE_S
            self._commands[key] = (value, apply_at)

    def _on_drive(self, name, payload, retain):
        """Check a light, frame or alert command and queue it for the worker."""
        label = name if name in DRIVE_PARSERS else "(unknown)"
        if retain:
            if self.log:
                self.log.info(f"[GabeCubeAura] ignored a retained Home Assistant drive/{label} command")
            return
        if not payload:
            return
        if name not in DRIVE_PARSERS:
            self._reject("drive/(unknown)", "drive/(unknown): not a light bar command")
            return
        key = f"drive/{name}"
        if self.config.public().get("light_bar_level") != "drive":
            self._reject(key, f"{key}: Light bar is not set to Home Assistant drives it")
            return
        if self._drive_provider() is None:
            self._reject(key, f"{key}: the Home Assistant display is not available")
            return
        try:
            command = DRIVE_PARSERS[name](payload)
        except ValueError as error:
            self._reject(key, f"{key}: {error}")
            return
        except RecursionError:
            self._reject(key, f"{key}: not valid JSON")
            return
        with self._lock:
            if name != "alert":
                self._drive_light = (name, command)
                return
            full = len(self._drive_alerts) >= ALERT_BACKLOG
            if not full:
                self._drive_alerts.append(command)
        if full:
            self._reject("drive/alert", "drive/alert: dropped, three alerts are already waiting")

    def _level_allows(self, control) -> bool:
        return self.config.public().get(f"{control.device}_level") in CONTROL_LEVELS

    def _reject(self, key, message):
        message = message[:ERROR_LIMIT]
        with self._lock:
            repeated, self._last_error = message == self._last_logged, message
            self._last_error_key = key
            self._last_logged = message
        if self.log and not repeated:
            self.log.warning(f"[GabeCubeAura] Home Assistant command refused: {message}")

    def note_refusal(self, key, message):
        """Show a refusal main.py found at start, without logging it again."""
        message = message[:ERROR_LIMIT]
        with self._lock:
            self._last_error, self._last_error_key, self._last_logged = message, key, message

    def _on_event(self, kind, data):
        with self._lock:
            if kind == "steam.download":
                self._download_active = bool((data or {}).get("active"))
            self._events.append((self._clock(), kind, dict(data or {})))

    def _run(self, stop_event):
        failures = 0
        while not stop_event.wait(0.25):
            try:
                self.step(stop_event)
                failures = 0
            except Exception as error:
                failures += 1
                if self.log:
                    self.log.warning(f"[GabeCubeAura] MQTT bridge step failed: {error}")
                if failures >= 3:
                    stop_event.wait(min(60.0, 5.0 * failures))

    def step(self, stop_event=None):
        """Run one worker pass; stop_event defaults to the current worker's."""
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
            self._art_state, self._art_retry = {}, {}
            self._frontend_published = None
            self._faceplate_described = False
            self._described = None
            self._settings_text = None
            self._drive_text = None
        self._apply_due_commands(stop_event)
        self._step_drive(stop_event)
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
            except Exception:
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
            self._policy.reset()
            self._frontend_published = None
            self._key_art_state = None
            self._key_art_retry = (None, 0.0)
            self._art_state, self._art_retry = {}, {}
            self._described = None
            self._settings_text = None
            self._drive_text = None
        for area, _, payload in events:
            try:
                client.publish(self.topics.event(area), _json(payload))
            except Exception:
                self._stale_dropped += 1
        if full or self._last_snapshot_at is None or now - self._last_snapshot_at >= SNAPSHOT_INTERVAL_S:
            self._last_snapshot_at = now
            self._publish_snapshot(client, full, now)
        self._sync_settings(client)

    def _controlled_devices(self) -> frozenset:
        """Devices that take settings commands, plus "drive" while it drives the light bar."""
        settings = self.config.public()
        scopes = {device for device in DEVICES if settings.get(f"{device}_level") in CONTROL_LEVELS}
        if settings.get("light_bar_level") == "drive":
            scopes.add("drive")
        return frozenset(scopes)

    def _sync_settings(self, client):
        """Describe or clear entities when a level changes, then publish their state."""
        active = self._controlled_devices()
        if active != self._described:
            if not self._describe_settings(client, active):
                return  # tried again next step; retained configs make that harmless
            self._described = active
            self._settings_text = None
            self._drive_text = None
        if not active:
            return
        values = self._safe(self._read_settings) if self._read_settings else None
        values = values if isinstance(values, dict) else {}
        state = {key: values[key] for key in self.schema.reported(active) if key in values}
        text = _json(_json_safe(state))
        if text != self._settings_text and client.publish(self.topics.state("settings"), text, retain=True):
            self._settings_text = text
        if "drive" in active:
            self._publish_light_state(client)

    def _describe_settings(self, client, active) -> bool:
        """Advertise the entities of the active devices and clear the rest.

        Only topics recorded in AdvertisedTopics are cleared, including any an
        earlier run left behind, so a broker that never had them hears nothing.
        """
        previous = self._described
        wanted, new = set(), []
        for control in self.schema.controls.values():
            if control.device in active:
                topic, payload = setting_discovery(self.topics, self._version, self.hostname, control)
                wanted.add(topic)
                if previous is None or control.device not in previous:
                    new.append((topic, payload))
        if active:
            wanted |= {self.topics.state("settings"), self.topics.preset_note}
        if "drive" in active:
            for topic, payload in drive_discovery(self.topics, self._version, self.hostname):
                wanted.add(topic)
                if previous is None or "drive" not in previous:
                    new.append((topic, payload))
            wanted.add(self.topics.state("drive"))
        # Recorded before publishing, so a crash in between still gets them
        # cleared by a later start.
        self._advertised.add(wanted)
        self._log_advertised_error()
        ok = True
        if active and not previous:
            ok = client.publish(self.topics.preset_note, _json(PRESET_NOTE), retain=True)
        for topic, payload in new:
            ok = client.publish(topic, _json(payload), retain=True) and ok
        # An empty retained config deletes the entity. Configs go first, in
        # this same pass: emptying the state while the entities still exist
        # makes Home Assistant render every template against nothing.
        stale = sorted(self._advertised.topics() - wanted, key=lambda topic: (not topic.endswith("/config"), topic))
        cleared = [topic for topic in stale if client.publish(topic, "", retain=True)]
        self._advertised.discard(cleared)
        self._log_advertised_error()
        done = ok and len(cleared) == len(stale)
        if not done and cleared:
            # Some entities are gone, so if the level comes back before the
            # retry nothing would advertise them again.
            self._described = None
        return done

    def _drive_provider(self):
        return getattr(self.engine, "home_assistant", None)

    def _step_drive(self, stop_event):
        """Follow the light bar's level, then apply waiting alerts and the newest colour or frame.

        Leaving "drive" empties the display slot and puts back the displays
        the light replaced, so nothing Home Assistant sent keeps showing.
        """
        # A worker that outlived stop() may only detach, never attach.
        driving = not stop_event.is_set() and self.config.public().get("light_bar_level") == "drive"
        provider = self._drive_provider()
        if driving != self._drive_attached:
            if driving:
                if provider is not None:
                    provider.attach(True)
                self._drive_attached = True
            else:
                self._detach_drive()
                self._restore_routes(stop_event)
        if not driving or provider is None:
            with self._lock:
                self._drive_light = None
                self._drive_alerts.clear()
            return
        with self._lock:
            alerts, self._drive_alerts = self._drive_alerts, []
        for alert in alerts:
            if stop_event.is_set():
                return
            self._apply_alert(alert)
        now = self._clock()
        if self._drive_applied_at is not None and now - self._drive_applied_at < DRIVE_INTERVAL_S:
            return
        with self._lock:
            pending, self._drive_light = self._drive_light, None
        if pending is None or stop_event.is_set():
            return
        self._drive_applied_at = now
        name, command = pending
        self._apply_light(provider, name, command, stop_event)

    def _apply_light(self, provider, name, command, stop_event):
        key = f"drive/{name}"
        if name == "light" and not command.on:
            provider.set_light(False)
            self._restore_routes(stop_event)
            self._clear_refusal(key)
            return
        refusal = self._drive_refusal()
        if refusal:
            self._reject(key, f"{key}: {refusal}")
            return
        if not self._route_home_assistant(key) or stop_event.is_set():
            return
        try:
            if name == "frame":
                provider.set_frame(command)
            else:
                provider.set_light(True, command.colour, command.brightness)
        except ValueError as error:
            self._reject(key, f"{key}: {error}")
            return
        self._clear_refusal(key)

    def _clear_refusal(self, key):
        """Forget a refusal once the same command applies, as for settings."""
        with self._lock:
            self._last_logged = ""
            if self._last_error_key == key:
                self._last_error, self._last_error_key = "", None

    def _apply_alert(self, alert):
        refusal = self._drive_refusal()
        result = None
        if not refusal:
            result = self._safe(lambda: self.engine.trigger_home_assistant_alert(
                alert.variant, alert.colour, alert.duration))
            if not isinstance(result, tuple) or len(result) != 2:
                refusal = "the light bar did not answer"
        if refusal:
            self._on_event("light_event", {"kind": "ha", "variant": alert.variant, "shown": False,
                                           "result": "dropped", "reason": refusal})
            self._reject("drive/alert", f"drive/alert: dropped, {refusal}")
            return
        shown, reason = result
        if not shown:
            self._reject("drive/alert", f"drive/alert: dropped, {reason}")
            return
        self._clear_refusal("drive/alert")

    def _drive_refusal(self) -> str:
        """Why Home Assistant may not take the light bar now, or "" if it may."""
        refusal = self._safe(self.engine.home_assistant_refusal)
        if not isinstance(refusal, str):
            return "the light bar did not answer"
        if refusal:
            return refusal
        update = self._safe(self._update_status)
        if isinstance(update, dict) and update.get("phase") in UPDATE_BUSY_PHASES:
            return "a GabeCubeAura update is being installed"
        return ""

    def _route_home_assistant(self, key) -> bool:
        """Select the Home Assistant display for what is on screen, if it is not already.

        This is a real settings change through set_setting, so the store
        switches to the Custom display preset as it would for the UI.
        """
        route = self._safe(self.engine.home_assistant_route)
        if not isinstance(route, dict):
            self._reject(key, f"{key}: the light bar did not answer")
            return False
        if route["selected"] == "home_assistant":
            return True
        if route["override"] != "inherit":
            self._reject(key, f"{key}: this game has its own display; choose Home Assistant for it "
                              "on the Steam Machine")
            return False
        if self._apply_setting is None:
            self._reject(key, f"{key}: settings control is not available")
            return False
        recorded = self._routed.remember(route["key"], route["selected"])
        try:
            self._apply_setting(route["key"], "home_assistant")
        except Exception as error:
            # A write that timed out may still have landed. Keeping its record
            # costs nothing: displays are only put back where the store still
            # says home_assistant.
            if recorded and not isinstance(error, TimeoutError):
                self._routed.forget(route["key"])
            if isinstance(error, ValueError):
                self._reject(key, f"{key}: {error}")
            elif isinstance(error, TimeoutError):
                self._reject(key, f"{key}: GabeCubeAura did not apply the change in time")
            else:
                self._reject(key, f"{key}: not applied ({type(error).__name__})")
            self._log_routed_error()
            return False
        self._log_routed_error()
        return True

    def _restore_routes(self, stop_event):
        """Put back the displays the light replaced, where Home Assistant still shows.

        A display chosen on the Steam Machine since then is left alone. A key
        is forgotten once it is put back, changed since or refused by the
        store. While stopping, or when the settings cannot be read, the record
        stays for main.py to deal with at the next start.
        """
        routed = self._routed.displays()
        if not routed or self._read_settings is None or self._apply_setting is None:
            return
        values = self._safe(self._read_settings)
        if not isinstance(values, dict):
            return
        for key, previous in sorted(routed.items()):
            if stop_event.is_set():
                break
            if values.get(key) == "home_assistant":
                try:
                    self._apply_setting(key, previous)
                except Exception as error:
                    if stop_event.is_set() or isinstance(error, (RuntimeError, TimeoutError)):
                        # Decky is unloading: the queued set_setting was
                        # cancelled, or main.py has let go of the loop.
                        break
                    self._reject(key, f"{key}: could not put back {previous} ({type(error).__name__})")
                    if not isinstance(error, ValueError):
                        continue  # tried again next time
            self._routed.forget(key)
        self._log_routed_error()

    def _detach_drive(self):
        provider = self._drive_provider()
        if provider is not None:
            provider.attach(False)
        self._drive_attached = False
        self._drive_text = None

    def _publish_light_state(self, client):
        provider = self._drive_provider()
        light = self._safe(provider.light) if provider is not None else None
        if not isinstance(light, dict):
            return
        text = _json(light_state(light))
        if text != self._drive_text and client.publish(self.topics.state("drive"), text, retain=True):
            self._drive_text = text

    def _log_routed_error(self):
        error = self._routed.error
        if error != self._routed_logged:
            self._routed_logged = error
            if error and self.log:
                self.log.warning(f"[GabeCubeAura] {error}")

    def _log_advertised_error(self):
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
            # This worker's own event, not self._stop_event: after a join timed
            # out, start() has already replaced that with the new worker's.
            if stop_event.is_set():
                break
            self._apply_command(key, value)

    def _apply_command(self, key, value):
        control = self.schema.controls[key]
        if not self._level_allows(control):
            self._reject(key, f"{key}: {DEVICE_NAMES[control.device]} is set to Report only")
            return
        if self._read_settings is None or self._apply_setting is None:
            self._reject(key, f"{key}: settings control is not available")
            return
        values = self._safe(self._read_settings)
        if not isinstance(values, dict):
            self._reject(key, f"{key}: settings control is not available")
            return
        current = values.get(key)
        if _same(current, value):
            # The store treats any write of a preset-controlled key as an edit
            # and leaves the display preset, even when nothing changes.
            return
        try:
            self._apply_setting(key, value)
        except ValueError as error:
            self._reject(key, f"{key}: {error}")
            return
        except TimeoutError:
            self._reject(key, f"{key}: GabeCubeAura did not apply the change in time")
            return
        except Exception as error:
            self._reject(key, f"{key}: not applied ({type(error).__name__})")
            return
        stored = (self._safe(self._read_settings) or {}).get(key)
        if not _same(stored, value):
            self._reject(key, f"{key}: GabeCubeAura kept {_shown(stored)} instead of {_shown(value)}")
            return
        with self._lock:
            self._last_logged = ""
            if self._last_error_key == key:
                self._last_error, self._last_error_key = "", None

    def _publish_discovery(self, client):
        version = self.engine.status().get("version") if hasattr(self.engine, "status") else None
        self._version = version
        faceplate = isinstance(self._safe(self._faceplate_status), dict)
        published = True
        for topic, payload in discovery_messages(self.topics, version, self.hostname, self._event_types,
                                                 self._key_art_type, faceplate=faceplate,
                                                 art_types=self._art_type):
            ok = client.publish(topic, _json(payload), retain=True)
            if payload["unique_id"].endswith("_faceplate"):
                published = ok
        self._faceplate_described = faceplate and bool(published)

    def _publish_faceplate_discovery(self, client):
        """Describe the Faceplate sensor when a faceplate service appears later."""
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
            self._publish_faceplate_discovery(client)
        frontend = "online" if facts["frontend_connected"] else "offline"
        if frontend != self._frontend_published:
            client.publish(self.topics.frontend, frontend, retain=True)
            self._frontend_published = frontend
        turbo = bool(self.config.public().get("turbo"))
        if turbo != self._turbo:
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
        self._publish_game_art(client, snapshot["game"], now)

    def _hold_performance(self, payload, now) -> bool:
        """Whether to hold back the first performance publish until CPU load has a reading.

        It waits at most PERFORMANCE_HOLD_S. Leaving the field out would not
        help, since the sensor templates show a missing field as unknown too.
        Thermal protection is news and never waits.
        """
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
            if client.publish(self.topics.key_art_image, b"", retain=True):
                self._key_art_state = "empty"
        self._key_art_retry = (appid, now + KEY_ART_RETRY_S)

    def _publish_key_art_type(self, client, content_type) -> bool:
        """Declare a new content type before the image; Home Assistant decodes by it."""
        if content_type == self._key_art_type:
            return True
        topic, payload = key_art_discovery(self.topics, self._version, self.hostname, content_type)
        if not client.publish(topic, _json(payload), retain=True):
            return False
        self._key_art_type = content_type
        return True

    def _publish_game_art(self, client, game, now):
        """Publish header, cover and logo art the same way as key art."""
        appid = game["appid"]
        for kind in GAME_ART:
            topic, state = self.topics.art_image(kind), self._art_state.get(kind)
            if not appid:
                if state != "empty" and client.publish(topic, b"", retain=True):
                    self._art_state[kind] = "empty"
                continue
            retry_appid, retry_at = self._art_retry.get(kind, (None, 0.0))
            if state == appid or (retry_appid == appid and now < retry_at):
                continue
            art = self._read_game_art(appid, kind)
            if art is not None:
                data, content_type = art
                if self._publish_art_type(client, kind, content_type) and client.publish(topic, data, retain=True):
                    self._art_state[kind] = appid
                    self._art_retry.pop(kind, None)
                    continue
            elif state != "empty" and client.publish(topic, b"", retain=True):
                self._art_state[kind] = "empty"
            self._art_retry[kind] = (appid, now + KEY_ART_RETRY_S)

    def _publish_art_type(self, client, kind, content_type) -> bool:
        if content_type == self._art_type[kind]:
            return True
        topic, payload = art_discovery(self.topics, self._version, self.hostname, kind, content_type)
        if not client.publish(topic, _json(payload), retain=True):
            return False
        self._art_type[kind] = content_type
        return True

    @classmethod
    def _read_game_art(cls, appid, kind):
        try:
            from signalbar.steam import find_game_art
            path = find_game_art(appid, kind, max_bytes=KEY_ART_LIMIT)
        except Exception:
            return None
        return None if path is None else cls._read_image_file(path)

    @classmethod
    def _read_key_art(cls, appid):
        try:
            from signalbar.steam import find_library_artwork
            path = find_library_artwork(appid, "hero")
        except OSError:
            return None
        return None if path is None else cls._read_image_file(path)

    @staticmethod
    def _read_image_file(path):
        """Return (bytes, content type) for a small JPEG, PNG or WebP file, else None.

        The grid folder is writable by the user and the plugin runs as root,
        so symlinks and anything but a regular file are refused. O_NONBLOCK
        keeps a FIFO swapped in from blocking the open.
        """
        try:
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
        except Exception:
            return None
