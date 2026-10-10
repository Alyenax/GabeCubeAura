from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from signalbar.backend import Engine
from signalbar.mqtt.policy import PublishingPolicy
from signalbar.mqtt.snapshot import build_snapshot, flatten_status, frontend_connected, is_redacted
from signalbar.settings import SettingsStore

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
        with tempfile.TemporaryDirectory() as directory:
            real = Engine(SettingsStore(str(Path(directory) / "config.json")), str(Path(directory) / "a.json")).status()
        self.assertLess(len(flatten_status(real)), 400)
        self.assertLess(len(json.dumps(flatten_status(real))), 16_000)


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
