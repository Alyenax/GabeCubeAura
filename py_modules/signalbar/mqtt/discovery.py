"""Home Assistant MQTT discovery for GabeCubeAura: topics, entities and event types.

Contracts the bridge must honour:
- Event entity state payloads are JSON with an "event_type" that is already listed in that entity's
  event_types (republish discovery first when a new type appears), and are published NOT retained.
- The key-art image topic carries raw image bytes (JPEG, PNG or WebP), not JSON; the image entity's
  content_type must match the bytes, so republish its discovery config before an image of a new type.
- The Faceplate sensor is described only while a faceplate service reports status (discovery_messages
  faceplate=True); a build or install without one never gets a permanently unavailable entity.
- Every entity sets has_entity_name: names stay short ("CPU load") and Home Assistant prefixes the
  device name, so entity_ids are device-scoped.
- Settings entities (switch, select, number) exist only while their level is "settings": the bridge
  publishes setting_discovery() for them and, when the level goes back to report only, an empty
  retained payload on exactly the config topics it advertised (Home Assistant then deletes the
  entity). Their state is one retained JSON topic (state/settings); commands arrive on set/<key>.
"""

from __future__ import annotations

import re

BASE_EVENT_TYPES = {
    "game": ["started", "stopped"],
    "light_events": ["notification", "achievement", "screenshot", "record-start", "record-stop"],
    "controllers": ["connected", "disconnected", "charging"],
    "steam": ["download_started", "download_finished"],
    "thermal": ["tripped", "recovered"],
    "light_bar": ["owner_changed"],
    "countdown": ["started", "ended"],
}
KEY_ART_TYPES = ("image/jpeg", "image/png", "image/webp")
DEFAULT_KEY_ART_TYPE = "image/jpeg"
# Areas whose data only exists while the Decky frontend is running.
FRONTEND_AREAS = frozenset({"game", "controllers", "countdown", "light_events", "steam"})


def _slug(value) -> str:
    """Topic- and unique_id-safe: lowercase [a-z0-9_-], anything else becomes '_'."""
    return re.sub(r"[^a-z0-9_-]", "_", str(value).lower()).strip("_") or "other"


def _num(field) -> str:
    """Numeric sensors must never render '' (HA rejects it); 'None' becomes unknown. A real 0 stays 0."""
    return f"{{{{ value_json.{field} if value_json.{field} is defined and value_json.{field} is not none else 'None' }}}}"


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
        self.commands = f"{self.root}/set/+"  # one subscription for every setting command
        self.preset_note = f"{self.root}/attributes/display_preset_note"

    def state(self, area):
        return f"{self.root}/state/{area}"

    def event(self, area):
        return f"{self.root}/event/{area}"

    def command(self, key):
        return f"{self.command_prefix}{key}"


# (component, key, name, area, value template, extra discovery fields)
SENSORS = (
    ("sensor", "current_game", "Current game", "game", "{{ value_json.title if value_json.running else 'None' }}",
     {"icon": "mdi:gamepad-variant", "json_attributes_topic": "game"}),
    ("binary_sensor", "game_running", "Game running", "game", "{{ 'ON' if value_json.running else 'OFF' }}", {}),
    ("sensor", "session_minutes", "Session length", "game", _num("session_minutes"),
     {"unit_of_measurement": "min", "device_class": "duration"}),
    ("sensor", "light_bar_owner", "Light bar owner", "light_bar", "{{ value_json.owner }}",
     {"json_attributes_topic": "light_bar"}),
    ("sensor", "light_bar_display", "Light bar display", "light_bar", "{{ value_json.display }}", {}),
    ("sensor", "light_bar_brightness", "Light bar brightness", "light_bar", _num("brightness"), {"state_class": "measurement"}),
    ("binary_sensor", "night_mode", "Night mode", "light_bar", "{{ 'ON' if value_json.night_mode_active else 'OFF' }}", {}),
    ("binary_sensor", "recording", "Recording", "light_bar", "{{ 'ON' if value_json.recording else 'OFF' }}", {}),
    ("binary_sensor", "screensaver", "Screensaver", "light_bar", "{{ 'ON' if value_json.screensaver else 'OFF' }}", {}),
    ("binary_sensor", "download_active", "Steam download", "light_bar", "{{ 'ON' if value_json.download_active else 'OFF' }}", {}),
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
    ("sensor", "countdown", "Playtime remaining", "countdown",
     "{{ value_json.remaining_minutes if value_json.active else 'None' }}",
     {"unit_of_measurement": "min", "json_attributes_topic": "countdown"}),
    ("sensor", "weather", "Weather", "weather", "{{ value_json.condition }}", {"json_attributes_topic": "weather"}),
    ("sensor", "update", "Update", "update", "{{ value_json.phase }}", {"json_attributes_topic": "update"}),
    ("binary_sensor", "frontend_connected", "Decky frontend", "bridge",
     "{{ 'ON' if value_json.frontend_connected else 'OFF' }}", {"device_class": "connectivity", "entity_category": "diagnostic"}),
    # Why Home Assistant's last command was refused or changed (Report only level, bad value, the store
    # kept another value). Home Assistant's own "last changed" time says when.
    ("sensor", "last_command_error", "Last command error", "bridge",
     "{{ value_json.last_error if value_json.last_error else 'None' }}",
     {"entity_category": "diagnostic", "icon": "mdi:alert-circle-outline"}),
    # State and attributes come from the tiny "info" area, never the "status" area: that flattened blob
    # is hundreds of keys, and Home Assistant's recorder would store it anew on every change. "status"
    # stays an MQTT-only topic for automations and debugging. (Sharing light_bar with "Light bar owner"
    # stored every light bar change twice.)
    ("sensor", "status", "Status", "info",
     "{{ 'Off' if not value_json.enabled else ('Running' if value_json.frontend_connected else 'Frontend offline') }}",
     {"json_attributes_topic": "info", "entity_category": "diagnostic"}),
)
# Described only when a faceplate service exists (see faceplate_discovery).
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


def _availability(topics, area):
    entries = [{"topic": topics.availability}]
    if area in FRONTEND_AREAS:
        entries.append({"topic": topics.frontend})
    return {"availability": entries, "availability_mode": "all"}


def key_art_discovery(topics, version, hostname, content_type=DEFAULT_KEY_ART_TYPE):
    """The image entity's discovery message alone, for republishing when the key art's type changes."""
    unique_id = f"gabecubeaura_{topics.node_id}_key_art"
    return (f"{topics.prefix}/image/{unique_id}/config", {
        "name": "Key art",
        "has_entity_name": True,
        "unique_id": unique_id,
        "image_topic": topics.key_art_image,
        "content_type": content_type if content_type in KEY_ART_TYPES else DEFAULT_KEY_ART_TYPE,
        "device": _device(topics, version, hostname),
        **_availability(topics, "game"),
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
        **_availability(topics, area),
    }
    for field, value in extra.items():
        payload[field] = topics.state(value) if field == "json_attributes_topic" else value
    return (f"{topics.prefix}/{component}/{unique_id}/config", payload)


def faceplate_discovery(topics, version, hostname):
    """The Faceplate sensor's discovery message alone, for when a faceplate service appears."""
    return _sensor_message(topics, _device(topics, version, hostname), FACEPLATE_SENSOR)


# Retained once at preset_note; every preset-controlled setting entity takes it as attributes, so the
# warning shows in Home Assistant's entity details. Static, so the recorder stores it once.
PRESET_NOTE = {
    "changes_display_preset": True,
    "note": "Changing this from Home Assistant switches GabeCubeAura to the Custom display preset "
            "(and drops the preset's undo), as changing it on the Steam Machine does.",
}


def _setting_unique_id(topics, control):
    return f"gabecubeaura_{topics.node_id}_setting_{control.key}"


def setting_discovery(topics, version, hostname, control):
    """A switch, select or number for one controllable setting (schema.Control)."""
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
        # Settings live in the backend: they stay controllable while the Decky frontend is down.
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


def discovery_messages(topics, version, hostname, event_types, content_type=DEFAULT_KEY_ART_TYPE,
                       faceplate=False):
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
    return messages
