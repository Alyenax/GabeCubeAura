from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from signalbar.mqtt.config import MqttConfig


class MqttEntryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.decky = types.ModuleType("decky")
        self.decky.logger = Mock()
        sys.modules["decky"] = self.decky
        self.addCleanup(sys.modules.pop, "decky", None)
        spec = importlib.util.spec_from_file_location("signalbar_mqtt_main_test",
                                                      Path(__file__).resolve().parents[2] / "main.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.plugin = self.module.Plugin()
        self.mqtt_dir = os.path.join(tmp.name, "runtime", "mqtt")

    def with_mqtt(self):
        self.plugin.mqtt_config = MqttConfig(self.mqtt_dir)
        self.plugin.mqtt = Mock()
        self.plugin.mqtt.status.return_value = {"connected_with_current_settings": True}

    def test_config_round_trips_without_the_password_and_only_connection_changes_reconnect(self):
        self.with_mqtt()
        result = asyncio.run(self.plugin.set_mqtt_config({"host": "192.0.2.10", "enabled": True}, "pw"))
        self.assertTrue(result["config"]["has_password"])
        self.assertNotIn("pw", repr(result))
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 1)
        asyncio.run(self.plugin.set_mqtt_config({"turbo": True}, None))
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 1)
        asyncio.run(self.plugin.set_mqtt_config({"turbo": False}, "new"))  # a password always reconnects
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 2)
        with self.assertRaises(ValueError):
            asyncio.run(self.plugin.set_mqtt_config({"port": 0}))


if __name__ == "__main__":
    unittest.main()
