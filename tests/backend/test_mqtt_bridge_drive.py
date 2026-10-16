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
        self.alerts, self.alert_result, self.tiers = [], (True, ""), []
        self.hub = type("Hub", (), {"dropped": 0})()

    def set_home_assistant_tier(self, tier):
        self.tiers.append(tier)

    def subscribe(self, callback):
        return lambda: None

    def status(self):
        return {"version": "1.4.0", "game": {"appid": 0, "title": ""}, "debug": {"frontend_heartbeat_age_s": 1.0},
                "performance": {"cpu_load": 20}}

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

    def connect(self, tier=2):
        self.config.update({"enabled": True, "host": "192.0.2.10", "light_bar_tier": tier}, password="pw")
        self.bridge.start()
        self.bridge.client.go_online()
        self.bridge.step()
        return self.bridge.client

    def tier(self, tier):
        self.config.update({"light_bar_tier": tier})

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
    def test_watch_only_clears_the_drive_entities_and_empties_the_slot(self):
        self.assertFalse(any("drive" in t for t, _, _ in self.connect(1).published))
        self.tier(2)
        self.settle()
        client = self.bridge.client
        self.provider.set_light(True, (255, 0, 0))
        client.published.clear()
        self.tier(1)
        self.settle()
        empties = [t for t, p, _ in client.published if p == ""]
        self.assertLess(empties.index(LIGHT), empties.index(DRIVE_STATE))
        self.assertIsNone(self.frame())
        self.assertFalse({LIGHT, DRIVE_STATE} & AdvertisedTopics(self.mqtt_dir).topics())

    def test_stopping_empties_the_slot_and_an_outliving_worker_never_offers_it_again(self):
        self.connect(2)
        self.provider.set_light(True, (255, 0, 0))
        old = self.bridge._stop_event
        self.bridge.stop()
        self.bridge._step_drive(old)
        self.assertIsNone(self.frame())
        self.assertFalse(self.provider.status()["offered"])
        self.assertEqual((self.engine.tiers[-1], self.bridge.status()["tier"]), (1, 1))


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

    def test_the_light_shows_at_once_through_the_startup_hold(self):
        self.connect()
        self.bridge.stop()
        path = os.path.join(self.mqtt_dir, "published.json")  # written by the first run, with this boot
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({**record, "owner": "GabeCubeAura"}, handle)  # an owner from before the restart
        self.bridge = self.make_bridge()
        client = self.connect()
        self.settle(1.1)
        self.assertNotIn(f"{ROOT}/state/light_bar", [t for t, _, _ in client.published])
        self.light_on()
        self.settle(1.1)
        self.assertIn(f"{ROOT}/state/light_bar", [t for t, _, _ in client.published])

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
        for tier in (2, 3, 4, 5):
            for phase in ("installing", "restart_pending"):
                self.tier(tier)
                self.update = {"phase": phase}
                self.send("frame", json.dumps([[1, 2, 3]] * 17).encode())
                self.settle()
                self.assertEqual(self.error(), "drive/frame: a GabeCubeAura update is being installed")
        self.assertEqual((self.applied, self.frame()), ([], None))
        self.tier(2)
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

    def test_nothing_applies_once_stopping_or_after_the_tier_drops(self):
        self.connect()
        self.send("light", RED_ON)
        self.tier(1)
        self.settle()
        self.tier(2)
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

    def test_waiting_alerts_never_play_after_the_tier_drops_or_the_bridge_stops(self):
        self.connect()
        self.send("alert", FLASH)
        self.tier(1)
        self.settle()
        self.tier(2)
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

    def test_leaving_help_out_puts_the_display_back_and_keeps_the_light(self):
        for tier in (1, 4):
            self.connect(2)
            self.light_on()
            self.tier(tier)
            self.settle()
            self.settle()
            self.assertEqual(self.applied[-2:], [("home_display", "home_assistant"), ("home_display", "audio_sync")])
            self.assertEqual(self.provider.status()["on"], tier == 4)
            self.bridge.stop()


class TierTests(DriveTestCase):
    def outage(self, how):
        if how == "broker":
            self.bridge.client.connected = False
        else:
            self.bridge.client.receive("homeassistant/status", b"offline")
        self.settle()

    def back(self, how):
        if how == "broker":
            self.bridge.client.go_online()
        else:
            self.bridge.client.receive("homeassistant/status", b"online")
        self.settle()

    def test_an_outage_of_thirty_seconds_falls_back_to_help_out_and_resumes(self):
        for how in ("broker", "home assistant"):
            self.connect(5)
            self.engine.tiers.clear()
            self.light_on()
            self.outage(how)
            self.settle(29.0)
            self.assertEqual(set(self.engine.tiers), {5}, how)
            self.settle(1.0)
            self.assertEqual((self.engine.tiers[-1], self.bridge.status()["falling_back"]), (2, True), how)
            self.light_on()  # another automation still talking to the broker
            self.assertIsNotNone(self.frame())  # the slot is kept
            self.back(how)
            self.assertEqual((self.engine.tiers[-1], self.bridge.status()["falling_back"]), (5, False), how)
            self.assertEqual(self.applied, [])  # falling back writes no settings
            self.bridge.stop()

    def test_with_the_switch_off_or_below_take_the_lead_nothing_falls_back(self):
        self.config.update({"ha_fallback": False})
        for tier in (4, 2, 1):
            self.connect(tier)
            self.outage("broker")
            self.settle(60.0)
            self.assertEqual((self.engine.tiers[-1], self.bridge.status()["falling_back"]), (tier, False))
            self.bridge.stop()

    def test_help_out_turns_the_light_off_once_thirty_seconds_into_an_outage(self):
        self.connect(2)
        self.light_on()
        self.outage("home assistant")
        self.settle(29.0)
        self.assertEqual((self.frame(), len(self.applied)), (RED, 1))
        self.settle(1.0)
        self.assertEqual((self.frame(), self.applied[-1]), (None, ("home_display", "audio_sync")))
        self.settle(60.0)
        self.assertEqual(len(self.applied), 2)
        self.back("home assistant")
        self.light_on()
        self.assertEqual((self.frame(), self.applied[-1]), (RED, ("home_display", "home_assistant")))

    def test_a_worker_stopped_during_a_put_back_leaves_watch_only(self):
        self.connect(2)
        self.light_on()
        stop_event = threading.Event()

        def apply_then_stop(key, value):
            # stop() runs on another thread while this worker waits on the put-back.
            self.apply(key, value)
            stop_event.set()
            self.bridge._detach_drive()

        self.bridge._apply_setting = apply_then_stop
        self.tier(5)
        self.now[0] += 0.25
        self.bridge.step(stop_event)
        self.assertEqual(self.applied[-1], ("home_display", "audio_sync"))
        self.assertEqual((self.engine.tiers[-1], self.bridge.status()["tier"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
