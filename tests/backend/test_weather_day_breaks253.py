"""Only day cloud breaks regain source exposure; preserve every other weather GIF."""
from pathlib import Path
import hashlib,json,unittest,zlib
from signalbar.faceplate.weather_artwork import (load_catalog,_preset,build_weather_artwork_scene,
    build_weather_artwork_dashboard_snapshot,weather_artwork_cache_revision)
from signalbar.backend.engine import faceplate_scene_cache_namespace
ROOT=Path(__file__).resolve().parents[2]
FROZEN=json.loads((ROOT/'tests/fixtures/weather-day-breaks253-preserved.json').read_text())
THEME='weather-artwork-v2'
sha=lambda data:hashlib.sha256(data).hexdigest()

class DayBreaks253Tests(unittest.TestCase):
    def test_every_unaffected_native_gif_and_weather_bank_keeps_its_exact_hash(self):
        for path,digest in FROZEN['assets'].items():
            with self.subTest(path=path):self.assertEqual(sha((ROOT/path).read_bytes()),digest)

    def test_actual_weather_and_dashboard_gifs_are_unchanged_for_every_other_scene(self):
        for key,expected in FROZEN['renders'].items():
            theme,preset,phase,kind=key.split('/')
            if theme==THEME and preset in {'breaks:0','breaks:1'}:continue
            condition,variant=preset.split(':');variant=int(variant)
            with self.subTest(key=key):
                if kind=='weather':
                    result,_=build_weather_artwork_scene(condition,variant,12,'celsius',phase,visual_theme=theme)
                else:
                    instant='2026-10-25T12:00:00' if phase=='day' else '2026-10-25T22:00:00'
                    result,_=build_weather_artwork_dashboard_snapshot(instant,condition,variant,12,'celsius',
                        '2026-10-25T07:30:00','2026-10-25T18:30:00',visual_theme=theme)
                self.assertEqual(sha(b''.join(result.frames)),expected['rgb'])
                self.assertEqual(sha(result.gif()),expected['gif'])
                self.assertEqual(result.signature,expected['signature'])
                self.assertEqual(faceplate_scene_cache_namespace(dict(kind=kind,visual_theme=theme,condition=condition)),expected['cache_namespace'])

    def test_both_day_breaks_regain_source_exposure_and_keep_the_loop_timing(self):
        for variant in (0,1):
            row=_preset(f'breaks:{variant}',THEME);source=_preset(f'breaks:{variant}','weather-artwork-v1')
            raw=zlib.decompress((ROOT/'assets/faceplate/weather-artwork-v2'/row['background_pack']).read_bytes())
            old=zlib.decompress((ROOT/'assets/faceplate/weather-artwork-v1'/source['background_pack']).read_bytes())
            self.assertGreaterEqual(sum(raw)/sum(old),.98);self.assertLessEqual(sum(raw)/sum(old),1.04)
            scene,_=build_weather_artwork_scene('breaks',variant,12,'celsius','day',visual_theme=THEME)
            previous=FROZEN['renders'][f'{THEME}/breaks:{variant}/day/weather']
            self.assertEqual(len(scene.frames),previous['frames']);self.assertEqual(list(scene.delays_cs),previous['delays'])
            self.assertNotEqual(sha(scene.gif()),previous['gif'])

    def test_only_day_breaks_cache_namespaces_are_replaced(self):
        for key,previous in FROZEN['renders'].items():
            theme,preset,phase,kind=key.split('/');condition=preset.split(':')[0]
            current=faceplate_scene_cache_namespace(dict(kind=kind,visual_theme=theme,condition=condition))
            if theme==THEME and condition=='breaks':
                self.assertNotEqual(current,previous['cache_namespace']);self.assertIn('breaks-day-source-exposure-1',current)
            else:self.assertEqual(current,previous['cache_namespace'])
