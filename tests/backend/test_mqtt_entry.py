from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import threading
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

    def with_loop(self):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        def close():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(2)
            loop.close()
        self.addCleanup(close)
        self.plugin._loop = loop
        self.plugin.engine = Mock()
        return loop, thread

    def test_config_round_trips_without_the_password_and_only_connection_changes_reconnect(self):
        self.with_mqtt()
        result = asyncio.run(self.plugin.set_mqtt_config({"host": "192.0.2.10", "enabled": True}, "pw"))
        self.assertTrue(result["config"]["has_password"])
        self.assertNotIn("pw", repr(result))
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 1)
        for changes in ({"turbo": True}, {"light_bar_level": "settings"}, {"faceplate_level": "settings"}):
            asyncio.run(self.plugin.set_mqtt_config(changes, None))
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 1)
        asyncio.run(self.plugin.set_mqtt_config({"turbo": False}, "new"))  # a password always reconnects
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 2)
        with self.assertRaises(ValueError):
            asyncio.run(self.plugin.set_mqtt_config({"port": 0}))

    def test_changes_after_stop_or_once_the_loop_is_closed_never_reach_the_store(self):
        self.plugin.engine = Mock()
        self.plugin._loop = asyncio.new_event_loop()
        self.plugin._loop.close()
        with self.assertRaises(RuntimeError):
            self.plugin._apply_setting_from_home_assistant("light_bar_day_brightness", 40)
        self.with_loop()
        self.plugin.mqtt = Mock()
        self.plugin._stop_mqtt()
        with self.assertRaises(RuntimeError):
            self.plugin._apply_setting_from_home_assistant("light_bar_day_brightness", 40)
        self.plugin.engine.update_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
