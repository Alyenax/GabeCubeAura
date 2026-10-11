"""Home Assistant MQTT discovery for GabeCubeAura: topics, entities and event types.

What the bridge relies on:
- An event payload is JSON whose "event_type" is already listed in the
  entity's event_types, so discovery is published again before a new type.
  Events are never retained.
- Image topics carry raw JPEG, PNG or WebP bytes. Home Assistant decodes them
  by the entity's content_type, so a new type is declared before the image.
- The Faceplate sensor exists only while a faceplate service reports status.
- Every entity sets has_entity_name, so names stay short ("CPU load") and
  entity IDs are scoped to the device.
- Setting entities, the light and the alert buttons exist only above Watch
  only. The bridge clears only the configs it recorded when the tier drops.
  Settings state is one retained topic, state/settings; commands arrive on
  set/<key>, drive commands on drive/<name>.
"""

from __future__ import annotations

import json
import re

BASE_EVENT_TYPES = {
    "game": ["started", "stopped"],
    "light_events": ["notification", "achievement", "screenshot", "record-start", "record-stop", "ha"],
    "controllers": ["connected", "disconnected", "charging"],
    "steam": ["download_started", "download_finished"],
    "thermal": ["tripped", "recovered"],
    "light_bar": ["owner_changed"],
    "countdown": ["started", "ended"],
}
KEY_ART_TYPES = ("image/jpeg", "image/png", "image/webp")
DEFAULT_KEY_ART_TYPE = "image/jpeg"
FRONTEND_AREAS = frozenset({"game", "controllers", "countdown", "light_events", "steam"})


def _slug(value) -> str:
    """Lowercase [a-z0-9_-] for topics and unique IDs; anything else becomes "_"."""
    return re.sub(r"[^a-z0-9_-]", "_", str(value).lower()).strip("_") or "other"


def _num(field) -> str:
    """Template for a numeric sensor: unknown when missing, never "" (Home Assistant rejects it)."""
    return (f"{{{{ value_json.{field} if value_json.{field} is defined "
            f"and value_json.{field} is not none else 'None' }}}}")


def _picked(fields) -> str:
    """Attributes template keeping only these fields of the area."""
    return "{{ {" + ", ".join(f"'{field}': value_json.{field}" for field in fields) + "} | tojson }}"


# Current game's attributes. session_minutes has its own sensor; in the
# attributes it would record a row every 5 minutes.
GAME_ATTRIBUTES = ("appid", "title", "non_steam", "started_at", "dominant_colours",
                   "key_art_url", "header_url", "capsule_url", "logo_url")


def _labelled(field, labels) -> str:
    """Template that shows a code as words; an unknown code shows as itself."""
    table = ", ".join(f"'{code}': '{word}'" for code, word in labels.items())
    return f"{{{{ {{{table}}}.get(value_json.{field}, value_json.{field}) }}}}"


# The codes themselves stay in each entity's attributes for automations.
WEATHER_LABELS = {
    "clear_day": "Clear", "clear_night": "Clear", "breaks": "Partly cloudy", "breaks_night": "Partly cloudy",
    "cloud": "Cloudy", "cloud_night": "Cloudy", "rain": "Rain", "snow": "Snow", "storm": "Thunderstorm",
}
UPDATE_LABELS = {
    "idle": "Idle", "checking": "Checking", "available": "Update available", "up_to_date": "Up to date",
    "error": "Error", "authorization_required": "Sign-in needed", "downloading": "Downloading",
    "verifying": "Verifying", "ready": "Ready to install", "installing": "Installing",
    "swap_started": "Installing", "swapped": "Installing", "restart_pending": "Restart needed",
    "updated": "Updated", "rolled_back": "Rolled back",
}
DISPLAY_LABELS = {
    "steam": "Steam", "blackout": "Blackout", "customization": "Customization+", "artwork": "Artwork",
    "performance": "Performance", "screen_sync": "Screen Sync", "audio_sync": "Audio Sync",
    "home_assistant": "Home Assistant", "weather": "Weather", "controller": "Controller status",
}


def node_id_for(hostname) -> str:
    return re.sub(r"[^a-z0-9_]", "_", str(hostname or "steammachine").lower()).strip("_") or "steammachine"


def event_area(kind, data):
    """Map a hub event to (event entity area, event type). New kinds map themselves."""
    if kind == "light_event":
        return "light_events", _slug(data.get("kind", "notification"))
    if kind == "steam.download":
        return "steam", "download_started" if data.get("active") else "download_finished"
    area, _, event_type = str(kind).partition(".")
    area = _slug(area)
    if area == "controller":
        area = "controllers"
    return area, _slug(event_type) if event_type else area


class Topics:
    def __init__(self, base_topic, node_id, discovery_prefix):
        self.node_id = node_id
        self.prefix = discovery_prefix
        self.root = f"{base_topic}/{node_id}"
        self.availability = f"{self.root}/availability"
        self.frontend = f"{self.root}/frontend"
        self.key_art_image = f"{self.root}/image/key_art"
        self.ha_status = f"{discovery_prefix}/status"
        self.command_prefix = f"{self.root}/set/"
        self.commands = f"{self.root}/set/+"
        self.preset_note = f"{self.root}/attributes/display_preset_note"
        self.drive_prefix = f"{self.root}/drive/"
        self.drive_commands = f"{self.root}/drive/+"

    def state(self, area):
        return f"{self.root}/state/{area}"

    def event(self, area):
        return f"{self.root}/event/{area}"

    def command(self, key):
        return f"{self.command_prefix}{key}"

    def drive(self, name):
        return f"{self.drive_prefix}{name}"

    def art_image(self, kind):
        return f"{self.root}/image/{kind}"


# (component, key, name, area, value template, extra discovery fields)
SENSORS = (
    ("sensor", "current_game", "Current game", "game",
     "{{ (value_json.title or value_json.appid) if value_json.running else 'Not playing' }}",
     {"icon": "mdi:gamepad-variant", "json_attributes_topic": "game",
      "json_attributes_template": _picked(GAME_ATTRIBUTES)}),
    ("binary_sensor", "game_running", "Game running", "game", "{{ 'ON' if value_json.running else 'OFF' }}", {}),
    ("sensor", "session_minutes", "Session length", "game", _num("session_minutes"),
     {"unit_of_measurement": "min", "device_class": "duration"}),
    ("sensor", "light_bar_owner", "Light bar owner", "light_bar", "{{ value_json.owner }}",
     {"json_attributes_topic": "light_bar"}),
    ("sensor", "light_bar_display", "Light bar display", "light_bar", _labelled("display", DISPLAY_LABELS), {}),
    # Valve's own brightness is not known while it owns the bar.
    ("sensor", "light_bar_brightness", "Light bar brightness", "light_bar", _num("brightness"),
     {"state_class": "measurement", "applies": "value_json.brightness is not none"}),
    ("binary_sensor", "night_mode", "Night mode", "light_bar",
     "{{ 'ON' if value_json.night_mode_active else 'OFF' }}", {}),
    ("binary_sensor", "recording", "Recording", "light_bar",
     "{{ 'ON' if value_json.recording else 'OFF' }}", {}),
    ("binary_sensor", "screensaver", "Screensaver", "light_bar",
     "{{ 'ON' if value_json.screensaver else 'OFF' }}", {}),
    ("binary_sensor", "download_active", "Steam download", "light_bar",
     "{{ 'ON' if value_json.download_active else 'OFF' }}", {}),
    ("binary_sensor", "thermal_protection", "Thermal protection", "performance",
     "{{ 'ON' if value_json.thermal_protection else 'OFF' }}", {"device_class": "heat"}),
    ("sensor", "cpu_load", "CPU load", "performance", _num("cpu_load"),
     {"unit_of_measurement": "%", "state_class": "measurement"}),
    ("sensor", "gpu_load", "GPU load", "performance", _num("gpu_load"),
     {"unit_of_measurement": "%", "state_class": "measurement"}),
    ("sensor", "cpu_temperature", "CPU temperature", "performance", _num("cpu_temperature"),
     {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}),
    ("sensor", "gpu_temperature", "GPU temperature", "performance", _num("gpu_temperature"),
     {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}),
    ("sensor", "controllers", "Controllers", "controllers", _num("count"),
     {"json_attributes_topic": "controllers", "icon": "mdi:controller", "state_class": "measurement"}),
    # Without a countdown a 0 would look like time ran out.
    ("sensor", "countdown", "Playtime remaining", "countdown", "{{ value_json.remaining_minutes }}",
     {"unit_of_measurement": "min", "json_attributes_topic": "countdown", "applies": "value_json.active"}),
    ("sensor", "weather", "Weather", "weather", _labelled("condition", WEATHER_LABELS),
     {"json_attributes_topic": "weather", "applies": "value_json.condition"}),
    ("sensor", "update", "Update", "update", _labelled("phase", UPDATE_LABELS),
     {"json_attributes_topic": "update", "applies": "value_json.phase"}),
    ("binary_sensor", "frontend_connected", "Decky frontend", "bridge",
     "{{ 'ON' if value_json.frontend_connected else 'OFF' }}",
     {"device_class": "connectivity", "entity_category": "diagnostic"}),
    # Not "None": Home Assistant reads that as unknown.
    ("sensor", "last_command_error", "Last command error", "bridge",
     "{{ value_json.last_error if value_json.last_error else 'No error' }}",
     {"entity_category": "diagnostic", "icon": "mdi:alert-circle-outline"}),
    # Fed by the tiny "info" area rather than "status": that one holds hundreds
    # of keys, and the recorder would store it again on every change. It stays
    # an MQTT-only topic for automations and debugging.
    ("sensor", "status", "Status", "info",
     "{{ 'Off' if not value_json.enabled else "
     "('Running' if value_json.frontend_connected else 'Frontend offline') }}",
     {"json_attributes_topic": "info", "entity_category": "diagnostic"}),
)
FACEPLATE_SENSOR = ("sensor", "faceplate", "Faceplate", "faceplate",
                    "{{ value_json.mode if value_json.available else 'None' }}",
                    {"json_attributes_topic": "faceplate", "icon": "mdi:grid"})


def _device(topics, version, hostname):
    return {
        "identifiers": [f"gabecubeaura_{topics.node_id}"],
        "name": f"GabeCubeAura ({hostname})",
        "manufacturer": "GabeCubeAura",
        "model": "Steam Machine",
        "sw_version": version or "unknown",
    }


def _availability(topics, area, applies=None):
    """The device's availability, the frontend's for its areas, and optionally a condition on the area.

    A value that does not apply (no countdown, Valve owning the bar) makes the
    entity unavailable rather than showing a made-up value. Home Assistant
    reads the condition from the same message as the state.
    """
    entries = [{"topic": topics.availability}]
    if area in FRONTEND_AREAS:
        entries.append({"topic": topics.frontend})
    if applies:
        entries.append({"topic": topics.state(area),
                        "value_template": f"{{{{ 'online' if {applies} else 'offline' }}}}"})
    return {"availability": entries, "availability_mode": "all"}


GAME_ART = {"header": "Header art", "capsule": "Cover art", "logo": "Logo"}
# The images keep the last game's art, so they are unavailable while no game
# runs rather than sent empty.
GAME_RUNNING = "value_json.running"


def art_discovery(topics, version, hostname, kind, content_type=DEFAULT_KEY_ART_TYPE):
    unique_id = f"gabecubeaura_{topics.node_id}_{kind}_art"
    return (f"{topics.prefix}/image/{unique_id}/config", {
        "name": GAME_ART[kind],
        "has_entity_name": True,
        "unique_id": unique_id,
        "image_topic": topics.art_image(kind),
        "content_type": content_type if content_type in KEY_ART_TYPES else DEFAULT_KEY_ART_TYPE,
        "device": _device(topics, version, hostname),
        **_availability(topics, "game", GAME_RUNNING),
    })


def key_art_discovery(topics, version, hostname, content_type=DEFAULT_KEY_ART_TYPE):
    unique_id = f"gabecubeaura_{topics.node_id}_key_art"
    return (f"{topics.prefix}/image/{unique_id}/config", {
        "name": "Key art",
        "has_entity_name": True,
        "unique_id": unique_id,
        "image_topic": topics.key_art_image,
        "content_type": content_type if content_type in KEY_ART_TYPES else DEFAULT_KEY_ART_TYPE,
        "device": _device(topics, version, hostname),
        **_availability(topics, "game", GAME_RUNNING),
    })


def _sensor_message(topics, device, entry):
    component, key, name, area, template, extra = entry
    unique_id = f"gabecubeaura_{topics.node_id}_{key}"
    payload = {
        "name": name,
        "has_entity_name": True,
        "unique_id": unique_id,
        "state_topic": topics.state(area),
        "value_template": template,
        "device": device,
        **_availability(topics, area, extra.get("applies")),
    }
    for field, value in extra.items():
        if field != "applies":
            payload[field] = topics.state(value) if field == "json_attributes_topic" else value
    return (f"{topics.prefix}/{component}/{unique_id}/config", payload)


def faceplate_discovery(topics, version, hostname):
    return _sensor_message(topics, _device(topics, version, hostname), FACEPLATE_SENSOR)


# Every preset-controlled setting entity takes this as attributes. It is
# static, so the recorder stores it once.
PRESET_NOTE = {
    "changes_display_preset": True,
    "note": "Changing this from Home Assistant switches GabeCubeAura to the Custom display preset "
            "(and drops the preset's undo), as changing it on the Steam Machine does.",
}


def _setting_unique_id(topics, control):
    return f"gabecubeaura_{topics.node_id}_setting_{control.key}"


def setting_discovery(topics, version, hostname, control):
    """Describe a switch, select or number for one schema.Control."""
    unique_id = _setting_unique_id(topics, control)
    key = control.key
    defined = f"value_json.{key} is defined and value_json.{key} is not none"
    payload = {
        "name": control.name,
        "has_entity_name": True,
        "unique_id": unique_id,
        "command_topic": topics.command(key),
        "state_topic": topics.state("settings"),
        "entity_category": "config",
        "device": _device(topics, version, hostname),
        **_availability(topics, "settings"),
    }
    if control.component == "switch":
        payload["payload_on"], payload["payload_off"] = "ON", "OFF"
        payload["value_template"] = f"{{{{ ('ON' if value_json.{key} else 'OFF') if {defined} else 'None' }}}}"
    elif control.component == "select":
        payload["value_template"] = f"{{{{ value_json.{key} if {defined} else 'None' }}}}"
        payload["options"] = list(control.options)
    else:
        payload["value_template"] = f"{{{{ value_json.{key} if {defined} else 'None' }}}}"
        payload.update({"min": control.minimum, "max": control.maximum, "step": control.step})
        if control.unit:
            payload["unit_of_measurement"] = control.unit
    if control.icon:
        payload["icon"] = control.icon
    if control.preset:
        payload["json_attributes_topic"] = topics.preset_note
    return (f"{topics.prefix}/{control.component}/{unique_id}/config", payload)


DRIVE_ALERT_VARIANTS = ("flash", "pulse", "sweep")


def drive_discovery(topics, version, hostname):
    """Describe the Home Assistant light and one button per alert variant."""
    device = _device(topics, version, hostname)
    availability = _availability(topics, "drive")
    light_id = f"gabecubeaura_{topics.node_id}_drive_light"
    messages = [(f"{topics.prefix}/light/{light_id}/config", {
        "name": "Light bar",
        "has_entity_name": True,
        "unique_id": light_id,
        "schema": "json",
        "command_topic": topics.drive("light"),
        "state_topic": topics.state("drive"),
        "brightness": True,
        "brightness_scale": 255,
        "supported_color_modes": ["rgb"],
        "icon": "mdi:led-strip-variant",
        "device": device,
        **availability,
    })]
    for variant in DRIVE_ALERT_VARIANTS:
        unique_id = f"gabecubeaura_{topics.node_id}_drive_alert_{variant}"
        messages.append((f"{topics.prefix}/button/{unique_id}/config", {
            "name": f"Alert: {variant}",
            "has_entity_name": True,
            "unique_id": unique_id,
            "command_topic": topics.drive("alert"),
            "payload_press": json.dumps({"variant": variant}, separators=(",", ":")),
            "icon": "mdi:alarm-light-outline",
            "device": device,
            **availability,
        }))
    return messages


def discovery_messages(topics, version, hostname, event_types, content_type=DEFAULT_KEY_ART_TYPE,
                       faceplate=False, art_types=None):
    device = _device(topics, version, hostname)
    messages = [_sensor_message(topics, device, entry) for entry in SENSORS]
    if faceplate:
        messages.append(_sensor_message(topics, device, FACEPLATE_SENSOR))
    for area, types in sorted(event_types.items()):
        unique_id = f"gabecubeaura_{topics.node_id}_events_{area}"
        messages.append((f"{topics.prefix}/event/{unique_id}/config", {
            "name": f"{area.removesuffix('_events').replace('_', ' ').capitalize()} events",
            "has_entity_name": True,
            "unique_id": unique_id,
            "state_topic": topics.event(area),
            "event_types": sorted(set(types)),
            "device": device,
            **_availability(topics, area),
        }))
    messages.append(key_art_discovery(topics, version, hostname, content_type))
    for kind in GAME_ART:
        messages.append(art_discovery(topics, version, hostname, kind,
                                      (art_types or {}).get(kind, DEFAULT_KEY_ART_TYPE)))
    return messages
