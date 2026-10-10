from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mqtt_fake_broker import FakeClient
from signalbar.mqtt.bridge import MqttBridge
from signalbar.mqtt.config import MqttConfig
from signalbar.steam import find_game_art

JPEG = b"\xff\xd8\xff\xe0jpegdata"
PNG = b"\x89PNG\r\n\x1a\npngdata"
IMAGE = "gabecubeaura/steammachine/image"


class GameArtFinderTests(unittest.TestCase):
    def test_custom_grid_art_first_then_both_cache_layouts_and_never_another_kind(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {"SIGNALBAR_STEAM_ROOT": folder}):
            cache, grid = Path(folder) / "appcache/librarycache", Path(folder) / "userdata/12345/config/grid"
            for path, data in ((cache / "570" / "logo.png", PNG), (grid / "570_logo.png", PNG + b"x" * 64),
                               (cache / "571" / "logo.png", b"")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            self.assertEqual(find_game_art(570, "logo"), grid / "570_logo.png")
            self.assertEqual(find_game_art(570, "logo", max_bytes=32), cache / "570" / "logo.png")  # too large
            for appid, kind in ((570, "header"), (571, "logo"), (0, "logo"), (570, "../logo")):
                self.assertIsNone(find_game_art(appid, kind), (appid, kind))


class Engine:
    appid = 0
    hub = type("Hub", (), {"dropped": 0})()

    def subscribe(self, callback):
        return lambda: None

    def status(self):
        return {"version": "1.4.0", "game": {"appid": self.appid, "title": "Game" if self.appid else ""},
                "debug": {"frontend_heartbeat_age_s": 1.0}}


class GameArtBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = MqttConfig(os.path.join(self.tmp.name, "mqtt"))
        self.config.update({"enabled": True, "host": "192.0.2.10"}, password="pw")
        self.engine = Engine()
        self.now = [100.0]
        self.art, self.calls = {}, []
        for name, value in (("signalbar.steam.find_library_artwork", lambda appid, kind: self.find(appid, kind)),
                            ("signalbar.steam.find_game_art", self.find)):
            patcher = mock.patch(name, value)
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

    def find(self, appid, kind, max_bytes=None):
        self.calls.append((appid, kind))
        return self.art.get(kind)

    def file(self, name, data):
        path = Path(self.tmp.name) / name
        path.write_bytes(data)
        return path

    def images(self, kind):
        return self.client.payloads(f"{IMAGE}/{kind}")

    def play(self, appid=570, seconds=1.1):
        self.engine.appid = appid
        self.now[0] += seconds
        self.bridge.step()

    def test_art_is_published_retained_once_per_game_and_emptied_when_it_ends(self):
        self.engine.appid = 730  # the broker may still hold an earlier run's art
        self.connect()
        self.assertEqual(self.images("key_art"), [b""])
        link = Path(self.tmp.name) / "link.png"
        link.symlink_to(self.file("logo.png", PNG))  # the grid folder is the user's: never followed
        self.art = {"hero": self.file("hero.jpg", JPEG), "header": self.file("h.png", PNG), "logo": link}
        self.play()
        for _ in range(5):
            self.play()
        self.assertEqual((self.images("key_art")[1:], self.images("header")[1:], self.images("logo")[1:]),
                         ([JPEG], [PNG], []))
        self.assertTrue(all(r for t, _, r in self.client.published if t.startswith(IMAGE)))
        self.assertEqual(self.calls.count((570, "header")), 1)
        self.play(0)
        self.assertEqual((self.images("key_art")[-1], self.images("header")[-1]), (b"", b""))

    def test_missing_art_is_looked_up_again_after_30_seconds(self):
        self.connect()
        self.play()
        self.play()
        self.assertEqual(self.calls.count((570, "hero")), 1)
        self.art["hero"] = self.file("hero.jpg", JPEG)
        self.play(seconds=30)
        self.assertEqual(self.images("key_art")[-1], JPEG)


if __name__ == "__main__":
    unittest.main()
