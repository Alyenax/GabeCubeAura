"""Which GabeCubeAura settings Home Assistant may change, and how each value is checked first.

The list builds itself from the settings store: a bool setting becomes a switch, and a setting whose
allowed values the store names (a VALID_* set named after the key, or EVENT_VARIANTS and
CONTROLLER_VARIANTS) becomes a select with exactly those options. Numbers are never guessed: only keys
in NUMBERS, with the range store._validate clamps to, become number entities. Keys in
store.LOCAL_ONLY_SETTINGS are GabeCubeAura's own decision: their values are reported, but only the
Steam Machine itself may change them. DENIED keys (private, legacy, derived) are neither controllable
nor reported; NOT_EXPOSED keys have no strict entity yet. A key in none of these is "unclassified",
and a test fails on it, so every new GabeCubeAura setting gets classified on purpose.

faceplate_* keys belong to the faceplate device and its own level. They exist only in builds with a
faceplate service; without them the faceplate simply has no controls.
"""

from __future__ import annotations

import re

from signalbar.settings import store

from .snapshot import is_redacted

DEVICES = ("light_bar", "faceplate")  # each has an MQTT config key f"{device}_level"
FACEPLATE_PREFIX = "faceplate_"
MAX_PAYLOAD = 64
# fullmatch: "$" would accept a trailing newline. Up to 17 decimals: an automation's float maths sends the
# full repr (0.35000000000000003), and the step check below has a tolerance for it. No exponent.
_NUMBER_TEXT = re.compile(r"-?[0-9]{1,6}(\.[0-9]{1,17})?")
# Decimal steps are checked in floating point: (0.34 - 0.15) / 0.01 is 19.000000000000004, not 19.
STEP_TOLERANCE = 1e-9

# Never controllable from Home Assistant and never reported, whatever the level: private values and
# fields that are not a setting of their own (legacy, retired, derived, internal revisions). What only
# the Steam Machine may change is GabeCubeAura's decision, in store.LOCAL_ONLY_SETTINGS, not here.
# Reasons are for people reading this.
DENIED = {
    "mode": "legacy field; writing it rewrites the in-game display",
    "led_output_calibration_mode": "retired; the store forces it",
    "audio_sync_sensitivity": "retired; the store forces it to 100",
    "audio_sync_style": "legacy pair that writes both Home and in-game styles; the Home/in-game keys are exposed",
    "audio_sync_palette": "legacy pair that writes both Home and in-game palettes; the Home/in-game keys are exposed",
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

# Could be controllable one day, but no strict Home Assistant entity fits yet. Colour triplets (a
# default that is a list of three numbers) are recognised by shape and land here too.
NOT_EXPOSED = {
    "audio_sync_lab_crest_strength": "Hi-Fi Crest beta lab calibration",
    "audio_sync_lab_edge_reach": "Hi-Fi Crest beta lab calibration",
    "audio_sync_lab_background": "Hi-Fi Crest beta lab calibration",
    "audio_sync_hifi_lab_enabled": "Hi-Fi Crest beta lab calibration",
    "faceplate_clock_colour": "colour text",
}

# key: (minimum, maximum, step, whole numbers, unit, name). Ranges are what store._validate clamps to;
# a test writes both ends and one step beyond each into a real store to prove it.
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
    # The store also keeps hot at least 1 °C above cool; the read-back reports when that moves it.
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
    # Faceplate builds only (faceplate/options.py clean()); inert while the keys do not exist.
    "faceplate_brightness": (0, 100, 1, True, "%", "Faceplate brightness"),
    "faceplate_aura_interval": (30, 600, 1, True, "s", "Faceplate aura interval"),
}

# Selects whose options the store checks against a set named after another key, or inline in
# _validate (no VALID_* set). A test proves every option round-trips through a real store.
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
# faceplate/options.py names its choices itself; read them only when that module exists.
FACEPLATE_CHOICE_NAMES = {
    "mode": "MODES", "artwork_idle": "IDLE_CHOICES", "art_style": "ART_STYLES",
    "logo_position": "LOGO_POSITIONS", "sleep_action": "SLEEP_ACTIONS", "shutdown_action": "SLEEP_ACTIONS",
}

# Select options Home Assistant may offer, per key, when the store accepts values the settings page
# never offers (internal or derived ones): key -> function(sorted options) -> the options to keep.
# test_select_options_are_ones_the_ui_offers checks every select against the UI source. Empty today:
# every option the store accepts is one the settings page offers, including Customization+'s borrowed
# "event:", "controller:" and "weather:" patterns (src/customization_catalog.ts lists them as choices).
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
    """One controllable setting: its entity kind and the strict check its command payload must pass."""

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
        # Writing it switches GabeCubeAura from a display preset to Custom (store.update).
        self.preset = preset

    def __repr__(self) -> str:
        return f"Control({self.key!r}, {self.component!r})"

    def parse(self, payload):
        """The setting value for a command payload, or ValueError with a short reason (no echo)."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError("value is not text")
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("value too long")
        try:
            text = bytes(payload).decode("utf-8")  # no strip: Home Assistant sends exact values
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
        # key -> "derived" | "override" | "denied" | "local_only" | "not_exposed" | None
        self.classes = classes
        # Kept on the Steam Machine (store.LOCAL_ONLY_SETTINGS): reported in state, never controllable.
        self.local_only = frozenset(key for key, kind in classes.items() if kind == "local_only")

    def for_device(self, device):
        return [control for control in self.controls.values() if control.device == device]

    def reported(self, devices):
        """Keys whose values go to state/settings while these devices are at level "settings"."""
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
    """The store's own option set for a key: EVENT/CONTROLLER_VARIANTS, or a VALID_* set named after it."""
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
    """Faceplate select options from faceplate/options.py, or {} in a build without a faceplate."""
    try:
        from signalbar.faceplate import options
    except Exception:  # noqa: BLE001 - ImportError on upstream main; anything else is a broken module
        # A faceplate module that fails to load must not take the light bar's controls with it. There
        # is no logger here (build_schema runs anywhere): fail closed, with no faceplate selects at all.
        return {}
    return {FACEPLATE_PREFIX + key: _strings(getattr(options, name, None))
            for key, name in FACEPLATE_CHOICE_NAMES.items() if _strings(getattr(options, name, None))}


def build_schema(defaults=None, faceplate=None, preset_keys=None, local_only=None,
                 option_filters=None) -> Schema:
    defaults = store.DEFAULTS if defaults is None else defaults
    choices = {**CHOICES, **(faceplate_choices() if faceplate is None else faceplate)}
    preset_keys = frozenset(store.DISPLAY_PRESET_CONTROLLED_KEYS if preset_keys is None else preset_keys)
    # GabeCubeAura's own list of what only the Steam Machine may change (settings/store.py).
    local_only = frozenset(store.LOCAL_ONLY_SETTINGS if local_only is None else local_only)
    option_filters = OPTION_FILTERS if option_filters is None else option_filters
    controls, classes = {}, {}
    for key in sorted(defaults):
        default = defaults[key]
        if denial(key):
            classes[key] = "denied"  # wins over local-only: a denied key is not even reported
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
        options, kind = (tuple(sorted(choices[key])), "override") if key in choices else (derived_choices(key), "derived")
        if not options:
            classes[key] = None
            continue
        if key in option_filters:
            options, kind = tuple(option for option in option_filters[key](options) if option in options), "override"
        if not options:
            classes[key] = "not_exposed"  # a filter that leaves nothing: no select at all
            continue
        controls[key] = Control(key, "select", options=options, preset=preset)
        classes[key] = kind
    return Schema(controls, classes)
