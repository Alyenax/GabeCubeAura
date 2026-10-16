from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from signalbar.providers.screen_sync import CAPTURE_HEIGHT, CAPTURE_WIDTH, ScreenSyncProcessor
from signalbar.room_lights.room import ZONES, RoomLights, ring_colour, send_order


class FakeLight:
    sent = []

    def __init__(self, ip):
        self.ip = ip
        self.streaming = False

    def __getattr__(self, name):
        def record(*args):
            FakeLight.sent.append((self.ip, name, args))
            if name == "start_stream":
                self.streaming = True
            if name == "stop_stream":
                self.streaming = False
            return True
        return record


FAKE = SimpleNamespace(
    scan=lambda: [{"id": "lamp", "ip": "10.0.0.5", "model": "H6022"}],
    identify=lambda ip: None,
    Light=FakeLight,
)


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


class SendOrderTest(unittest.TestCase):
    def test_lamps_and_strips_start_at_the_lowest_end(self):
        self.assertEqual(send_order(["left-1", "left-2", "left-3"]), ["left-3", "left-2", "left-1"])
        self.assertEqual(send_order(["right-1", "right-2", "right-3"]), ["right-3", "right-2", "right-1"])
        self.assertEqual(send_order(["bottom-1", "bottom-2", "bottom-3", "bottom-4"]),
                         ["bottom-1", "bottom-2", "bottom-3", "bottom-4"])
        self.assertEqual(send_order(["top-4", "top-right", "right-1"]), ["right-1", "top-right", "top-4"])

    def test_reverse_and_whole(self):
        self.assertEqual(send_order(["left-1", "left-2"], reverse=True), ["left-1", "left-2"])
        self.assertEqual(send_order(["whole"]), ["whole"])

    def test_ring_wraps(self):
        palette = [(255, 0, 0), (0, 0, 255)]
        self.assertEqual(ring_colour(palette, 0.0), (255, 0, 0))
        self.assertEqual(ring_colour(palette, 1.0), (255, 0, 0))
        self.assertEqual(ring_colour(palette, 0.25), (127.5, 0, 127.5))


class ZonesTest(unittest.TestCase):
    def test_every_cell_is_sampled(self):
        raw = bytes((0, 0, 255, 0)) * (CAPTURE_WIDTH * CAPTURE_HEIGHT)
        processor = ScreenSyncProcessor()
        self.assertIsNone(processor.zones())
        processor.process(raw)
        self.assertEqual(set(processor.zones()), set(ZONES))


class RoomLightsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.dir.name) / "room-lights.json")
        FakeLight.sent = []

    def tearDown(self):
        self.dir.cleanup()

    def test_broken_settings_file_falls_back_to_defaults(self):
        Path(self.path).write_text(json.dumps({"enabled": "yes", "lights": [1, 2]}))
        room = RoomLights(self.path, drivers={"govee": FAKE})
        self.assertFalse(room.status()["enabled"])
        self.assertEqual(room.status()["lights"], {})

    def test_screen_light_streams_then_goes_idle(self):
        clock = Clock()
        room = RoomLights(self.path, clock=clock, drivers={"govee": FAKE})
        room.set_options({"idle": "off"})
        room.scan()
        room.set_light("lamp", "10.0.0.5", "H6022", "screen", ["left-1", "left-2"], None)
        room.set_options({"enabled": True})
        room.update(zones={z: (10, 20, 30) for z in ZONES}, game_running=True)
        self.assertIn(("10.0.0.5", "frame", ([(10, 20, 30), (10, 20, 30)],)), FakeLight.sent)
        clock.now += 2.0
        room.update(zones=None, game_running=False)
        self.assertIn(("10.0.0.5", "stop_stream", ()), FakeLight.sent)
        self.assertIn(("10.0.0.5", "power", (False,)), FakeLight.sent)

    def test_update_never_raises(self):
        room = RoomLights(self.path, drivers={"govee": FAKE})
        room.config["enabled"] = True
        room.config["lights"]["x"] = {"role": "screen"}  # missing everything
        room.update(zones={}, game_running=True)
        self.assertTrue(room.status()["last_error"])


if __name__ == "__main__":
    unittest.main()
