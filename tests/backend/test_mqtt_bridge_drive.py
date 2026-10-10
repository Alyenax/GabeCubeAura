from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock

from mqtt_fake_broker import FakeClient
from signalbar.mqtt.advertised import AdvertisedTopics
from signalbar.mqtt.bridge import MqttBridge
from signalbar.mqtt.config import MqttConfig
from signalbar.mqtt.routed import RoutedDisplays
from signalbar.providers.home_assistant import HomeAssistantProvider
from signalbar.settings import SettingsStore

ROOT = "gabecubeaura/steammachine"
LIGHT = "homeassistant/light/gabecubeaura_steammachine_drive_light/config"
DRIVE_STATE = f"{ROOT}/state/drive"
RED_ON = b'{"state":"ON","brightness":128,"color":{"r":255,"g":0,"b":0}}'
OFF = b'{"state":"OFF"}'
FLASH = b'{"variant":"flash"}'
RED = ((128, 0, 0),) * 17


class DriveEngine:
    """What the bridge uses of the engine to drive the bar, with a real Home Assistant display slot."""

    def __init__(self, store):
        self.store = store
        self.home_assistant = HomeAssistantProvider()
        self.refusal, self.override, self.route_key = "", "inherit", "home_display"
        self.alerts, self.alert_result = [], (True, "")
        self.hub = type("Hub", (), {"dropped": 0})()

    def subscribe(self, callback):
        return lambda: None

    def status(self):
        return {"version": "1.4.0", "game": {"appid": 0, "title": ""}, "debug": {"frontend_heartbeat_age_s": 1.0}}

    def home_assistant_refusal(self):
        return self.refusal

    def home_assistant_route(self):
        selected = self.store.all()[self.route_key] if self.override == "inherit" else self.override
        return {"key": self.route_key, "selected": selected, "override": self.override}

    def trigger_home_assistant_alert(self, variant, colour, duration=None):
        self.alerts.append((variant, colour, duration))
        return self.alert_result


class DriveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mqtt_dir = os.path.join(self.tmp.name, "mqtt")
        self.config = MqttConfig(self.mqtt_dir)
        self.store = SettingsStore(os.path.join(self.tmp.name, "config.json"))
        self.engine = DriveEngine(self.store)
        self.provider = self.engine.home_assistant
        self.now = [100.0]
        self.applied = []
        self.update = {"phase": "idle"}
        self.log = Mock()
        self.bridge = self.make_bridge()

    def make_bridge(self):
        bridge = MqttBridge(self.config, self.engine, lambda: None, lambda: self.update, logger=self.log,
                            hostname="steammachine", client_factory=FakeClient,
                            clock=lambda: self.now[0], wall=lambda: 1_760_000_000.0 + self.now[0],
                            run_thread=False, read_settings=self.store.all, apply_setting=self.apply,
                            advertised=AdvertisedTopics(self.mqtt_dir), routed=RoutedDisplays(self.mqtt_dir))
        self.addCleanup(bridge.stop)
        return bridge

    def apply(self, key, value):
        self.applied.append((key, value))
        self.store.update({key: value})

    def connect(self, level="drive"):
        self.config.update({"enabled": True, "host": "192.0.2.10", "light_bar_level": level}, password="pw")
        self.bridge.start()
        self.bridge.client.go_online()
        self.bridge.step()
        return self.bridge.client

    def level(self, level):
        self.config.update({"light_bar_level": level})

    def send(self, name, payload, retain=False):
        self.bridge.client.receive(f"{ROOT}/drive/{name}", payload, retain)

    def settle(self, seconds=0.25):
        self.now[0] += seconds
        self.bridge.step()

    def light_on(self):
        self.send("light", RED_ON)
        self.settle()

    def error(self):
        return self.bridge.status()["command_error"]

    def recorded(self):
        return RoutedDisplays(self.mqtt_dir).displays()  # as a restart would find it

    def frame(self):
        return self.provider.output().frame


class DriveEntityTests(DriveTestCase):
    def test_report_only_clears_the_drive_entities_and_empties_the_slot(self):
        self.assertFalse(any("drive" in t for t, _, _ in self.connect("report").published))
        self.level("drive")
        self.settle()
        client = self.bridge.client
        self.provider.set_light(True, (255, 0, 0))
        client.published.clear()
        self.level("report")
        self.settle()
        empties = [t for t, p, _ in client.published if p == ""]
        self.assertLess(empties.index(LIGHT), empties.index(DRIVE_STATE))
        self.assertIsNone(self.frame())
        self.assertFalse({LIGHT, DRIVE_STATE} & AdvertisedTopics(self.mqtt_dir).topics())

    def test_stopping_empties_the_slot_and_an_outliving_worker_never_offers_it_again(self):
        self.connect()
        self.provider.set_light(True, (255, 0, 0))
        old = self.bridge._stop_event
        self.bridge.stop()
        self.bridge._step_drive(old)
        self.assertIsNone(self.frame())
        self.assertFalse(self.provider.status()["offered"])


class DriveLightTests(DriveTestCase):
    def test_the_light_routes_the_display_once_and_off_puts_it_back(self):
        self.connect()
        self.light_on()
        self.assertEqual(self.applied, [("home_display", "home_assistant")])
        self.assertEqual((self.frame(), self.store.all()["display_preset"]), (RED, "custom"))
        self.assertEqual(self.recorded(), {"home_display": "audio_sync"})
        self.send("light", b'{"state":"ON","color":{"r":0,"g":0,"b":255}}')
        self.settle()
        self.assertEqual(len(self.applied), 1)  # already routed: no second write
        for _ in range(2):
            self.send("light", OFF)
            self.settle()
        self.assertEqual(self.applied, [("home_display", "home_assistant"), ("home_display", "audio_sync")])
        self.assertEqual((self.frame(), self.recorded(), self.error()), (None, {}, ""))

    def test_nothing_is_written_when_the_display_is_already_routed_or_was_changed_since(self):
        self.store.update({"home_display": "home_assistant"})
        self.connect()
        self.light_on()
        self.send("light", OFF)
        self.settle()
        self.assertEqual((self.applied, self.recorded()), ([], {}))
        self.store.update({"home_display": "audio_sync"})
        self.light_on()
        self.store.update({"home_display": "performance"})  # chosen on the Steam Machine
        self.send("light", OFF)
        self.settle()
        self.assertEqual(self.applied, [("home_display", "home_assistant")])
        self.assertEqual(self.store.all()["home_display"], "performance")

    def test_refusals_change_nothing_and_say_why_but_off_always_works(self):
        self.connect()
        for refusal in ("thermal protection is active", "Light bar control is off on the Steam Machine",
                        "a display preset preview is running"):
            self.engine.refusal = refusal
            self.light_on()
            self.assertEqual(self.error(), f"drive/light: {refusal}")
        self.engine.refusal = ""
        for phase in ("installing", "restart_pending"):
            self.update = {"phase": phase}
            self.send("frame", json.dumps([[1, 2, 3]] * 17).encode())
            self.settle()
            self.assertEqual(self.error(), "drive/frame: a GabeCubeAura update is being installed")
        self.assertEqual((self.applied, self.frame()), ([], None))
        self.update = {"phase": "idle"}
        self.light_on()
        self.engine.refusal = "thermal protection is active"
        self.send("light", OFF)
        self.settle()
        self.assertEqual((self.frame(), self.store.all()["home_display"]), (None, "audio_sync"))

    def test_retained_empty_unknown_and_malformed_commands(self):
        self.connect()
        self.send("light", RED_ON, retain=True)
        self.send("light", b"")
        self.settle()
        self.assertEqual((self.applied, self.error()), ([], ""))
        self.log.info.assert_any_call("[GabeCubeAura] ignored a retained Home Assistant drive/light command")
        self.send("light", b'{"state":"ON","secret-x":1}')
        self.assertEqual(self.error(), "drive/light: unsupported field")
        self.send("strobe", b"1")
        self.assertEqual(self.error(), "drive/(unknown): not a light bar command")
        self.assertEqual(self.applied, [])

    def test_nothing_applies_once_stopping_or_after_the_level_drops(self):
        self.connect()
        self.send("light", RED_ON)
        self.level("settings")
        self.settle()
        self.level("drive")
        self.send("light", RED_ON)
        self.bridge._stop_event.set()
        self.settle()
        self.assertEqual((self.applied, self.frame()), ([], None))


class DriveAlertTests(DriveTestCase):
    def test_an_alert_goes_to_the_engine_without_touching_the_display(self):
        self.connect()
        self.send("light", RED_ON)
        self.settle(0.0)
        self.send("alert", b'{"variant":"pulse","color":{"r":0,"g":200,"b":0},"duration":2}')
        self.send("alert", FLASH)
        self.settle(0.05)  # not held back by the light's rate limit
        self.assertEqual(self.engine.alerts, [("ha-pulse", (0, 200, 0), 2.0), ("ha-flash", (255, 255, 255), None)])
        self.assertEqual(self.applied, [("home_display", "home_assistant")])

    def test_dropped_alerts_say_why_and_are_published_as_dropped(self):
        client = self.connect()
        self.engine.alert_result = (False, "Home Assistant alerts are off on the Steam Machine")
        self.send("alert", FLASH)
        self.settle()
        self.assertEqual(self.error(), "drive/alert: dropped, Home Assistant alerts are off on the Steam Machine")
        self.update = {"phase": "installing"}
        self.send("alert", FLASH)
        self.settle()
        self.settle()
        self.assertEqual(len(self.engine.alerts), 1)
        event = json.loads(client.payloads(f"{ROOT}/event/light_events")[-1])
        self.assertEqual((event["event_type"], event["result"], event["shown"]), ("ha", "dropped", False))
        for _ in range(4):
            self.send("alert", FLASH)
        self.assertEqual(self.error(), "drive/alert: dropped, three alerts are already waiting")

    def test_waiting_alerts_never_play_after_the_level_drops_or_the_bridge_stops(self):
        self.connect()
        self.send("alert", FLASH)
        self.level("settings")
        self.settle()
        self.level("drive")
        self.send("alert", FLASH)
        self.send("alert", b'{"variant":"pulse"}')
        play, stopping = self.engine.trigger_home_assistant_alert, threading.Event()

        def play_then_stop(variant, colour, duration=None):
            stopping.set()
            return play(variant, colour, duration)

        self.engine.trigger_home_assistant_alert = play_then_stop
        self.bridge._step_drive(stopping)
        self.assertEqual([alert[0] for alert in self.engine.alerts], ["ha-flash"])


class PutBackTests(DriveTestCase):
    def test_stopping_or_turning_mqtt_off_puts_the_display_back(self):
        for stop in (self.bridge.stop, lambda: (self.config.update({"enabled": False}), self.bridge.reconfigure())):
            self.connect()
            self.light_on()
            stop()
            self.assertIsNone(self.bridge.client)
            self.assertEqual((self.store.all()["home_display"], self.recorded()), ("audio_sync", {}))

    def test_an_unload_keeps_the_record_and_the_next_run_puts_it_back(self):
        self.connect()
        self.light_on()
        self.bridge._apply_setting = Mock(side_effect=RuntimeError("Decky's loop is gone"))
        self.bridge.stop()
        self.assertEqual(self.recorded(), {"home_display": "audio_sync"})
        self.assertEqual(self.store.all()["home_display"], "home_assistant")  # main.py puts it back
        self.bridge = self.make_bridge()
        self.connect()
        self.send("light", OFF)
        self.settle()
        self.assertEqual((self.applied[-1], self.recorded()), (("home_display", "audio_sync"), {}))

    def test_leaving_drive_puts_the_display_back_and_empties_the_slot(self):
        for level in ("report", "settings"):
            self.connect()
            self.light_on()
            self.level(level)
            self.settle()
            self.settle()
            self.assertEqual(self.applied[-2:], [("home_display", "home_assistant"), ("home_display", "audio_sync")])
            self.assertEqual((self.frame(), self.provider.status()["on"]), (None, False))
            self.bridge.stop()


if __name__ == "__main__":
    unittest.main()
