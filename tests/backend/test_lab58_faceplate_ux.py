import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.faceplate import artwork_dashboard as dashboard
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate, DASHBOARD_PACK_REVISION


class DraftArtworkTests(unittest.TestCase):
    def _candidate(self, library, value, draft=False):
        root = library._prepared_root(620, "static", draft=draft)
        root.mkdir(parents=True)
        data = b"GIF89a" + bytes([value])
        pack = bytes([value]) * (64 * 54 * 3)
        (root / "faceplate.gif").write_bytes(data)
        (root / "artwork-dashboard.rgb").write_bytes(pack)
        (root / "manifest.json").write_text(json.dumps({
            "schema": 2, "appid": 620, "mode": "static", "asset_id": value,
            "ready": True, "sha256": hashlib.sha256(data).hexdigest(),
            "dashboard_pack": "artwork-dashboard.rgb", "dashboard_pack_frames": 1,
            "dashboard_pack_sha256": hashlib.sha256(pack).hexdigest(),
            "dashboard_pack_revision": DASHBOARD_PACK_REVISION,
        }))
        return data

    def test_preparing_draft_and_assigning_home_do_not_change_game_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            old = self._candidate(library, 30)
            library.activate_prepared(620, "static")
            self._candidate(library, 90, draft=True)
            self.assertEqual(library.selected(620)[0], old)
            library.assign_home(620, "static", draft=True)
            self.assertEqual(library.selected(620)[0], old)
            self.assertEqual(library.home_dashboard_manifest(620)["asset_id"], 90)
            reference = library.home_dashboard_pack_reference(620)
            self.assertEqual(reference[1].read_bytes()[0], 90)

    def test_explicit_game_activation_does_not_change_home_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            self._candidate(library, 30)
            library.activate_prepared(620, "static")
            library.assign_home(620, "static")
            new = self._candidate(library, 90, draft=True)
            library.activate_prepared(620, "static", draft=True)
            self.assertEqual(library.selected(620)[0], new)
            self.assertEqual(library.home_dashboard_manifest(620)["asset_id"], 30)

    def test_failed_promotion_keeps_previous_prepared_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            old = self._candidate(library, 30)
            library.activate_prepared(620, "static")
            self._candidate(library, 90, draft=True)
            import os
            original = os.replace
            def fail_install(source, target):
                if Path(source).name.endswith(".applying"):
                    raise OSError("simulated disk failure")
                return original(source, target)
            with patch("signalbar.faceplate.steamgriddb.os.replace", side_effect=fail_install):
                with self.assertRaises(OSError):
                    library.activate_prepared(620, "static", draft=True)
            self.assertEqual(library.selected(620)[0], old)

    def test_lab57_home_assignment_falls_back_to_game_pack_until_explicitly_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            self._candidate(library, 30)
            library.activate_prepared(620, "static")
            self.assertEqual(library.home_dashboard_pack_reference(620), library.selected_dashboard_pack_reference(620))

    def test_failed_selection_write_restores_the_previous_game_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            old = self._candidate(library, 30)
            library.activate_prepared(620, "static")
            self._candidate(library, 90, draft=True)
            with patch("signalbar.faceplate.steamgriddb._atomic_json", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    library.activate_prepared(620, "static", draft=True)
            self.assertEqual(library.selected(620)[0], old)


class DashboardBoundsTests(unittest.TestCase):
    def _labels(self, **options):
        records = []
        original = dashboard.draw_text
        def draw(canvas, x, y, label, colour):
            records.append((x, y, label, colour))
            return original(canvas, x, y, label, colour)
        with patch.object(dashboard, "draw_text", side_effect=draw):
            dashboard.build_artwork_dashboard((bytes(64 * 54 * 3),), "2026-10-10T12:48:00+00:00", 0,
                                               ux_enabled=True, **options)
        return records

    def test_percentages_and_extreme_temperatures_fit_native_matrix(self):
        for unit in ("celsius", "fahrenheit"):
            for temperature in (-100, -12, 0, 100, None):
                for mode in ("today", "next_hour", "controllers"):
                    records = self._labels(unit=unit, bottom_mode=mode, show_p2=True,
                        controllers=({"percent": 100}, {"percent": 100}),
                        weather={"temperature_c": temperature, "condition": None},
                        forecast={"morning_temperature_c": temperature, "afternoon_temperature_c": temperature,
                                  "next_hour_temperature_c": temperature, "next_hour_precipitation_probability": 100})
                    for x, y, label, _ in records:
                        self.assertGreaterEqual(x, 0, (mode, unit, label))
                        self.assertLessEqual(x + dashboard.measure_text(label), 64, (mode, unit, label))

    def test_next_hour_matches_approved_distributed_positions_for_zero_fifty_and_hundred(self):
        for chance, expected in ((0, [2,18,30,44,55]), (50, [2,17,28,41,51]), (100, [2,16,26,38,47])):
            with patch.object(dashboard, "_weather_icon", wraps=dashboard._weather_icon) as weather, \
                 patch.object(dashboard, "_precipitation_risk_icon", wraps=dashboard._precipitation_risk_icon) as risk:
                records = self._labels(bottom_mode="next_hour", forecast={"next_hour_condition":"rain",
                    "next_hour_temperature_c":13, "next_hour_precipitation_probability":chance})
            labels = [(x, label) for x,y,label,_ in records if y == 48]
            self.assertEqual([label for _,label in labels], ["+1H", "13°", f"{chance}%"])
            self.assertEqual([labels[0][0], weather.call_args.args[2], labels[1][0], risk.call_args.args[1], labels[2][0]], expected)

    def test_next_hour_every_probability_and_temperature_keeps_balanced_dark_gutters(self):
        for ux in (False, True):
            for unit in ("celsius", "fahrenheit"):
                for temperature in (-100, -12, 0, 13, 100, None):
                    for chance in (*range(101), None):
                        canvas = dashboard.Canvas()
                        records = []
                        original = dashboard.draw_text
                        def draw(canvas, x, y, label, colour):
                            records.append((x,label))
                            return original(canvas,x,y,label,colour)
                        with patch.object(dashboard,"draw_text",side_effect=draw), \
                             patch.object(dashboard,"_weather_icon",wraps=dashboard._weather_icon) as weather, \
                             patch.object(dashboard,"_precipitation_risk_icon",wraps=dashboard._precipitation_risk_icon) as risk:
                            dashboard._draw_bottom_row(canvas,"next_hour",ux_enabled=ux,unit=unit,
                                forecast={"next_hour_condition":"rain", "next_hour_temperature_c":temperature,
                                          "next_hour_precipitation_probability":chance})
                        with self.subTest(ux=ux,unit=unit,temperature=temperature,chance=chance):
                            prefix,temp,percent=records
                            xs=[prefix[0],weather.call_args.args[2],temp[0],risk.call_args.args[1],percent[0]]
                            widths=[dashboard.measure_text(prefix[1]),7,dashboard.measure_text(temp[1]),7,dashboard.measure_text(percent[1])]
                            gutters=[xs[i+1]-xs[i]-widths[i] for i in range(4)]
                            self.assertEqual(xs[0],2)
                            self.assertEqual(xs[-1]+widths[-1],62)
                            self.assertGreaterEqual(min(gutters),1)
                            self.assertLessEqual(max(gutters)-min(gutters),1)
                            for i,gap in enumerate(gutters):
                                for x in range(xs[i]+widths[i],xs[i]+widths[i]+gap):
                                    self.assertTrue(all(canvas.pixels[y*64+x]==dashboard.RAIL_BACKGROUND for y in range(46,54)))
                            self.assertEqual(percent[1], "--%" if chance is None else f"{chance}%")

    def test_unknown_battery_and_weather_show_unknown_marks(self):
        records = self._labels(bottom_mode="controllers", battery_style="bar",
                               controllers=({"percent": None},), weather={"condition": None})
        self.assertGreaterEqual(sum(label == "?" for _, _, label, _ in records), 2)

    def test_today_readings_use_weather_and_spaced_slash_not_am_pm(self):
        with patch.object(dashboard, "_weather_icon", wraps=dashboard._weather_icon) as icon:
            records = self._labels(bottom_mode="today", forecast={"today_condition": "breaks", "morning_temperature_c": 12, "afternoon_temperature_c": 19})
        labels = [label for _, y, label, _ in records if y == 48]
        self.assertEqual(labels, ["12°C", "/", "19°C"])
        self.assertTrue(any(call.args[1:4] == ("breaks", 11, 48) for call in icon.call_args_list))

    def test_today_all_supported_values_keep_units_and_separate_pixel_regions(self):
        for ux in (False, True):
            for unit in ("celsius", "fahrenheit"):
                for morning in (-100, -12, 0, 9, 100, None):
                    for afternoon in (-100, -12, 0, 14, 100, None):
                        canvas = dashboard.Canvas()
                        records = []
                        original = dashboard.draw_text
                        def draw(canvas, x, y, label, colour):
                            records.append((x, label, colour))
                            return original(canvas, x, y, label, colour)
                        with patch.object(dashboard, "draw_text", side_effect=draw), \
                             patch.object(dashboard, "_weather_icon", wraps=dashboard._weather_icon) as icon:
                            dashboard._draw_bottom_row(canvas, "today", ux_enabled=ux, unit=unit,
                                forecast={"today_condition":"breaks", "morning_temperature_c":morning,
                                          "afternoon_temperature_c":afternoon})
                        with self.subTest(ux=ux, unit=unit, morning=morning, afternoon=afternoon):
                            left, slash, right = records
                            self.assertEqual(left[1], dashboard._temperature(morning, unit))
                            self.assertEqual(right[1], dashboard._temperature(afternoon, unit))
                            self.assertEqual(left[2], dashboard.MORNING_BLUE)
                            self.assertEqual(right[2], dashboard.AFTERNOON_ORANGE)
                            self.assertEqual(slash[1], "/")
                            ix = icon.call_args.args[2]
                            self.assertGreaterEqual(ix, 0)
                            self.assertGreaterEqual(left[0] - (ix + 6), 1)
                            self.assertGreaterEqual(slash[0] - (left[0] + dashboard.measure_text(left[1])), 1)
                            self.assertGreaterEqual(right[0] - (slash[0] + dashboard.measure_text("/")), 1)
                            self.assertLessEqual(right[0] + dashboard.measure_text(right[1]), 63)

    def test_today_known_conditions_keep_approved_rail_identical_in_both_ux_modes(self):
        for condition in dashboard._WEATHER_MARKS:
            args = dict(bottom_mode="today", forecast={"today_condition":condition,
                        "morning_temperature_c":9, "afternoon_temperature_c":14})
            old = dashboard.build_artwork_dashboard((bytes(64*54*3),), "2026-10-11T10:00:00", 0, **args)
            new = dashboard.build_artwork_dashboard((bytes(64*54*3),), "2026-10-11T10:00:00", 0, ux_enabled=True, **args)
            self.assertEqual(old.frames[0][45*64*3:], new.frames[0][45*64*3:])


if __name__ == "__main__":
    unittest.main()
