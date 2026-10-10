from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mqtt_fake_broker import FakeClient
from signalbar.mqtt.bridge import MqttBridge
from signalbar.mqtt.config import MqttConfig

JPEG = b"\xff\xd8\xff\xe0jpegdata"
KEY_ART = "gabecubeaura/steammachine/image/key_art"


class Engine:
    appid = 0
    hub = type("Hub", (), {"dropped": 0})()

    def subscribe(self, callback):
        return lambda: None

    def status(self):
        return {"version": "1.4.0", "game": {"appid": self.appid, "title": "Game" if self.appid else ""},
                "debug": {"frontend_heartbeat_age_s": 1.0}}


class KeyArtBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = MqttConfig(os.path.join(self.tmp.name, "mqtt"))
        self.config.update({"enabled": True, "host": "192.0.2.10"}, password="pw")
        self.engine = Engine()
        self.now = [100.0]
        self.art, self.calls = {}, []
        patcher = mock.patch("signalbar.steam.find_library_artwork", self.find)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bridge = MqttBridge(self.config, self.engine, lambda: None, lambda: {}, hostname="steammachine",
                                 client_factory=FakeClient, clock=lambda: self.now[0],
                                 wall=lambda: 1_760_000_000.0 + self.now[0], run_thread=False)
        self.addCleanup(self.bridge.stop)

    def connect(self):
        self.bridge.start()
        self.client = self.bridge.client
        self.client.go_online()
        self.bridge.step()

    def find(self, appid, kind):
        self.calls.append((appid, kind))
        return self.art.get(kind)

    def file(self, name, data):
        path = Path(self.tmp.name) / name
        path.write_bytes(data)
        return path

    def images(self):
        return self.client.payloads(KEY_ART)

    def play(self, appid=570, seconds=1.1):
        self.engine.appid = appid
        self.now[0] += seconds
        self.bridge.step()

    def test_art_is_published_retained_once_per_game_and_emptied_when_it_ends(self):
        self.engine.appid = 730  # the broker may still hold an earlier run's art
        self.connect()
        self.assertEqual(self.images(), [b""])
        self.art = {"hero": self.file("hero.jpg", JPEG)}
        self.play()
        for _ in range(5):
            self.play()
        self.assertEqual(self.images()[1:], [JPEG])
        self.assertTrue(all(r for t, _, r in self.client.published if t == KEY_ART))
        self.assertEqual(self.calls.count((570, "hero")), 1)
        self.play(0)
        self.assertEqual(self.images()[-1], b"")

    def test_missing_art_is_looked_up_again_after_30_seconds(self):
        self.connect()
        link = Path(self.tmp.name) / "link.jpg"
        link.symlink_to(self.file("real.jpg", JPEG))  # the grid folder is the user's: never followed
        self.art["hero"] = link
        self.play()
        self.play()
        self.assertEqual((self.calls.count((570, "hero")), self.images()), (1, [b""]))
        self.art["hero"] = self.file("hero.jpg", JPEG)
        self.play(seconds=30)
        self.assertEqual(self.images()[-1], JPEG)


if __name__ == "__main__":
    unittest.main()
