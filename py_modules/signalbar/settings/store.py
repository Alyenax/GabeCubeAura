"""Atomic, schema-limited JSON settings persistence."""

from __future__ import annotations

import json
import math
import os
import threading
from copy import deepcopy

from signalbar.providers.customization import CUSTOMIZATION_PATTERNS

DEFAULTS = {
    # Only genuinely fresh installations see the guided setup. Existing
    # configuration files without this key are migrated to completed below.
    "onboarding_completed": False,
    "mode": "audio_sync",
    "signalbar_enabled": True,
    "home_display": "audio_sync",
    "game_display": "audio_sync",
    "display_profiles": {},
    "display_preset": "immersive-plus",
    "display_preset_restore": {},
    "valve_ownership_policy": "downloads",
    # Legacy import/export field. Runtime brightness is now entirely owned by
    # the explicit day value below.
    "led_output_calibration_mode": "consistent",
    "light_bar_day_brightness": 9,
    "screen_sync_style": "panorama",
    "screen_sync_brightness": 160,
    "screen_sync_reactivity": "balanced",
    "screen_sync_colour_intensity": "natural",
    "screen_sync_black_threshold": 8,
    "screen_sync_ignore_black_bars": True,
    "screen_sync_screensaver_enabled": True,
    "audio_sync_style": "slow-prism",
    "audio_sync_brightness": 180,
    # Retained as a neutral compatibility field for older exports/frontends.
    # Runtime analysis always uses 100 because programme-level matching makes
    # a user-facing pre-normalisation trim misleading after warm-up.
    "audio_sync_sensitivity": 100,
    "audio_sync_reactivity": "fast",
    "audio_sync_palette": "screen-sync",
    # Pattern and palette are contextual. The legacy pair above remains as a
    # migration and API compatibility seed, but runtime routing resolves one
    # of these explicit Home or in-game pairs.
    "audio_sync_home_style": "slow-prism",
    "audio_sync_home_palette": "screen-sync",
    "audio_sync_game_style": "slow-prism",
    "audio_sync_game_palette": "screen-sync",
    "audio_sync_home_colour_low": [11, 94, 142],
    "audio_sync_home_colour_middle": [8, 127, 191],
    "audio_sync_home_colour_high": [6, 148, 249],
    "audio_sync_game_colour_low": [11, 94, 142],
    "audio_sync_game_colour_middle": [8, 127, 191],
    "audio_sync_game_colour_high": [26, 159, 255],
    # Temporary on-device calibration controls for the Hi-Fi Crest beta lab.
    # A value of 100 preserves the reference 1.3.1 renderer exactly.
    "audio_sync_lab_crest_strength": 100,
    "audio_sync_lab_edge_reach": 100,
    "audio_sync_lab_background": 100,
    "audio_sync_hifi_lab_enabled": False,
    "audio_sync_colour_low": [11, 94, 142],
    "audio_sync_colour_middle": [8, 127, 191],
    "audio_sync_colour_high": [26, 159, 255],
    "customization_pattern": "steady",
    "customization_colour_count": 1,
    "customization_colour_1": [255, 153, 10],
    "customization_colour_2": [0, 200, 255],
    "customization_colour_3": [180, 48, 255],
    "customization_brightness": 60,
    "customization_speed": 50,
    "customization_direction": "forward",
    # Retained only to migrate v0.1/v0.2 Automatic configurations.
    "performance_enabled": True,
    "performance_metric": "mixed",
    "performance_smoothing": "responsive",
    "performance_always": False,
    "mixed_direction": "mirrored",
    "temperature_palette": "classic",
    "temperature_custom_cool": [30, 180, 230],
    "temperature_custom_middle": [245, 180, 45],
    "temperature_custom_hot": [235, 45, 55],
    "artwork_mode": "auto",
    "artwork_manual_y": 0.34,
    "artwork_source": "hero",
    "artwork_vibrance": 100,
    "artwork_profiles": {
        "1030300": {"manual_y": 0.34, "mode": "auto", "source": "hero", "vibrance": 100},
        "977880": {"manual_y": 0.34, "mode": "auto", "source": "hero", "vibrance": 100},
    },
    "launch_artwork_animation_enabled": True,
    "launch_artwork_pattern": "arpege-crossed",
    "launch_artwork_colour_count": 2,
    "launch_artwork_duration_seconds": 5,
    "launch_artwork_source": "hero",
    "launch_artwork_profiles": {},
    "cool_temp_c": 45.0,
    "hot_temp_c": 78.0,
    "reverse_led_order": True,
    "parental_countdown_enabled": True,
    "countdown_colour": "white",
    # 0 follows the timer's initial duration; otherwise this is fixed minutes.
    "countdown_full_bar_minutes": 0,
    "countdown_dark_edge_compensation": 2,
    "free_timer_minutes": 60,
    "events_enabled": True,
    "event_notifications_enabled": True,
    "event_achievements_enabled": True,
    "event_screenshots_enabled": True,
    "event_recording_enabled": True,
    # Optional optical separation for the persistent red recording marker.
    "recording_marker_isolation": True,
    "event_notification_variant": "notification-beacon",
    "event_achievement_variant": "achievement-constellation",
    "event_screenshot_variant": "screenshot-bloom",
    "controller_battery_display": "off",
    # Charging choices are exclusive; legacy display/enabled keys are derived
    # for compatibility with older local beta settings.
    "controller_charging_mode": "brief",
    "controller_charging_display": "off",
    "controller_alert_context": "both",
    "controller_alerts_enabled": True,
    "controller_connect_enabled": True,
    "controller_low_enabled": True,
    "controller_charging_enabled": True,
    "controller_low_threshold": 20,
    "controller_connect_variant": "welcome",
    "controller_persistent_variant": "tip",
    "controller_low_variant": "beacon",
    "controller_charging_variant": "breath",
    "controller_duo_variant": "double-welcome",
    "controller_colour_preset": "automatic",
    "controller_colour_mode": "battery",
    "controller_colour_normal": [0, 180, 45],
    "controller_colour_medium": [230, 110, 0],
    "controller_colour_low": [220, 12, 24],
    "controller_colour_charging": [0, 145, 220],
    "controller_player_colour_1": [36, 199, 245],
    "controller_player_colour_2": [255, 167, 26],
    "controller_player_colour_3": [106, 26, 255],
    "controller_player_colour_4": [70, 210, 136],
    "controller_player_palette_revision": 1,
    "controller_gauge_brightness": 65,
    "weather_display": "off",
    "weather_location": None,
    "weather_topbar_enabled": True,
    "weather_icon_style": "phosphor-duotone",
    "weather_temperature_unit": "celsius",
    "night_mode_enabled": False,
    "night_mode_brightness": 35,
    "weather_brightness": 100,
    "weather_shadow_cutoff": 0,
    "weather_sequence_revision": 12,
    "weather_clear_day_variant": 0,
    "weather_clear_night_variant": 0,
    "weather_rain_variant": 0,
    "weather_cloud_variant": 3,
    "weather_cloud_night_variant": 2,
    "weather_breaks_variant": 0,
    "weather_breaks_night_variant": 0,
    "weather_snow_variant": 1,
    "weather_storm_variant": 0,
    "stripmine_integration_enabled": True,
    "tw3_steamrgb_integration_enabled": True,
    "stripmine_priority_artwork": "stripmine",
    "stripmine_priority_performance": "stripmine",
    "stripmine_priority_weather": "stripmine",
    "stripmine_priority_controller": "stripmine",
    "stripmine_priority_light_events": "signalbar",
    "stripmine_priority_game_launches": "signalbar",
    "stripmine_priority_customization": "stripmine",
    "stripmine_priority_screen_sync": "stripmine",
    "stripmine_priority_audio_sync": "stripmine",
    "guard_cooldown_s": 5.0,
    "guard_stable_s": 2.0,
    "updates_auto_check": True,
    "updates_notifications": True,
    "updates_check_interval_minutes": 1440,
    "updates_channel": "stable",
}

VALID_MODES = {"artwork", "performance", "customization", "screen_sync", "audio_sync", "blackout", "events", "disabled"}
VALID_HOME_DISPLAYS = {"steam", "blackout", "customization", "performance", "audio_sync", "weather", "controller"}
VALID_GAME_DISPLAYS = {"steam", "blackout", "customization", "artwork", "performance", "screen_sync", "audio_sync", "weather", "controller"}
VALID_DISPLAY_PRESETS = {
    "custom", "lights-out", "focus", "essential", "moderate",
    "atmosphere", "signals", "immersive", "immersive-plus", "festive",
}
VALID_VALVE_OWNERSHIP_POLICIES = {"cooperative", "downloads", "critical"}
VALID_SCREEN_SYNC_STYLES = {"panorama", "ambient"}
VALID_SCREEN_SYNC_REACTIVITY = {"calm", "balanced", "fast"}
VALID_SCREEN_SYNC_COLOUR_INTENSITY = {"natural", "vivid"}
VALID_AUDIO_SYNC_STYLES = {
    "hifi-crest", "velvet-relay", "negative-bloom", "stereo-lanterns",
    "constellation", "slow-prism", "spectrum", "spatial", "bass",
    "audio-pulse",
}
VALID_AUDIO_SYNC_REACTIVITY = {"calm", "balanced", "fast", "punchy"}

# Reference tunings are deliberately different for each optical pattern. They
# are loaded when the user selects a style, then remain freely adjustable.
# Bright, sparse renderers can use more headroom than full-width patterns on
# the Steam Machine diffuser without producing the same white bloom.
AUDIO_SYNC_STYLE_TUNING = {
    "hifi-crest": {
        "audio_sync_brightness": 160,
        "audio_sync_reactivity": "balanced",
        "audio_sync_lab_crest_strength": 100,
        "audio_sync_lab_edge_reach": 100,
        "audio_sync_lab_background": 100,
    },
    "velvet-relay": {
        "audio_sync_brightness": 184,
        "audio_sync_reactivity": "fast",
    },
    "negative-bloom": {
        "audio_sync_brightness": 192,
        "audio_sync_reactivity": "fast",
    },
    "stereo-lanterns": {
        "audio_sync_brightness": 172,
        "audio_sync_reactivity": "balanced",
    },
    "constellation": {
        "audio_sync_brightness": 205,
        "audio_sync_reactivity": "fast",
    },
    "slow-prism": {
        "audio_sync_brightness": 180,
        "audio_sync_reactivity": "fast",
    },
    "spectrum": {
        "audio_sync_brightness": 190,
        "audio_sync_reactivity": "fast",
    },
    "spatial": {
        "audio_sync_brightness": 170,
        "audio_sync_reactivity": "balanced",
    },
    "bass": {
        "audio_sync_brightness": 185,
        "audio_sync_reactivity": "fast",
    },
    "audio-pulse": {
        "audio_sync_brightness": 168,
        "audio_sync_reactivity": "balanced",
    },
}
VALID_AUDIO_SYNC_PALETTES = {
    "aurora", "ember", "magma", "forest", "ice", "copper", "solar",
    "pearl", "glacier", "lagoon", "lime", "orchid", "plasma",
    "sunset", "deep-sea", "silver", "candy", "sapphire", "coastline",
    "screen-sync", "artwork", "custom",
}
VALID_ARTWORK_MODES = {"auto", "center", "lower", "manual"}
VALID_ARTWORK_SOURCES = {"hero", "header", "capsule"}
VALID_LAUNCH_ARTWORK_PATTERNS = {
    "arpege-crossed", "two-hands", "legato", "nocturne", "crescendo",
    "color-wipe", "scanner", "theater-chase", "twinkle", "ripple",
}
VALID_CUSTOMIZATION_PATTERNS = CUSTOMIZATION_PATTERNS
VALID_CUSTOMIZATION_DIRECTIONS = {"forward", "reverse"}
VALID_PERFORMANCE_METRICS = {"cpu", "gpu", "mixed"}
VALID_PERFORMANCE_SMOOTHING = {"responsive", "balanced", "smooth"}
VALID_MIXED_DIRECTIONS = {"same", "mirrored"}
VALID_TEMPERATURE_PALETTES = {"thermal", "classic", "icefire", "custom"}
VALID_COUNTDOWN_COLOURS = {"cyan", "green", "amber", "violet", "white"}
VALID_COMPANION_PRIORITIES = {"stripmine", "signalbar"}
VALID_WEATHER_ICON_STYLES = {
    "current", "material-rounded", "phosphor-duotone",
}

DISPLAY_PRESET_RECIPES = {
    "lights-out": {
        "signalbar_enabled": True,
        "home_display": "blackout",
        "game_display": "blackout",
        "display_profiles": {},
        "valve_ownership_policy": "critical",
        "launch_artwork_animation_enabled": False,
        "parental_countdown_enabled": True,
        "events_enabled": False,
        "controller_alerts_enabled": False,
        "controller_alert_context": "off",
        "controller_connect_enabled": False,
        "controller_low_enabled": False,
        "controller_charging_mode": "off",
        "screen_sync_screensaver_enabled": False,
    },
    "focus": {
        "signalbar_enabled": True,
        "home_display": "customization",
        "game_display": "customization",
        "display_profiles": {},
        "valve_ownership_policy": "critical",
        "launch_artwork_animation_enabled": False,
        "parental_countdown_enabled": True,
        "events_enabled": False,
        "controller_alerts_enabled": False,
        "controller_alert_context": "off",
        "controller_connect_enabled": False,
        "controller_low_enabled": False,
        "controller_charging_mode": "off",
        "screen_sync_screensaver_enabled": False,
    },
    "essential": {
        "signalbar_enabled": True,
        "home_display": "blackout",
        "game_display": "blackout",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": False,
        "parental_countdown_enabled": True,
        "events_enabled": False,
        "controller_alerts_enabled": False,
        "controller_alert_context": "off",
        "controller_connect_enabled": False,
        "controller_low_enabled": False,
        "controller_charging_mode": "off",
        "screen_sync_screensaver_enabled": False,
    },
    "moderate": {
        "signalbar_enabled": True,
        "home_display": "customization",
        "game_display": "artwork",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": True,
        "parental_countdown_enabled": True,
        "events_enabled": True,
        "event_notifications_enabled": True,
        "event_achievements_enabled": True,
        "event_screenshots_enabled": True,
        "event_recording_enabled": True,
        "controller_alerts_enabled": True,
        "controller_alert_context": "both",
        "controller_connect_enabled": True,
        "controller_low_enabled": True,
        "controller_charging_mode": "brief",
        "screen_sync_screensaver_enabled": True,
    },
    "atmosphere": {
        "signalbar_enabled": True,
        "home_display": "weather",
        "game_display": "artwork",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": True,
        "parental_countdown_enabled": True,
        "events_enabled": True,
        "event_notifications_enabled": True,
        "event_achievements_enabled": True,
        "event_screenshots_enabled": True,
        "event_recording_enabled": True,
        "controller_alerts_enabled": True,
        "controller_alert_context": "both",
        "controller_connect_enabled": True,
        "controller_low_enabled": True,
        "controller_charging_mode": "brief",
        "screen_sync_screensaver_enabled": True,
        "audio_sync_style": "slow-prism",
        "audio_sync_home_style": "slow-prism",
        "audio_sync_brightness": 180,
        "audio_sync_reactivity": "fast",
        "audio_sync_palette": "screen-sync",
        "audio_sync_home_palette": "screen-sync",
    },
    "signals": {
        "signalbar_enabled": True,
        "home_display": "controller",
        "game_display": "performance",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": True,
        "parental_countdown_enabled": True,
        "events_enabled": True,
        "event_notifications_enabled": True,
        "event_achievements_enabled": True,
        "event_screenshots_enabled": True,
        "event_recording_enabled": True,
        "controller_alerts_enabled": True,
        "controller_alert_context": "both",
        "controller_connect_enabled": True,
        "controller_low_enabled": True,
        "controller_charging_mode": "continuous-home",
        "screen_sync_screensaver_enabled": True,
    },
    "immersive": {
        "signalbar_enabled": True,
        "home_display": "audio_sync",
        "game_display": "screen_sync",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": True,
        "parental_countdown_enabled": True,
        "events_enabled": True,
        "event_notifications_enabled": True,
        "event_achievements_enabled": True,
        "event_screenshots_enabled": True,
        "event_recording_enabled": True,
        "controller_alerts_enabled": True,
        "controller_alert_context": "both",
        "controller_connect_enabled": True,
        "controller_low_enabled": True,
        "controller_charging_mode": "brief",
        "screen_sync_screensaver_enabled": True,
        "audio_sync_style": "slow-prism",
        "audio_sync_home_style": "slow-prism",
        "audio_sync_brightness": 180,
        "audio_sync_reactivity": "fast",
        "audio_sync_palette": "sapphire",
        "audio_sync_home_palette": "sapphire",
        "audio_sync_game_style": "slow-prism",
        "audio_sync_game_palette": "screen-sync",
    },
    "immersive-plus": {
        "signalbar_enabled": True,
        "home_display": "audio_sync",
        "game_display": "audio_sync",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": True,
        "parental_countdown_enabled": True,
        "events_enabled": True,
        "event_notifications_enabled": True,
        "event_achievements_enabled": True,
        "event_screenshots_enabled": True,
        "event_recording_enabled": True,
        "controller_alerts_enabled": True,
        "controller_alert_context": "both",
        "controller_connect_enabled": True,
        "controller_low_enabled": True,
        "controller_charging_mode": "brief",
        "screen_sync_screensaver_enabled": True,
        "audio_sync_style": "slow-prism",
        "audio_sync_home_style": "slow-prism",
        "audio_sync_game_style": "slow-prism",
        "audio_sync_brightness": 180,
        "audio_sync_reactivity": "fast",
        "audio_sync_palette": "screen-sync",
        "audio_sync_home_palette": "screen-sync",
        "audio_sync_game_palette": "screen-sync",
    },
    "festive": {
        "signalbar_enabled": True,
        "home_display": "audio_sync",
        "game_display": "audio_sync",
        "display_profiles": {},
        "valve_ownership_policy": "downloads",
        "launch_artwork_animation_enabled": True,
        "parental_countdown_enabled": True,
        "events_enabled": True,
        "event_notifications_enabled": True,
        "event_achievements_enabled": True,
        "event_screenshots_enabled": True,
        "event_recording_enabled": True,
        "controller_alerts_enabled": True,
        "controller_alert_context": "both",
        "controller_connect_enabled": True,
        "controller_low_enabled": True,
        "controller_charging_mode": "brief",
        "screen_sync_screensaver_enabled": True,
        "audio_sync_style": "slow-prism",
        "audio_sync_home_style": "slow-prism",
        "audio_sync_game_style": "slow-prism",
        "audio_sync_brightness": 180,
        "audio_sync_reactivity": "fast",
        "audio_sync_palette": "screen-sync",
        "audio_sync_home_palette": "screen-sync",
        "audio_sync_game_palette": "aurora",
    },
}
# Steam Families and the validated SteamOS top-bar weather indicator remain
# available in every named routing recipe, including deliberately quiet ones.
for _preset_recipe in DISPLAY_PRESET_RECIPES.values():
    _preset_recipe["parental_countdown_enabled"] = True
    _preset_recipe["weather_topbar_enabled"] = True
DISPLAY_PRESET_CONTROLLED_KEYS = tuple(sorted({
    key for recipe in DISPLAY_PRESET_RECIPES.values() for key in recipe
} | {
    "audio_sync_home_style",
    "audio_sync_home_palette",
    "audio_sync_game_style",
    "audio_sync_game_palette",
}))
EVENT_VARIANTS = {
    "event_notification_variant": {
        "notification-original", "notification-return", "notification-echo",
        "notification-ample", "notification-double", "notification-beacon",
    },
    "event_achievement_variant": {
        "achievement-original", "achievement-confetti", "achievement-rebound",
        "achievement-constellation", "achievement-twoway", "achievement-supernova",
    },
    "event_screenshot_variant": {
        "screenshot-original", "screenshot-double", "screenshot-scan",
        "screenshot-bloom", "screenshot-ripple",
    },
}
CONTROLLER_VARIANTS = {
    "controller_connect_variant": {"welcome", "orbit", "handshake"},
    "controller_persistent_variant": {"clean", "tip", "horizon"},
    "controller_low_variant": {"beacon", "drain", "heartbeat"},
    "controller_charging_variant": {"current", "breath", "spark"},
    "controller_duo_variant": {"twin", "focus", "double-welcome"},
}
WEATHER_VARIANT_KEYS = tuple(key for key in DEFAULTS if key.startswith("weather_") and key.endswith("_variant"))
WEATHER_VARIANT_COUNTS = {
    "clear_day": 2, "clear_night": 2, "rain": 2, "cloud": 4,
    "cloud_night": 4, "breaks": 2, "breaks_night": 2,
    "snow": 2, "storm": 2,
}


def _valid_weather_location(value):
    if not isinstance(value, dict):
        return None
    try:
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
        name = str(value["name"]).strip()[:80]
        country = str(value.get("country", "")).strip()[:80]
        if (not name or not math.isfinite(latitude) or not math.isfinite(longitude)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return {"name": name, "country": country, "latitude": latitude, "longitude": longitude}


class SettingsStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._data = deepcopy(DEFAULTS)
        self.load()

    def load(self):
        with self._lock:
            try:
                with open(self.path, encoding="utf-8") as handle:
                    raw = json.load(handle)
                if isinstance(raw, dict):
                    for key in DEFAULTS:
                        if key in raw:
                            self._data[key] = raw[key]
                    if "onboarding_completed" not in raw:
                        # Do not interrupt existing users after an upgrade.
                        self._data["onboarding_completed"] = True
                    if "display_preset" not in raw:
                        # A legacy configuration is not guaranteed to match
                        # the new fresh-install Immersive+ recipe.
                        self._data["display_preset"] = "custom"
                    # Lab 20 splits the Audio Sync pattern and palette by
                    # context. Existing installations must look identical in
                    # both contexts until the user deliberately changes one.
                    legacy_audio_style = raw.get(
                        "audio_sync_style", DEFAULTS["audio_sync_style"],
                    )
                    legacy_audio_palette = raw.get(
                        "audio_sync_palette", DEFAULTS["audio_sync_palette"],
                    )
                    for key in ("audio_sync_home_style", "audio_sync_game_style"):
                        if key not in raw:
                            self._data[key] = legacy_audio_style
                    for key in ("audio_sync_home_palette", "audio_sync_game_palette"):
                        if key not in raw:
                            self._data[key] = legacy_audio_palette
                    # Lab 22 gives Home and in-game Custom palettes their own
                    # three colours. Seed both from the former shared palette
                    # so existing installations remain visually unchanged.
                    for context in ("home", "game"):
                        for role in ("low", "middle", "high"):
                            contextual_key = f"audio_sync_{context}_colour_{role}"
                            legacy_key = f"audio_sync_colour_{role}"
                            if contextual_key not in raw:
                                self._data[contextual_key] = deepcopy(
                                    raw.get(legacy_key, DEFAULTS[contextual_key])
                                )
                    legacy_routing = (
                        "signalbar_enabled" not in raw
                        and "home_display" not in raw
                        and "game_display" not in raw
                    )
                    if raw.get("weather_sequence_revision") not in (10, 11, 12):
                        migration = {
                            "clear_night": {0: 0, 3: 1},
                            "rain": {2: 0, 3: 1},
                            "storm": {3: 0, 4: 1},
                        }
                        for condition, variants in migration.items():
                            key = f"weather_{condition}_variant"
                            self._data[key] = variants.get(raw.get(key), 0)
                        self._data["weather_sequence_revision"] = 12
                    if "controller_charging_mode" not in raw:
                        display = raw.get("controller_charging_display")
                        if display == "home":
                            self._data["controller_charging_mode"] = "continuous-home"
                        elif display == "everywhere":
                            self._data["controller_charging_mode"] = "continuous-everywhere"
                        else:
                            self._data["controller_charging_mode"] = (
                                "brief" if raw.get("controller_charging_enabled", True) else "off"
                            )
                    if raw.get("controller_player_palette_revision") != 1:
                        old_defaults = (
                            [37, 200, 245], [255, 180, 59],
                            [167, 119, 255], [75, 211, 138],
                        )
                        for player, old_default in enumerate(old_defaults, 1):
                            key = f"controller_player_colour_{player}"
                            if key not in raw or raw.get(key) == old_default:
                                self._data[key] = list(DEFAULTS[key])
                        self._data["controller_player_palette_revision"] = 1
                    if "controller_colour_preset" not in raw:
                        colour_keys = (
                            "controller_colour_normal", "controller_colour_medium",
                            "controller_colour_low", "controller_colour_charging",
                            "controller_player_colour_1", "controller_player_colour_2",
                            "controller_player_colour_3", "controller_player_colour_4",
                        )
                        customised = any(
                            self._data.get(key) != DEFAULTS[key] for key in colour_keys
                        )
                        self._data["controller_colour_preset"] = (
                            "manual"
                            if raw.get("controller_colour_mode") == "players" or customised
                            else "automatic"
                        )
                    # v0.7.x stored one display mode plus independent context
                    # switches. Preserve the effective Home/game result once,
                    # then make the new routing fields authoritative.
                    if "signalbar_enabled" not in raw:
                        self._data["signalbar_enabled"] = raw.get("mode") != "disabled"
                    if "home_display" not in raw:
                        weather = raw.get("weather_display", "off")
                        controller = raw.get("controller_battery_display", "off")
                        if weather in {"home", "everywhere"}:
                            self._data["home_display"] = "weather"
                        elif controller in {"home", "everywhere"}:
                            self._data["home_display"] = "controller"
                        elif raw.get("mode") == "performance" and raw.get("performance_always", True):
                            self._data["home_display"] = "performance"
                        else:
                            self._data["home_display"] = "steam"
                    if "game_display" not in raw:
                        weather = raw.get("weather_display", "off")
                        controller = raw.get("controller_battery_display", "off")
                        if weather in {"game", "everywhere"}:
                            self._data["game_display"] = "weather"
                        elif controller in {"game", "everywhere"}:
                            self._data["game_display"] = "controller"
                        elif raw.get("mode") == "automatic":
                            self._data["game_display"] = (
                                "performance" if raw.get("performance_enabled", True) else "artwork"
                            )
                        elif raw.get("mode") in {"artwork", "performance"}:
                            self._data["game_display"] = raw["mode"]
                        else:
                            self._data["game_display"] = "steam"
                    # In v0.7.x, Signals only and Disabled suppressed every
                    # saved per-game permanent display. Do not reactivate a
                    # dormant Artwork or Performance override during routing
                    # migration. Artwork sampling choices remain preserved.
                    if legacy_routing and raw.get("mode") in {"events", "disabled"}:
                        self._data["display_profiles"] = {}
            except (OSError, ValueError, TypeError):
                pass
            self._validate()
            return dict(self._data)

    def _validate(self):
        self._data["onboarding_completed"] = bool(
            self._data["onboarding_completed"]
        )
        if self._data.get("display_preset") not in VALID_DISPLAY_PRESETS:
            self._data["display_preset"] = DEFAULTS["display_preset"]
        if self._data.get("valve_ownership_policy") not in VALID_VALVE_OWNERSHIP_POLICIES:
            self._data["valve_ownership_policy"] = DEFAULTS["valve_ownership_policy"]
        # Compatibility key retained for older configuration exports. Follow
        # Steam is intentionally retired because Steam cannot change this gain
        # while GabeCubeAura owns the bar.
        self._data["led_output_calibration_mode"] = "consistent"
        try:
            self._data["light_bar_day_brightness"] = max(
                1, min(255, int(round(float(self._data["light_bar_day_brightness"]))))
            )
        except (TypeError, ValueError, OverflowError):
            self._data["light_bar_day_brightness"] = DEFAULTS["light_bar_day_brightness"]
        raw_restore = self._data.get("display_preset_restore")
        self._data["display_preset_restore"] = (
            {
                key: deepcopy(raw_restore[key])
                for key in DISPLAY_PRESET_CONTROLLED_KEYS
                if isinstance(raw_restore, dict) and key in raw_restore
            }
            if isinstance(raw_restore, dict) else {}
        )
        self._data["stripmine_integration_enabled"] = bool(self._data["stripmine_integration_enabled"])
        self._data["tw3_steamrgb_integration_enabled"] = bool(
            self._data["tw3_steamrgb_integration_enabled"]
        )
        for key in (
            "stripmine_priority_artwork", "stripmine_priority_performance",
            "stripmine_priority_weather", "stripmine_priority_controller",
            "stripmine_priority_light_events",
            "stripmine_priority_game_launches",
            "stripmine_priority_customization",
            "stripmine_priority_screen_sync",
            "stripmine_priority_audio_sync",
        ):
            if self._data[key] not in VALID_COMPANION_PRIORITIES:
                self._data[key] = DEFAULTS[key]
        self._data["performance_enabled"] = bool(self._data["performance_enabled"])
        self._data["performance_always"] = bool(self._data["performance_always"])
        if self._data["mode"] == "automatic":
            self._data["mode"] = "performance" if self._data["performance_enabled"] else "artwork"
        elif self._data["mode"] not in VALID_MODES:
            self._data["mode"] = DEFAULTS["mode"]
        self._data["signalbar_enabled"] = bool(self._data["signalbar_enabled"])
        if self._data["home_display"] not in VALID_HOME_DISPLAYS:
            self._data["home_display"] = DEFAULTS["home_display"]
        if self._data["game_display"] not in VALID_GAME_DISPLAYS:
            self._data["game_display"] = DEFAULTS["game_display"]
        if self._data["screen_sync_style"] not in VALID_SCREEN_SYNC_STYLES:
            self._data["screen_sync_style"] = DEFAULTS["screen_sync_style"]
        if self._data["screen_sync_reactivity"] not in VALID_SCREEN_SYNC_REACTIVITY:
            self._data["screen_sync_reactivity"] = DEFAULTS["screen_sync_reactivity"]
        if self._data["screen_sync_colour_intensity"] not in VALID_SCREEN_SYNC_COLOUR_INTENSITY:
            self._data["screen_sync_colour_intensity"] = DEFAULTS["screen_sync_colour_intensity"]
        self._data["screen_sync_ignore_black_bars"] = bool(self._data["screen_sync_ignore_black_bars"])
        self._data["screen_sync_screensaver_enabled"] = bool(
            self._data["screen_sync_screensaver_enabled"]
        )
        for key, lower, upper in (
            ("screen_sync_brightness", 34, 255),
            ("screen_sync_black_threshold", 0, 32),
        ):
            try:
                self._data[key] = max(lower, min(upper, int(round(float(self._data[key])))))
            except (TypeError, ValueError, OverflowError):
                self._data[key] = DEFAULTS[key]
        legacy_audio_styles = {
            "screen-pulse": "audio-pulse",
            "screen-spatial": "spatial",
        }
        for key in (
            "audio_sync_style",
            "audio_sync_home_style",
            "audio_sync_game_style",
        ):
            self._data[key] = legacy_audio_styles.get(self._data[key], self._data[key])
        if self._data["audio_sync_style"] not in VALID_AUDIO_SYNC_STYLES:
            self._data["audio_sync_style"] = DEFAULTS["audio_sync_style"]
        if self._data["audio_sync_reactivity"] not in VALID_AUDIO_SYNC_REACTIVITY:
            self._data["audio_sync_reactivity"] = DEFAULTS["audio_sync_reactivity"]
        if self._data["audio_sync_palette"] == "game":
            self._data["audio_sync_palette"] = "screen-sync"
        if self._data["audio_sync_palette"] not in VALID_AUDIO_SYNC_PALETTES:
            self._data["audio_sync_palette"] = DEFAULTS["audio_sync_palette"]
        for key in ("audio_sync_home_style", "audio_sync_game_style"):
            if self._data[key] not in VALID_AUDIO_SYNC_STYLES:
                self._data[key] = DEFAULTS[key]
        for key in ("audio_sync_home_palette", "audio_sync_game_palette"):
            if self._data[key] == "game":
                self._data[key] = "screen-sync"
            if self._data[key] not in VALID_AUDIO_SYNC_PALETTES:
                self._data[key] = DEFAULTS[key]
        for key, lower, upper in (
            ("audio_sync_brightness", 34, 255),
            ("audio_sync_lab_crest_strength", 0, 250),
            ("audio_sync_lab_edge_reach", 50, 200),
            ("audio_sync_lab_background", 0, 150),
        ):
            try:
                self._data[key] = max(lower, min(upper, int(round(float(self._data[key])))))
            except (TypeError, ValueError, OverflowError):
                self._data[key] = DEFAULTS[key]
        # Older configurations may still carry this compatibility field. Keep
        # it neutral because runtime source-level matching is authoritative.
        self._data["audio_sync_sensitivity"] = 100
        if self._data["customization_pattern"] not in VALID_CUSTOMIZATION_PATTERNS:
            self._data["customization_pattern"] = DEFAULTS["customization_pattern"]
        if self._data["customization_direction"] not in VALID_CUSTOMIZATION_DIRECTIONS:
            self._data["customization_direction"] = DEFAULTS["customization_direction"]
        for key, lower, upper in (
            ("customization_colour_count", 1, 3),
            ("customization_brightness", 34, 255),
            ("customization_speed", 1, 100),
        ):
            try:
                self._data[key] = max(lower, min(upper, int(round(float(self._data[key])))))
            except (TypeError, ValueError, OverflowError):
                self._data[key] = DEFAULTS[key]
        if self._data["artwork_mode"] not in VALID_ARTWORK_MODES:
            self._data["artwork_mode"] = DEFAULTS["artwork_mode"]
        if self._data["artwork_source"] not in VALID_ARTWORK_SOURCES:
            self._data["artwork_source"] = DEFAULTS["artwork_source"]
        if self._data["launch_artwork_source"] not in VALID_ARTWORK_SOURCES:
            self._data["launch_artwork_source"] = DEFAULTS["launch_artwork_source"]
        self._data["launch_artwork_animation_enabled"] = bool(
            self._data["launch_artwork_animation_enabled"]
        )
        if self._data["launch_artwork_pattern"] not in VALID_LAUNCH_ARTWORK_PATTERNS:
            self._data["launch_artwork_pattern"] = DEFAULTS["launch_artwork_pattern"]
        try:
            colour_count = int(self._data["launch_artwork_colour_count"])
            self._data["launch_artwork_colour_count"] = colour_count if colour_count in (2, 3) else 2
        except (TypeError, ValueError, OverflowError):
            self._data["launch_artwork_colour_count"] = DEFAULTS["launch_artwork_colour_count"]
        try:
            self._data["launch_artwork_duration_seconds"] = max(
                3, min(45, int(round(float(self._data["launch_artwork_duration_seconds"]))))
            )
        except (TypeError, ValueError, OverflowError):
            self._data["launch_artwork_duration_seconds"] = DEFAULTS["launch_artwork_duration_seconds"]
        if self._data["performance_metric"] not in VALID_PERFORMANCE_METRICS:
            self._data["performance_metric"] = DEFAULTS["performance_metric"]
        if self._data["performance_smoothing"] not in VALID_PERFORMANCE_SMOOTHING:
            self._data["performance_smoothing"] = DEFAULTS["performance_smoothing"]
        if self._data["mixed_direction"] not in VALID_MIXED_DIRECTIONS:
            self._data["mixed_direction"] = DEFAULTS["mixed_direction"]
        if self._data["temperature_palette"] not in VALID_TEMPERATURE_PALETTES:
            self._data["temperature_palette"] = DEFAULTS["temperature_palette"]
        for key in (
            "temperature_custom_cool", "temperature_custom_middle", "temperature_custom_hot",
            "controller_colour_normal", "controller_colour_medium", "controller_colour_low", "controller_colour_charging",
            "controller_player_colour_1", "controller_player_colour_2",
            "controller_player_colour_3", "controller_player_colour_4",
            "customization_colour_1", "customization_colour_2", "customization_colour_3",
            "audio_sync_colour_low", "audio_sync_colour_middle", "audio_sync_colour_high",
            "audio_sync_home_colour_low", "audio_sync_home_colour_middle", "audio_sync_home_colour_high",
            "audio_sync_game_colour_low", "audio_sync_game_colour_middle", "audio_sync_game_colour_high",
        ):
            value = self._data.get(key)
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                self._data[key] = list(DEFAULTS[key])
                continue
            try:
                self._data[key] = [max(0, min(255, int(round(float(channel))))) for channel in value]
            except (TypeError, ValueError, OverflowError):
                self._data[key] = list(DEFAULTS[key])
        try:
            self._data["controller_gauge_brightness"] = max(10, min(100, int(self._data["controller_gauge_brightness"])))
        except (TypeError, ValueError, OverflowError):
            self._data["controller_gauge_brightness"] = DEFAULTS["controller_gauge_brightness"]
        self._data["controller_player_palette_revision"] = 1
        raw_display = self._data.get("display_profiles")
        display = {}
        if isinstance(raw_display, dict):
            for raw_id, mode in list(raw_display.items())[:512]:
                try:
                    appid = int(raw_id)
                except (TypeError, ValueError, OverflowError):
                    continue
                if 0 < appid <= 0xffffffff and isinstance(mode, str) and mode in VALID_GAME_DISPLAYS:
                    display[str(appid)] = mode
        self._data["display_profiles"] = display
        self._data["reverse_led_order"] = bool(self._data["reverse_led_order"])
        self._data["parental_countdown_enabled"] = bool(self._data["parental_countdown_enabled"])
        for key in (
            "events_enabled", "event_notifications_enabled", "event_achievements_enabled",
            "event_screenshots_enabled", "event_recording_enabled", "recording_marker_isolation",
            "controller_alerts_enabled", "controller_connect_enabled", "controller_low_enabled",
            "controller_charging_enabled", "audio_sync_hifi_lab_enabled",
            "updates_auto_check", "updates_notifications",
        ):
            self._data[key] = bool(self._data[key])
        try:
            interval = int(self._data["updates_check_interval_minutes"])
        except (TypeError, ValueError, OverflowError):
            interval = DEFAULTS["updates_check_interval_minutes"]
        self._data["updates_check_interval_minutes"] = (
            interval if interval in {15, 60, 180, 360, 720, 1440}
            else DEFAULTS["updates_check_interval_minutes"]
        )
        if self._data["updates_channel"] not in {"stable", "beta", "private"}:
            self._data["updates_channel"] = DEFAULTS["updates_channel"]
        for key, choices in EVENT_VARIANTS.items():
            if not isinstance(self._data[key], str) or self._data[key] not in choices:
                self._data[key] = DEFAULTS[key]
        if (not isinstance(self._data["controller_battery_display"], str)
                or self._data["controller_battery_display"] not in {"off", "home", "game", "everywhere"}):
            self._data["controller_battery_display"] = DEFAULTS["controller_battery_display"]
        if self._data.get("controller_colour_mode") not in {"battery", "players"}:
            self._data["controller_colour_mode"] = DEFAULTS["controller_colour_mode"]
        if self._data.get("controller_colour_preset") not in {"automatic", "manual"}:
            self._data["controller_colour_preset"] = DEFAULTS["controller_colour_preset"]
        if self._data["weather_display"] not in {"off", "home", "game", "everywhere"}:
            self._data["weather_display"] = DEFAULTS["weather_display"]
        if not isinstance(self._data["weather_topbar_enabled"], bool):
            self._data["weather_topbar_enabled"] = DEFAULTS["weather_topbar_enabled"]
        self._data["night_mode_enabled"] = bool(self._data["night_mode_enabled"])
        try:
            self._data["night_mode_brightness"] = max(
                10, min(100, int(round(float(self._data["night_mode_brightness"]))))
            )
        except (TypeError, ValueError, OverflowError):
            self._data["night_mode_brightness"] = DEFAULTS["night_mode_brightness"]
        if self._data["weather_icon_style"] not in VALID_WEATHER_ICON_STYLES:
            self._data["weather_icon_style"] = DEFAULTS["weather_icon_style"]
        if self._data["weather_temperature_unit"] not in {"celsius", "fahrenheit"}:
            self._data["weather_temperature_unit"] = DEFAULTS["weather_temperature_unit"]
        self._data["weather_location"] = _valid_weather_location(self._data["weather_location"])
        if self._data["weather_location"] is None:
            self._data["night_mode_enabled"] = False
        if self._data["weather_location"] is None:
            # Atmosphere intentionally keeps Weather as its Home route without
            # a city so the engine can use the recipe's former Slow Prism Home
            # display as a real fallback until Weather becomes available.
            if (self._data["home_display"] == "weather"
                    and self._data.get("display_preset") != "atmosphere"):
                self._data["home_display"] = "steam"
            if self._data["game_display"] == "weather":
                self._data["game_display"] = "steam"
            for appid, display in list(self._data["display_profiles"].items()):
                if display == "weather":
                    self._data["display_profiles"].pop(appid)
        for key, lower, upper in (("weather_brightness", 10, 100), ("weather_shadow_cutoff", 0, 60)):
            try:
                self._data[key] = max(lower, min(upper, int(round(float(self._data[key])))))
            except (TypeError, ValueError, OverflowError):
                self._data[key] = DEFAULTS[key]
        self._data["weather_sequence_revision"] = 12
        for key in WEATHER_VARIANT_KEYS:
            try:
                value = int(self._data[key])
                condition = key.removeprefix("weather_").removesuffix("_variant")
                count = WEATHER_VARIANT_COUNTS[condition]
                self._data[key] = value if 0 <= value < count else DEFAULTS[key]
            except (TypeError, ValueError, OverflowError):
                self._data[key] = DEFAULTS[key]
        # Compatibility fields remain exportable, but routing owns where each
        # permanent provider is allowed to appear.
        profile_displays = set(self._data["display_profiles"].values())
        home_weather = self._data["home_display"] == "weather"
        game_weather = self._data["game_display"] == "weather" or "weather" in profile_displays
        self._data["weather_display"] = (
            "everywhere" if home_weather and game_weather else "home" if home_weather
            else "game" if game_weather else "off"
        )
        home_controller = self._data["home_display"] == "controller"
        game_controller = self._data["game_display"] == "controller" or "controller" in profile_displays
        self._data["controller_battery_display"] = (
            "everywhere" if home_controller and game_controller else "home" if home_controller
            else "game" if game_controller else "off"
        )
        self._data["performance_always"] = self._data["home_display"] == "performance"
        self._data["mode"] = (
            "disabled" if not self._data["signalbar_enabled"]
            else self._data["game_display"] if self._data["game_display"] in {"artwork", "performance", "customization", "screen_sync", "audio_sync"}
            else "events"
        )
        charging_mode = self._data["controller_charging_mode"]
        if not isinstance(charging_mode, str) or charging_mode not in {
            "off", "brief", "continuous-home", "continuous-everywhere"
        }:
            charging_mode = DEFAULTS["controller_charging_mode"]
        self._data["controller_charging_mode"] = charging_mode
        self._data["controller_charging_enabled"] = charging_mode == "brief"
        self._data["controller_charging_display"] = {
            "off": "off", "brief": "off", "continuous-home": "home",
            "continuous-everywhere": "everywhere",
        }[charging_mode]
        if (not isinstance(self._data["controller_alert_context"], str)
                or self._data["controller_alert_context"] not in {"off", "home", "game", "both"}):
            self._data["controller_alert_context"] = DEFAULTS["controller_alert_context"]
        for key, choices in CONTROLLER_VARIANTS.items():
            if not isinstance(self._data[key], str) or self._data[key] not in choices:
                self._data[key] = DEFAULTS[key]
        try:
            threshold = int(round(float(self._data["controller_low_threshold"])))
            self._data["controller_low_threshold"] = max(5, min(30, threshold))
        except (TypeError, ValueError):
            self._data["controller_low_threshold"] = DEFAULTS["controller_low_threshold"]
        if self._data["countdown_colour"] not in VALID_COUNTDOWN_COLOURS:
            self._data["countdown_colour"] = DEFAULTS["countdown_colour"]
        try:
            full_bar_minutes = int(round(float(self._data["countdown_full_bar_minutes"])))
            self._data["countdown_full_bar_minutes"] = (
                full_bar_minutes if full_bar_minutes in {0, 60, 120, 180, 240} else 0
            )
        except (TypeError, ValueError):
            self._data["countdown_full_bar_minutes"] = DEFAULTS["countdown_full_bar_minutes"]
        try:
            self._data["countdown_dark_edge_compensation"] = max(
                0, min(6, int(round(float(self._data["countdown_dark_edge_compensation"]))))
            )
        except (TypeError, ValueError):
            self._data["countdown_dark_edge_compensation"] = DEFAULTS["countdown_dark_edge_compensation"]
        try:
            self._data["free_timer_minutes"] = max(5, min(240, int(round(float(self._data["free_timer_minutes"])))))
        except (TypeError, ValueError):
            self._data["free_timer_minutes"] = DEFAULTS["free_timer_minutes"]
        self._data["artwork_manual_y"] = max(0.15, min(0.90, float(self._data["artwork_manual_y"])))
        try:
            self._data["artwork_vibrance"] = max(
                0, min(200, int(round(float(self._data["artwork_vibrance"]))))
            )
        except (TypeError, ValueError, OverflowError):
            self._data["artwork_vibrance"] = DEFAULTS["artwork_vibrance"]
        self._data["cool_temp_c"] = max(20.0, min(100.0, float(self._data["cool_temp_c"])))
        self._data["hot_temp_c"] = max(self._data["cool_temp_c"] + 1.0, min(120.0, float(self._data["hot_temp_c"])))
        self._data["guard_cooldown_s"] = max(1.0, min(30.0, float(self._data["guard_cooldown_s"])))
        self._data["guard_stable_s"] = max(0.5, min(10.0, float(self._data["guard_stable_s"])))
        raw_profiles = self._data.get("artwork_profiles")
        profiles = {}
        if isinstance(raw_profiles, dict):
            for raw_appid, raw_profile in list(raw_profiles.items())[:512]:
                try:
                    appid = str(int(raw_appid))
                except (TypeError, ValueError):
                    continue
                if int(appid) <= 0 or not isinstance(raw_profile, dict):
                    continue
                mode = raw_profile.get("mode", DEFAULTS["artwork_mode"])
                if mode not in VALID_ARTWORK_MODES:
                    mode = DEFAULTS["artwork_mode"]
                source = raw_profile.get("source", DEFAULTS["artwork_source"])
                if source not in VALID_ARTWORK_SOURCES:
                    source = DEFAULTS["artwork_source"]
                try:
                    manual_y = max(0.15, min(0.90, float(raw_profile.get("manual_y", DEFAULTS["artwork_manual_y"]))))
                except (TypeError, ValueError):
                    manual_y = DEFAULTS["artwork_manual_y"]
                try:
                    vibrance = max(0, min(200, int(round(float(
                        raw_profile.get("vibrance", DEFAULTS["artwork_vibrance"])
                    )))))
                except (TypeError, ValueError, OverflowError):
                    vibrance = DEFAULTS["artwork_vibrance"]
                profiles[appid] = {
                    "mode": mode, "manual_y": manual_y, "source": source,
                    "vibrance": vibrance,
                }
        self._data["artwork_profiles"] = profiles
        raw_launch_profiles = self._data.get("launch_artwork_profiles")
        launch_profiles = {}
        if isinstance(raw_launch_profiles, dict):
            for raw_appid, raw_profile in list(raw_launch_profiles.items())[:512]:
                try:
                    appid = str(int(raw_appid))
                except (TypeError, ValueError, OverflowError):
                    continue
                if int(appid) <= 0 or not isinstance(raw_profile, dict):
                    continue
                mode = raw_profile.get("palette_mode", "artwork")
                if mode not in {"artwork", "custom"}:
                    mode = "artwork"
                defaults = {
                    "2": [list(DEFAULTS["customization_colour_1"]), list(DEFAULTS["customization_colour_2"])],
                    "3": [list(DEFAULTS["customization_colour_1"]), list(DEFAULTS["customization_colour_2"]), list(DEFAULTS["customization_colour_3"])],
                }
                palettes = {}
                raw_palettes = raw_profile.get("custom_palettes", {})
                for count in (2, 3):
                    raw = raw_palettes.get(str(count)) if isinstance(raw_palettes, dict) else None
                    if not isinstance(raw, (list, tuple)) or len(raw) != count:
                        palettes[str(count)] = defaults[str(count)]
                        continue
                    clean = []
                    for colour in raw:
                        if not isinstance(colour, (list, tuple)) or len(colour) != 3:
                            clean = []
                            break
                        try:
                            clean.append([max(0, min(255, int(round(float(channel))))) for channel in colour])
                        except (TypeError, ValueError, OverflowError):
                            clean = []
                            break
                    palettes[str(count)] = clean if len(clean) == count else defaults[str(count)]
                launch_profiles[appid] = {"palette_mode": mode, "custom_palettes": palettes}
        self._data["launch_artwork_profiles"] = launch_profiles

    def all(self):
        with self._lock:
            return dict(self._data)

    def update(self, changes: dict):
        with self._lock:
            changes = dict(changes)
            # Older frontends and imported configuration used one global
            # pair. Keep that API meaningful by applying it to both contexts.
            if "audio_sync_style" in changes:
                changes.setdefault("audio_sync_home_style", changes["audio_sync_style"])
                changes.setdefault("audio_sync_game_style", changes["audio_sync_style"])
            if "audio_sync_palette" in changes:
                changes.setdefault("audio_sync_home_palette", changes["audio_sync_palette"])
                changes.setdefault("audio_sync_game_palette", changes["audio_sync_palette"])
            for role in ("low", "middle", "high"):
                legacy_key = f"audio_sync_colour_{role}"
                if legacy_key in changes:
                    changes.setdefault(f"audio_sync_home_colour_{role}", changes[legacy_key])
                    changes.setdefault(f"audio_sync_game_colour_{role}", changes[legacy_key])
            requested_preset = changes.pop("display_preset", None)
            if requested_preset is not None:
                if requested_preset not in VALID_DISPLAY_PRESETS:
                    raise ValueError("Choose a supported display preset")
                if requested_preset == "custom":
                    restore = self._data.get("display_preset_restore", {})
                    if isinstance(restore, dict):
                        for key in DISPLAY_PRESET_CONTROLLED_KEYS:
                            if key in restore:
                                self._data[key] = deepcopy(restore[key])
                    self._data["display_preset_restore"] = {}
                    self._data["display_preset"] = "custom"
                else:
                    if self._data.get("display_preset") == "custom" \
                            or not self._data.get("display_preset_restore"):
                        self._data["display_preset_restore"] = {
                            key: deepcopy(self._data[key])
                            for key in DISPLAY_PRESET_CONTROLLED_KEYS
                        }
                    else:
                        # Recipes are overlays on the user's saved Custom
                        # baseline, not on the previously selected recipe.
                        # This prevents Atmosphere's fixed Slow Prism/Screen Sync
                        # choice from leaking into Festive or another preset.
                        restore = self._data.get("display_preset_restore", {})
                        if isinstance(restore, dict):
                            for key in DISPLAY_PRESET_CONTROLLED_KEYS:
                                if key in restore:
                                    self._data[key] = deepcopy(restore[key])
                    self._data.update(deepcopy(DISPLAY_PRESET_RECIPES[requested_preset]))
                    self._data["display_preset"] = requested_preset
            elif self._data.get("display_preset") != "custom" \
                    and any(key in DISPLAY_PRESET_CONTROLLED_KEYS for key in changes):
                # A direct edit intentionally starts from the active recipe.
                # The preset label must not claim that its exact recipe is
                # still active after the user changes one of its fields.
                self._data["display_preset"] = "custom"
                self._data["display_preset_restore"] = {}
            requested_audio_style = (
                changes.get("audio_sync_home_style")
                or changes.get("audio_sync_game_style")
                or changes.get("audio_sync_style")
            )
            if requested_audio_style in AUDIO_SYNC_STYLE_TUNING:
                # Explicit values in the same transaction win. This keeps
                # imports and tests deterministic while a normal style change
                # receives the hardware-tuned recommendation automatically.
                changes = {
                    **deepcopy(AUDIO_SYNC_STYLE_TUNING[requested_audio_style]),
                    **changes,
                }
            wants_weather = (
                changes.get("weather_display") not in (None, "off")
                or changes.get("home_display") == "weather"
                or changes.get("game_display") == "weather"
                or changes.get("night_mode_enabled") is True
            )
            if (wants_weather
                    and _valid_weather_location(changes.get("weather_location", self._data["weather_location"])) is None):
                raise ValueError("Choose a city before enabling Weather or automatic night mode")
            if "mode" in changes:
                legacy_mode = changes["mode"]
                if legacy_mode == "disabled":
                    changes = {**changes, "signalbar_enabled": False}
                elif legacy_mode in {"artwork", "performance", "customization", "screen_sync", "audio_sync", "blackout"}:
                    changes = {**changes, "signalbar_enabled": True, "game_display": legacy_mode}
                elif legacy_mode == "events":
                    changes = {**changes, "signalbar_enabled": True, "game_display": "steam"}
            if "weather_display" in changes:
                display = changes["weather_display"]
                changes = dict(changes)
                changes["home_display"] = "weather" if display in {"home", "everywhere"} else (
                    "steam" if changes.get("home_display", self._data["home_display"]) == "weather"
                    else changes.get("home_display", self._data["home_display"])
                )
                changes["game_display"] = "weather" if display in {"game", "everywhere"} else (
                    "steam" if changes.get("game_display", self._data["game_display"]) == "weather"
                    else changes.get("game_display", self._data["game_display"])
                )
            if "controller_battery_display" in changes:
                display = changes["controller_battery_display"]
                changes = dict(changes)
                changes["home_display"] = "controller" if display in {"home", "everywhere"} else (
                    "steam" if changes.get("home_display", self._data["home_display"]) == "controller"
                    else changes.get("home_display", self._data["home_display"])
                )
                changes["game_display"] = "controller" if display in {"game", "everywhere"} else (
                    "steam" if changes.get("game_display", self._data["game_display"]) == "controller"
                    else changes.get("game_display", self._data["game_display"])
                )
            for key, value in changes.items():
                if key in DEFAULTS:
                    self._data[key] = value
            self._validate()
            self.save()
            return dict(self._data)

    def replace_configuration(self, global_values: dict, display_profiles: dict,
                              artwork_profiles: dict, launch_artwork_profiles=None):
        """Atomically replace saved choices; malformed imports leave them intact."""
        launch_artwork_profiles = {} if launch_artwork_profiles is None else launch_artwork_profiles
        if not isinstance(global_values, dict) or not isinstance(display_profiles, dict) \
                or not isinstance(artwork_profiles, dict) or not isinstance(launch_artwork_profiles, dict):
            raise ValueError("Configuration sections must be objects")
        unsupported = set(global_values) - set(DEFAULTS) - {"display_profiles", "artwork_profiles", "launch_artwork_profiles"}
        if unsupported or any(key in global_values for key in ("display_profiles", "artwork_profiles", "launch_artwork_profiles")):
            raise ValueError("Configuration contains unsupported settings")
        if "mode" in global_values and global_values["mode"] not in VALID_MODES | {"automatic"}:
            raise ValueError("Invalid configuration setting: mode")
        imported = deepcopy(global_values)
        if "controller_colour_preset" not in imported:
            colour_keys = (
                "controller_colour_normal", "controller_colour_medium",
                "controller_colour_low", "controller_colour_charging",
                "controller_player_colour_1", "controller_player_colour_2",
                "controller_player_colour_3", "controller_player_colour_4",
            )
            customised = any(
                key in imported and imported[key] != DEFAULTS[key]
                for key in colour_keys
            )
            imported["controller_colour_preset"] = (
                "manual"
                if imported.get("controller_colour_mode") == "players" or customised
                else "automatic"
            )
        if "signalbar_enabled" not in imported:
            imported["signalbar_enabled"] = imported.get("mode") != "disabled"
        if "home_display" not in imported:
            weather = imported.get("weather_display", "off")
            controller = imported.get("controller_battery_display", "off")
            imported["home_display"] = (
                "weather" if weather in {"home", "everywhere"}
                else "controller" if controller in {"home", "everywhere"}
                else "performance" if imported.get("mode") == "performance"
                and imported.get("performance_always", True) else "steam"
            )
        if "game_display" not in imported:
            weather = imported.get("weather_display", "off")
            controller = imported.get("controller_battery_display", "off")
            imported["game_display"] = (
                "weather" if weather in {"game", "everywhere"}
                else "controller" if controller in {"game", "everywhere"}
                else ("performance" if imported.get("performance_enabled", True) else "artwork")
                if imported.get("mode") == "automatic"
                else imported.get("mode") if imported.get("mode") in {"artwork", "performance"}
                else "steam"
            )
        legacy_audio_style = imported.get("audio_sync_style", DEFAULTS["audio_sync_style"])
        legacy_audio_palette = imported.get("audio_sync_palette", DEFAULTS["audio_sync_palette"])
        imported.setdefault("audio_sync_home_style", legacy_audio_style)
        imported.setdefault("audio_sync_game_style", legacy_audio_style)
        imported.setdefault("audio_sync_home_palette", legacy_audio_palette)
        imported.setdefault("audio_sync_game_palette", legacy_audio_palette)
        for context in ("home", "game"):
            for role in ("low", "middle", "high"):
                imported.setdefault(
                    f"audio_sync_{context}_colour_{role}",
                    deepcopy(imported.get(
                        f"audio_sync_colour_{role}",
                        DEFAULTS[f"audio_sync_{context}_colour_{role}"],
                    )),
                )
        imported["display_profiles"] = deepcopy(display_profiles)
        imported["artwork_profiles"] = deepcopy(artwork_profiles)
        imported["launch_artwork_profiles"] = deepcopy(launch_artwork_profiles)
        with self._lock:
            previous = self._data
            try:
                self._data = deepcopy(DEFAULTS)
                self._data.update(imported)
                self._validate()
                # Reject invalid values rather than silently changing a user
                # selected import. Derived compatibility fields are expected
                # to be normalized from controller_charging_mode.
                derived = {
                    "mode", "performance_always", "weather_display", "controller_battery_display",
                    "controller_charging_enabled", "controller_charging_display",
                    "weather_sequence_revision",
                }
                for key, value in imported.items():
                    if key not in derived and self._data[key] != value:
                        raise ValueError(f"Invalid configuration setting: {key}")
                self.save()
            except Exception:
                self._data = previous
                raise
            return dict(self._data)

    def reset_configuration(self):
        return self.replace_configuration({}, {}, {})

    def artwork_for(self, appid=0):
        with self._lock:
            appid = int(appid or 0)
            profile = self._data["artwork_profiles"].get(str(appid), {}) if appid > 0 else {}
            return {
                "mode": profile.get("mode", self._data["artwork_mode"]),
                "manual_y": profile.get("manual_y", self._data["artwork_manual_y"]),
                "source": profile.get("source", self._data["artwork_source"]),
                "vibrance": profile.get("vibrance", self._data["artwork_vibrance"]),
                "custom": bool(profile),
            }

    def display_for(self, appid=0):
        with self._lock:
            appid = int(appid or 0)
            override = self._data["display_profiles"].get(str(appid), "inherit") if appid > 0 else "inherit"
            default = self._data["game_display"] if appid > 0 else self._data["home_display"]
            selected = default if override == "inherit" else override
            mode = (
                "disabled" if not self._data["signalbar_enabled"]
                else selected if selected in {"artwork", "performance", "customization", "screen_sync", "audio_sync", "blackout"} else "events"
            )
            return {"default": default, "override": override, "selected": selected, "mode": mode}

    def update_display(self, appid, mode):
        appid = int(appid)
        if not 0 < appid <= 0xffffffff or not isinstance(mode, str) or mode not in {"inherit", *VALID_GAME_DISPLAYS}:
            raise ValueError("A game AppID and a supported display or Inherit are required")
        with self._lock:
            if mode == "weather" and self._data["weather_location"] is None:
                raise ValueError("Choose a weather city before selecting Weather")
            if self._data.get("display_preset") != "custom":
                # Per-game routing is part of every preset recipe. Once the
                # user changes it, the result is an intentional custom setup.
                self._data["display_preset"] = "custom"
                self._data["display_preset_restore"] = {}
            profiles = dict(self._data["display_profiles"])
            if mode == "inherit":
                profiles.pop(str(appid), None)
            else:
                if str(appid) not in profiles and len(profiles) >= 512:
                    raise ValueError("Display profile limit reached (512)")
                profiles[str(appid)] = mode
            self._data["display_profiles"] = profiles
            self._validate()
            self.save()
            return self.display_for(appid)

    def update_artwork(self, appid, changes):
        with self._lock:
            appid = int(appid or 0)
            if appid <= 0:
                mapped = {}
                if "mode" in changes:
                    mapped["artwork_mode"] = changes["mode"]
                if "manual_y" in changes:
                    mapped["artwork_manual_y"] = changes["manual_y"]
                if "source" in changes:
                    mapped["artwork_source"] = changes["source"]
                if "vibrance" in changes:
                    mapped["artwork_vibrance"] = changes["vibrance"]
                return self.update(mapped)

            profiles = dict(self._data["artwork_profiles"])
            profile = dict(profiles.get(str(appid), self.artwork_for(0)))
            profile.pop("custom", None)
            if "mode" in changes:
                profile["mode"] = changes["mode"]
            if "manual_y" in changes:
                profile["manual_y"] = changes["manual_y"]
            if "source" in changes:
                profile["source"] = changes["source"]
            if "vibrance" in changes:
                profile["vibrance"] = changes["vibrance"]
            profiles[str(appid)] = profile
            self._data["artwork_profiles"] = profiles
            self._validate()
            self.save()
            return self.artwork_for(appid)

    def launch_artwork_for(self, appid=0):
        """Return the launch palette choice while retaining both custom sizes."""
        defaults = {
            "2": [list(DEFAULTS["customization_colour_1"]), list(DEFAULTS["customization_colour_2"])],
            "3": [list(DEFAULTS["customization_colour_1"]), list(DEFAULTS["customization_colour_2"]), list(DEFAULTS["customization_colour_3"])],
        }
        with self._lock:
            appid = int(appid or 0)
            profile = self._data["launch_artwork_profiles"].get(str(appid), {}) if appid > 0 else {}
            return {
                "palette_mode": profile.get("palette_mode", "artwork"),
                "custom_palettes": deepcopy(profile.get("custom_palettes", defaults)),
                "custom": bool(profile),
            }

    def update_launch_artwork(self, appid, changes):
        appid = int(appid or 0)
        if appid <= 0:
            raise ValueError("A running game AppID is required for a custom launch palette")
        with self._lock:
            profiles = deepcopy(self._data["launch_artwork_profiles"])
            profile = self.launch_artwork_for(appid)
            profile.pop("custom", None)
            if "palette_mode" in changes:
                profile["palette_mode"] = changes["palette_mode"]
            if "custom_palettes" in changes:
                profile["custom_palettes"] = deepcopy(changes["custom_palettes"])
            profiles[str(appid)] = profile
            self._data["launch_artwork_profiles"] = profiles
            self._validate()
            self.save()
            return self.launch_artwork_for(appid)

    def save(self):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, self.path)
