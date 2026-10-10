from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from signalbar.backend import Engine
from signalbar.mqtt.policy import PublishingPolicy
from signalbar.mqtt.snapshot import (
    NOISY_KEYS, STATUS_KEY_LIMIT, UPDATE_NOT_PUBLISHED, build_snapshot, flatten_status, frontend_connected,
    is_redacted, is_volatile,
)
from signalbar.settings import SettingsStore
from signalbar.updates import UpdateManager

FACTS = {"started_at": "2026-09-14T01:00:00+00:00", "session_minutes": 12.5, "download_active": False,
         "events_dropped": 0, "frontend_connected": True}
FACEPLATE = {"phase": "running", "connected": True, "lifetime_uploads": 42,
             "settings": {"mode": "artwork", "image_path": "/home/deck/private.png"}}
UPDATE = {"installed_version": "1.4.0", "available_version": "1.4.1", "phase": "available",
          "confirmation_token": "tok", "private_user_code": "code"}


def status(**overrides):
    base = {
        "version": "1.4.0", "owner": "GabeCubeAura", "signalbar_enabled": True,
        "game": {"appid": 335300, "title": "DARK SOULS™ II"},
        "artwork": {"dominant_colors": [[10, 20, 30]], "colors": [[1, 2, 3]] * 17},
        "screen_sync": {"runtime_dir": "/run/user/1000", "stderr_tail": "secret-ish"},
        "performance": {"cpu_load": 41.4, "gpu_load": 76.6, "cpu_temperature": 61.26, "gpu_temperature": 70.74},
        "controllers": {"controllers": [{"id": "steam:1", "name": "Controller", "percent": 64, "level": None}]},
        "countdown": {"active": True, "source": "parental", "remaining_seconds": 1800, "total_seconds": 3600},
        "weather": {"location": {"name": "Kingston", "latitude": 35.8, "longitude": -84.5}},
        "debug": {"frontend_heartbeat_age_s": 1.2},
    }
    base.update(overrides)
    return base


class SnapshotTests(unittest.TestCase):
    def test_headline_areas(self):
        snap = build_snapshot(status(), FACEPLATE, UPDATE, FACTS)
        self.assertEqual((snap["game"]["appid"], snap["game"]["session_minutes"]), (335300, 12.5))
        self.assertTrue(snap["game"]["key_art_url"].endswith("/steam/apps/335300/library_hero.jpg"))
        self.assertEqual(snap["countdown"]["remaining_minutes"], 30.0)
        self.assertEqual(snap["update"], {"installed_version": "1.4.0", "available_version": "1.4.1",
                                          "phase": "available"})
        self.assertEqual(snap["status"]["faceplate.lifetime_uploads"], 42)  # counters stay out of attributes
        self.assertNotIn("lifetime_uploads", snap["faceplate"])
        self.assertEqual((snap["performance"]["cpu_load"], snap["performance"]["cpu_temperature"]), (41, 61.5))

    def test_private_fields_never_appear_at_any_depth(self):
        odd = status(faceplate_image_path="/h/x.png", a={"weather_latitude": 1, "api_token": "t0k",
                                                          "Wifi_Password": "pw"},
                     items=[{"image_path": "/h/y.png", "secret_note": "s"}])
        text = json.dumps(build_snapshot(odd, FACEPLATE, UPDATE, FACTS))
        for forbidden in ("latitude", "longitude", "private.png", "confirmation_token", "private_user_code",
                          "stderr_tail", "/run/user", "/h/x.png", "t0k", "Wifi_Password", "secret_note"):
            self.assertNotIn(forbidden, text)
        self.assertFalse(any(is_redacted(key) for key in flatten_status(odd)))

    def test_paths_in_error_text_and_private_lab_release_notes_never_go_out(self):
        flat = build_snapshot(status(
            performance={"error": "open /dev/input/by-path/pci-0000:00:14.0-usb-0:1:1.0-event: busy"},
            weather={"error": "HTTP 503 from https://api.open-meteo.com/v1/forecast"}), None, None, FACTS)["status"]
        self.assertEqual(flat["performance.error"], "open <path>: busy")
        self.assertEqual(flat["weather.error"], "HTTP 503 from https://api.open-meteo.com/v1/forecast")
        for channel, published in (("stable", True), ("private", False)):
            update = {**UPDATE, "channel": channel, "release_notes": "Lab build for the rig"}
            text = json.dumps(build_snapshot(status(), None, update, FACTS))
            self.assertEqual("Lab build" in text, published, channel)

    def test_odd_inputs_never_raise_and_stay_valid_json(self):
        snap = build_snapshot({}, None, None, {})
        self.assertEqual((snap["game"]["appid"], snap["controllers"]["count"], snap["update"]["phase"]), (0, 0, None))
        snap = build_snapshot(status(game={"appid": "abc"}, controllers={"controllers": "nope"},
                                     countdown={"active": True, "remaining_seconds": float("nan")}),
                              ["bad"], "bad", {"events_dropped": float("inf")})
        json.dumps(snap, allow_nan=False)
        self.assertEqual((snap["game"]["appid"], snap["countdown"]["remaining_minutes"]), (0, 0.0))
        self.assertFalse(frontend_connected(status(debug={"frontend_heartbeat_age_s": 30})))

    def test_status_is_capped_in_keys_text_and_depth(self):
        self.assertEqual(len(flatten_status({"k%d" % i: i for i in range(500)}, limit=50)), 50)
        flat = flatten_status({"s": "x" * 1000, "l": ["y" * 1000]})
        self.assertEqual((len(flat["s"]), len(flat["l"][0])), (256, 256))
        deep = node = {}
        for _ in range(5000):
            node["n"] = node = {}
        self.assertEqual(flatten_status(deep), {})
        cyclic = {}
        cyclic["me"] = cyclic
        self.assertEqual(flatten_status(cyclic), {})
        last_error = build_snapshot(status(), None, None, {**FACTS, "last_error": "x" * 400})["bridge"]["last_error"]
        self.assertEqual(len(last_error), 256)
        with tempfile.TemporaryDirectory() as directory:
            real = Engine(SettingsStore(str(Path(directory) / "config.json")), str(Path(directory) / "a.json")).status()
        self.assertLess(len(flatten_status(real)), 400)
        self.assertLess(len(json.dumps(flatten_status(real))), 16_000)


class ReportEverythingTests(unittest.TestCase):
    """Every field GabeCubeAura reports reaches Home Assistant unless snapshot.py says why not."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        store = SettingsStore(str(Path(tmp.name) / "config.json"))
        engine = Engine(store, str(Path(tmp.name) / "art.json"))
        engine.set_game(570, "Dota 2")
        engine.update_controllers([{"id": "one", "name": "Controller", "percent": 64, "level": None,
                                    "charging": False}])
        cls.engine_status = engine.status()
        cls.update_status = UpdateManager("1.4.0", store, str(Path(tmp.name) / "runtime"), tmp.name, None).status()
        cls.snapshot = build_snapshot(cls.engine_status, None, cls.update_status, {"frontend_connected": True})

    @staticmethod
    def leaves(value, prefix=""):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from ReportEverythingTests.leaves(child, f"{prefix}.{key}" if prefix else str(key))
        else:
            yield prefix, value

    def test_every_engine_and_update_field_is_published_or_left_out_on_purpose(self):
        status = self.snapshot["status"]
        self.assertLess(len(status), STATUS_KEY_LIMIT)  # at the cap later fields would be cut off
        missing = []
        for path, value in self.leaves(self.engine_status):
            if path in status or any(is_redacted(p) or p in NOISY_KEYS or is_volatile(p) for p in path.split(".")):
                continue
            if path == "controllers.controllers":
                sent = self.snapshot["controllers"]["controllers"]
                self.assertEqual(len(sent), len(value))
                missing += [f"{path}[].{key}" for key in value[0] if not is_redacted(key) and key not in sent[0]]
                continue
            missing.append(path)
        missing += [f"update.{key}" for key in self.update_status
                    if key not in self.snapshot["update"] and f"update.{key}" not in status
                    and not is_redacted(key) and key not in UPDATE_NOT_PUBLISHED]
        self.assertEqual(missing, [], "publish these in snapshot.py or leave them out there with a reason")
        self.assertEqual(sorted(set(UPDATE_NOT_PUBLISHED) - set(self.update_status)), [])

    def test_a_new_settings_key_is_reported_without_any_work(self):
        engine_status = {**self.engine_status, "future_setting_speed": 3}
        snapshot = build_snapshot(engine_status, None, self.update_status, {"frontend_connected": True})
        self.assertEqual(snapshot["status"]["future_setting_speed"], 3)


def perf(cpu=20, cpu_t=50.0, thermal=False):
    return {"cpu_load": cpu, "gpu_load": 30, "cpu_temperature": cpu_t, "gpu_temperature": 55.0,
            "thermal_protection": thermal}


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PublishingPolicy()

    def offer(self, area, payload, now, turbo=False):
        """Shape, ask and record as the bridge does; return what was published, or None."""
        shaped = self.policy.shape(area, payload, turbo)
        text = json.dumps(shaped, sort_keys=True)
        if not self.policy.due(area, shaped, text, now, turbo):
            return None
        self.policy.published(area, shaped, text, now)
        return shaped

    def test_performance_waits_for_its_deadband_and_30_seconds(self):
        self.assertIsNotNone(self.offer("performance", perf(), 0.0))
        for tick in range(1, 100):
            self.assertIsNone(self.offer("performance", perf(cpu=20 + tick % 5, cpu_t=50.0 + (tick % 4) / 2),
                                         float(tick)), tick)
        self.policy.reset()
        self.offer("performance", perf(), 0.0)
        self.assertIsNone(self.offer("performance", perf(cpu=25), 29.9))
        self.assertIsNotNone(self.offer("performance", perf(cpu=25), 30.0))
        self.assertIsNone(self.offer("performance", perf(cpu=29), 70.0))  # from the new reference
        self.assertIsNotNone(self.offer("performance", perf(cpu=29, cpu_t=52.0), 71.0))
        self.assertIsNotNone(self.offer("performance", perf(cpu=29, cpu_t=52.0, thermal=True), 71.5))

    def test_other_areas_have_their_own_cadence(self):
        shaped = self.offer("countdown", {"active": True, "source": "parental", "label": "",
                                          "remaining_minutes": 12.3, "total_minutes": 59.6}, 0.0)
        self.assertEqual((shaped["remaining_minutes"], shaped["total_minutes"]), (13, 60))
        self.assertEqual([self.policy.shape("game", {"session_minutes": m}, False)["session_minutes"]
                          for m in (4.9, 5.0, 12.3)], [0, 5, 10])
        for area, wait in (("status", 60.0), ("light_bar", 1.0)):
            self.offer(area, {"owner": "a"}, 0.0)
            self.assertIsNone(self.offer(area, {"owner": "b"}, wait - 0.1), area)
            self.assertIsNotNone(self.offer(area, {"owner": "b"}, wait), area)

    def test_turbo_skips_deadbands_and_rounding_but_keeps_once_a_second(self):
        self.offer("performance", perf(), 0.0, turbo=True)
        self.assertIsNotNone(self.offer("performance", perf(cpu=21), 1.0, turbo=True))
        self.assertIsNone(self.offer("performance", perf(cpu=22), 2.0))  # back to the deadband
        self.assertEqual(self.policy.shape("game", {"session_minutes": 12.3}, True)["session_minutes"], 12.3)
        self.offer("status", {"owner": "a"}, 0.0, turbo=True)
        self.assertIsNone(self.offer("status", {"owner": "b"}, 0.5, turbo=True))
        self.assertIsNotNone(self.offer("status", {"owner": "b"}, 1.0, turbo=True))


if __name__ == "__main__":
    unittest.main()
