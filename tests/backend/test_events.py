from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.integration import LightEventLease, StripMineClaimReader
from signalbar.models import GameState, ProviderOutput, normalize_frame
from signalbar.providers.events import DURATIONS, VARIANT_DURATIONS, EventProvider, RED, event_frame
from signalbar.settings import SettingsStore


BLACK = normalize_frame([(0, 0, 0)] * 17)
BASE = normalize_frame([(10, 20, 30)] * 17)
NATIVE = normalize_frame([(0, 0, 40)] * 17)


class LoopHardware:
    device_path = "/fake/valve-leds"
    reverse = False

    def __init__(self):
        self.frame = NATIVE

    def set_reverse(self, reverse):
        self.reverse = bool(reverse)

    def read_frame(self):
        return self.frame

    def read_signature(self):
        return self.frame

    def write_frame(self, frame):
        self.frame = normalize_frame(frame)

    def try_restore(self, frame):
        self.write_frame(frame)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RecordingLease:
    def __init__(self):
        self.refreshes = []
        self.releases = 0

    def refresh(self, event="", purpose="light-event"):
        self.refreshes.append((event, purpose))
        return True

    def acknowledged(self):
        return True

    def release(self):
        self.releases += 1


class RecordingStripMineClaim:
    def __init__(self):
        self.enabled = True
        self.acknowledgements = []

    def active(self):
        return self.enabled

    def acknowledge(self, priority, provider=""):
        self.acknowledgements.append((priority, provider))
        return True

    def release(self):
        self.enabled = False


class OrderedStripMineClaim(RecordingStripMineClaim):
    def __init__(self, hardware):
        super().__init__()
        self.enabled = False
        self.hardware = hardware
        self.frames_at_acknowledgement = []

    def acknowledge(self, priority, provider=""):
        self.frames_at_acknowledgement.append(self.hardware.frame)
        return super().acknowledge(priority, provider)


class EventTests(unittest.TestCase):
    def test_every_mockup_variant_is_a_bounded_seventeen_led_animation(self):
        for variant, duration in VARIANT_DURATIONS.items():
            kind = variant if variant.startswith("record-") else variant.split("-", 1)[0]
            with self.subTest(variant=variant):
                lit = False
                for step in range(1, 20):
                    frame = event_frame(kind, duration * step / 20, variant)
                    self.assertEqual(len(frame), 17)
                    self.assertTrue(all(0 <= channel <= 255 for pixel in frame for channel in pixel))
                    lit |= any(pixel != (0, 0, 0) for pixel in frame)
                self.assertTrue(lit)
                if kind != "record-start":
                    self.assertEqual(event_frame(kind, duration, variant), BLACK)

    def test_selected_variants_persist_and_preview_does_not_change_preference(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "settings.json")
            settings = SettingsStore(path)
            settings.update({"event_notification_variant": "notification-ample",
                             "event_achievement_variant": "achievement-supernova",
                             "event_screenshot_variant": "screenshot-ripple"})
            restored = SettingsStore(path)
            self.assertEqual(restored.all()["event_notification_variant"], "notification-ample")
            clock = Clock()
            provider = EventProvider(clock=clock)
            provider.set_variants(restored.all())
            self.assertTrue(provider.trigger("notification"))
            self.assertEqual(provider.status()["variant"], "notification-ample")
            provider.clear_transients()
            self.assertTrue(provider.trigger("notification", preview=True, variant="notification-return"))
            self.assertEqual(provider.status()["variant"], "notification-return")
            provider.clear_transients()
            clock.advance(.81)
            self.assertTrue(provider.trigger("notification"))
            self.assertEqual(provider.status()["variant"], "notification-ample")
            self.assertFalse(provider.trigger("notification", preview=True, variant="achievement-supernova"))

    def test_invalid_persisted_variant_falls_back_without_corrupting_other_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = SettingsStore(str(Path(temp) / "settings.json"))
            result = settings.update({"event_notification_variant": ["bad"],
                                      "event_achievement_variant": "achievement-supernova"})
            self.assertEqual(result["event_notification_variant"], "notification-beacon")
            self.assertEqual(result["event_achievement_variant"], "achievement-supernova")

    def test_queued_event_keeps_variant_selected_at_trigger_time(self):
        clock = Clock()
        provider = EventProvider(clock=clock)
        provider.set_variants({"event_notification_variant": "notification-return"})
        provider.trigger("achievement")
        provider.trigger("notification")
        provider.set_variants({"event_notification_variant": "notification-double"})
        clock.advance(DURATIONS["achievement"] + .01)
        self.assertEqual(provider.status()["variant"], "notification-return")

    def test_notification_crosses_all_seventeen_positions(self):
        early = event_frame("notification", .15)
        late = event_frame("notification", 1.25)
        self.assertGreater(max(range(17), key=lambda i: sum(early[i])), 12)
        self.assertLess(max(range(17), key=lambda i: sum(late[i])), 4)
        self.assertEqual(len(early), 17)

    def test_achievement_builds_before_sweeping_and_fills_bar(self):
        build = event_frame("achievement", .35)
        sweep = event_frame("achievement", 1.4)
        finale = event_frame("achievement", 2.15)
        self.assertNotEqual(build[8], (0, 0, 0))
        self.assertEqual(build[0], (0, 0, 0))
        self.assertGreater(sum(pixel != (0, 0, 0) for pixel in sweep), 5)
        self.assertEqual(sum(pixel != (0, 0, 0) for pixel in finale), 17)
        self.assertEqual(event_frame("achievement", 2.7), BLACK)

    def test_screenshot_and_recording_patterns_are_17_pixel_frames(self):
        shutter = event_frame("screenshot", .1)
        self.assertNotEqual(shutter[0], (0, 0, 0))
        self.assertNotEqual(shutter[16], (0, 0, 0))
        self.assertNotEqual(event_frame("record-start", 1.1)[8], (0, 0, 0))
        self.assertNotEqual(event_frame("record-stop", .1)[8], (0, 0, 0))

    def test_event_provider_deduplicates_queues_and_restores_base(self):
        clock = Clock()
        provider = EventProvider(clock=clock)
        self.assertTrue(provider.trigger("notification"))
        self.assertFalse(provider.trigger("notification"))
        self.assertTrue(provider.trigger("achievement"))
        self.assertEqual(provider.output().provider, "event:notification")
        clock.advance(1.41)
        self.assertEqual(provider.output().provider, "event:achievement")
        clock.advance(2.71)
        self.assertIsNone(provider.output().frame)

    def test_finished_animation_returns_current_not_frozen_countdown_frame(self):
        clock = Clock()
        provider = EventProvider(clock=clock)
        arbiter = Arbiter()
        provider.trigger("notification")
        def choose(timer_frame):
            return arbiter.choose(
                mode="artwork", guard_allows=True, game=GameState(42, "Test"),
                performance=ProviderOutput("performance", BASE, ""),
                artwork=ProviderOutput("artwork", BASE, ""),
                idle=ProviderOutput("idle", None, ""),
                signal=ProviderOutput("countdown", timer_frame, ""),
                event=provider.output(),
            )
        self.assertEqual(choose(BASE).provider, "event:notification")
        clock.advance(1.41)
        updated_timer = normalize_frame([(40, 0, 0)] * 9 + [(0, 0, 0)] * 8)
        result = choose(updated_timer)
        self.assertEqual(result.provider, "countdown")
        self.assertEqual(result.frame, updated_timer)

    def test_recording_state_is_not_changed_by_previews(self):
        provider = EventProvider(clock=Clock())
        provider.trigger("record-start", preview=True)
        self.assertFalse(provider.recording)
        provider.trigger("record-start")
        self.assertTrue(provider.recording)
        provider.trigger("record-stop")
        self.assertFalse(provider.recording)

    def test_arbiter_events_preempt_stable_native_state_even_without_a_game(self):
        arbiter = Arbiter()
        game = GameState(42, "Test")
        base = ProviderOutput("artwork", BASE, "artwork")
        event = ProviderOutput("event:achievement", event_frame("achievement", 2.1), "achievement")
        timer = ProviderOutput("countdown", BASE, "timer")
        kwargs = dict(game=game, performance=base, artwork=base,
                      idle=ProviderOutput("idle", None, ""), signal=timer, event=event)
        self.assertEqual(arbiter.choose(mode="artwork", guard_allows=True, **kwargs).provider,
                         "event:achievement")
        self.assertEqual(arbiter.choose(mode="artwork", guard_allows=True,
                                        signal_critical=True, **kwargs).provider, "countdown")
        self.assertEqual(arbiter.choose(mode="disabled", guard_allows=True, **kwargs).provider, "none")
        self.assertEqual(arbiter.choose(mode="events", guard_allows=False, **kwargs).provider,
                         "event:achievement")
        self.assertEqual(arbiter.choose(mode="artwork", guard_allows=False, **kwargs).provider,
                         "event:achievement")
        self.assertEqual(arbiter.choose(mode="artwork", guard_allows=False,
                                        game=GameState(), **{k: v for k, v in kwargs.items() if k != "game"}).provider,
                         "event:achievement")
        without_event = {**kwargs, "event": ProviderOutput("event", None, "")}
        events_only = arbiter.choose(mode="events", guard_allows=True, **without_event)
        self.assertEqual(events_only.provider, "countdown")
        without_timer = {**without_event, "signal": ProviderOutput("countdown", None, "")}
        events_only_idle = arbiter.choose(mode="events", guard_allows=True, **without_timer)
        self.assertEqual(events_only_idle.provider, "none")
        self.assertIsNone(events_only_idle.frame)
        self.assertEqual(arbiter.choose(mode="artwork", guard_allows=False, **without_event).provider,
                         "valve")
        self.assertEqual(arbiter.choose(mode="artwork", guard_allows=True, **without_event).provider,
                         "countdown")
        marked = arbiter.choose(mode="artwork", guard_allows=True,
                                recording_marker=True, **without_timer)
        self.assertEqual(marked.frame[8], RED)
        self.assertEqual(marked.frame[7], BASE[7])
        isolated = arbiter.choose(
            mode="artwork", guard_allows=True, recording_marker=True,
            recording_marker_isolation=True, **without_timer,
        )
        self.assertEqual(isolated.frame[8], RED)
        self.assertEqual(isolated.frame[7], (0, 0, 0))
        self.assertEqual(isolated.frame[9], (0, 0, 0))
        self.assertEqual(isolated.frame[6], BASE[6])
        event_with_marker = arbiter.choose(
            mode="artwork", guard_allows=True, recording_marker=True,
            recording_marker_isolation=True, **kwargs,
        )
        self.assertEqual(event_with_marker.provider, "event:achievement")
        self.assertEqual(event_with_marker.frame, event.frame)
        countdown_with_marker = arbiter.choose(
            mode="artwork", guard_allows=True, signal_critical=True,
            recording_marker=True, recording_marker_isolation=True, **kwargs,
        )
        self.assertEqual(countdown_with_marker.provider, "countdown")
        self.assertEqual(countdown_with_marker.frame, timer.frame)

    def test_engine_settings_game_exit_and_preview_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            engine.set_game(42, "Test")
            engine.update_settings({"events_enabled": False})
            self.assertFalse(engine.trigger_event("achievement"))
            engine.update_settings({"events_enabled": True})
            self.assertTrue(engine.trigger_event("achievement"))
            engine.update_settings({"event_achievements_enabled": False})
            self.assertFalse(engine.trigger_event("achievement"))
            self.assertFalse(engine.events.status()["active"])
            self.assertTrue(engine.trigger_event("achievement", preview=True))
            engine.set_game(0, "")
            self.assertTrue(engine.events.status()["active"])
            self.assertTrue(engine.trigger_event("screenshot"))
            self.assertTrue(engine.trigger_event("record-start"))

    def test_engine_uses_saved_animation_and_preview_can_override_it(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"events_enabled": True,
                             "event_notification_variant": "notification-ample"})
            engine = Engine(settings, str(Path(folder) / "artwork.json"))
            self.assertTrue(engine.trigger_event("notification"))
            self.assertEqual(engine.status()["events"]["variant"], "notification-ample")
            self.assertTrue(engine.trigger_event("notification", preview=True,
                                                 variant="notification-beacon"))
            self.assertEqual(engine.status()["events"]["variant"], "notification-beacon")
            self.assertEqual(settings.all()["event_notification_variant"], "notification-ample")

    def test_event_over_native_frame_restores_it_after_expiry(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(DURATIONS, {"notification": .3}):
            hardware = LoopHardware()
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"),
                            hardware_factory=lambda: hardware)
            engine.update_settings({"mode": "artwork", "events_enabled": True,
                                    "event_notification_variant": "notification-original", "performance_always": False,
                                    "controller_battery_display": "off",
                                    "valve_ownership_policy": "cooperative"})
            engine.start()
            try:
                self.assertTrue(self._wait_until(
                    lambda: engine.status()["debug"]["guard_state"] == "ready", timeout=3.0,
                ))
                self.assertTrue(engine.trigger_event("notification"))
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "event:notification"))
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "valve"))
                self.assertEqual(hardware.frame, NATIVE)
            finally:
                engine.stop()

    def test_light_event_lease_wraps_the_physical_takeover(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(DURATIONS, {"notification": .3}):
            hardware = LoopHardware()
            lease = RecordingLease()
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"mode": "events", "events_enabled": True,
                             "event_notification_variant": "notification-original",
                             "controller_battery_display": "off", "weather_display": "off"})
            engine = Engine(settings, str(Path(folder) / "artwork.json"),
                            hardware_factory=lambda: hardware, event_lease=lease)
            engine.start()
            try:
                self.assertTrue(self._wait_until(
                    lambda: engine.status()["debug"]["guard_state"] == "ready", timeout=3.0,
                ))
                self.assertTrue(engine.trigger_event("notification"))
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "event:notification"))
                self.assertTrue(lease.refreshes)
                self.assertTrue(self._wait_until(
                    lambda: engine.status()["provider"] in {"none", "valve"}
                ))
                self.assertGreater(lease.releases, 0)
                self.assertEqual(hardware.frame, NATIVE)
            finally:
                engine.stop()

    def test_light_event_lease_file_is_atomic_bounded_and_owner_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "signalbar-light-event.json"
            clock = Clock()
            lease = LightEventLease(path, clock=clock, ttl_s=.5)
            self.assertTrue(lease.refresh("event:achievement"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], "SignalBar")
            self.assertEqual(payload["purpose"], "light-event")
            self.assertGreater(payload["expires_at"], clock())
            ack = {
                "protocol": 1, "owner": "StripMine", "token": payload["token"],
                "expires_at": payload["expires_at"],
            }
            lease.ack_path.write_text(json.dumps(ack), encoding="utf-8")
            self.assertTrue(lease.acknowledged())
            lease.release()
            self.assertFalse(path.exists())
            self.assertFalse(lease.ack_path.exists())

    def test_stripmine_claim_is_owner_scoped_and_acknowledges_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stripmine-led-claim.json"
            clock = Clock()
            reader = StripMineClaimReader(path, clock=clock)
            path.write_text(json.dumps({
                "protocol": 1, "owner": "StripMine", "purpose": "continuous-game",
                "token": "mine-1", "expires_at": 110.0,
            }), encoding="utf-8")
            self.assertTrue(reader.active())
            self.assertTrue(reader.acknowledge("signalbar", "weather:cloud"))
            acknowledgement = json.loads(reader.ack_path.read_text(encoding="utf-8"))
            self.assertEqual(acknowledgement["token"], "mine-1")
            self.assertEqual(acknowledgement["priority"], "signalbar")
            self.assertEqual(acknowledgement["provider"], "weather:cloud")
            clock.advance(11)
            self.assertFalse(reader.active())

    def test_configured_provider_priority_transfers_without_guard_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            hardware = LoopHardware()
            lease = RecordingLease()
            claim = RecordingStripMineClaim()
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"guard_stable_s": .5})
            engine = Engine(settings, str(Path(folder) / "artwork.json"),
                            hardware_factory=lambda: hardware, event_lease=lease,
                            stripmine_claim=claim)
            engine.arbiter.choose = lambda **_kwargs: ProviderOutput("performance", BASE, "test")
            engine.start()
            try:
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "companion:stripmine"))
                self.assertEqual(hardware.frame, NATIVE)
                self.assertIn(("stripmine", "performance"), claim.acknowledgements)
                engine.update_settings({"stripmine_priority_performance": "signalbar"})
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "performance"))
                self.assertEqual(hardware.frame, BASE)
                self.assertIn(("signalbar", "performance"), claim.acknowledgements)
                self.assertTrue(any(purpose == "priority-output" for _provider, purpose in lease.refreshes))
            finally:
                engine.stop()

    def test_stripmine_priority_is_acknowledged_only_after_signalbar_restores(self):
        with tempfile.TemporaryDirectory() as folder:
            hardware = LoopHardware()
            claim = OrderedStripMineClaim(hardware)
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"guard_stable_s": .5})
            engine = Engine(settings, str(Path(folder) / "artwork.json"),
                            hardware_factory=lambda: hardware, stripmine_claim=claim)
            engine.arbiter.choose = lambda **_kwargs: ProviderOutput("performance", BASE, "test")
            engine.start()
            try:
                self.assertTrue(self._wait_until(lambda: hardware.frame == BASE))
                claim.enabled = True
                self.assertTrue(self._wait_until(
                    lambda: engine.status()["provider"] == "companion:stripmine"
                ))
                self.assertTrue(claim.frames_at_acknowledgement)
                self.assertEqual(claim.frames_at_acknowledgement[-1], NATIVE)
                self.assertEqual(hardware.frame, NATIVE)
            finally:
                engine.stop()

    def test_empty_signals_only_display_yields_to_active_stripmine(self):
        with tempfile.TemporaryDirectory() as folder:
            hardware = LoopHardware()
            claim = RecordingStripMineClaim()
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            settings.update({"mode": "events", "controller_battery_display": "off",
                             "weather_display": "off", "guard_stable_s": .5})
            engine = Engine(settings, str(Path(folder) / "artwork.json"),
                            hardware_factory=lambda: hardware, stripmine_claim=claim)
            engine.start()
            try:
                self.assertTrue(self._wait_until(
                    lambda: engine.status()["provider"] == "companion:stripmine"
                ))
                self.assertIn(("stripmine", "none"), claim.acknowledgements)
                self.assertEqual(hardware.frame, NATIVE)
            finally:
                engine.stop()

    def test_new_native_write_interrupts_event_without_restoring_stale_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            hardware = LoopHardware()
            settings = SettingsStore(str(Path(folder) / "settings.json"))
            engine = Engine(settings, str(Path(folder) / "artwork.json"),
                            hardware_factory=lambda: hardware)
            engine.update_settings({"events_enabled": True,
                                    "valve_ownership_policy": "cooperative"})
            engine.start()
            try:
                self.assertTrue(self._wait_until(
                    lambda: engine.status()["debug"]["guard_state"] == "ready", timeout=3.0,
                ))
                self.assertTrue(engine.trigger_event("notification"))
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "event:notification"))
                external = normalize_frame([(4, 5, 6)] * 17)
                hardware.write_frame(external)
                self.assertTrue(self._wait_until(lambda: engine.status()["provider"] == "valve"))
                self.assertEqual(hardware.frame, external)
                self.assertFalse(engine.events.status()["active"])
            finally:
                engine.stop()

    @staticmethod
    def _wait_until(predicate, timeout=1.5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(.01)
        return False

    def test_event_defaults_and_category_choices_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "settings.json")
            settings = SettingsStore(path)
            self.assertTrue(settings.all()["events_enabled"])
            settings.update({"events_enabled": True, "event_screenshots_enabled": False})
            restored = SettingsStore(path)
            self.assertTrue(restored.all()["events_enabled"])
            self.assertFalse(restored.all()["event_screenshots_enabled"])

            settings.update({"recording_marker_isolation": True})
            restored = SettingsStore(path)
            self.assertTrue(restored.all()["recording_marker_isolation"])

    def test_engine_drops_events_during_critical_countdown_but_tracks_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(SettingsStore(str(Path(folder) / "settings.json")),
                            str(Path(folder) / "artwork.json"))
            engine.set_game(42, "Test")
            engine.update_settings({"events_enabled": True})
            engine.countdown.start("free", 240, label="Free timer")
            self.assertFalse(engine.trigger_event("achievement"))
            self.assertFalse(engine.trigger_event("notification", preview=True))
            self.assertFalse(engine.events.status()["active"])
            self.assertFalse(engine.trigger_event("record-start"))
            self.assertTrue(engine.events.recording)
            self.assertFalse(engine.events.status()["active"])
            engine.set_game(0, "")
            self.assertFalse(engine.events.recording)

    def test_recording_capture_state_survives_disabled_visual_events(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = Engine(SettingsStore(str(Path(folder) / "settings.json")),
                            str(Path(folder) / "artwork.json"))
            engine.update_settings({"events_enabled": False, "event_recording_enabled": False})
            self.assertFalse(engine.trigger_event("record-start"))
            self.assertTrue(engine.events.recording)
            self.assertFalse(engine.events.status()["active"])
            self.assertFalse(engine.trigger_event("record-stop"))
            self.assertFalse(engine.events.recording)


if __name__ == "__main__":
    unittest.main()
