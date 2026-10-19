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
from signalbar.mqtt.session import SessionRecord
from signalbar.mqtt.sleep import SleepWatch
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
                      "thermal_protection": {"active": False},
                      # As a new engine: the frontend has not synced a game yet.
                      "debug": {"frontend_heartbeat_age_s": 1.0, "game_sync_ms": None},
                      "performance": {"cpu_load": 20, "cpu_temperature": 50.0},
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
        self.engine.state["debug"]["game_sync_ms"] = 12.0  # a running engine the frontend has synced
        self.now = [100.0]
        self.asleep = 0.0  # wall time spent suspended, which the monotonic clock skips
        self.applied = []
        self.bridge = self.make_bridge()

    def make_bridge(self, client_factory=FakeClient, schema=None, run_thread=False):
        # A fresh AdvertisedTopics on the same directory, as after a restart.
        bridge = MqttBridge(self.config, self.engine, lambda: None, lambda: {"phase": "idle"},
                            hostname="steammachine", client_factory=client_factory,
                            clock=lambda: self.now[0], wall=lambda: 1_760_000_000.0 + self.now[0] + self.asleep,
                            run_thread=run_thread, read_settings=self.store.all, apply_setting=self.apply,
                            schema=schema, advertised=AdvertisedTopics(self.mqtt_dir))
        self.addCleanup(bridge.stop)
        return bridge

    def apply(self, key, value):
        # Stands in for main.py's set_setting: the same store call the UI makes.
        self.applied.append((key, value))
        self.store.update({key: value})

    def connect(self, tier=2, bridge=None):
        bridge = bridge or self.bridge
        self.config.update({"enabled": True, "host": "192.0.2.10", "username": "gca", "light_bar_tier": tier},
                           password="pw")
        bridge.start()
        bridge.client.go_online()
        bridge.step()
        return bridge.client

    def online(self, tier=1):
        client = self.connect(tier)
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
        client = self.connect(1)
        self.assertEqual(client.kwargs["will"], (AVAILABILITY, "offline", True))
        self.assertEqual(client.payloads(AVAILABILITY), ["online"])
        self.assertIn(f"{ROOT}/state/game", self.topics(client))
        self.assertTrue(all(r for t, _, r in client.published if t.endswith("/config")))
        self.assertTrue(self.bridge.status()["connected_with_current_settings"])
        blob = "".join(p for _, p, _ in client.published if isinstance(p, str))
        for forbidden in ("latitude", "longitude", "pw\"", "password"):
            self.assertNotIn(forbidden, blob)

    def test_fresh_state_goes_out_before_the_device_comes_online(self):
        # Otherwise Home Assistant shows the values from before the outage first.
        client = self.connect(2)
        for _ in range(2):
            topics = self.topics(client)
            fresh = [t for t in topics if t.startswith(f"{ROOT}/state/") or t == f"{ROOT}/frontend"]
            self.assertTrue({SETTINGS, f"{ROOT}/frontend", f"{ROOT}/state/game"} <= set(fresh))
            self.assertEqual(topics[len(topics) - topics[::-1].index(AVAILABILITY):], [])
            self.assertEqual(topics.count(AVAILABILITY), 1)
            client.connected = False
            self.settle()
            client.published.clear()
            client.go_online()
            self.bridge.step()
        # Events, derived ones too, follow it, so they reach an available entity.
        client.connected = False
        self.engine.state["thermal_protection"] = {"active": True}
        self.settle()
        client.published.clear()
        client.go_online()
        self.bridge.step()
        topics = self.topics(client)
        self.assertLess(topics.index(AVAILABILITY), topics.index(f"{ROOT}/event/thermal"))

    def test_a_republish_that_fails_part_way_is_tried_again_and_keeps_its_events(self):
        self.config.update({"enabled": True, "host": "192.0.2.10"}, password="pw")
        self.bridge.start()
        client, status, calls = self.bridge.client, self.engine.status, []
        self.engine.status = lambda: status() if calls.append(1) or len(calls) > 1 else 1 / 0
        self.engine.emit("light_event", {"kind": "achievement"})
        client.go_online()
        try:
            self.bridge.step()
        except ZeroDivisionError:
            pass
        self.settle()
        self.assertEqual(client.payloads(AVAILABILITY), ["online"])
        self.assertEqual(len(client.payloads(f"{ROOT}/event/light_events")), 1)

    def test_a_download_rides_out_a_frontend_reload(self):
        client = self.online()
        self.engine.emit("steam.download", {"active": True})
        self.settle()
        self.engine.state["debug"]["frontend_heartbeat_age_s"] = 99.0
        self.settle(7.0)
        self.engine.state["debug"]["frontend_heartbeat_age_s"] = 1.0
        self.settle()
        self.assertEqual({json.loads(p)["download_active"] for p in client.payloads(LIGHT_BAR)}, {True})

    def test_the_frontend_flag_rides_out_a_decky_restart_and_drops_after_30_seconds(self):
        # 14 entities follow it; a reload blipped them all unavailable.
        frontend, debug = f"{ROOT}/frontend", self.engine.state["debug"]
        debug["frontend_heartbeat_age_s"] = None  # a new engine, before the frontend's first heartbeat
        self.connect(1)
        self.bridge.stop()
        self.bridge = self.make_bridge()  # a Decky restart on the same boot
        client = self.connect(1)
        for age in (None,) * 25 + (0.5,) + (7.0,) * 25 + (0.5,) + (40.0,) * 31 + (0.5,):
            debug["frontend_heartbeat_age_s"] = age
            self.settle(1.0)
        self.assertEqual(client.payloads(frontend), ["online", "offline", "online"])

    def test_a_restart_with_the_same_game_sends_the_same_image_discovery(self):
        # A PNG logo announced as JPEG first made Home Assistant update the entity at every start.
        art = os.path.join(self.tmp.name, "art.png")
        with open(art, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\npngdata")
        runs = []
        with mock.patch("signalbar.steam.find_library_artwork", lambda appid, kind: art), \
                mock.patch("signalbar.steam.find_game_art", lambda appid, kind, max_bytes=None: art):
            for _ in range(2):
                self.engine.state["game"] = {"appid": 570, "title": "Dota 2"}
                bridge = self.make_bridge()
                client = self.connect(1, bridge)
                self.settle(1.1, bridge)
                sent = {}
                for topic, payload, _ in client.published:
                    if topic.startswith("homeassistant/image/"):
                        sent.setdefault(topic, set()).add(payload)
                runs.append(sent)
                bridge.stop()
        self.assertEqual(len(runs[1]), 4)
        self.assertEqual(runs[1], {topic: {max(payloads, key=lambda p: "image/png" in p)}
                                   for topic, payloads in runs[0].items()})

    def test_waking_from_sleep_makes_a_new_connection_and_republishes(self):
        # The socket may have died during sleep; the keepalive would take up to 45 s to notice.
        client = self.online()
        self.settle(30.0)
        self.asleep += 3600.0
        self.settle(1.0)
        self.assertEqual((getattr(client, "reconnects", 0), client.payloads(AVAILABILITY)), (1, ["online"]))

    def test_going_to_sleep_marks_the_device_offline_and_waking_or_shutting_down_does_not(self):
        client = self.online()
        missing = SleepWatch(self.bridge.on_sleep, command=["/nonexistent/gdbus"])
        missing.start()  # no gdbus is no error
        missing.stop()
        seen = []
        watch = SleepWatch(lambda sleeping: seen.append(sleeping) or self.bridge.on_sleep(sleeping))
        for name, value in (("PrepareForSleep", "false"), ("PrepareForShutdown", "true"), ("PrepareForSleep", "true")):
            watch.handle(f"/org/freedesktop/login1: org.freedesktop.login1.Manager.{name} ({value},)\n")
        self.assertEqual((seen, client.payloads(AVAILABILITY)), ([False, True], ["offline"]))

    def test_a_suspend_whose_end_was_missed_comes_back_online_after_two_minutes(self):
        # Steam's delay lock can hold a suspend for longer than 30 s before it starts.
        client = self.online()
        self.bridge.on_sleep(True)
        for _ in range(119):
            self.settle(1.0)
        self.assertEqual(client.payloads(AVAILABILITY), ["offline"])
        self.settle(2.0)
        self.assertEqual(client.payloads(AVAILABILITY), ["offline", "online"])

    def test_a_settings_save_during_a_sleep_announcement_does_not_keep_the_device_offline(self):
        self.online()
        self.bridge.on_sleep(True)
        self.bridge.reconfigure()  # the wake signal would go to the old watch
        client = self.bridge.client
        client.go_online()
        self.bridge.step()
        self.assertEqual(client.payloads(AVAILABILITY), ["online"])

    def test_one_wake_makes_one_new_connection_and_drops_what_came_before_the_sleep(self):
        client = self.online()
        self.bridge.on_sleep(True)
        client.receive("homeassistant/status", b"online")  # a republish: online and events wait
        self.engine.emit("light_event", {"kind": "achievement"})
        self.settle(1.0)
        self.asleep += 8 * 3600.0
        self.settle(1.0)  # the step sees the jump first
        self.bridge.on_sleep(False)
        self.settle(1.0)
        self.assertEqual((client.reconnects, client.payloads(AVAILABILITY), client.payloads(f"{ROOT}/event/light_events")),
                         (1, ["offline", "online"], []))

    def test_a_wake_signal_before_the_step_sees_the_jump_makes_one_new_connection(self):
        client = self.online()
        self.bridge.on_sleep(True)
        self.settle(1.0)
        self.engine.emit("light_event", {"kind": "achievement"})  # inside Steam's delay, before the sleep
        self.asleep += 600.0
        self.bridge.on_sleep(False)
        self.settle(1.0)
        self.assertEqual((client.reconnects, client.payloads(f"{ROOT}/event/light_events")), (1, []))

    def test_a_sleep_announced_while_online_goes_out_leaves_the_device_offline(self):
        client = self.online()
        publish = client.publish

        def racing(topic, payload, retain=False):
            sent = publish(topic, payload, retain)
            if (topic, payload) == (AVAILABILITY, "online") and not client.payloads(AVAILABILITY)[:-1]:
                self.bridge._sleep_at = self.now[0]  # the watch thread, past on_sleep's own offline
            return sent
        client.publish = racing
        client.receive("homeassistant/status", b"online")
        self.settle(1.0)
        self.assertEqual(client.payloads(AVAILABILITY), ["online", "offline"])

    def test_a_short_sleep_comes_back_online_on_the_wake_and_never_before(self):
        client = self.online()
        self.bridge.on_sleep(True)
        client.receive("homeassistant/status", b"online")  # a republish under way still stays offline
        self.settle(1.0)
        self.asleep += 15.0  # too short to be seen as a clock jump
        self.settle(1.0)
        self.assertEqual(client.payloads(AVAILABILITY), ["offline"])
        self.bridge.on_sleep(False)  # with a new connection: 12 s asleep can still leave the socket stalled
        self.settle(1.0)
        self.assertEqual((client.payloads(AVAILABILITY), getattr(client, "reconnects", 0)), (["offline", "online"], 1))

    def test_a_start_never_shows_the_last_runs_performance_as_current(self):
        # CPU load needs two samples; until then the broker holds the last run's.
        performance = f"{ROOT}/state/performance"
        self.engine.state["performance"] = {"cpu_load": None, "cpu_temperature": None}
        client = self.connect(1)
        self.assertEqual(client.payloads(AVAILABILITY), [])
        self.engine.state["performance"] = {"cpu_load": 26, "cpu_temperature": 138.2}
        self.settle(1.0)
        topics = self.topics(client)
        self.assertLess(topics.index(performance), topics.index(AVAILABILITY))

    def test_a_reading_from_before_a_sleep_is_never_shown_after_it(self):
        # The monotonic clock stands still in sleep, so a kept reading would look seconds old.
        performance = f"{ROOT}/state/performance"
        for signalled in (True, False):  # or seen only as a clock jump
            client = self.online()
            self.engine.state["performance"] = {"cpu_load": None}
            if signalled:
                self.bridge.on_sleep(True)
                self.bridge.on_sleep(False)
            else:
                self.asleep += 600.0
            self.settle(1.0)
            self.assertIsNone(self.last(client, performance)["cpu_load"])
            self.engine.state["performance"] = {"cpu_load": 20}
            self.bridge.stop()
            self.bridge = self.make_bridge()

    def test_only_a_start_waits_for_performance(self):
        client = self.online()
        client.connected = False
        self.engine.state["performance"] = {"cpu_load": None}
        self.settle(70.0)
        client.go_online()
        self.bridge.step()
        self.assertEqual(client.payloads(AVAILABILITY), ["online"])

    def test_a_reading_missing_for_under_a_minute_keeps_its_last_value(self):
        client = self.online()
        self.engine.state["performance"] = {"cpu_load": None, "cpu_temperature": 50.0}
        loads = lambda: [json.loads(p)["cpu_load"] for p in client.payloads(f"{ROOT}/state/performance")]
        for _ in range(55):
            self.settle(1.0)
        self.assertNotIn(None, loads())
        for _ in range(40):
            self.settle(1.0)
        self.assertEqual(loads()[-1], None)

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

    def test_the_connection_status_reads_plainly_and_never_holds_the_password(self):
        def connection():
            status = self.bridge.status()
            return tuple(status[key] for key in ("phase", "reason", "retry_in_s", "broker"))

        self.assertEqual(connection(), ("off", "", None, ""))
        self.config.update({"enabled": True, "host": "fd00::5", "port": 8883}, password="secret-pw")
        self.bridge.start()
        client = self.bridge.client
        self.assertEqual(connection(), ("connecting", "", None, "[fd00::5]:8883"))
        client.last_reason, client.last_error, client.retry = "Wrong username or password", "bad password", 12.34
        self.assertEqual(connection(), ("waiting_retry", "Wrong username or password", 12.3, "[fd00::5]:8883"))
        self.assertEqual(self.bridge.status()["last_error"], "bad password")
        self.assertNotIn("secret-pw", json.dumps(self.bridge.status()))
        client.go_online()
        self.assertEqual(connection()[:2], ("connected", ""))
        self.assertEqual(self.bridge.status()["topic_root"], ROOT)


class GameTests(BridgeTestCase):
    def play(self, appid, title="Dota 2", seconds=1.1):
        before = self.engine.state["game"]
        self.engine.state["game"] = {"appid": appid, "title": title if appid else ""}
        if appid != before["appid"]:
            if before["appid"]:
                self.engine.emit("game.stopped", dict(before))
            if appid:
                self.engine.emit("game.started", {"appid": appid, "title": title})
        self.settle(seconds)

    @staticmethod
    def games(client):
        return [json.loads(p) for p in client.payloads(f"{ROOT}/state/game")]

    @staticmethod
    def game_events(client):
        return [json.loads(p)["event_type"] for p in client.payloads(f"{ROOT}/event/game")]

    def test_a_game_back_within_30_seconds_is_one_session_and_sends_nothing(self):
        # Waking from sleep and mod launchers both stop the game for a moment.
        client = self.online()
        self.play(570)
        self.play(0)
        for _ in range(25):
            self.settle(1.0)
        self.play(570)
        self.settle(40.0)
        self.assertEqual([g["appid"] for g in self.games(client)], [570])
        self.assertEqual(self.game_events(client), ["started"])

    def test_a_real_stop_shows_30_seconds_late_and_another_game_at_once(self):
        client = self.online()
        self.play(570)
        started = self.games(client)[-1]["started_at"]
        self.play(0)
        self.settle(27.0)
        self.assertEqual((self.games(client)[-1]["started_at"], self.game_events(client)), (started, ["started"]))
        self.settle(3.0)
        self.assertEqual((self.games(client)[-1]["running"], self.game_events(client)), (False, ["started", "stopped"]))
        self.play(570)
        self.play(0)
        self.play(730, "Counter-Strike 2")
        self.assertEqual([(g["appid"], g["title"]) for g in self.games(client)[-2:]],
                         [(570, "Dota 2"), (730, "Counter-Strike 2")])
        self.assertEqual(self.game_events(client), ["started", "stopped", "started", "stopped", "started"])


    def test_a_game_back_before_its_started_event_is_still_one_session(self):
        # The engine changes its state first; the hub delivers the event later.
        client = self.online()
        self.play(570)
        self.play(0)
        self.engine.state["game"] = {"appid": 570, "title": "Dota 2"}
        self.settle()
        self.engine.emit("game.started", {"appid": 570, "title": "Dota 2"})
        self.settle(40.0)
        self.assertEqual(self.game_events(client), ["started"])

    def test_a_new_games_images_go_out_before_they_become_available(self):
        # The broker still holds the last game's; they would show first for a moment.
        art = os.path.join(self.tmp.name, "art.png")
        with open(art, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\npngdata")
        client = self.online()
        with mock.patch("signalbar.steam.find_library_artwork", lambda appid, kind: art), \
                mock.patch("signalbar.steam.find_game_art", lambda appid, kind, max_bytes=None: art):
            self.play(105600, "Terraria")
        topics = self.topics(client)
        for kind in ("key_art", "header", "capsule", "logo"):
            self.assertLess(topics.index(f"{ROOT}/image/{kind}"), topics.index(f"{ROOT}/state/game"), kind)

    def test_a_game_quit_and_launched_again_while_offline_is_a_new_session(self):
        client = self.online()
        self.play(570)
        started = self.games(client)[-1]["started_at"]
        client.connected = False
        self.play(0)
        self.settle(600.0)
        with open(os.path.join(self.mqtt_dir, "session.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["appid"], 0)
        client.go_online()
        self.bridge.step()
        self.assertFalse(self.games(client)[-1]["running"])  # at once, not 30 s later
        client.connected = False
        self.play(570)
        self.settle(60.0)
        client.go_online()
        self.bridge.step()
        game = self.games(client)[-1]
        self.assertEqual((game["running"], game["started_at"] == started, game["session_minutes"]), (True, False, 0))

    def test_a_stop_held_over_a_long_outage_is_history_and_never_eats_a_later_start(self):
        client = self.online()
        self.play(570)
        self.play(0, seconds=5.0)
        client.connected = False
        self.settle(60.0)
        self.play(570, seconds=120.0)  # launched again while away; its "started" ages out
        client.go_online()
        self.bridge.step()
        self.settle(40.0)
        self.assertEqual(self.game_events(client), ["started"])
        self.settle(3600.0)
        self.play(0)
        self.settle(40.0)
        self.play(570)
        self.play(0, seconds=5.0)
        client.connected = False
        self.settle(7200.0)
        client.go_online()
        self.bridge.step()
        self.assertEqual(self.game_events(client), ["started", "stopped", "started"])

    def test_a_held_stop_is_sent_later_if_it_could_not_be_and_never_after_a_restart(self):
        client = self.online()
        self.play(570)
        self.play(0)
        publish = client.publish
        client.publish = lambda topic, payload, retain=False: (
            not topic.endswith("/event/game") and publish(topic, payload, retain))
        self.settle(30.0)
        client.publish = publish
        self.engine.state["game"] = {"appid": 570, "title": "Dota 2"}  # relaunched before the retry
        self.settle()
        self.engine.emit("game.started", {"appid": 570, "title": "Dota 2"})
        self.settle()
        self.assertEqual(self.game_events(client), ["started", "stopped", "started"])
        self.play(0)
        self.bridge.stop()
        self.now[0] += 3600
        self.assertEqual(self.game_events(self.connect(1)), [])


    def test_sleep_pauses_the_session_and_a_restart_carries_it_on(self):
        client = self.online()
        self.play(570)
        started = self.games(client)[-1]["started_at"]
        for minutes, asleep in ((20, 8 * 3600.0), (30, 0.0)):
            for _ in range(minutes):
                self.settle(60.0)
            self.asleep += asleep  # overnight: the wall clock jumps, the monotonic one does not
        self.assertEqual((self.games(client)[-1]["started_at"], self.games(client)[-1]["session_minutes"]),
                         (started, 50))
        self.bridge.stop()
        # A Decky restart: the monotonic clock starts afresh, the wall clock goes on.
        for appid, damaged, carries_on in ((570, False, True), (730, False, False), (730, True, False)):
            if damaged:
                with open(os.path.join(self.mqtt_dir, "session.json"), "w") as handle:
                    handle.write("{not json")
            self.engine.state["game"] = {"appid": appid, "title": "Dota 2"}
            self.now[0] -= 10_000.0
            self.asleep += 10_005.0
            bridge = self.make_bridge()
            game = self.last(self.connect(1, bridge), f"{ROOT}/state/game")
            self.assertEqual((game["started_at"] == started, game["session_minutes"]),
                             (True, 50) if carries_on else (False, 0), appid)
            bridge.stop()

    def test_two_session_writes_at_once_never_damage_the_record(self):
        # stop() on an executor thread can save while the worker does.
        directory = os.path.join(self.tmp.name, "session")
        record = SessionRecord(directory)
        for _ in range(100):
            go = threading.Event()
            threads = [threading.Thread(target=lambda args=args: go.wait() and record.save(*args))
                       for args in ((570, 1.0, 2.0, 3.0), ())]
            for thread in threads:
                thread.start()
            go.set()
            for thread in threads:
                thread.join()
            with open(record.path, encoding="utf-8") as handle:
                json.load(handle)
        self.assertEqual(os.listdir(directory), ["session.json"])
        record.save(570, float("nan"), 1.0, 2.0)  # not JSON: the old record stays, nothing raises
        record.save(570, object(), 1.0, 2.0)
        self.assertEqual(os.listdir(directory), ["session.json"])

    def test_a_restart_carries_on_only_a_game_still_running_in_the_same_boot(self):
        boot = os.path.join(self.tmp.name, "boot_id")
        patcher = mock.patch("signalbar.mqtt.session.BOOT_ID_PATH", boot)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Each run: its boot, whether the game is quit just before Decky stops, whether it carried on.
        for run, (boot_id, quit, carries_on) in enumerate((("a", True, False), ("a", False, False),
                                                           ("b", False, False), ("b", False, True))):
            with open(boot, "w", encoding="utf-8") as handle:
                handle.write(boot_id + "\n")
            bridge = self.make_bridge()  # Decky loads the plugin
            self.engine.state["game"] = {"appid": 570, "title": "Dota 2"}
            game = self.last(self.connect(1, bridge), f"{ROOT}/state/game")
            self.assertEqual(game["session_minutes"] > 0, carries_on, run)
            self.settle(600.0, bridge)
            if quit:
                self.engine.state["game"] = {"appid": 0, "title": ""}  # inside the 30 s hold
                self.settle(5.0, bridge)
            bridge.stop()
            self.now[0] -= 10_000.0
            self.asleep += 10_060.0

    def test_mqtt_turned_on_hours_after_decky_started_does_not_carry_on_an_old_session(self):
        self.online()
        self.play(570)
        self.settle(300.0)
        self.bridge.stop()
        self.now[0] -= 10_000.0
        self.asleep += 10_005.0
        self.bridge = self.make_bridge()  # Decky loads with MQTT off; the record is fresh now
        self.config.update({"enabled": False})
        self.now[0] += 3 * 3600.0
        game = self.last(self.connect(1), f"{ROOT}/state/game")
        self.assertEqual((game["running"], game["session_minutes"]), (True, 0))

    def test_a_cold_start_waits_for_the_frontends_first_sync_even_without_a_record(self):
        # A new engine says no game until the frontend's seed, which it sends with source "startup".
        self.connect(1)  # an earlier run on this boot
        for appid, title in ((1942280, "Brotato"), (0, "")):
            self.engine = FakeEngine()
            self.engine.state["debug"]["game_detection_source"] = "startup"
            self.bridge = self.make_bridge()
            client = self.connect(1)
            for _ in range(5):
                self.settle(1.0)
            self.engine.state["debug"]["game_sync_ms"] = 15.0
            self.engine.state["game"] = {"appid": appid, "title": title}
            self.settle(1.0)
            self.assertEqual([g["running"] for g in self.games(client)], [bool(appid)], appid)
            self.bridge.stop()

    def test_after_a_reboot_nothing_from_before_is_held(self):
        # The broker's values are all stale: no game survives a reboot, and Decky is not loaded yet.
        boot = os.path.join(self.tmp.name, "boot_id")
        patcher = mock.patch("signalbar.mqtt.session.BOOT_ID_PATH", boot)
        patcher.start()
        self.addCleanup(patcher.stop)
        for boot_id in ("a", "b"):
            with open(boot, "w", encoding="utf-8") as handle:
                handle.write(boot_id)
            self.engine = FakeEngine()
            self.engine.state.update(owner="Valve", debug={"frontend_heartbeat_age_s": None, "game_sync_ms": None})
            self.bridge.stop()
            self.bridge = self.make_bridge()
            client = self.connect(1)
            if boot_id == "a":
                self.play(570)
                self.engine.state["owner"] = "GabeCubeAura"
                self.settle(40.0)
        self.assertEqual((self.games(client)[-1]["running"], self.last(client, LIGHT_BAR)["owner"],
                          client.payloads(f"{ROOT}/frontend")), (False, "Valve", ["offline"]))

    def test_a_decky_restart_mid_game_shows_neither_a_gap_nor_a_new_start(self):
        # The new engine has no game until the frontend reports the one still running.
        self.online()
        self.play(570)
        for _ in range(20):
            self.settle(60.0)
        for comes_back, expected in ((True, [(True, 20)]), (False, [(False, 0)])):
            self.bridge.stop()
            self.engine = FakeEngine()
            self.now[0] -= 5000.0
            self.asleep += 5005.0
            self.bridge = self.make_bridge()
            client = self.connect(1)
            self.settle(1.0)
            if comes_back:
                self.play(570)
            self.settle(30.0)
            self.assertEqual([(g["running"], g["session_minutes"]) for g in self.games(client)], expected)
            self.assertEqual(self.game_events(client), [])

    def test_a_quit_longer_than_the_hold_while_offline_is_a_stop_and_a_start(self):
        client = self.online()
        self.play(570)
        client.connected = False
        self.play(0)
        for _ in range(40):
            self.settle(1.0)
        self.play(570)
        client.go_online()
        self.settle()
        self.assertEqual(self.game_events(client), ["started", "stopped", "started"])

    def test_decky_stopping_inside_the_hold_sends_the_stop_first(self):
        client = self.online()
        self.play(570)
        self.play(0, seconds=5.0)
        self.bridge.stop()
        self.assertEqual((self.game_events(client), self.games(client)[-1]["running"]), (["started", "stopped"], False))
        topics = self.topics(client)
        self.assertLess(topics.index(f"{ROOT}/event/game"), topics.index(AVAILABILITY))

    def test_a_settings_save_during_the_hold_keeps_the_stop(self):
        client = self.online()
        self.play(570)
        self.play(0, seconds=5)
        self.bridge.reconfigure()  # every settings save does this
        client = self.bridge.client
        client.go_online()
        for _ in range(40):
            self.settle(1.0)
        self.assertEqual(self.game_events(client), ["stopped"])


class SettlingTests(BridgeTestCase):
    PAD = {"id": "steam:1", "name": "Controller", "percent": 74, "level": None, "charging": False}

    def test_a_settings_save_keeps_a_full_controller_reading(self):
        self.online()
        self.roster(self.PAD)
        self.roster({**self.PAD, "percent": 100})
        self.bridge.reconfigure()
        client = self.bridge.client
        client.go_online()
        self.roster({**self.PAD, "percent": 100})
        self.assertEqual(self.sent(client), [(1, [100])])

    def roster(self, *pads, seconds=1.1):
        self.engine.state["controllers"] = {"controllers": [dict(pad) for pad in pads]}
        self.settle(seconds)

    @staticmethod
    def sent(client):
        return [(c["count"], [pad["percent"] for pad in c["controllers"]])
                for c in map(json.loads, client.payloads(f"{ROOT}/state/controllers"))]

    def test_an_owner_change_that_reverts_within_seconds_is_not_an_event(self):
        # A notification over Steam's bar hands it to GabeCubeAura for 3-4 s.
        client = self.online()
        for owner, seconds in (("Valve", 4), ("GabeCubeAura", 4), ("Valve", 12)):
            self.engine.state["owner"] = owner
            for _ in range(seconds):
                self.settle(1.0)
        self.assertEqual([json.loads(p)["owner"] for p in client.payloads(f"{ROOT}/event/light_bar")], ["Valve"])

    def test_a_new_controller_battery_waits_for_a_real_reading(self):
        # Steam lists a new controller at 100% until its first battery report.
        client = self.online()
        full = {**self.PAD, "percent": 100}
        self.roster(full)
        self.roster(self.PAD)
        self.roster(self.PAD, {**full, "id": "steam:2"})
        self.roster(self.PAD, {**full, "id": "steam:2"}, seconds=60)
        self.assertEqual(self.sent(client), [(1, [None]), (1, [74]), (2, [74, None]), (2, [74, 100])])

    def test_a_restart_keeps_the_light_bar_as_it_was_until_the_frontend_reports(self):
        # A new engine thinks it is at home until then: Steam's bar, Controller status.
        self.online()
        self.bridge.stop()
        self.engine = FakeEngine()
        cold = {"owner": "Valve", "current_display": "controller", "debug": {"frontend_heartbeat_age_s": None}}
        self.engine.state.update(cold)
        self.bridge = self.make_bridge()
        client = self.connect(1)
        for _ in range(7):
            self.settle(1.0)
        warm = {"owner": "GabeCubeAura", "current_display": "artwork", "debug": {"frontend_heartbeat_age_s": 0.5}}
        self.engine.state.update(warm)
        for _ in range(30):
            self.settle(1.0)
        self.assertEqual([json.loads(p)["owner"] for p in client.payloads(LIGHT_BAR)], ["GabeCubeAura"])
        self.assertEqual(client.payloads(f"{ROOT}/event/light_bar"), [])

    def test_the_startup_settle_is_neither_an_owner_change_nor_an_event(self):
        # With no game the new engine took the bar for 11 s, then gave it back to Steam.
        self.engine.state["owner"] = "Valve"
        self.online()
        self.settle(40.0)
        self.bridge.stop()
        self.engine = FakeEngine()
        self.engine.state["owner"] = "Valve"
        self.bridge = self.make_bridge()
        client = self.connect(1)
        for owner, seconds in (("Valve", 9), ("GabeCubeAura", 11), ("Valve", 30)):
            self.engine.state["owner"] = owner
            for _ in range(seconds):
                self.settle(1.0)
        self.assertEqual([json.loads(p)["owner"] for p in client.payloads(LIGHT_BAR)], ["Valve"])
        self.assertEqual(client.payloads(f"{ROOT}/event/light_bar"), [])

    def test_the_startup_hold_needs_an_owner_from_before_and_outlasts_a_setting_change(self):
        client = self.connect(2)  # a first install: nothing to keep, so nothing is held
        self.assertTrue(client.payloads(LIGHT_BAR))
        self.bridge.stop()
        self.bridge = self.make_bridge()
        client = self.connect(2)
        # A setting does not say who has the bar; the cold engine's owner would go out with it.
        client.receive(f"{ROOT}/set/light_bar_day_brightness", b"40")
        self.settle()
        self.settle()
        self.assertEqual((client.payloads(LIGHT_BAR), self.applied), ([], [("light_bar_day_brightness", 40)]))

    def test_a_lapsed_roster_is_neither_a_zero_nor_a_new_connection(self):
        client = self.online()
        self.roster(self.PAD)
        self.engine.state["debug"]["frontend_heartbeat_age_s"] = 30.0  # gamescope restarting
        self.roster(seconds=15)
        self.engine.state["debug"]["frontend_heartbeat_age_s"] = 1.0
        self.roster(seconds=3)
        self.engine.emit("controller.connected", {"id": "steam:1", "name": "Controller", "percent": 74})
        self.roster(self.PAD)
        self.engine.emit("controller.connected", {"id": "steam:2", "name": "Controller", "percent": 100})
        self.roster(self.PAD, {**self.PAD, "id": "steam:2"})
        self.assertEqual([count for count, _ in self.sent(client)], [1, 2])
        events = [json.loads(p) for p in client.payloads(f"{ROOT}/event/controllers")]
        self.assertEqual([(e["id"], "percent" in e) for e in events], [("steam:2", False)])


    def test_a_controller_switched_on_long_after_a_lapse_is_a_new_connection(self):
        client = self.online()
        self.roster(self.PAD)
        self.engine.state["debug"]["frontend_heartbeat_age_s"] = 30.0  # switched off meanwhile
        self.roster(seconds=15)
        self.engine.state["debug"]["frontend_heartbeat_age_s"] = 1.0
        self.roster(seconds=3)
        self.roster(seconds=60)
        self.engine.emit("controller.connected", {"id": "steam:1", "name": "Controller", "percent": 100})
        self.roster({**self.PAD, "percent": 100})
        self.assertEqual([json.loads(p)["id"] for p in client.payloads(f"{ROOT}/event/controllers")], ["steam:1"])
        self.assertEqual(self.sent(client)[-1], (1, [None]))  # a new listing again


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

    def test_help_out_describes_every_control_once_then_the_state(self):
        client = self.connect(2)
        for tier in (3, 4, 5):
            self.config.update({"light_bar_tier": tier})
            self.bridge.step()
        topics = self.topics(client)
        for topic in self.everything - {SETTINGS}:
            self.assertEqual(topics.count(topic), 1, topic)
            self.assertLess(topics.index(topic), topics.index(SETTINGS))
        state = self.last(client, SETTINGS)
        self.assertEqual(set(state), set(self.controls) | store_module.LOCAL_ONLY_SETTINGS)
        self.assertEqual(self.on_disk(), self.everything)

    def test_leaving_for_watch_only_clears_exactly_what_was_advertised_configs_first(self):
        client = self.connect(2)
        client.published.clear()
        self.config.update({"light_bar_tier": 1})
        self.bridge.step()
        cleared = [t for t, p, _ in client.published if p == ""]
        self.assertEqual((sorted(cleared), len(client.published)), (sorted(self.everything), len(self.everything)))
        self.assertEqual(sorted(cleared[-2:]), sorted([SETTINGS, NOTE]))
        self.assertEqual(self.on_disk(), frozenset())
        client.published.clear()
        client.receive("homeassistant/status", b"online")
        self.bridge.step()
        self.assertEqual(self.empties(client), [])

    def test_a_start_at_watch_only_clears_what_an_interrupted_earlier_run_left(self):
        sent = []

        class DropsAfterTen(FakeClient):
            def publish(self, topic, payload, retain=False):
                if payload == "":
                    sent.append(topic)
                    self.connected = len(sent) <= 10
                return super().publish(topic, payload, retain)

        first = self.make_bridge(DropsAfterTen)
        self.connect(2, first)
        self.config.update({"light_bar_tier": 1})
        first.step()
        first.stop()
        remaining = self.on_disk()
        self.assertEqual(len(self.everything) - len(remaining), 10)
        client = self.connect(1, self.make_bridge())
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

    def test_a_refusal_clears_when_the_current_value_is_sent(self):
        client = self.connect()
        current = str(self.store.all()["light_bar_day_brightness"]).encode()
        self.send(client, "light_bar_day_brightness", b"abc")
        self.settle()
        self.assertEqual(self.error(), "light_bar_day_brightness: expected a number")
        self.send(client, "light_bar_day_brightness", current)
        self.settle()
        self.assertEqual((self.error(), self.applied), ("", []))

    def test_refusals_say_why_and_change_nothing(self):
        cases = (
            (1, "home_display", b"blackout", "home_display: Light bar is set to Watch only"),
            (2, "weather_location", b"{}", "weather_location: not a setting Home Assistant can change"),
            (2, "updates_channel", b"beta", "updates_channel: can only be changed on the Steam Machine"),
            (2, "Home/../x", b"1", "(unreadable): not a setting Home Assistant can change"),
            (2, "home_display", b"<b>nope</b>", "home_display: not one of the allowed options"),
            (2, "light_bar_day_brightness", b"999", "light_bar_day_brightness: must be 1-255"),
            (2, "signalbar_enabled", b"true", "signalbar_enabled: expected ON or OFF"),
        )
        client = self.connect()
        for tier, key, payload, expected in cases:
            with self.subTest(key=key, payload=payload):
                self.config.update({"light_bar_tier": tier})
                self.send(client, key, payload)
                self.settle()
                self.assertEqual(self.last(client, f"{ROOT}/state/bridge")["last_error"], expected)
        self.assertEqual(self.applied, [])

    def test_local_only_settings_are_reported_but_never_advertised_or_applied(self):
        # Plus two keys that would otherwise be controls, one of them preset-controlled.
        local = store_module.LOCAL_ONLY_SETTINGS | {"home_display", "light_bar_day_brightness"}
        bridge = self.make_bridge(schema=build_schema(local_only=local))
        client = self.connect(2, bridge)
        state = self.last(client, SETTINGS)
        for key in ("home_display", "light_bar_day_brightness", "updates_auto_check", "valve_ownership_policy"):
            self.assertFalse(any(f"_setting_{key}/" in t for t in self.topics(client)), key)
            self.assertEqual(state[key], self.store.all()[key], key)
            for tier in (2, 1):
                self.config.update({"light_bar_tier": tier})
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
