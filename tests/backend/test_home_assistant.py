"""The Home Assistant display slot, its alerts, and who wins the light bar at each tier."""

from __future__ import annotations

import tempfile
import time
import unittest
from contextlib import contextmanager
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
CONNECT = output("controller:connect", (0, 90, 90))
LOW = output("controller:low", (200, 0, 0))
COUNTDOWN = output("countdown", (255, 255, 255))
LAUNCH = output("launch-artwork:sweep", (90, 0, 90))
PERFORMANCE = output("performance", (0, 120, 0))
RED_BAR = HA.frame
NATIVE = normalize_frame([(0, 0, 40)] * 17)
NONE = ("none", None)


def choose(tier=1, **overrides):
    arguments = dict(mode="performance", guard_allows=True, game=GameState(570, "Dota 2"), performance=PERFORMANCE,
                     artwork=PERFORMANCE, idle=ProviderOutput("idle", None, "idle"), home_assistant_base=HA,
                     home_assistant_tier=tier)
    arguments.update(overrides)
    return Arbiter().choose(**arguments)


def shown(decision):
    return decision.provider, decision.frame


class TierArbiterTests(unittest.TestCase):
    def test_watch_only_and_help_out_show_the_light_only_on_the_routed_display(self):
        for tier in (1, 2):
            self.assertEqual(choose(tier), PERFORMANCE, tier)
            self.assertEqual(choose(tier, mode="home_assistant"), HA, tier)
            self.assertEqual(choose(tier, mode="home_assistant", event=NOTIFICATION), NOTIFICATION, tier)
            self.assertEqual(choose(tier, mode="home_assistant", launch_artwork=LAUNCH), LAUNCH, tier)
            self.assertEqual(choose(tier, event=ALERT, controller_event=LOW), LOW, tier)
        self.assertEqual(shown(choose(2, mode="home_assistant", home_assistant_base=EMPTY)), NONE)
        self.assertEqual(choose(2, mode="home_assistant", recording_marker=True).provider, "home-assistant+recording")

    def test_take_the_lead_comes_before_everything_but_the_critical_signals(self):
        for extra in ({"event": NOTIFICATION}, {"controller_event": CONNECT}, {"launch_artwork": LAUNCH},
                      {"signal": COUNTDOWN}, {"companion_hud_active": True}, {"mode": "audio_sync"}):
            self.assertEqual(choose(3, **extra), HA, extra)
        self.assertEqual(choose(3, event=ALERT, home_assistant_base=EMPTY), ALERT)
        self.assertEqual(choose(3, steam_priority=True, event=ALERT).provider, "valve")
        self.assertEqual(choose(3, guard_allows=False).provider, "valve")
        self.assertEqual(choose(3, controller_event=LOW, event=ALERT), LOW)
        self.assertEqual(choose(3, signal=COUNTDOWN, signal_critical=True, event=ALERT), COUNTDOWN)
        self.assertEqual(shown(choose(3, mode="disabled", event=ALERT)), NONE)
        self.assertEqual(choose(3, home_assistant_base=EMPTY, event=NOTIFICATION), NOTIFICATION)  # quiet: as usual

    def test_in_control_hands_a_quiet_bar_to_steam(self):
        self.assertEqual(choose(4, signal=COUNTDOWN), HA)
        self.assertEqual(choose(4, controller_event=CONNECT), HA)
        self.assertEqual(choose(4, controller_event=LOW), LOW)
        self.assertEqual(choose(4, steam_priority=True).provider, "valve")
        for extra in ({}, {"event": NOTIFICATION}, {"launch_artwork": LAUNCH}, {"mode": "home_assistant"}):
            self.assertEqual(shown(choose(4, home_assistant_base=EMPTY, **extra)), NONE, extra)
        self.assertEqual(choose(4, home_assistant_base=EMPTY, signal=COUNTDOWN, signal_critical=True), COUNTDOWN)

    def test_full_control_yields_only_to_steams_own_animations_and_light_bar_control_off(self):
        critical = dict(guard_allows=False, controller_event=LOW, signal=COUNTDOWN, signal_critical=True)
        self.assertEqual(choose(5, **critical), HA)
        self.assertEqual(choose(5, event=ALERT, **critical), ALERT)
        for extra in ({}, {"event": ALERT}, {"home_assistant_base": EMPTY}):
            self.assertEqual(choose(5, steam_priority=True, **extra).reason, "Steam system priority", extra)
        for extra in ({"controller_event": LOW}, {"signal": COUNTDOWN, "signal_critical": True}):
            self.assertEqual(shown(choose(5, home_assistant_base=EMPTY, **extra)), NONE, extra)
        self.assertEqual(shown(choose(5, mode="disabled", event=ALERT)), NONE)


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
        self.engine.home_assistant.attach(True)  # as the bridge does above Watch only

    def alert(self, variant="ha-pulse"):
        return self.engine.trigger_home_assistant_alert(variant, GREEN)

    def test_the_tier_starts_at_watch_only_and_the_display_is_offered_at_help_out_only(self):
        self.assertEqual(self.engine.home_assistant_tier(), 1)
        for bad in (0, 6):
            with self.assertRaises(ValueError):
                self.engine.set_home_assistant_tier(bad)
        for tier in (1, 2, 3, 4, 5):
            self.engine.set_home_assistant_tier(tier)
            self.assertIs(self.engine.status()["home_assistant"]["offered"], tier == 2, tier)

    def test_refusals_at_each_tier(self):
        self.assertEqual(self.engine.home_assistant_refusal(), "")
        self.engine.preview_display_preset("moderate", 3.0)
        self.assertEqual(self.engine.home_assistant_refusal(), "a display preset preview is running")
        self.engine.thermal_protection = Tripped()
        self.engine.thermal_protection.update(None)
        for tier, refusal in ((2, "thermal protection is active"), (3, "thermal protection is active"),
                              (4, "thermal protection is active"), (5, "")):
            self.engine.set_home_assistant_tier(tier)
            self.assertEqual(self.engine.home_assistant_refusal(), refusal, tier)
        self.engine.thermal_protection = ThermalProtection()
        self.engine._display_preset_preview_until = 0.0
        self.engine.update_settings({"signalbar_enabled": False})
        for tier in (2, 5):
            self.engine.set_home_assistant_tier(tier)
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

    def test_full_control_alerts_ignore_the_critical_signals_but_not_the_alerts_switch(self):
        self.engine.preview_countdown()
        self.engine.controllers.preview("low", dict(self.settings.all()))
        self.engine.set_home_assistant_tier(4)
        self.assertEqual(self.alert(), (False, "a controller low-battery alert is showing"))
        self.engine.set_home_assistant_tier(5)
        self.assertEqual(self.alert(), (True, ""))
        self.engine.update_settings({"ha_alerts_enabled": False})
        self.assertIsNone(self.engine.events.output().frame)  # switching alerts off cancels a playing one
        self.assertEqual(self.alert("ha-flash"), (False, "Home Assistant alerts are off on the Steam Machine"))

    def alert_survives_a_low_controller(self, tier):
        self.engine.set_home_assistant_tier(tier)
        battery = {"id": "one", "name": "one", "percent": 74, "level": None, "charging": False}
        self.engine.update_controllers([battery])
        self.assertEqual(self.alert(), (True, ""))
        self.engine.update_controllers([{**battery, "percent": 10}])
        self.assertEqual(self.engine.controllers.event_output().provider, "controller:low")
        return self.engine.events.holds("ha")

    def test_a_low_controller_cuts_an_alert_short_below_full_control(self):
        self.assertFalse(self.alert_survives_a_low_controller(4))

    def test_a_low_controller_leaves_an_alert_alone_at_full_control(self):
        self.assertTrue(self.alert_survives_a_low_controller(5))


class LoopHardware:
    device_path = "/fake/valve-leds"
    reverse = False

    def __init__(self):
        self.frame = NATIVE
        self.writes = 0

    def set_reverse(self, reverse):
        pass

    def read_frame(self):
        return self.frame

    def read_signature(self):
        return self.frame

    def write_frame(self, frame):
        self.writes += 1
        self.frame = normalize_frame(frame)

    def try_restore(self, frame):
        self.write_frame(frame)


class EngineLoopTests(unittest.TestCase):
    @staticmethod
    def wait_until(predicate, timeout=4.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(.02)
        return predicate()

    @contextmanager
    def running(self, tier, **settings):
        with tempfile.TemporaryDirectory() as folder:
            hardware = LoopHardware()
            store = SettingsStore(str(Path(folder) / "settings.json"))
            store.update({"home_display": "blackout", "guard_stable_s": .5, **settings})
            engine = Engine(store, str(Path(folder) / "artwork.json"), hardware_factory=lambda: hardware)
            engine.home_assistant.attach(True)
            engine.set_home_assistant_tier(tier)
            engine.start()
            try:
                yield engine, hardware
            finally:
                engine.stop()

    def provider(self, engine, name):
        return self.wait_until(lambda: engine.status()["provider"] == name)

    def test_full_control_keeps_the_bar_through_thermal_protection(self):
        with self.running(5) as (engine, hardware):
            engine.thermal_protection = Tripped()
            engine.home_assistant.set_light(True, (255, 0, 0))
            self.assertTrue(self.provider(engine, "home-assistant"))
            self.assertTrue(engine.status()["thermal_protection"]["active"])  # still reported
            engine.set_home_assistant_tier(4)
            self.assertTrue(self.provider(engine, "thermal-protection"))

    def test_full_control_never_writes_over_a_steam_download(self):
        with self.running(5) as (engine, hardware):
            engine.home_assistant.set_light(True, (255, 0, 0))
            self.assertTrue(self.wait_until(lambda: hardware.frame == RED_BAR))
            engine.set_steam_activity(True, "Steam download activity")
            self.assertTrue(self.provider(engine, "valve"))
            time.sleep(.2)
            before = hardware.writes
            for step in range(20):  # Steam's download animation writes the bar over and over
                hardware.frame = normalize_frame([(0, 10 + step * 10, 0)] * 17)
                time.sleep(.05)
            self.assertEqual((hardware.writes, engine.status()["provider"]), (before, "valve"))
            engine.set_steam_activity(False)
            self.assertTrue(self.wait_until(lambda: hardware.frame == RED_BAR))


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
