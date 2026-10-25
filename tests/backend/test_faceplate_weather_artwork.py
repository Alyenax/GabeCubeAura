from pathlib import Path
from datetime import datetime
from io import BytesIO
import hashlib
import json
import runpy
import tempfile
import unittest
import zlib
from unittest.mock import patch

from PIL import Image, ImageSequence

from signalbar.faceplate.scene_renderer import FaceplateRenderError, render_isolated
from signalbar.faceplate.weather_artwork import (
    WEATHER_ARTWORK_REVISION,
    WEATHER_ARTWORK_DASHBOARD_REVISION,
    WEATHER_ARTWORK_THEME,
    WEATHER_ARTWORK_V2_DASHBOARD_REVISION,
    WEATHER_ARTWORK_V2_OUTPUT_REVISION,
    WEATHER_ARTWORK_V2_REVISION,
    WEATHER_ARTWORK_V2_THEME,
    build_weather_artwork_dashboard_snapshot,
    build_weather_artwork_scene,
    load_catalog,
    select_weather_artwork,
    weather_artwork_cache_revision,
)
from signalbar.backend.engine import Engine, faceplate_scene_cache_namespace
from signalbar.faceplate.routing import FaceplateSceneTicket
from signalbar.faceplate.scenes import WEATHER_VARIANTS


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/pixel-studio-alternative/assets/weather-artwork-palette-v1"
RUNTIME = ROOT / "assets/faceplate/weather-artwork-v1"
V2_SOURCE = ROOT / "tools/pixel-studio-alternative/assets/weather-artwork-palette-v2"
V2_RUNTIME = ROOT / "assets/faceplate/weather-artwork-v2"
NIGHT_RAIN_SHA256 = "bcfc2e416071a1ced71da3da2e4a1f9e21563a93e418e96e7f4bc3ad4316d79d"


class WeatherArtworkRuntimeTests(unittest.TestCase):


    def test_luminous_v2_runtime_is_bounded_loop_safe_and_distinct_from_v1(self):
        catalog = load_catalog(WEATHER_ARTWORK_V2_THEME)
        self.assertEqual(catalog["theme"], WEATHER_ARTWORK_V2_THEME)
        self.assertEqual(catalog["collection_revision"], WEATHER_ARTWORK_V2_REVISION)
        self.assertEqual(catalog["variant_count"], 22)
        self.assertEqual(catalog["frame_count"], 24)
        total = 0
        v1 = {item["id"]: item for item in load_catalog()["presets"]}
        for item in catalog["presets"]:
            packed = (V2_RUNTIME / item["background_pack"]).read_bytes()
            self.assertEqual(hashlib.sha256(packed).hexdigest(), item["background_pack_sha256"])
            raw = zlib.decompress(packed)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["background_raw_sha256"])
            frame_size = 64 * 54 * 3
            frames = [raw[offset:offset + frame_size] for offset in range(0, len(raw), frame_size)]
            self.assertEqual(len(frames), 24)
            self.assertEqual(len(set(frames)), 24)
            loads = [sum(frame) / (len(frame) * 255.0) for frame in frames]
            if item["condition"] == "breaks":
                source = zlib.decompress((RUNTIME / v1[item["id"]]["background_pack"]).read_bytes())
                self.assertGreaterEqual(sum(raw) / sum(source), 0.98, item["id"])
                self.assertLessEqual(sum(raw) / sum(source), 1.04, item["id"])
            else:
                self.assertLessEqual(max(loads), 0.47, item["id"])
            bright = max(
                sum(1 for offset in range(0, len(frame), 3)
                    if max(frame[offset:offset + 3]) > 240) / (64 * 54)
                for frame in frames
            )
            if item["condition"] != "breaks":
                self.assertLess(bright, 0.07, item["id"])
            steps = [
                sum(abs(left - right) for left, right in zip(frame, frames[(index + 1) % 24]))
                / (len(frame) * 255.0)
                for index, frame in enumerate(frames)
            ]
            self.assertLessEqual(max(steps), 0.055, item["id"])
            self.assertLessEqual(steps[-1], max(steps[:-1]) * 1.25 + 0.0005, item["id"])
            self.assertNotEqual(item["background_raw_sha256"], v1[item["id"]]["background_raw_sha256"])
            total += len(packed)
        self.assertLess(total, 2 * 1024 * 1024)

    def test_luminous_v2_weather_and_dashboard_use_the_selected_theme(self):
        v1, _ = build_weather_artwork_scene(
            "rain", 0, 12, "celsius", "night",
        )
        v2, metadata = build_weather_artwork_scene(
            "rain", 0, 12, "celsius", "night",
            visual_theme=WEATHER_ARTWORK_V2_THEME,
        )
        self.assertEqual(v2.revision, WEATHER_ARTWORK_V2_REVISION)
        self.assertEqual(metadata["visual_theme"], WEATHER_ARTWORK_V2_THEME)
        self.assertNotEqual(v1.frames, v2.frames)
        arguments = (
            datetime(2026, 10, 9, 18, 1), "cloud_night", 2, 9, "celsius",
            datetime(2026, 10, 9, 7, 30), datetime(2026, 10, 9, 19, 15),
        )
        dashboard, dashboard_metadata = build_weather_artwork_dashboard_snapshot(
            *arguments, visual_theme=WEATHER_ARTWORK_V2_THEME,
        )
        self.assertEqual(len(dashboard.frames), 24)
        self.assertEqual(dashboard.delay_cs, 10)
        self.assertEqual(len(set(dashboard.frames)), 24)
        self.assertEqual(dashboard.revision, WEATHER_ARTWORK_V2_DASHBOARD_REVISION)
        self.assertEqual(dashboard_metadata["visual_theme"], WEATHER_ARTWORK_V2_THEME)

    def test_rain_dashboard_keeps_systemic_motion_below_fixed_overlay(self):
        result, _metadata = build_weather_artwork_dashboard_snapshot(
            datetime(2026, 10, 9, 21, 48), "rain", 0, 12, "celsius",
            datetime(2026, 10, 9, 7, 30), datetime(2026, 10, 9, 19, 15),
            visual_theme=WEATHER_ARTWORK_V2_THEME, bottom_mode="next_hour", show_clock=True,
            forecast={
                "next_hour_condition": "rain",
                "next_hour_temperature_c": 13,
                "next_hour_precipitation_probability": 80,
            },
        )
        self.assertEqual(len(result.frames), 24)
        self.assertEqual(result.delay_cs, 10)
        notch_pixels = tuple(
            (x, y) for y in range(11) for x in range(37, 64)
            if (x, y) not in {(37, 0), (63, 0), (37, 10), (63, 10)}
        )
        notch_regions = {
            b"".join(frame[(y * 64 + x) * 3:(y * 64 + x + 1) * 3]
                     for x, y in notch_pixels)
            for frame in result.frames
        }
        warm_white = bytes((255, 231, 190))
        clock_pixels = tuple(
            (x, y) for y in range(11) for x in range(20)
            if result.frames[0][(y * 64 + x) * 3:(y * 64 + x + 1) * 3]
            == warm_white
        )
        rails = {
            b"".join(frame[y * 64 * 3:(y + 1) * 64 * 3] for y in range(45, 54))
            for frame in result.frames
        }
        weather_field = {
            b"".join(frame[y * 64 * 3:(y + 1) * 64 * 3] for y in range(11, 45))
            for frame in result.frames
        }
        self.assertEqual(len(notch_regions), 1)
        self.assertTrue(clock_pixels)
        self.assertTrue(all(
            all(frame[(y * 64 + x) * 3:(y * 64 + x + 1) * 3] == warm_white
                for x, y in clock_pixels)
            for frame in result.frames
        ))
        self.assertEqual(len(rails), 1)
        self.assertGreaterEqual(len(weather_field), 20)
        with Image.open(BytesIO(result.gif())) as image:
            durations = [
                frame.info.get("duration", 0)
                for frame in ImageSequence.Iterator(image)
            ]
        self.assertGreaterEqual(len(durations), 20)
        self.assertEqual(sum(durations), 2400)

    def test_every_v2_dashboard_retains_the_complete_systemic_loop(self):
        instant = datetime(2026, 10, 9, 21, 48)
        sunrise = datetime(2026, 10, 9, 7, 30)
        sunset = datetime(2026, 10, 9, 19, 15)
        for condition, names in WEATHER_VARIANTS.items():
            for variant in range(len(names)):
                with self.subTest(condition=condition, variant=variant):
                    result, metadata = build_weather_artwork_dashboard_snapshot(
                        instant, condition, variant, 12, "celsius",
                        sunrise, sunset, visual_theme=WEATHER_ARTWORK_V2_THEME,
                    )
                    self.assertEqual(len(result.frames), 24)
                    self.assertEqual(len(set(result.frames)), 24)
                    self.assertEqual(result.delay_cs, 10)
                    self.assertEqual(metadata["power_scale"], 1.0)
                    self.assertLessEqual(len(result.gif()), 512 * 1024)

    def test_realistic_v2_dashboard_keeps_the_approved_next_hour_rail_exact(self):
        result, metadata = build_weather_artwork_dashboard_snapshot(
            datetime(2026, 10, 9, 21, 48), "rain", 0, 12, "celsius",
            datetime(2026, 10, 9, 7, 30), datetime(2026, 10, 9, 19, 15),
            visual_theme=WEATHER_ARTWORK_V2_THEME, bottom_mode="next_hour",
            forecast={
                "next_hour_condition": "rain",
                "next_hour_temperature_c": 13,
                "next_hour_precipitation_probability": 80,
            },
        )
        frame = result.frames[0]
        rail = b"".join(
            frame[(y * 64) * 3:((y + 1) * 64) * 3]
            for y in range(45, 54)
        )
        self.assertEqual(
            hashlib.sha256(rail).hexdigest(),
            "5de8116a304f028e7b30f2d1307e682cfee888816a6989064f0fc8d1404c844b",
        )
        self.assertEqual(metadata["power_scale"], 1.0)
        self.assertEqual(
            frame[(0 * 64 + 38) * 3:(0 * 64 + 63) * 3],
            bytes((30, 116, 157)) * 25,
        )
        self.assertEqual(
            frame[(10 * 64 + 38) * 3:(10 * 64 + 63) * 3],
            bytes((30, 116, 157)) * 25,
        )

    def test_luminous_v2_cache_identity_tracks_the_installed_asset_revision(self):
        weather_revision = weather_artwork_cache_revision(
            WEATHER_ARTWORK_V2_THEME, "weather",
        )
        dashboard_revision = weather_artwork_cache_revision(
            WEATHER_ARTWORK_V2_THEME, "dashboard",
        )
        self.assertEqual(
            weather_revision,
            f"{WEATHER_ARTWORK_V2_REVISION}:{WEATHER_ARTWORK_V2_OUTPUT_REVISION}",
        )
        self.assertEqual(
            dashboard_revision,
            f"{WEATHER_ARTWORK_V2_REVISION}:{WEATHER_ARTWORK_V2_DASHBOARD_REVISION}:"
            "artwork-dashboard-26-umbrella-lowered",
        )
        namespace = faceplate_scene_cache_namespace({
            "kind": "weather", "visual_theme": WEATHER_ARTWORK_V2_THEME,
        })
        self.assertIn(WEATHER_ARTWORK_V2_REVISION, namespace)
        self.assertNotEqual(namespace, faceplate_scene_cache_namespace({
            "kind": "weather", "visual_theme": WEATHER_ARTWORK_THEME,
        }))

    def test_persistent_scene_cache_rejects_pre_revision_manifests(self):
        result, _metadata = build_weather_artwork_scene(
            "rain", 0, 12, "celsius", "night",
            visual_theme=WEATHER_ARTWORK_V2_THEME,
        )
        payload = {
            "kind": "weather", "visual_theme": WEATHER_ARTWORK_V2_THEME,
            "condition": "rain", "variant": 0, "temperature_c": 12,
            "unit": "celsius", "phase": "night", "city": "Test",
        }
        ticket = FaceplateSceneTicket(
            generation=0, scene="weather", context="preview",
            content_key="unchanged-live-weather", preference_revision=0,
        )
        namespace = faceplate_scene_cache_namespace(payload)
        cache_key = hashlib.sha256(
            f"{namespace}:{ticket.scene}:{ticket.content_key}".encode("utf-8"),
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "faceplate-scene-cache"
            root.mkdir()
            (root / f"{cache_key}.gif").write_bytes(result.gif())
            (root / f"{cache_key}.json").write_text(json.dumps({
                "content_key": ticket.content_key,
                "signature": "stale-without-asset-revision",
            }), encoding="utf-8")
            engine = Engine.__new__(Engine)
            engine._faceplate_scene_cache = str(root)
            engine._faceplate_state_directory = directory
            engine._warn = lambda _message: None
            with patch(
                "signalbar.backend.engine.render_isolated",
                return_value=(result.gif(), {"signature": "fresh"}),
            ) as renderer:
                _data, manifest = engine._render_faceplate_scene(payload, ticket)
            renderer.assert_called_once()
            self.assertEqual(manifest["signature"], "fresh")
            self.assertEqual(manifest["cache_namespace"], namespace)
            with patch(
                "signalbar.backend.engine.render_isolated",
                side_effect=AssertionError("the revisioned cache should be reused"),
            ):
                _cached_data, cached_manifest = engine._render_faceplate_scene(
                    payload, ticket,
                )
            self.assertEqual(cached_manifest["cache_namespace"], namespace)

    def test_luminous_v2_hardware_gif_keeps_the_source_palette_precision(self):
        result, _metadata = build_weather_artwork_scene(
            "breaks_night", 0, 12, "celsius", "night",
            visual_theme=WEATHER_ARTWORK_V2_THEME,
        )
        payload = result.gif()
        # Logical-screen packed field: a value of 7 means a 256-colour global
        # table.  This is the same precision used by the individual V2 source
        # GIFs and their showcase.
        self.assertEqual(payload[10] & 0x07, 7)
        with Image.open(BytesIO(payload)) as image:
            frames = [frame.convert("RGB").tobytes() for frame in ImageSequence.Iterator(image)]
        self.assertEqual(len(frames), 24)
        self.assertEqual(len(set(frames)), 24)



    def test_catalog_has_22_small_hashed_background_packs(self):
        catalog = load_catalog()
        self.assertEqual(catalog["collection_revision"], WEATHER_ARTWORK_REVISION)
        self.assertEqual(catalog["theme"], WEATHER_ARTWORK_THEME)
        self.assertEqual((catalog["width"], catalog["height"]), (64, 54))
        self.assertEqual(len(catalog["presets"]), 22)
        self.assertEqual(catalog["condition_count"], 9)
        self.assertEqual(catalog["variant_count"], 22)
        self.assertEqual(catalog["conservative_power_budget"], 0.5)
        self.assertEqual(catalog["motion_model"], "systemic-scene-integrated-v2")
        self.assertIn("no translated cloud sprites", catalog["motion_rules"])
        self.assertIn("no travelling cadence marker", catalog["motion_rules"])
        total = 0
        for item in catalog["presets"]:
            path = RUNTIME / item["background_pack"]
            data = path.read_bytes()
            total += len(data)
            self.assertEqual(hashlib.sha256(data).hexdigest(), item["background_pack_sha256"])
            self.assertEqual(item["motion_model"], "systemic-scene-integrated-v2")
            self.assertLess(len(data), 128 * 1024)
        self.assertLess(total, 1024 * 1024)



    def test_selection_maps_every_runtime_variant_exactly_without_hidden_overrides(self):
        for condition, names in WEATHER_VARIANTS.items():
            for variant in range(len(names)):
                for phase in ("dawn", "day", "dusk", "night"):
                    with self.subTest(condition=condition, variant=variant, phase=phase):
                        selected = select_weather_artwork(
                            condition, variant, phase,
                            weather_code=45, wind_speed_kmh=80,
                        )
                        self.assertEqual(selected.preset_id, f"{condition}:{variant}")
                        self.assertEqual(selected.selection_status, "exact")

    def test_dynamic_badge_supports_celsius_fahrenheit_and_stable_rounding(self):
        celsius, metadata = build_weather_artwork_scene(
            "rain", 0, 12.1, "celsius", "night",
        )
        same_display, _ = build_weather_artwork_scene(
            "rain", 0, 12.4, "celsius", "night",
        )
        fahrenheit, fahrenheit_metadata = build_weather_artwork_scene(
            "rain", 0, 12.1, "fahrenheit", "night",
        )
        self.assertEqual(len(celsius.frames), 24)
        self.assertTrue(all(len(frame) == 64 * 54 * 3 for frame in celsius.frames))
        self.assertEqual(celsius.signature, same_display.signature)
        self.assertNotEqual(celsius.signature, fahrenheit.signature)
        self.assertEqual((celsius.temperature, celsius.unit), (12, "C"))
        self.assertEqual((fahrenheit.temperature, fahrenheit.unit), (54, "F"))
        self.assertEqual(metadata["preset_id"], "rain:0")
        self.assertEqual(metadata["variant_name"], "Bluewater")
        self.assertEqual(metadata["selection_status"], "exact")
        self.assertEqual(fahrenheit_metadata["collection_revision"], WEATHER_ARTWORK_REVISION)
        self.assertGreater(metadata["peak_load"], 0)
        self.assertLessEqual(metadata["peak_load"], 0.5)
        self.assertLessEqual(len(celsius.gif()), 512 * 1024)

    def test_every_configurable_weather_scene_uses_the_artwork_runtime(self):
        for condition, names in WEATHER_VARIANTS.items():
            for variant in range(len(names)):
                result, metadata = build_weather_artwork_scene(
                    condition, variant, 11, "celsius", "day",
                )
                self.assertEqual(metadata["selection_status"], "exact")
                self.assertEqual(metadata["preset_id"], f"{condition}:{variant}")
                self.assertEqual(result.revision, WEATHER_ARTWORK_REVISION)

    def test_home_dashboard_uses_the_exact_artwork_palette_with_a_stable_clock(self):
        arguments = (
            datetime(2026, 10, 9, 18, 1), "cloud", 2, 14, "celsius",
            datetime(2026, 10, 9, 7, 30), datetime(2026, 10, 9, 19, 15),
        )
        result, metadata = build_weather_artwork_dashboard_snapshot(
            *arguments, status={
                "recording": "active", "recent_event": "", "controllers": 1,
            }, battery={"percent": 80, "charging": False},
        )
        other, _ = build_weather_artwork_dashboard_snapshot(
            arguments[0], "cloud", 3, *arguments[3:],
        )
        self.assertEqual(result.revision, WEATHER_ARTWORK_DASHBOARD_REVISION)
        self.assertEqual(len(result.frames), 24)
        self.assertEqual(result.delay_cs, 10)
        self.assertEqual(len(result.frames[0]), 64 * 54 * 3)
        self.assertEqual(metadata["preset_id"], "cloud:2")
        self.assertEqual(metadata["variant_name"], "Cross & gather")
        self.assertEqual(metadata["selection_status"], "exact")
        self.assertLessEqual(metadata["peak_load"], 0.5)
        self.assertNotEqual(result.frames[0], other.frames[0])
        self.assertLessEqual(len(result.gif()), 512 * 1024)

    def test_isolated_renderer_returns_selection_metadata_and_rejects_other_kinds(self):
        request = {
            "kind": "weather", "visual_theme": WEATHER_ARTWORK_THEME,
            "condition": "rain", "variant": 0, "temperature_c": 12,
            "unit": "celsius", "phase": "night", "city": "Test",
        }
        with tempfile.TemporaryDirectory() as directory:
            data, manifest = render_isolated(request, temporary_root=directory)
            self.assertTrue(data.startswith(b"GIF89a"))
            self.assertEqual(manifest["preset_id"], "rain:0")
            self.assertEqual(manifest["variant_name"], "Bluewater")
            self.assertEqual(manifest["selection_status"], "exact")
            self.assertEqual(manifest["collection_revision"], WEATHER_ARTWORK_REVISION)
            luminous, luminous_manifest = render_isolated({
                **request, "visual_theme": WEATHER_ARTWORK_V2_THEME,
            }, temporary_root=directory)
            self.assertTrue(luminous.startswith(b"GIF89a"))
            self.assertEqual(
                luminous_manifest["collection_revision"], WEATHER_ARTWORK_V2_REVISION,
            )
            self.assertEqual(luminous_manifest["visual_theme"], WEATHER_ARTWORK_V2_THEME)
            self.assertNotEqual(luminous, data)
            dashboard, dashboard_manifest = render_isolated({
                "kind": "dashboard", "visual_theme": WEATHER_ARTWORK_THEME,
                "condition": "breaks", "variant": 1, "temperature_c": 18,
                "unit": "celsius", "phase": "day", "city": "Test",
                "display_at": "2026-10-09T18:01:00",
                "sunrise": "2026-10-09T07:30:00",
                "sunset": "2026-10-09T19:15:00",
                "clock_24h": True,
            }, temporary_root=directory)
            self.assertTrue(dashboard.startswith(b"GIF89a"))
            self.assertEqual(dashboard_manifest["preset_id"], "breaks:1")
            self.assertEqual(
                dashboard_manifest["dashboard_revision"],
                WEATHER_ARTWORK_DASHBOARD_REVISION,
            )
            with self.assertRaises(FaceplateRenderError):
                render_isolated({
                    "kind": "performance", "visual_theme": WEATHER_ARTWORK_THEME,
                    "cpu_load": 10, "gpu_load": 20,
                    "cpu_temp_c": 40, "gpu_temp_c": 45,
                }, temporary_root=directory)


if __name__ == "__main__":
    unittest.main()
