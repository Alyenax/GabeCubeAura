from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest

from signalbar.mqtt.advertised import AdvertisedTopics, is_ours
from signalbar.mqtt.config import DEVICE_TIERS, LIVE_KEYS, TIER_NAMES, MqttConfig
from signalbar.mqtt.routed import RoutedDisplays

CONFIG = "homeassistant/switch/gabecubeaura_steammachine_setting_signalbar_enabled/config"
STATE = "gabecubeaura/steammachine/state/settings"


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "mqtt")

    def write(self, name, content):
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
            handle.write(content if isinstance(content, str) else json.dumps(content))


class ConfigTests(StorageTestCase):
    def tiers(self, values):
        self.write("mqtt.json", values)
        public = MqttConfig(self.dir).public()
        return public["light_bar_tier"], public["faceplate_tier"]

    def test_defaults_are_off_and_nothing_is_written(self):
        public = MqttConfig(self.dir).public()
        self.assertEqual((public["enabled"], public["port"], public["turbo"], public["ha_fallback"],
                          public["light_bar_tier"], public["faceplate_tier"]), (False, 1883, False, True, 2, 2))
        self.assertNotIn("password", public)
        self.assertFalse(os.path.exists(self.dir))

    def test_the_password_stays_private_in_a_0600_file(self):
        MqttConfig(self.dir).update({"enabled": True, "host": "192.0.2.10"}, password="s3cret")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, "mqtt.json")).st_mode), 0o600)
        again = MqttConfig(self.dir)
        self.assertEqual(again.password(), "s3cret")
        self.assertTrue(again.public()["has_password"])
        self.assertNotIn("s3cret", json.dumps(again.public()))
        again.update({"port": 1884})
        self.assertEqual(MqttConfig(self.dir).password(), "s3cret")
        again.update({}, password="")
        self.assertFalse(MqttConfig(self.dir).public()["has_password"])

    def test_invalid_values_are_refused_before_anything_is_saved(self):
        config = MqttConfig(self.dir)
        bad = [{"port": 0}, {"port": "x"}, {"host": "bad host"}, {"host": "[::1]"}, {"host": None},
               {"username": 5}, {"base_topic": "a/+"}, {"discovery_prefix": "/x"}, {"unknown": 1},
               {"enabled": True}, {"turbo": 1}, {"ha_fallback": "no"}]
        bad += [{key: value} for key, highest in DEVICE_TIERS.items() for value in (0, highest + 1, "2", True, 2.0)]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config.update(changes)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "mqtt.json")))
        self.assertEqual(config.update({"host": "fe80::1"})["host"], "fe80::1")

    def test_only_connection_settings_change_the_connection_key(self):
        self.assertTrue({"turbo", "light_bar_tier", "faceplate_tier", "ha_fallback"} <= LIVE_KEYS)
        config = MqttConfig(self.dir)
        config.update({"enabled": True, "host": "broker"}, password="a")
        key = config.connection_key()
        config.update({"turbo": True, "light_bar_tier": 4, "faceplate_tier": 1, "ha_fallback": False})
        self.assertEqual(config.connection_key(), key)
        self.assertIs(MqttConfig(self.dir).public()["turbo"], True)
        config.update({}, password="b")
        self.assertNotEqual(config.connection_key(), key)

    def test_levels_from_an_older_file_become_tiers(self):
        cases = (({"light_bar_level": "report", "faceplate_level": "settings"}, (1, 2)),
                 ({"light_bar_level": "drive", "faceplate_level": "report"}, (2, 1)),
                 ({"light_bar_level": "settings"}, (2, 2)),
                 ({"light_bar_tier": 4, "light_bar_level": "report"}, (4, 2)),
                 ({"light_bar_level": "steer", "faceplate_level": 3}, (2, 2)))
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(self.tiers(values), expected)
        MqttConfig(self.dir).update({"turbo": True})
        with open(os.path.join(self.dir, "mqtt.json"), encoding="utf-8") as handle:
            self.assertNotIn("light_bar_level", json.load(handle))

    def test_out_of_range_tiers_in_the_file_are_clamped_to_help_out(self):
        self.assertEqual(TIER_NAMES, {1: "Watch only", 2: "Help out", 3: "Take the lead", 4: "In control",
                                      5: "Full control"})
        self.assertEqual(self.tiers({"light_bar_tier": 3, "faceplate_tier": 5}), (3, 2))
        for odd in (0, 6, -1, "4", None, True, 2.5, [3]):
            with self.subTest(odd=odd):
                self.assertEqual(self.tiers({"light_bar_tier": odd, "faceplate_tier": odd}), (2, 2))


class RecordTests(StorageTestCase):
    def test_only_our_settings_and_drive_topics_count_as_ours(self):
        for topic in (CONFIG, STATE, "homeassistant/light/gabecubeaura_steammachine_drive_light/config"):
            self.assertTrue(is_ours(topic), topic)
        for topic in ("homeassistant/sensor/gabecubeaura_steammachine_cpu_load/config",
                      "homeassistant/switch/other_setting_x/config", "zigbee2mqtt/lamp", "#",
                      "gabecubeaura/steammachine/drive/light", CONFIG + "\n", None, 5):
            self.assertFalse(is_ours(topic), topic)

    def test_advertised_topics_ignore_foreign_topics_and_skip_unchanged_saves(self):
        path = os.path.join(self.dir, "advertised.json")
        advertised = AdvertisedTopics(self.dir)
        advertised.discard([CONFIG])
        self.assertFalse(os.path.exists(path))
        advertised.add([CONFIG, STATE, "zigbee2mqtt/lamp"])
        self.assertEqual(AdvertisedTopics(self.dir).topics(), {CONFIG, STATE})
        modified = os.stat(path).st_mtime_ns
        advertised.add([CONFIG])
        self.assertEqual(os.stat(path).st_mtime_ns, modified)
        advertised.discard([CONFIG])
        self.assertEqual(AdvertisedTopics(self.dir).topics(), {STATE})
        self.write("advertised.json", {"topics": [CONFIG, "homeassistant/sensor/other/config", 7]})
        self.assertEqual(AdvertisedTopics(self.dir).topics(), {CONFIG})

    def test_displaced_displays_survive_a_restart_and_only_plain_display_names_are_kept(self):
        routed = RoutedDisplays(self.dir)
        for key, value in (("mode", "audio_sync"), ("home_display", "home_assistant"), ("home_display", "../x")):
            self.assertFalse(routed.remember(key, value), (key, value))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "routed.json")))
        routed.remember("game_display", "artwork")
        self.assertTrue(routed.remember("game_display", "performance"))
        self.assertEqual(RoutedDisplays(self.dir).displays(), {"game_display": "performance"})
        RoutedDisplays(self.dir).forget("game_display")
        self.assertEqual(RoutedDisplays(self.dir).displays(), {})
        self.write("routed.json", {"displays": {"home_display": "performance", "updates_channel": "beta"}})
        self.assertEqual(RoutedDisplays(self.dir).displays(), {"home_display": "performance"})


if __name__ == "__main__":
    unittest.main()
