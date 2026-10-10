"""The Home Assistant display slot, its alerts, and where it shows on the light bar."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.models import LED_COUNT, GameState, ProviderOutput, normalize_frame
from signalbar.providers.home_assistant import HomeAssistantProvider
from signalbar.settings import SettingsStore
from signalbar.thermal import ThermalProtection


def output(provider, colour):
    return ProviderOutput(provider, normalize_frame([colour] * 17), provider)


GREEN = (0, 200, 0)
HA = output("home-assistant", (255, 0, 0))
EMPTY = ProviderOutput("home-assistant", None, "Home Assistant light is off")
ALERT = output("event:ha", GREEN)
NOTIFICATION = output("event:notification", (40, 40, 40))
LOW = output("controller:low", (200, 0, 0))
LAUNCH = output("launch-artwork:sweep", (90, 0, 90))
PERFORMANCE = output("performance", (0, 120, 0))
NONE = ("none", None)


def choose(**overrides):
    arguments = dict(mode="performance", guard_allows=True, game=GameState(570, "Dota 2"), performance=PERFORMANCE,
                     artwork=PERFORMANCE, idle=ProviderOutput("idle", None, "idle"), home_assistant_base=HA)
    arguments.update(overrides)
    return Arbiter().choose(**arguments)


def shown(decision):
    return decision.provider, decision.frame


class ArbiterTests(unittest.TestCase):
    def test_the_light_shows_only_on_the_routed_display(self):
        self.assertEqual(choose(), PERFORMANCE)
        self.assertEqual(choose(mode="home_assistant"), HA)
        self.assertEqual(choose(mode="home_assistant", event=NOTIFICATION), NOTIFICATION)
        self.assertEqual(choose(mode="home_assistant", launch_artwork=LAUNCH), LAUNCH)
        self.assertEqual(choose(event=ALERT, controller_event=LOW), LOW)
        self.assertEqual(shown(choose(mode="home_assistant", home_assistant_base=EMPTY)), NONE)
        self.assertEqual(choose(mode="home_assistant", recording_marker=True).provider, "home-assistant+recording")


class Tripped(ThermalProtection):
    def update(self, sample, now=None):
        with self._lock:
            self._active = True
        return True


class EngineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.settings = SettingsStore(str(Path(tmp.name) / "settings.json"))
        self.engine = Engine(self.settings, str(Path(tmp.name) / "artwork.json"))
        self.engine.hub.emit = Mock()
        self.engine.home_assistant.attach(True)  # as the bridge does at "drive"

    def alert(self, variant="ha-pulse"):
        return self.engine.trigger_home_assistant_alert(variant, GREEN)

    def test_the_display_is_offered_only_while_the_bridge_drives_the_light_bar(self):
        self.assertIs(self.engine.status()["home_assistant"]["offered"], True)
        self.engine.home_assistant.attach(False)
        self.assertIs(self.engine.status()["home_assistant"]["offered"], False)

    def test_refusals_name_the_reason(self):
        self.assertEqual(self.engine.home_assistant_refusal(), "")
        self.engine.preview_display_preset("moderate", 3.0)
        self.assertEqual(self.engine.home_assistant_refusal(), "a display preset preview is running")
        self.engine.thermal_protection = Tripped()
        self.engine.thermal_protection.update(None)
        self.assertEqual(self.engine.home_assistant_refusal(), "thermal protection is active")
        self.engine.thermal_protection = ThermalProtection()
        self.engine._display_preset_preview_until = 0.0
        self.engine.update_settings({"signalbar_enabled": False})
        self.assertEqual(self.engine.home_assistant_refusal(), "Light bar control is off on the Steam Machine")

    def test_alerts_play_like_steam_events_or_are_dropped_with_a_reason(self):
        self.assertEqual(self.alert("ha-flash"), (True, ""))
        self.engine.hub.emit.assert_called_with("light_event", {
            "kind": "ha", "variant": "ha-flash", "appid": 0, "shown": True, "result": "shown", "reason": ""})
        self.assertEqual(self.alert(), (False, "the previous alert started less than a second ago"))
        self.assertEqual(self.engine.hub.emit.call_args.args[1]["result"], "dropped")
        self.assertEqual(self.alert("ha-strobe"), (False, "not a Home Assistant alert"))
        self.settings.update({"events_enabled": False})
        self.assertEqual(self.alert(), (False, "Light Events are off on the Steam Machine"))
        self.settings.update({"events_enabled": True})
        self.engine.preview_countdown()  # 15 s left
        self.assertEqual(self.alert(), (False, "a playtime countdown is in its last five minutes"))

    def test_the_alerts_switch_and_a_low_controller_drop_alerts(self):
        self.assertEqual(self.alert(), (True, ""))
        self.engine.update_settings({"ha_alerts_enabled": False})
        self.assertIsNone(self.engine.events.output().frame)  # switching alerts off cancels a playing one
        self.assertEqual(self.alert("ha-flash"), (False, "Home Assistant alerts are off on the Steam Machine"))
        self.engine.update_settings({"ha_alerts_enabled": True})
        self.engine.controllers.preview("low", dict(self.settings.all()))
        self.assertEqual(self.alert(), (False, "a controller low-battery alert is showing"))


class SlotTests(unittest.TestCase):
    def setUp(self):
        self.provider = HomeAssistantProvider()
        self.provider.attach(True)

    def test_colour_brightness_and_frames_show_only_while_attached(self):
        self.assertIsNone(self.provider.output().frame)
        frame = tuple((index * 10, 0, 255 - index * 10) for index in range(LED_COUNT))
        self.provider.set_frame(frame)
        self.assertEqual((self.provider.output().provider, self.provider.output().frame), ("home-assistant:frame", frame))
        self.provider.set_light(True, (255, 0, 0), 51)
        self.provider.set_light(False)
        self.provider.set_light(True)  # keeps the last colour and brightness
        self.assertEqual(self.provider.output().frame, ((51, 0, 0),) * LED_COUNT)
        self.provider.set_light(True, (300, -5, 12.6), 999)
        self.assertEqual(self.provider.output().frame, ((255, 0, 13),) * LED_COUNT)
        for bad in (lambda: self.provider.set_light(True, (1, 2, 3), float("nan")),
                    lambda: self.provider.set_frame([(0, 0, 0)] * 16)):
            self.assertRaises(ValueError, bad)
        self.assertEqual(self.provider.output().frame, ((255, 0, 13),) * LED_COUNT)
        self.provider.attach(False)
        self.provider.set_light(True, (255, 0, 0), 200)  # a worker that outlived stop()
        self.assertIsNone(self.provider.output().frame)
        self.assertEqual(self.provider.status(), {"offered": False, "on": False, "source": "",
                                                  "colour": [255, 0, 13], "brightness": 255})


if __name__ == "__main__":
    unittest.main()
