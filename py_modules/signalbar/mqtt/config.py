"""MQTT connection settings, kept apart from the settings store.

They live in the plugin runtime directory, owner-readable only, so the
broker password never reaches configuration export, and a configuration
import or reset can never switch MQTT on or raise what Home Assistant may do.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading

# From 2 up Home Assistant may change settings and has the light, frames and
# alerts; 3 to 5 decide who wins when both want the bar.
TIER_NAMES = {1: "Watch only", 2: "Help out", 3: "Take the lead", 4: "In control", 5: "Full control"}
# The faceplate has nothing Home Assistant can show yet, so it stops at 2.
DEVICE_TIERS = {"light_bar_tier": 5, "faceplate_tier": 2}
DEFAULT_TIER = 2
# Files written before tiers existed hold these.
OLD_LEVELS = {"report": 1, "settings": 2, "drive": 2}
DEFAULTS = {
    "enabled": False,
    "host": "",
    "port": 1883,
    "tls": False,
    "username": "",
    "discovery_prefix": "homeassistant",
    "base_topic": "gabecubeaura",
    "light_bar_tier": DEFAULT_TIER,
    "faceplate_tier": DEFAULT_TIER,
    "ha_fallback": True,
    "turbo": False,
}
# The running bridge picks these up on its next step. Reconnecting for them
# would only hide the settings until the new connection is up.
LIVE_KEYS = frozenset({"turbo", "light_bar_tier", "faceplate_tier", "ha_fallback"})
# No brackets: "[::1]" is URL syntax, and the socket layer wants the bare IPv6 address ("::1").
_HOST = re.compile(r"^[A-Za-z0-9.\-:]{1,253}$")
_TEXT_KEYS = ("host", "username", "discovery_prefix", "base_topic")
_TOPIC = re.compile(r"^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*$")


def _clean(key, value):
    if key in _TEXT_KEYS and not isinstance(value, str):
        # str(None) would quietly become a host or topic called "None".
        raise ValueError(f"{key} must be text")
    if key in ("enabled", "tls", "turbo", "ha_fallback"):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key == "port":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise ValueError("port must be 1-65535")
        return value
    if key == "host":
        value = value.strip()
        if value and not _HOST.match(value):
            raise ValueError("host must be a hostname or IP address (IPv6 without brackets)")
        return value
    if key == "username":
        if len(value) > 128:
            raise ValueError("username is too long")
        return value
    if key in ("discovery_prefix", "base_topic"):
        value = value.strip()
        if len(value) > 64 or not _TOPIC.match(value):
            raise ValueError(f"{key} may use letters, digits, - and _ separated by /")
        return value
    if key in DEVICE_TIERS:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= DEVICE_TIERS[key]:
            raise ValueError(f"{key} must be 1-{DEVICE_TIERS[key]}")
        return value
    raise ValueError(f"unknown MQTT setting {key}")


def _saved_tier(raw, key):
    """Read a tier from the file, never raising.

    A tier the device does not offer yet becomes its highest one, an older
    file's level becomes its tier, and anything else the default.
    """
    value = raw.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= max(TIER_NAMES):
        return min(value, DEVICE_TIERS[key])
    if key not in raw:
        level = raw.get(key.replace("_tier", "_level"))
        if isinstance(level, str) and level in OLD_LEVELS:
            return OLD_LEVELS[level]
    return DEFAULT_TIER


class MqttConfig:
    def __init__(self, directory: str):
        self.path = os.path.join(directory, "mqtt.json")
        self._lock = threading.Lock()
        self.values = dict(DEFAULTS)
        self._password = ""
        self.load_error = ""
        self._load()

    def __repr__(self) -> str:
        return "MqttConfig()"

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            self.load_error = f"MQTT settings unreadable, using defaults: {error}"
            return
        if not isinstance(raw, dict):
            return
        for key in DEVICE_TIERS:
            self.values[key] = _saved_tier(raw, key)
        for key in DEFAULTS:
            if key in raw and key not in DEVICE_TIERS:
                try:
                    self.values[key] = _clean(key, raw[key])
                except ValueError:
                    continue
        password = raw.get("password", "")
        self._password = password if isinstance(password, str) and len(password) <= 256 else ""

    def public(self) -> dict:
        with self._lock:
            return {**self.values, "has_password": bool(self._password), "load_error": self.load_error}

    def password(self) -> str:
        with self._lock:
            return self._password

    def connection_key(self) -> tuple:
        with self._lock:
            digest = hashlib.sha256(self._password.encode("utf-8")).hexdigest()
            return (self.values["host"], self.values["port"], self.values["tls"], self.values["username"], digest)

    def update(self, changes: dict, password=None) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("MQTT settings must be an object")
        cleaned = {key: _clean(key, value) for key, value in changes.items()}
        if password is not None and (not isinstance(password, str) or len(password) > 256):
            raise ValueError("password must be text of at most 256 characters")
        with self._lock:
            merged = {**self.values, **cleaned}
            if merged["enabled"] and not merged["host"]:
                raise ValueError("enter the broker host before turning MQTT on")
            self._save(merged, self._password if password is None else password)
            self.values = merged
            if password is not None:
                self._password = password
            self.load_error = ""
        return self.public()

    def _save(self, values, password):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        temporary = self.path + ".tmp"
        # A leftover temp file could carry looser permissions; O_CREAT keeps those.
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({**values, "password": password}, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        os.chmod(self.path, 0o600)
