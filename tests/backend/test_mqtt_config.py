from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest

from signalbar.mqtt.config import LIVE_KEYS, MqttConfig


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "mqtt")


class ConfigTests(StorageTestCase):
    def test_defaults_are_off_and_nothing_is_written(self):
        public = MqttConfig(self.dir).public()
        self.assertEqual((public["enabled"], public["port"], public["turbo"], public["light_bar_level"],
                          public["faceplate_level"]), (False, 1883, False, "report", "report"))
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
               {"enabled": True}, {"turbo": 1}, {"light_bar_level": "drive"}, {"faceplate_level": "settings"}]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config.update(changes)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "mqtt.json")))
        self.assertEqual(config.update({"host": "fe80::1"})["host"], "fe80::1")

    def test_only_connection_settings_change_the_connection_key(self):
        self.assertEqual(LIVE_KEYS, {"turbo"})
        config = MqttConfig(self.dir)
        config.update({"enabled": True, "host": "broker"}, password="a")
        key = config.connection_key()
        config.update({"turbo": True})
        self.assertEqual(config.connection_key(), key)
        self.assertIs(MqttConfig(self.dir).public()["turbo"], True)
        config.update({}, password="b")
        self.assertNotEqual(config.connection_key(), key)


if __name__ == "__main__":
    unittest.main()
