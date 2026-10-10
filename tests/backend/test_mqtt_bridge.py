from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest

from mqtt_fake_broker import FakeClient
from signalbar.mqtt.bridge import MqttBridge
from signalbar.mqtt.config import MqttConfig

ROOT = "gabecubeaura/steammachine"
AVAILABILITY = f"{ROOT}/availability"
STATUS = f"{ROOT}/state/status"
LIGHT_BAR = f"{ROOT}/state/light_bar"


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
        self.config = MqttConfig(os.path.join(self.tmp.name, "mqtt"))
        self.engine = FakeEngine()
        self.now = [100.0]
        self.bridge = self.make_bridge()

    def make_bridge(self, client_factory=FakeClient, run_thread=False):
        bridge = MqttBridge(self.config, self.engine, lambda: None, lambda: {"phase": "idle"},
                            hostname="steammachine", client_factory=client_factory,
                            clock=lambda: self.now[0], wall=lambda: 1_760_000_000.0 + self.now[0],
                            run_thread=run_thread)
        self.addCleanup(bridge.stop)
        return bridge

    def connect(self):
        self.config.update({"enabled": True, "host": "192.0.2.10", "username": "gca"}, password="pw")
        self.bridge.start()
        self.bridge.client.go_online()
        self.bridge.step()
        return self.bridge.client

    def online(self):
        client = self.connect()
        client.published.clear()
        return client

    def settle(self, seconds=1.1):
        self.now[0] += seconds
        self.bridge.step()

    @staticmethod
    def last(client, topic):
        return json.loads(client.payloads(topic)[-1])

    @staticmethod
    def topics(client):
        return [t for t, _, _ in client.published]


class PublishingTests(BridgeTestCase):
    def test_connect_publishes_retained_discovery_availability_and_state_without_private_values(self):
        client = self.connect()
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


if __name__ == "__main__":
    unittest.main()
