from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from mqtt_fake_broker import FakeClient
from signalbar.mqtt.advertised import AdvertisedTopics
from signalbar.mqtt.bridge import MqttBridge
from signalbar.mqtt.config import MqttConfig
from signalbar.mqtt.schema import build_schema
from signalbar.settings import SettingsStore
from signalbar.settings import store as store_module

ROOT = "gabecubeaura/steammachine"
AVAILABILITY = f"{ROOT}/availability"
STATUS = f"{ROOT}/state/status"
LIGHT_BAR = f"{ROOT}/state/light_bar"
SETTINGS = f"{ROOT}/state/settings"
NOTE = f"{ROOT}/attributes/display_preset_note"


class FakeEngine:
    def __init__(self):
        self.callbacks = []
        self.state = {"version": "1.4.0", "owner": "GabeCubeAura", "game": {"appid": 0, "title": ""},
                      "thermal_protection": {"active": False}, "debug": {"frontend_heartbeat_age_s": 1.0},
                      "weather": {"location": {"name": "Kingston", "latitude": 35.8, "longitude": -84.5}}}
        self.hub = type("Hub", (), {"dropped": 0, "known_kinds": set()})()

    def subscribe(self, callback):
        self.callbacks.append(callback)
        return lambda: None

    def status(self):
        return json.loads(json.dumps(self.state))

    def emit(self, kind, data):
        self.hub.known_kinds.add(kind)
        for callback in self.callbacks:
            callback(kind, data)


class BridgeTestCase(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mqtt_dir = os.path.join(self.tmp.name, "mqtt")
        self.config = MqttConfig(self.mqtt_dir)
        self.store = SettingsStore(os.path.join(self.tmp.name, "config.json"))
        self.engine = FakeEngine()
        self.now = [100.0]
        self.applied = []
        self.bridge = self.make_bridge()

    def make_bridge(self, client_factory=FakeClient, schema=None, run_thread=False):
        # A fresh AdvertisedTopics on the same directory, as after a restart.
        bridge = MqttBridge(self.config, self.engine, lambda: None, lambda: {"phase": "idle"},
                            hostname="steammachine", client_factory=client_factory,
                            clock=lambda: self.now[0], wall=lambda: 1_760_000_000.0 + self.now[0],
                            run_thread=run_thread, read_settings=self.store.all, apply_setting=self.apply,
                            schema=schema, advertised=AdvertisedTopics(self.mqtt_dir))
        self.addCleanup(bridge.stop)
        return bridge

    def apply(self, key, value):
        # Stands in for main.py's set_setting: the same store call the UI makes.
        self.applied.append((key, value))
        self.store.update({key: value})

    def connect(self, level="settings", bridge=None):
        bridge = bridge or self.bridge
        self.config.update({"enabled": True, "host": "192.0.2.10", "username": "gca", "light_bar_level": level},
                           password="pw")
        bridge.start()
        bridge.client.go_online()
        bridge.step()
        return bridge.client

    def online(self, level="report"):
        client = self.connect(level)
        client.published.clear()
        return client

    def settle(self, seconds=1.1, bridge=None):
        self.now[0] += seconds
        (bridge or self.bridge).step()

    @staticmethod
    def last(client, topic):
        return json.loads(client.payloads(topic)[-1])

    @staticmethod
    def topics(client):
        return [t for t, _, _ in client.published]


class PublishingTests(BridgeTestCase):
    def test_connect_publishes_retained_discovery_availability_and_state_without_private_values(self):
        client = self.connect("report")
        self.assertEqual(client.kwargs["will"], (AVAILABILITY, "offline", True))
        self.assertEqual(client.payloads(AVAILABILITY), ["online"])
        self.assertIn(f"{ROOT}/state/game", self.topics(client))
        self.assertTrue(all(r for t, _, r in client.published if t.endswith("/config")))
        self.assertTrue(self.bridge.status()["connected_with_current_settings"])
        blob = "".join(p for _, p, _ in client.published if isinstance(p, str))
        for forbidden in ("latitude", "longitude", "pw\"", "password"):
            self.assertNotIn(forbidden, blob)

    def test_only_changed_areas_go_out_at_most_once_a_second_and_status_once_a_minute(self):
        client = self.online()
        self.bridge.step()
        self.engine.state["owner"] = "Valve"
        self.settle(0.3)
        self.assertEqual(client.published, [])
        for tick in range(120):
            self.engine.state["owner"] = f"owner-{tick}"
            self.settle(1.0)
        self.assertNotIn(f"{ROOT}/state/game", self.topics(client))
        self.assertEqual(len(client.payloads(STATUS)), 2)
        self.assertGreater(len(client.payloads(LIGHT_BAR)), 110)

    def test_home_assistant_coming_back_online_republishes_discovery_and_state(self):
        client = self.online()
        client.receive("homeassistant/status", b"offline")
        self.settle()
        self.assertEqual(client.published, [])
        client.receive("homeassistant/status", b"online")
        self.bridge.step()
        self.assertTrue(any(t.startswith("homeassistant/sensor/") for t in self.topics(client)))
        self.assertIn(STATUS, self.topics(client))
        self.assertEqual(len(FakeClient.instances), 1)

    def test_turbo_applies_without_reconnecting_and_switching_back_republishes(self):
        self.engine.state["countdown"] = {"active": True, "source": "parental", "remaining_seconds": 737,
                                          "total_seconds": 3600}
        client = self.online()
        for turbo, minutes in ((True, 12.3), (False, 13)):
            self.config.update({"turbo": turbo})
            self.settle(1.0)
            self.assertEqual(self.last(client, f"{ROOT}/state/countdown")["remaining_minutes"], minutes)
        self.assertEqual(len(FakeClient.instances), 1)
        self.assertEqual(len(client.payloads(STATUS)), 2)

    def test_hub_events_are_published_redacted_and_never_retained(self):
        client = self.online()
        self.engine.emit("light_event", {"kind": "notification", 1: "a", "b": 2})  # unsortable keys
        self.engine.emit("light_event", {"kind": "achievement", "image_path": "/x", "token": "t",
                                         "nested": {"weather_latitude": 1, "ok": 2}, "event_type": "evil"})
        self.engine.emit("future_feature.did_thing", {"x": 1})
        self.engine.state["thermal_protection"] = {"active": True}
        self.settle()
        events = {t: (json.loads(p), r) for t, p, r in client.published if t.startswith(f"{ROOT}/event/")}
        self.assertEqual(events[f"{ROOT}/event/light_events"],
                         ({"event_type": "achievement", "kind": "achievement", "nested": {"ok": 2}}, False))
        self.assertEqual(events[f"{ROOT}/event/thermal"][0]["event_type"], "tripped")
        configs = [json.loads(p) for t, p, _ in client.published if t.startswith("homeassistant/event/")]
        self.assertTrue(any("did_thing" in c["event_types"] for c in configs))


class WorkerTests(BridgeTestCase):
    @staticmethod
    def workers(count):
        for _ in range(40):
            alive = [t for t in threading.enumerate() if t.name == "gabecubeaura-mqtt-bridge" and t.is_alive()]
            if len(alive) == count:
                break
            threading.Event().wait(0.1)
        return len(alive)

    def test_start_stop_start_leaves_one_worker_and_a_worker_blocked_in_publish_exits(self):
        release, entered = threading.Event(), threading.Event()

        class SlowClient(FakeClient):
            def publish(self, topic, payload, retain=False):
                entered.set()
                release.wait(5)
                return super().publish(topic, payload, retain)

        self.config.update({"enabled": True, "host": "192.0.2.10"}, password="pw")
        bridge = self.make_bridge(SlowClient, run_thread=True)
        bridge.join_timeout_s = 0.2
        for _ in range(2):
            bridge.start()
            bridge.start()
            self.assertEqual(self.workers(1), 1)
            bridge.stop()
            self.assertEqual(self.workers(0), 0)
        bridge.start()
        FakeClient.instances[-1].go_online()
        self.assertTrue(entered.wait(3))
        bridge.stop()  # the join times out with the worker stuck in publish
        release.set()
        self.assertEqual(self.workers(0), 0)


class SettingsEntityTests(BridgeTestCase):
    def setUp(self):
        super().setUp()
        self.controls = self.bridge.schema.controls
        self.everything = {self.config_topic(c) for c in self.controls.values()} | {SETTINGS, NOTE}

    @staticmethod
    def config_topic(control):
        return f"homeassistant/{control.component}/gabecubeaura_steammachine_setting_{control.key}/config"

    def on_disk(self):
        return AdvertisedTopics(self.mqtt_dir).topics()

    @staticmethod
    def empties(client):
        return sorted(t for t, p, _ in client.published if p == "")

    def test_the_settings_level_describes_every_control_once_then_the_state(self):
        client = self.connect()
        for _ in range(3):
            self.settle()
        topics = self.topics(client)
        for topic in self.everything - {SETTINGS}:
            self.assertEqual(topics.count(topic), 1, topic)
            self.assertLess(topics.index(topic), topics.index(SETTINGS))
        state = self.last(client, SETTINGS)
        self.assertEqual(set(state), set(self.controls) | store_module.LOCAL_ONLY_SETTINGS)
        self.assertEqual(self.on_disk(), self.everything)

    def test_dropping_to_report_only_clears_exactly_what_was_advertised_configs_first(self):
        client = self.connect()
        client.published.clear()
        self.config.update({"light_bar_level": "report"})
        self.bridge.step()
        cleared = [t for t, p, _ in client.published if p == ""]
        self.assertEqual((sorted(cleared), len(client.published)), (sorted(self.everything), len(self.everything)))
        self.assertEqual(sorted(cleared[-2:]), sorted([SETTINGS, NOTE]))
        self.assertEqual(self.on_disk(), frozenset())
        client.published.clear()
        client.receive("homeassistant/status", b"online")
        self.bridge.step()
        self.assertEqual(self.empties(client), [])

    def test_a_start_at_report_only_clears_what_an_interrupted_earlier_run_left(self):
        sent = []

        class DropsAfterTen(FakeClient):
            def publish(self, topic, payload, retain=False):
                if payload == "":
                    sent.append(topic)
                    self.connected = len(sent) <= 10
                return super().publish(topic, payload, retain)

        first = self.make_bridge(DropsAfterTen)
        self.connect("settings", first)
        self.config.update({"light_bar_level": "report"})
        first.step()
        first.stop()
        remaining = self.on_disk()
        self.assertEqual(len(self.everything) - len(remaining), 10)
        client = self.connect("report", self.make_bridge())
        self.assertEqual(self.empties(client), sorted(remaining))
        self.assertEqual(self.on_disk(), frozenset())


class SettingsCommandTests(BridgeTestCase):
    def send(self, client, key, payload, retain=False):
        client.receive(f"{ROOT}/set/{key}", payload, retain)

    def error(self):
        return self.bridge.status()["command_error"]

    def test_commands_apply_the_newest_value_once_a_second_per_setting(self):
        client = self.connect()
        for value in (10, 20, 30, 40):
            self.send(client, "light_bar_day_brightness", str(value).encode())
            self.settle(0.15)
        self.send(client, "night_mode_brightness", b"20")
        self.assertEqual(self.applied, [])
        self.settle(0.5)
        self.assertEqual(self.applied, [("light_bar_day_brightness", 40)])
        self.settle()
        self.settle()
        self.assertEqual(self.applied, [("light_bar_day_brightness", 40), ("night_mode_brightness", 20)])
        self.assertEqual(self.last(client, SETTINGS)["light_bar_day_brightness"], 40)

    def test_resending_current_values_never_touches_the_store_or_the_preset(self):
        # Scenes resend what is already set, and the store counts each write as an edit.
        preset = self.store.all()["display_preset"]
        client = self.connect()
        for control in self.bridge.schema.controls.values():
            value = self.store.all()[control.key]
            self.send(client, control.key, (b"ON" if value else b"OFF") if control.component == "switch"
                      else str(value).encode())
        self.settle()
        self.assertEqual((self.applied, self.error(), self.store.all()["display_preset"]), ([], "", preset))
        self.send(client, "home_display", b"blackout")
        self.settle()
        self.assertEqual(self.store.all()["display_preset"], "custom")

    def test_refusals_say_why_and_change_nothing(self):
        cases = (
            ("report", "home_display", b"blackout", "home_display: Light bar is set to Report only"),
            ("settings", "weather_location", b"{}", "weather_location: not a setting Home Assistant can change"),
            ("settings", "updates_channel", b"beta", "updates_channel: can only be changed on the Steam Machine"),
            ("settings", "Home/../x", b"1", "(unreadable): not a setting Home Assistant can change"),
            ("settings", "home_display", b"<b>nope</b>", "home_display: not one of the allowed options"),
            ("settings", "light_bar_day_brightness", b"999", "light_bar_day_brightness: must be 1-255"),
            ("settings", "signalbar_enabled", b"true", "signalbar_enabled: expected ON or OFF"),
        )
        client = self.connect()
        for level, key, payload, expected in cases:
            with self.subTest(key=key, payload=payload):
                self.config.update({"light_bar_level": level})
                self.send(client, key, payload)
                self.settle()
                self.assertEqual(self.last(client, f"{ROOT}/state/bridge")["last_error"], expected)
        self.assertEqual(self.applied, [])

    def test_local_only_settings_are_reported_but_never_advertised_or_applied(self):
        # Plus two keys that would otherwise be controls, one of them preset-controlled.
        local = store_module.LOCAL_ONLY_SETTINGS | {"home_display", "light_bar_day_brightness"}
        bridge = self.make_bridge(schema=build_schema(local_only=local))
        client = self.connect("settings", bridge)
        state = self.last(client, SETTINGS)
        for key in ("home_display", "light_bar_day_brightness", "updates_auto_check", "valve_ownership_policy"):
            self.assertFalse(any(f"_setting_{key}/" in t for t in self.topics(client)), key)
            self.assertEqual(state[key], self.store.all()[key], key)
            for level in ("settings", "report"):
                self.config.update({"light_bar_level": level})
                self.send(client, key, b"OFF")
                self.assertEqual(bridge.status()["command_error"], f"{key}: can only be changed on the Steam Machine")
        self.assertEqual(self.applied, [])

    def test_store_refusals_and_failures_are_reported_without_details(self):
        client = self.connect()  # no weather city: the store refuses night mode
        self.send(client, "night_mode_enabled", b"ON")
        self.settle()
        self.assertTrue(self.error().startswith("night_mode_enabled: Choose a city"))
        self.assertIs(self.last(client, SETTINGS)["night_mode_enabled"], False)
        self.bridge._apply_setting = mock.Mock(side_effect=OSError("/home/deck/private/file"))
        self.send(client, "light_bar_day_brightness", b"41")
        self.settle()
        self.assertEqual(self.error(), "light_bar_day_brightness: not applied (OSError)")
        self.bridge._read_settings = mock.Mock(side_effect=OSError("/home/deck/private/file"))
        self.send(client, "light_bar_day_brightness", b"42")
        self.settle()
        self.assertEqual(self.error(), "light_bar_day_brightness: settings control is not available")

    def test_nothing_applies_once_the_bridge_is_stopping(self):
        client = self.connect()

        def apply_then_stop(key, value):
            self.apply(key, value)
            self.bridge._stop_event.set()
        self.bridge._apply_setting = apply_then_stop
        self.send(client, "light_bar_day_brightness", b"40")
        self.send(client, "weather_brightness", b"30")
        self.settle()
        self.assertEqual(len(self.applied), 1)

    def test_a_worker_that_outlived_a_restart_obeys_its_own_stop(self):
        # When stop()'s join times out, start() gives the new worker a fresh event.
        client = self.connect()
        own = threading.Event()

        def apply_then_restart(key, value):
            self.apply(key, value)
            own.set()
            self.bridge._stop_event = threading.Event()
        self.bridge._apply_setting = apply_then_restart
        self.send(client, "light_bar_day_brightness", b"40")
        self.send(client, "weather_brightness", b"30")
        self.now[0] += 1.1
        self.bridge.step(own)
        self.assertEqual(self.applied, [("light_bar_day_brightness", 40)])


if __name__ == "__main__":
    unittest.main()
