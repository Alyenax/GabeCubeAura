"""Turn GabeCubeAura's status into the small areas published to Home Assistant, minus anything private."""

from __future__ import annotations

import math
import re

FRONTEND_TIMEOUT_S = 6.0
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"
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
# Timers, rates and live audio meters change every second without saying
# anything new, and each change would be another retained publish.
VOLATILE_KEYS = frozenset({
    "last_write", "writes", "left_level", "right_level", "hifi_metrics", "buffered_ms",
    "queued_blocks", "dropped_blocks",
    "last_external",  # a monotonic clock reading, meaningless off the machine
})
VOLATILE_SUFFIXES = ("age_s", "remaining_s", "_remaining", "remaining_seconds", "per_second")
# Keys ending like this hold free text, often built from an exception
# (debug.last_runtime_error, screen_sync.fallback_reason). It is still sent,
# but any file or device path in it becomes "<path>" first. URLs stay.
FREE_TEXT_SUFFIXES = ("error", "reason", "detail", "message")
# A path segment may hold paired brackets (valve-leds[0]) and colons between
# other characters (pci-0000:00:14.0), so "open /a/b: busy" keeps its colon.
_SEGMENT = r"(?:[\w.@+-]|\[[\w.@+:-]*\]|:(?=[\w.@+\[-]))+"
# An absolute or ~/ path at the start or after whitespace, a quote, a bracket,
# "=", "," or ":" (path lists); the path in https://host/path follows the host
# and never matches.
# Windows paths (X:\...) too.
_PATH = re.compile(rf"""(?:^|(?<=[\s'"(\[=,:]))~?/(?:{_SEGMENT}/)*{_SEGMENT}/?|\b[A-Za-z]:\\[^\s'"()]*""")


def scrub_paths(text):
    """Replace every file or device path in text with "<path>"."""
    return _PATH.sub("<path>", text)


UPDATE_NOT_PUBLISHED = {
    "error": "updater text that can hold local paths and URLs; error_category says what failed",
}
# Left out on the Private Lab channel, whose notes describe private builds.
UPDATE_PRIVATE_CHANNEL_ONLY = frozenset({"release_notes"})
UPDATE_HEADLINE = ("installed_version", "available_version", "phase")
# A real status flattens to about 330 keys; the cap only bounds a runaway one.
STATUS_KEY_LIMIT = 400


def _get(mapping, *path, default=None):
    for key in path:
        if not isinstance(mapping, dict):
            return default
        mapping = mapping.get(key)
    return default if mapping is None else mapping


def _number(value, kind):
    """Coerce to int or float; anything odd becomes 0, so building never raises."""
    try:
        result = kind(value or 0)
    except (TypeError, ValueError, OverflowError):
        return kind(0)
    return result if math.isfinite(result) else kind(0)


def is_volatile(key) -> bool:
    name = str(key).lower()
    return name in VOLATILE_KEYS or name.endswith(VOLATILE_SUFFIXES)


def _rounded(value, step):
    """Round to the nearest step so sensor jitter is not a state change."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return value
    result = round(value / step) * step
    return int(result) if step >= 1 else float(result)


def is_redacted(key) -> bool:
    name = str(key).lower()
    return name in REDACTED_KEYS or any(fragment in name for fragment in REDACTED_FRAGMENTS)


def _list(value):
    return value if isinstance(value, list) else []


def _small_item(item) -> bool:
    """Whether the status area can carry this list item: a scalar or a colour."""
    if isinstance(item, (str, int, float, bool)) or item is None:
        return True
    return (isinstance(item, (list, tuple)) and len(item) <= 4
            and all(isinstance(part, (int, float)) and not isinstance(part, bool) for part in item))


def _json_safe(value, depth=0):
    """Replace Infinity and NaN, which are not JSON, with None at any depth."""
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
    """Return Steam's CDN address for each kind of art; Home Assistant fetches them itself."""
    if not appid or non_steam:
        return {"key_art_url": None, "header_url": None, "capsule_url": None, "logo_url": None}
    return {"key_art_url": f"{STEAM_CDN}/{appid}/library_hero.jpg",
            "header_url": f"{STEAM_CDN}/{appid}/header.jpg",
            "capsule_url": f"{STEAM_CDN}/{appid}/library_600x900.jpg",
            "logo_url": f"{STEAM_CDN}/{appid}/logo.png"}


def flatten_status(status, limit=STATUS_KEY_LIMIT) -> dict:
    """Flatten the status to "a.b.c" keys, leaving out private, noisy and volatile fields."""
    flat = {}

    def scalar(value, free_text=False):
        if isinstance(value, str):
            return (scrub_paths(value) if free_text else value)[:MAX_STRING]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    def walk(value, prefix, depth):
        if len(flat) >= limit or depth > MAX_DEPTH:
            return
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if is_redacted(key) or key in NOISY_KEYS or is_volatile(key):
                    continue
                walk(child, f"{prefix}.{key}" if prefix else str(key), depth + 1)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            flat[prefix] = scalar(value, prefix.rsplit(".", 1)[-1].lower().endswith(FREE_TEXT_SUFFIXES))
        elif isinstance(value, list) and len(value) <= 8 and all(_small_item(item) for item in value):
            flat[prefix] = [[scalar(part) for part in item] if isinstance(item, (list, tuple)) else scalar(item)
                            for item in value]

    walk(status if isinstance(status, dict) else {}, "", 0)
    return flat


def build_snapshot(engine_status, faceplate_status, update_status, facts) -> dict:
    s = engine_status if isinstance(engine_status, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    appid = _number(_get(s, "game", "appid", default=0), int)
    non_steam = appid >= 2 ** 31
    controllers = [
        {key: value for key, value in item.items() if not is_redacted(key)}
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
            # lifetime_uploads goes to "status" instead: a counter in the
            # entity's attributes would make every recorded row unique.
            "brightness_applied": faceplate_status.get("brightness_applied"),
            "appid": faceplate_status.get("appid"),
        }
    update_status = update_status if isinstance(update_status, dict) else {}
    private_channel = update_status.get("channel") == "private"
    # Areas that become entity attributes carry no counters or timestamps,
    # since the recorder stores each distinct set. Those go to "status".
    status = flatten_status(s)
    if isinstance(faceplate_status, dict):
        status.setdefault("faceplate.lifetime_uploads", faceplate_status.get("lifetime_uploads"))
    status.setdefault("update.last_checked_at", update_status.get("last_checked_at"))
    for key, value in update_status.items():
        if key.endswith("_at") and not is_redacted(key):
            status.setdefault(f"update.{key}", value)
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
        "update": {**{key: update_status.get(key) for key in UPDATE_HEADLINE},
                   **{key: (value[:MAX_STRING] if isinstance(value, str) else value)
                      for key, value in update_status.items()
                      if not is_redacted(key) and not key.endswith("_at") and key not in UPDATE_NOT_PUBLISHED
                      and not (private_channel and key in UPDATE_PRIVATE_CHANNEL_ONLY)
                      and isinstance(value, (str, int, float, bool, type(None)))}},
        "bridge": {
            "frontend_connected": bool(facts.get("frontend_connected", False)),
            "events_dropped": _number(facts.get("events_dropped", 0), int),
            "version": _get(s, "version"),
            "last_error": str(facts.get("last_error") or "")[:MAX_STRING],
        },
        "info": {
            "version": _get(s, "version"),
            "enabled": bool(_get(s, "signalbar_enabled", default=False)),
            "frontend_connected": bool(facts.get("frontend_connected", False)),
        },
        "status": status,
    })
