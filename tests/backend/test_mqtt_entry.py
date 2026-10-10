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
from unittest import mock
from unittest.mock import Mock

from signalbar.mqtt.config import MqttConfig
from signalbar.mqtt.routed import RoutedDisplays
from signalbar.settings import SettingsStore

WEATHER_REFUSAL = ("game_display: could not put back weather: "
                   "Choose a city before enabling Weather or automatic night mode")


class MqttEntryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.decky = types.ModuleType("decky")
        self.decky.logger = Mock()
        self.decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(tmp.name, "settings")
        self.decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(tmp.name, "runtime")
        self.decky.DECKY_PLUGIN_DIR = tmp.name
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
        for changes in ({"turbo": True}, {"light_bar_level": "drive"}, {"faceplate_level": "settings"}):
            asyncio.run(self.plugin.set_mqtt_config(changes, None))
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 1)
        asyncio.run(self.plugin.set_mqtt_config({"turbo": False}, "new"))  # a password always reconnects
        self.assertEqual(self.plugin.mqtt.reconfigure.call_count, 2)
        with self.assertRaises(ValueError):
            asyncio.run(self.plugin.set_mqtt_config({"port": 0}))
        self.assertIs(asyncio.run(self.plugin.get_mqtt_status())["ha_alerts_enabled"], False)  # no engine yet

    def test_main_puts_displays_back_before_the_bridge_starts(self):
        store = SettingsStore(os.path.join(self.dir, "store.json"))
        store.update({"home_display": "home_assistant", "game_display": "home_assistant"})
        earlier = RoutedDisplays(self.mqtt_dir)
        earlier.remember("home_display", "audio_sync")
        earlier.remember("game_display", "weather")
        seen = {}

        def make_bridge(*args, **kwargs):
            seen["displays"] = (store.all()["home_display"], store.all()["game_display"])
            seen["kwargs"] = kwargs
            return Mock()

        with mock.patch.object(self.module, "Engine") as engine, mock.patch.object(self.module, "UpdateManager"), \
                mock.patch.object(self.module, "MqttBridge", side_effect=make_bridge):
            engine.return_value.settings = store
            engine.return_value.update_settings.side_effect = store.update
            asyncio.run(self.plugin._main())
        self.assertEqual(seen["displays"], ("audio_sync", "home_assistant"))
        self.assertEqual(seen["kwargs"]["read_settings"], store.all)
        self.assertEqual(seen["kwargs"]["apply_setting"], self.plugin._apply_setting_from_home_assistant)
        self.assertEqual(seen["kwargs"]["routed"].path, os.path.join(self.mqtt_dir, "routed.json"))
        self.plugin.mqtt.note_refusal.assert_called_once_with("game_display", WEATHER_REFUSAL)
        self.plugin.mqtt.start.assert_called_once_with()
        self.decky.logger.warning.assert_called_once_with(f"[GabeCubeAura] {WEATHER_REFUSAL}")
        self.assertEqual(RoutedDisplays(self.mqtt_dir).displays(), {})

    def test_a_put_back_that_cannot_finish_stays_recorded(self):
        store = SettingsStore(os.path.join(self.dir, "store.json"))
        store.update({"home_display": "home_assistant", "game_display": "home_assistant"})
        self.plugin.engine = Mock(settings=store)
        self.plugin.engine.update_settings.side_effect = [OSError("/home/deck/config.json"), None]
        routed = RoutedDisplays(self.mqtt_dir)
        routed.remember("home_display", "audio_sync")
        routed.remember("game_display", "weather")
        refused = asyncio.run(self.plugin._restore_home_assistant_displays(RoutedDisplays(self.mqtt_dir)))
        self.assertEqual(refused, [("game_display", "game_display: could not put back weather: OSError")])
        self.assertEqual(RoutedDisplays(self.mqtt_dir).displays(), {"game_display": "weather"})

    def test_changes_after_stop_or_without_a_running_loop_never_reach_the_store(self):
        self.plugin.engine = Mock()
        self.plugin._loop = asyncio.new_event_loop()
        self.addCleanup(self.plugin._loop.close)
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
