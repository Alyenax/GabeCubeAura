"""Faceplate settings: defaults, validation, per-game overrides and the Pixel Faceplate import.

They live in GabeCubeAura's settings store with a ``faceplate_`` prefix, so
export and import carry them. The service sees them without the prefix.
"""

from __future__ import annotations

import json
import os

PREFIX = "faceplate_"
MODES = ("off", "artwork", "clock", "aura", "image")
IDLE_CHOICES = ("steam", "clock", "keep")
ART_STYLES = ("logo_dim", "logo", "art", "logo_only")
LOGO_POSITIONS = ("bottom", "centre", "top")
SLEEP_ACTIONS = ("off", "dim", "keep")
# Only these can differ per game; everything else belongs to the console.
GAME_KEYS = ("art_style", "logo_position")

DEFAULTS = {
    # "off" leaves the panel alone: it keeps playing whatever it last stored.
    "mode": "off",
    "brightness": 60,
    # Artwork mode with no game running: the Steam logo (one write per game
    # exit), the clock (a write a minute) or keep the last game's picture.
    "artwork_idle": "steam",
    # logo_dim draws the logo over a darkened band so the title reads on busy
    # art; logo skips the band; art has no logo; logo_only is the logo on black.
    "art_style": "logo_dim",
    "logo_position": "bottom",
    "clock_24h": False,
    "clock_colour": "#ff8c14",
    # Every upload lands in the panel's SPI flash (it survives a power cycle,
    # and each one looks like a sector erase), so aura samples slowly and only
    # sends when the colours visibly change.
    "aura_interval": 60,
    "image_path": "",
    # What the panel does when the Steam Machine sleeps or shuts down. USB
    # stays powered through sleep, so "keep" leaves the picture on all night.
    "sleep_action": "off",
    "shutdown_action": "off",
    # Faceplate mounted upside down so the cable leaves on the right. The
    # included cable is too short for that side; it needs a longer one.
    "rotate": False,
    # Per-game overrides keyed by app ID: {"1931770": {"art_style": "logo"}}.
    "game_profiles": {},
}


def _int(value, name, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a whole number" % name)
    if isinstance(value, float) and value != number:
        raise ValueError("%s must be a whole number" % name)
    if not low <= number <= high:
        raise ValueError("%s must be %d-%d" % (name, low, high))
    return number


def _choice(value, name, choices):
    if value not in choices:
        raise ValueError("%s must be one of %s" % (name, ", ".join(choices)))
    return value


def parse_colour(text):
    text = str(text).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("colour must look like #ff8c14")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise ValueError("colour must look like #ff8c14")


def clean(key, value):
    """One validated setting (unprefixed key); raises ValueError."""
    if key == "mode":
        return _choice(value, key, MODES)
    if key == "artwork_idle":
        return _choice(value, key, IDLE_CHOICES)
    if key == "art_style":
        return _choice(value, key, ART_STYLES)
    if key == "logo_position":
        return _choice(value, key, LOGO_POSITIONS)
    if key in ("sleep_action", "shutdown_action"):
        return _choice(value, key, SLEEP_ACTIONS)
    if key in ("clock_24h", "rotate"):
        return bool(value)
    if key == "brightness":
        return _int(value, "brightness", 0, 100)
    if key == "aura_interval":
        return _int(value, "aura interval", 30, 600)
    if key == "clock_colour":
        parse_colour(value)
        return "#" + str(value).strip().lstrip("#").lower()
    if key == "image_path":
        path = os.path.expanduser(str(value or "").strip())
        if path and not os.path.isfile(path):
            raise ValueError("image not found: %s" % path)
        return path
    if key == "game_profiles":
        if not isinstance(value, dict):
            raise ValueError("game_profiles must be a mapping")
        return {str(_int(appid, "app ID", 1, 0xFFFFFFFF)): game_profile(profile)
                for appid, profile in value.items()}
    raise ValueError("unknown faceplate setting %s" % key)


def game_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("a game profile must be a mapping")
    unknown = set(profile) - set(GAME_KEYS)
    if unknown:
        raise ValueError("%s can't be set per game" % ", ".join(sorted(unknown)))
    return {key: clean(key, value) for key, value in profile.items()}


def stored_defaults():
    """DEFAULTS as GabeCubeAura's store keys them."""
    return {PREFIX + key: value for key, value in DEFAULTS.items()}


def validate_stored(data):
    """Clean every faceplate_ key in a store dict in place; bad values fall back to defaults."""
    for key, default in DEFAULTS.items():
        try:
            data[PREFIX + key] = clean(key, data.get(PREFIX + key, default))
        except ValueError:
            data[PREFIX + key] = json.loads(json.dumps(default))


def unprefixed(values):
    """The service's view of the store: faceplate settings without their prefix."""
    return {key: values.get(PREFIX + key, default) for key, default in DEFAULTS.items()}


def for_game(values, appid):
    """Settings as one game sees them: the console's, with that game's overrides on top."""
    profile = values.get("game_profiles", {}).get(str(appid)) if appid else None
    return dict(values, **profile) if profile else dict(values)


def import_pixel_faceplate(settings_dir):
    """Choices saved by the standalone Pixel Faceplate plugin, as store keys ({} if none).

    Decky keeps each plugin's settings in a sibling folder, so this reads
    ../Pixel-Faceplate/settings.json once, the first time GabeCubeAura sees
    no faceplate settings of its own. Anything unreadable is skipped.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(settings_dir)), "Pixel-Faceplate", "settings.json")
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # Pixel Faceplate 0.2 spells these the American way.
    renamed = {"clock_color": "clock_colour"}
    values = {}
    for key, value in raw.items():
        key = renamed.get(key, key)
        if key == "logo_position" and value == "center":
            value = "centre"
        if key == "game_profiles" and isinstance(value, dict):
            value = {
                appid: {k: ("centre" if v == "center" else v) for k, v in profile.items()}
                for appid, profile in value.items() if isinstance(profile, dict)
            }
        if key not in DEFAULTS:
            continue
        try:
            values[PREFIX + key] = clean(key, value)
        except ValueError:
            continue
    return values
