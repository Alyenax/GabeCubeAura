from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from signalbar.mqtt.discovery import BASE_EVENT_TYPES, Topics, discovery_messages, node_id_for, setting_discovery
from signalbar.mqtt.schema import build_schema, denial
from signalbar.mqtt.snapshot import is_redacted
from signalbar.settings import SettingsStore
from signalbar.settings import store as store_module

CITY = {"latitude": 35.8, "longitude": -84.5, "name": "Kingston", "country": "US"}


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = build_schema()
        self.controls = self.schema.controls

    def test_every_settings_key_is_classified(self):
        # A new setting: add it to NUMBERS, CHOICES, NOT_EXPOSED or DENIED in mqtt/schema.py,
        # or to LOCAL_ONLY_SETTINGS in settings/store.py if only the Steam Machine may change it.
        self.assertEqual(self.schema.unclassified(), [])
        schema = build_schema({**store_module.DEFAULTS, "future_speed": 3, "future_label": "x", "future_flag": False})
        self.assertEqual(schema.unclassified(), ["future_label", "future_speed"])

    def test_denied_keys_are_never_controls(self):
        for key in ("display_profiles", "display_preset_restore", "mode", "weather_location", "weather_display"):
            self.assertNotIn(key, self.controls, key)
            self.assertEqual(self.schema.classes[key], "denied", key)
        self.assertTrue(denial("faceplate_image_path"))
        self.assertFalse(any(is_redacted(key) for key in self.controls))

    def test_local_only_settings_are_reported_but_never_controllable(self):
        self.assertEqual(self.schema.local_only, store_module.LOCAL_ONLY_SETTINGS)
        for key in store_module.LOCAL_ONLY_SETTINGS:
            self.assertEqual(self.schema.classes[key], "local_only", key)
            self.assertNotIn(key, self.controls, key)
            self.assertIsNone(denial(key), key)
        self.assertTrue(store_module.LOCAL_ONLY_SETTINGS <= set(self.schema.reported({"light_bar"})))
        with mock.patch.object(store_module, "LOCAL_ONLY_SETTINGS", store_module.LOCAL_ONLY_SETTINGS | {"home_display"}):
            self.assertEqual(build_schema().classes["home_display"], "local_only")
        extra = build_schema(local_only=store_module.LOCAL_ONLY_SETTINGS | {"weather_location"})
        self.assertEqual(extra.classes["weather_location"], "denied")  # privacy wins

    def test_parse_is_strict_and_never_echoes_the_payload(self):
        switch, select, number = (self.controls[key] for key in ("signalbar_enabled", "home_display",
                                                                  "light_bar_day_brightness"))
        manual_y, cool = self.controls["artwork_manual_y"], self.controls["cool_temp_c"]
        for control, payload, value in ((switch, b"ON", True), (switch, b"OFF", False), (select, b"blackout", "blackout"),
                                        (number, b"9.0", 9), (manual_y, b"0.34", 0.34), (cool, b"45", 45.0),
                                        (manual_y, b"0.35000000000000003", 0.35000000000000003)):
            self.assertEqual(control.parse(payload), value, payload)
        for control, payload in ((switch, b"on"), (switch, b"1"), (select, b"Blackout"), (select, b"weather "),
                                 (number, b"0"), (number, b"256"), (number, b"9.5"), (number, b"nan"),
                                 (number, b"1e2"), (number, b""), (number, b"40\n"), (manual_y, b".35"),
                                 (self.controls["countdown_full_bar_minutes"], b"90")):
            with self.subTest(key=control.key, payload=payload), self.assertRaises(ValueError):
                control.parse(payload)
        for control, payload, reason in ((manual_y, b"0.345", "must be in steps of 0.01"),
                                         (cool, b"45.5", "must be in steps of 1"), (switch, b"x" * 65, "value too long"),
                                         (number, b"31415", "must be 1-255")):
            with self.assertRaises(ValueError) as caught:
                control.parse(payload)
            self.assertEqual(str(caught.exception), reason)


class SchemaMatchesStoreTests(unittest.TestCase):
    """Every value the schema promises Home Assistant is one the real store keeps as sent."""

    def test_every_option_switch_and_number_limit_round_trips(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = SettingsStore(os.path.join(tmp.name, "config.json"))
        store.update({"weather_location": CITY})  # Weather and night mode need a city
        for control in build_schema().controls.values():
            prerequisites = {"cool_temp_c": 20.0} if control.key == "hot_temp_c" else {}
            if control.component == "select":
                values, refused = control.options, ()
            elif control.component == "switch":
                values, refused = (not store.all()[control.key], store.all()[control.key]), ()
            else:
                values = (control.minimum, control.maximum)
                refused = (control.minimum - control.step, control.maximum + control.step)
            for value in values:
                store.update({**prerequisites, control.key: value})
                self.assertEqual(store.all()[control.key], value, (control.key, value))
                self.assertEqual(control.parse(str(value).encode()) if control.component == "number" else value,
                                 value, control.key)
            for value in refused:
                store.update({**prerequisites, control.key: value})
                self.assertNotEqual(store.all()[control.key], value, (control.key, value))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.topics = Topics("gabecubeaura", node_id_for("SteamMachine.local"), "homeassistant")
        self.messages = discovery_messages(self.topics, "1.4.0", "steammachine", BASE_EVENT_TYPES)

    def by_suffix(self, suffix):
        return next(p for _, p in self.messages if p["unique_id"].endswith(suffix))

    def test_every_entity_is_unique_named_and_tied_to_the_device(self):
        unique_ids = set()
        for topic, payload in self.messages:
            self.assertEqual(topic, f"homeassistant/{topic.split('/')[1]}/{payload['unique_id']}/config")
            self.assertIn(topic.split("/")[1], ("sensor", "binary_sensor", "event", "image"))
            self.assertEqual(payload["device"]["identifiers"], ["gabecubeaura_steammachine_local"])
            self.assertIn({"topic": self.topics.availability}, payload["availability"])
            self.assertIs(payload["has_entity_name"], True)
            self.assertNotIn("GabeCubeAura", payload["name"])
            unique_ids.add(payload["unique_id"])
        self.assertEqual(len(unique_ids), len(self.messages))
        self.assertIn({"topic": self.topics.frontend}, self.by_suffix("_current_game")["availability"])
        self.assertNotIn({"topic": self.topics.frontend}, self.by_suffix("_thermal_protection")["availability"])
        # Hundreds of status keys as attributes would be recorded again on every change.
        self.assertNotIn(self.topics.state("status"), {p.get("json_attributes_topic") for _, p in self.messages})

    def test_setting_entities_follow_the_schema(self):
        controls = build_schema().controls
        for control in controls.values():
            topic, payload = setting_discovery(self.topics, "1.4.0", "steammachine", control)
            self.assertEqual(payload["command_topic"], self.topics.command(control.key))
            self.assertIn(f"value_json.{control.key}", payload["value_template"])
            self.assertEqual(payload["entity_category"], "config")
            self.assertNotIn("retain", payload)  # Home Assistant then never retains commands
            self.assertEqual("json_attributes_topic" in payload, control.preset, control.key)
        number = setting_discovery(self.topics, "1.4.0", "steammachine", controls["cool_temp_c"])[1]
        self.assertEqual((number["min"], number["max"], number["step"]), (20, 100, 1))


if __name__ == "__main__":
    unittest.main()
