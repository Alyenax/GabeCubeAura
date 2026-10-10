"""Which GabeCubeAura settings Home Assistant may change, and how each value is checked first.

The list builds itself from the settings store. A bool setting becomes a
switch, and a setting whose allowed values the store names (a VALID_* set
named after the key, EVENT_VARIANTS or CONTROLLER_VARIANTS) becomes a select
with exactly those options. Numbers are never guessed: only the keys in
NUMBERS become number entities.

store.LOCAL_ONLY_SETTINGS are reported but only the Steam Machine may change
them. DENIED keys are neither controllable nor reported, and NOT_EXPOSED keys
have no fitting entity yet. A test fails on any key left unclassified, so each
new setting gets sorted.

faceplate_* keys belong to the faceplate device and its own level; builds
without a faceplate service simply have none.
"""

from __future__ import annotations

import re

from signalbar.settings import store

from .snapshot import is_redacted

DEVICES = ("light_bar", "faceplate")  # each has its own "<device>_level" in mqtt.json
FACEPLATE_PREFIX = "faceplate_"
MAX_PAYLOAD = 64
# Used with fullmatch, since "$" would accept a trailing newline. Up to 17
# decimals because automations send float results in full
# (0.35000000000000003); the step check allows for that. No exponents.
_NUMBER_TEXT = re.compile(r"-?[0-9]{1,6}(\.[0-9]{1,17})?")
# Steps are checked in floating point, where (0.34 - 0.15) / 0.01 is
# 19.000000000000004.
STEP_TOLERANCE = 1e-9

# Never controllable and never reported: private values and fields that are
# not a setting of their own. What only the Steam Machine may change lives in
# store.LOCAL_ONLY_SETTINGS instead.
DENIED = {
    "mode": "legacy field; writing it rewrites the in-game display",
    "led_output_calibration_mode": "retired; the store forces it",
    "audio_sync_sensitivity": "retired; the store forces it to 100",
    "audio_sync_style": "legacy; writes both the Home and in-game styles, which are exposed",
    "audio_sync_palette": "legacy; writes both the Home and in-game palettes, which are exposed",
    "performance_enabled": "legacy migration field",
    "performance_always": "derived from the Home display",
    "weather_display": "derived; writing it changes the displays without leaving the display preset",
    "controller_battery_display": "derived; writing it changes the displays without leaving the display preset",
    "controller_charging_display": "derived from controller_charging_mode",
    "controller_charging_enabled": "derived from controller_charging_mode",
    "controller_player_palette_revision": "internal revision; the store forces it",
    "weather_sequence_revision": "internal revision; the store forces it",
    "weather_location": "your location; it never leaves the device",
    "faceplate_image_path": "a file path on the device",
}
DENIED_SUFFIXES = {"_profiles": "per-game maps, not one value", "_restore": "the display preset's undo state"}

NOT_EXPOSED = {
    "audio_sync_lab_crest_strength": "Hi-Fi Crest beta lab calibration",
    "audio_sync_lab_edge_reach": "Hi-Fi Crest beta lab calibration",
    "audio_sync_lab_background": "Hi-Fi Crest beta lab calibration",
    "audio_sync_hifi_lab_enabled": "Hi-Fi Crest beta lab calibration",
    "faceplate_clock_colour": "colour text",
}

# key: (minimum, maximum, step, whole numbers, unit, name). The ranges are
# what store._validate clamps to; a test checks both ends against a real store.
NUMBERS = {
    "light_bar_day_brightness": (1, 255, 1, True, None, "Day brightness"),
    "night_mode_brightness": (10, 100, 1, True, None, "Night brightness"),
    "screen_sync_brightness": (34, 255, 1, True, None, "Screen Sync brightness"),
    "screen_sync_black_threshold": (0, 32, 1, True, None, "Screen Sync black threshold"),
    "audio_sync_brightness": (34, 255, 1, True, None, "Audio Sync brightness"),
    "customization_colour_count": (1, 3, 1, True, None, "Customization+ colours"),
    "customization_brightness": (34, 255, 1, True, None, "Customization+ brightness"),
    "customization_speed": (1, 100, 1, True, None, "Customization+ speed"),
    "artwork_manual_y": (0.15, 0.9, 0.01, False, None, "Artwork sample height"),
    "artwork_vibrance": (0, 200, 1, True, "%", "Artwork vibrance"),
    "launch_artwork_colour_count": (2, 3, 1, True, None, "Game launch colours"),
    "launch_artwork_duration_seconds": (3, 45, 1, True, "s", "Game launch duration"),
    "cool_temp_c": (20, 100, 1, False, "°C", "Cool temperature"),
    "hot_temp_c": (21, 120, 1, False, "°C", "Hot temperature"),
    "countdown_full_bar_minutes": (0, 240, 60, True, "min", "Countdown full bar"),
    "countdown_dark_edge_compensation": (0, 6, 1, True, None, "Countdown edge compensation"),
    "free_timer_minutes": (5, 240, 1, True, "min", "Free timer length"),
    "controller_low_threshold": (5, 30, 1, True, "%", "Controller low battery"),
    "controller_gauge_brightness": (10, 100, 1, True, None, "Controller gauge brightness"),
    "weather_brightness": (10, 100, 1, True, None, "Weather brightness"),
    "weather_shadow_cutoff": (0, 60, 1, True, None, "Weather shadow cutoff"),
    **{key: (0, store.WEATHER_VARIANT_COUNTS[key.removeprefix("weather_").removesuffix("_variant")] - 1,
             1, True, None, None) for key in store.WEATHER_VARIANT_KEYS},
    "faceplate_brightness": (0, 100, 1, True, "%", "Faceplate brightness"),
    "faceplate_aura_interval": (30, 600, 1, True, "s", "Faceplate aura interval"),
}

CHOICES = {
    "audio_sync_home_style": store.VALID_AUDIO_SYNC_STYLES,
    "audio_sync_game_style": store.VALID_AUDIO_SYNC_STYLES,
    "audio_sync_home_palette": store.VALID_AUDIO_SYNC_PALETTES,
    "audio_sync_game_palette": store.VALID_AUDIO_SYNC_PALETTES,
    "launch_artwork_source": store.VALID_ARTWORK_SOURCES,
    "controller_charging_mode": ("off", "brief", "continuous-home", "continuous-everywhere"),
    "controller_alert_context": ("off", "home", "game", "both"),
    "controller_colour_preset": ("automatic", "manual"),
    "controller_colour_mode": ("battery", "players"),
    "weather_temperature_unit": ("celsius", "fahrenheit"),
}
FACEPLATE_CHOICE_NAMES = {
    "mode": "MODES", "artwork_idle": "IDLE_CHOICES", "art_style": "ART_STYLES",
    "logo_position": "LOGO_POSITIONS", "sleep_action": "SLEEP_ACTIONS", "shutdown_action": "SLEEP_ACTIONS",
}

# key -> function(sorted options) -> the options to keep. Empty, because the
# UI offers every option the store accepts, Customization+'s event:,
# controller: and weather: patterns included.
OPTION_FILTERS = {}

NAMES = {
    "signalbar_enabled": "Light bar control",
    "display_preset": "Display preset",
    "home_display": "Home display",
    "game_display": "In-game display",
    "events_enabled": "Light events",
    "night_mode_enabled": "Night mode",
    "reverse_led_order": "Reverse LED order",
    "audio_sync_home_style": "Audio Sync style (Home)",
    "audio_sync_game_style": "Audio Sync style (in game)",
    "audio_sync_home_palette": "Audio Sync palette (Home)",
    "audio_sync_game_palette": "Audio Sync palette (in game)",
}
ICONS = {
    "signalbar_enabled": "mdi:led-strip-variant",
    "display_preset": "mdi:palette",
    "home_display": "mdi:home",
    "game_display": "mdi:gamepad-variant",
}


class Control:
    """One controllable setting: its entity kind and the check its payload must pass."""

    def __init__(self, key, component, *, options=(), minimum=None, maximum=None, step=1, integer=True,
                 unit=None, name=None, preset=False):
        self.key = key
        self.device = device_of(key)
        self.component = component  # "switch" | "select" | "number"
        self.options = tuple(options)
        self.minimum, self.maximum, self.step, self.integer = minimum, maximum, step, integer
        self.unit = unit
        self.name = name or NAMES.get(key) or key.replace("_", " ").capitalize()
        self.icon = ICONS.get(key)
        self.preset = preset

    def __repr__(self) -> str:
        return f"Control({self.key!r}, {self.component!r})"

    def parse(self, payload):
        """Return the value a command payload asks for, or raise ValueError with a short reason."""
        if isinstance(payload, str):
            try:
                payload = payload.encode("utf-8")
            except UnicodeEncodeError:  # a lone surrogate; the error's own text would quote it
                raise ValueError("value is not text") from None
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError("value is not text")
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("value too long")
        try:
            text = bytes(payload).decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("value is not text") from None
        if self.component == "switch":
            if text in ("ON", "OFF"):
                return text == "ON"
            raise ValueError("expected ON or OFF")
        if self.component == "select":
            if text in self.options:
                return text
            raise ValueError("not one of the allowed options")
        if not _NUMBER_TEXT.fullmatch(text):
            raise ValueError("expected a number")
        number = float(text)
        if not self.minimum <= number <= self.maximum:
            raise ValueError(f"must be {_text(self.minimum)}-{_text(self.maximum)}")
        if not self.integer:
            steps = (number - self.minimum) / self.step
            if abs(steps - round(steps)) > STEP_TOLERANCE * max(1.0, abs(steps)):
                raise ValueError(f"must be in steps of {_text(self.step)}")
            return number
        if number != int(number):
            raise ValueError("must be a whole number")
        number = int(number)
        if (number - int(self.minimum)) % int(self.step):
            raise ValueError(f"must be in steps of {int(self.step)}")
        return number


class Schema:
    def __init__(self, controls, classes):
        self.controls = controls  # key -> Control
        # key -> "derived", "override", "denied", "local_only", "not_exposed" or None
        self.classes = classes
        self.local_only = frozenset(key for key, kind in classes.items() if kind == "local_only")

    def for_device(self, device):
        return [control for control in self.controls.values() if control.device == device]

    def reported(self, devices):
        """Keys whose values go to state/settings while these devices accept settings commands."""
        keys = [control.key for control in self.controls.values() if control.device in devices]
        return sorted(keys + [key for key in self.local_only if device_of(key) in devices])

    def unclassified(self):
        return sorted(key for key, kind in self.classes.items() if kind is None)


def device_of(key) -> str:
    return "faceplate" if key.startswith(FACEPLATE_PREFIX) else "light_bar"


def _text(number) -> str:
    return str(int(number)) if float(number).is_integer() else str(number)


def denial(key):
    """Why a key may never be controlled, or None."""
    if key in DENIED:
        return DENIED[key]
    for suffix, reason in DENIED_SUFFIXES.items():
        if key.endswith(suffix):
            return reason
    if is_redacted(key):
        return "private by name (never published either)"
    return None


def _is_colour(value) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value))


def _strings(value):
    if isinstance(value, (set, frozenset, tuple, list)) and value and all(isinstance(v, str) for v in value):
        return tuple(sorted(value))
    return ()


def derived_choices(key):
    """Return the store's own options for a key, or () if it names none."""
    for source in (store.EVENT_VARIANTS, store.CONTROLLER_VARIANTS):
        if key in source:
            return _strings(source[key])
    upper = key.upper()
    names = [f"VALID_{upper}", f"VALID_{upper}S", f"VALID_{upper}ES"]
    if upper.endswith("Y"):
        names.append(f"VALID_{upper[:-1]}IES")
    for name in names:
        options = _strings(getattr(store, name, None))
        if options:
            return options
    return ()


def faceplate_choices():
    """Return the faceplate's select options, or {} in a build without a faceplate."""
    try:
        from signalbar.faceplate import options
    except Exception:
        # Not only ImportError: a broken faceplate module must not take the
        # light bar's controls with it.
        return {}
    return {FACEPLATE_PREFIX + key: _strings(getattr(options, name, None))
            for key, name in FACEPLATE_CHOICE_NAMES.items() if _strings(getattr(options, name, None))}


def build_schema(defaults=None, faceplate=None, preset_keys=None, local_only=None,
                 option_filters=None) -> Schema:
    defaults = store.DEFAULTS if defaults is None else defaults
    choices = {**CHOICES, **(faceplate_choices() if faceplate is None else faceplate)}
    preset_keys = frozenset(store.DISPLAY_PRESET_CONTROLLED_KEYS if preset_keys is None else preset_keys)
    local_only = frozenset(store.LOCAL_ONLY_SETTINGS if local_only is None else local_only)
    option_filters = OPTION_FILTERS if option_filters is None else option_filters
    controls, classes = {}, {}
    for key in sorted(defaults):
        default = defaults[key]
        if denial(key):
            classes[key] = "denied"
            continue
        if key in local_only:
            classes[key] = "local_only"
            continue
        if key in NOT_EXPOSED or _is_colour(default):
            classes[key] = "not_exposed"
            continue
        preset = key in preset_keys
        if key in NUMBERS:
            minimum, maximum, step, integer, unit, name = NUMBERS[key]
            controls[key] = Control(key, "number", minimum=minimum, maximum=maximum, step=step,
                                    integer=integer, unit=unit, name=name, preset=preset)
            classes[key] = "override"
            continue
        if isinstance(default, bool) and key not in choices:
            controls[key] = Control(key, "switch", preset=preset)
            classes[key] = "derived"
            continue
        if key in choices:
            options, kind = tuple(sorted(choices[key])), "override"
        else:
            options, kind = derived_choices(key), "derived"
        if not options:
            classes[key] = None
            continue
        if key in option_filters:
            kept = option_filters[key](options)
            options, kind = tuple(option for option in kept if option in options), "override"
        if not options:
            classes[key] = "not_exposed"
            continue
        controls[key] = Control(key, "select", options=options, preset=preset)
        classes[key] = kind
    return Schema(controls, classes)
