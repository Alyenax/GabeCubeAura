from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from signalbar.backend import Engine
from signalbar.hub import EventHub
from signalbar.settings import SettingsStore


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class HubTests(unittest.TestCase):
    def test_every_subscriber_gets_events_and_a_failing_one_harms_nobody(self):
        hub = EventHub()
        self.addCleanup(hub.stop)
        seen = []
        hub.subscribe(lambda kind, data: 1 / 0)
        hub.subscribe(lambda kind, data: seen.append((kind, data)))
        hub.emit("game.started", {"appid": 1})
        self.assertTrue(wait_for(lambda: seen))
        self.assertEqual(seen[0], ("game.started", {"appid": 1}))
        self.assertIn("game.started", hub.known_kinds)


class EngineEventTests(unittest.TestCase):
    def test_the_engine_reports_games_light_events_controllers_and_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(SettingsStore(str(Path(folder) / "config.json")), str(Path(folder) / "art.json"))
            self.addCleanup(engine.hub.stop)
            events = []
            engine.subscribe(lambda kind, data: events.append((kind, data)))
            engine.set_game(3000000000, "Emulator", True, "lifetime")
            engine.set_game(0, "", False, "lifetime")
            engine.settings.update({"events_enabled": False})
            engine.trigger_event("achievement")  # published even when not shown
            engine.trigger_event("screenshot", preview=True)
            controller = {"id": "a", "name": "a", "percent": 80, "level": None, "charging": False}
            engine.update_controllers([controller])  # the first roster is the baseline
            engine.update_controllers([{**controller, "charging": True}])
            for active in (True, True, False):
                engine.set_steam_activity(active, "Steam download activity (items)")
            self.assertTrue(wait_for(lambda: len(events) == 6))
        self.assertEqual(events, [
            ("game.started", {"appid": 3000000000, "title": "Emulator", "non_steam": True, "launch": True}),
            ("game.stopped", {"appid": 3000000000, "title": "Emulator"}),
            ("light_event", {"kind": "achievement", "appid": 0, "shown": False}),
            ("controller.charging", {"id": "a", "name": "a", "charging": True}),
            ("steam.download", {"active": True}),
            ("steam.download", {"active": False}),
        ])


if __name__ == "__main__":
    unittest.main()
