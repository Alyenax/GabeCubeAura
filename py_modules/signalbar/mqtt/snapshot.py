"""Turn GabeCubeAura's status into the small, private-data-free areas published to Home Assistant."""

from __future__ import annotations

import math

FRONTEND_TIMEOUT_S = 6.0
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"
# Exact names, plus any key whose lowercased name contains a fragment below (so faceplate_image_path
# and weather_latitude are caught as well as the bare names).
REDACTED_KEYS = frozenset({
    "game_profiles", "weather_location", "led_path", "capture_identity", "discovery_detail",
    "controller_telemetry",
})
REDACTED_FRAGMENTS = (
    "image_path", "latitude", "longitude", "token", "private_", "password", "secret", "stderr",
    "runtime_dir", "verification_uri", "user_code",
)
MAX_STRING = 256
MAX_DEPTH = 8
# Arrays of 17 pixels or audio levels change many times a second.
NOISY_KEYS = frozenset({"colors", "levels", "dominant_colors", "screen_palette"})
# Timers, rates and live audio meters: they change every second while meaning nothing new, and the
# status area is retained on the broker, so each tick would be a pointless retained publish.
VOLATILE_KEYS = frozenset({
    "last_write", "writes", "left_level", "right_level", "hifi_metrics", "buffered_ms",
    "queued_blocks", "dropped_blocks",
})
VOLATILE_SUFFIXES = ("age_s", "remaining_s", "_remaining", "remaining_seconds", "per_second")
# Top-level sections left out of the status area: "debug" is engine internals (guard timers, write
# counters) that churn constantly and only matter in the plugin's own debug view.
STATUS_SKIPPED_SECTIONS = frozenset({"debug"})
# Measured against a real Engine.status() (2026-10-09): about 300 keys once debug and volatile keys
# are gone, so 400 keeps every section with headroom while still bounding a runaway status.
STATUS_KEY_LIMIT = 400


def _get(mapping, *path, default=None):
    for key in path:
        if not isinstance(mapping, dict):
            return default
        mapping = mapping.get(key)
    return default if mapping is None else mapping


def _number(value, kind):
    """Coerce to int/float; anything odd (None, text, bool junk) becomes 0 so the builder never raises."""
    try:
        result = kind(value or 0)
    except (TypeError, ValueError, OverflowError):
        return kind(0)
    return result if math.isfinite(result) else kind(0)


def is_volatile(key) -> bool:
    name = str(key).lower()
    return name in VOLATILE_KEYS or name.endswith(VOLATILE_SUFFIXES)


def _rounded(value, step):
    """Round to the nearest step so 1 Hz sensor jitter is not a state change; non-numbers pass through."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return value
    result = round(value / step) * step
    return int(result) if step >= 1 else float(result)


def is_redacted(key) -> bool:
    name = str(key).lower()
    return name in REDACTED_KEYS or any(fragment in name for fragment in REDACTED_FRAGMENTS)


def _list(value):
    return value if isinstance(value, list) else []


def _json_safe(value, depth=0):
    """Replace Infinity/NaN with None anywhere in the snapshot (they are not valid JSON)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if depth > MAX_DEPTH:
        return None
    if isinstance(value, dict):
        return {key: _json_safe(child, depth + 1) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child, depth + 1) for child in value]
    return value


def frontend_connected(engine_status) -> bool:
    age = _get(engine_status, "debug", "frontend_heartbeat_age_s")
    return isinstance(age, (int, float)) and age < FRONTEND_TIMEOUT_S


def key_art_urls(appid, non_steam) -> dict:
    if not appid or non_steam:
        return {"key_art_url": None, "header_url": None}
    return {"key_art_url": f"{STEAM_CDN}/{appid}/library_hero.jpg",
            "header_url": f"{STEAM_CDN}/{appid}/header.jpg"}


def flatten_status(status, limit=STATUS_KEY_LIMIT) -> dict:
    """Scalar leaves of the status as 'a.b.c' keys, without private, noisy, volatile or debug fields."""
    flat = {}

    def scalar(value):
        if isinstance(value, str):
            return value[:MAX_STRING]
        if isinstance(value, float) and not math.isfinite(value):
            return None  # Infinity/NaN are not valid JSON
        return value

    def walk(value, prefix, depth):
        if len(flat) >= limit or depth > MAX_DEPTH:
            return
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if is_redacted(key) or key in NOISY_KEYS or is_volatile(key):
                    continue
                if depth == 0 and key in STATUS_SKIPPED_SECTIONS:
                    continue
                walk(child, f"{prefix}.{key}" if prefix else str(key), depth + 1)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            flat[prefix] = scalar(value)
        elif isinstance(value, list) and len(value) <= 8 and all(
                isinstance(item, (str, int, float, bool)) for item in value):
            flat[prefix] = [scalar(item) for item in value]

    walk(status if isinstance(status, dict) else {}, "", 0)
    return flat


def build_snapshot(engine_status, faceplate_status, update_status, facts) -> dict:
    s = engine_status if isinstance(engine_status, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    appid = _number(_get(s, "game", "appid", default=0), int)
    non_steam = appid >= 2 ** 31
    controllers = [
        {key: item.get(key) for key in ("id", "name", "percent", "charging")}
        for item in _list(_get(s, "controllers", "controllers", default=[])) if isinstance(item, dict)
    ]
    remaining = _number(_get(s, "countdown", "remaining_seconds", default=0), float)
    total = _number(_get(s, "countdown", "total_seconds", default=0), float)
    faceplate = {"available": False}
    if isinstance(faceplate_status, dict):
        faceplate = {
            "available": True,
            "phase": faceplate_status.get("phase"),
            "connected": bool(faceplate_status.get("connected")),
            "mode": _get(faceplate_status, "settings", "mode"),
            # No lifetime_uploads here: this area is the Faceplate entity's attributes, and a counter that
            # ticks every clock minute would make each recorded attribute blob unique (it is in "status").
            "brightness_applied": faceplate_status.get("brightness_applied"),
            "appid": faceplate_status.get("appid"),
        }
    update_status = update_status if isinstance(update_status, dict) else {}
    # Areas used as entity attributes carry no counters or timestamps (Home Assistant's recorder stores
    # every distinct attribute blob); those few values go to the MQTT-only status topic instead.
    status = flatten_status(s)
    if isinstance(faceplate_status, dict):
        status.setdefault("faceplate.lifetime_uploads", faceplate_status.get("lifetime_uploads"))
    status.setdefault("update.last_checked_at", update_status.get("last_checked_at"))
    return _json_safe({
        "game": {
            "running": bool(appid),
            "appid": appid,
            "title": str(_get(s, "game", "title", default="")),
            "non_steam": non_steam,
            "started_at": facts.get("started_at") or None,
            "session_minutes": facts.get("session_minutes", 0.0),
            "dominant_colours": _get(s, "artwork", "dominant_colors", default=[]),
            **key_art_urls(appid, non_steam),
        },
        "light_bar": {
            "owner": _get(s, "owner", default="Valve"),
            "active": bool(_get(s, "active", default=False)),
            "provider": _get(s, "provider", default="none"),
            "display": _get(s, "current_display"),
            "home_display": _get(s, "home_display"),
            "game_display": _get(s, "game_display"),
            "enabled": bool(_get(s, "signalbar_enabled", default=False)),
            "suspension_reason": _get(s, "suspension_reason", default=""),
            "brightness_output": _get(s, "light_bar_brightness", "current_output"),
            "brightness": _get(s, "light_bar_brightness", "target_brightness"),
            "night_mode_active": bool(_get(s, "night_mode", "active", default=False)),
            "recording": bool(_get(s, "events", "recording", default=False)),
            "screensaver": bool(_get(s, "screen_sync", "activation", "screensaver_active", default=False)),
            "download_active": bool(facts.get("download_active", False)),
        },
        "performance": {
            # Whole percent and half degrees: finer readings only add 1 Hz recorder churn.
            "cpu_load": _rounded(_get(s, "performance", "cpu_load"), 1),
            "gpu_load": _rounded(_get(s, "performance", "gpu_load"), 1),
            "cpu_temperature": _rounded(_get(s, "performance", "cpu_temperature"), 0.5),
            "gpu_temperature": _rounded(_get(s, "performance", "gpu_temperature"), 0.5),
            "thermal_protection": bool(_get(s, "thermal_protection", "active", default=False)),
        },
        "controllers": {"count": len(controllers), "controllers": controllers},
        "countdown": {
            "active": bool(_get(s, "countdown", "active", default=False)),
            "source": _get(s, "countdown", "source", default=""),
            "label": _get(s, "countdown", "label", default=""),
            "remaining_minutes": round(remaining / 60.0, 1),
            "total_minutes": round(total / 60.0, 1),
        },
        "weather": {
            "condition": _get(s, "weather", "condition"),
            "temperature_c": _get(s, "weather", "temperature_c"),
            "is_day": _get(s, "weather", "is_day"),
            "location_name": _get(s, "weather", "location", "name"),
        },
        "faceplate": faceplate,
        "update": {key: update_status.get(key)
                   for key in ("installed_version", "available_version", "phase")},
        "bridge": {
            "frontend_connected": bool(facts.get("frontend_connected", False)),
            "events_dropped": _number(facts.get("events_dropped", 0), int),
            "version": _get(s, "version"),
            # Why Home Assistant's last command was refused (the Last command error sensor); "" if none,
            # or once that same setting later applied from Home Assistant.
            "last_error": str(facts.get("last_error") or "")[:MAX_STRING],
        },
        # The Status diagnostic sensor's own state and attributes: tiny, stable, no counters.
        "info": {
            "version": _get(s, "version"),
            "enabled": bool(_get(s, "signalbar_enabled", default=False)),
            "frontend_connected": bool(facts.get("frontend_connected", False)),
        },
        "status": status,
    })
