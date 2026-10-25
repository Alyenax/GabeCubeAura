"""Pixel-exact translation, effective clock guard and persisted context choices."""
from pathlib import Path
import tempfile
import unittest
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard
from signalbar.settings import SettingsStore
from signalbar.dashboard_settings import dashboard_context
from signalbar.faceplate.scene_renderer import render_isolated
import hashlib

RGB=bytes((40,70,110))*(64*54)
TIME='2026-10-22T12:00:00+02:00'

def render(position,**kw):
    return build_artwork_dashboard((RGB,),TIME,0,show_weather_notch=True,
        weather={'condition':'rain','temperature_c':-100},show_status_rail=False,
        weather_position=position,**kw)

class Notch205(unittest.TestCase):
    def test_exact_template_translation_and_no_old_notch_ghost(self):
        base=render('right').frames[0]
        for position,left in [('left',0),('center',18),('right',37)]:
            frame=render(position).frames[0]
            for y in range(11):
                for dx in range(27):
                    self.assertEqual(base[(y*64+37+dx)*3:(y*64+38+dx)*3],frame[(y*64+left+dx)*3:(y*64+left+dx+1)*3])
                for x in range(64):
                    if not left <= x < left+27:
                        self.assertEqual(RGB[(y*64+x)*3:(y*64+x+1)*3],frame[(y*64+x)*3:(y*64+x+1)*3])
            self.assertEqual(RGB[11*64*3:],frame[11*64*3:])

    def test_clock_forces_right_without_mutating_saved_choice_and_game_has_no_clock(self):
        for position in ('left','center'):
            self.assertEqual(render('right',show_clock=True).frames,render(position,show_clock=True).frames)
            self.assertNotEqual(render('right',show_clock=True,game_running=True).frames,
                                render(position,show_clock=True,game_running=True).frames)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'settings.json');store=SettingsStore(path)
            store.update({'faceplate_dashboard_contexts':{'home':{'weather_position':'center'},'game':{'weather_position':'left'}}})
            values=SettingsStore(path).all()
            self.assertEqual('center',dashboard_context(values,False)['weather_position'])
            self.assertEqual('left',dashboard_context(values,True)['weather_position'])

    def test_actual_worker_preserves_position_and_signature(self):
        request=dict(kind='artwork-dashboard',display_at=TIME,dashboard_background_rgb=RGB.hex(),
            dashboard_pack_frames=1,dashboard_pack_sha256=hashlib.sha256(RGB).hexdigest(),
            weather={'condition':'rain','temperature_c':12},show_weather_notch=True,
            dashboard_show_status_rail=False,weather_position='left')
        for kind in ('artwork-dashboard','dashboard'):
            case={**request,'kind':kind,'visual_theme':'weather-artwork-v2','condition':'rain',
                  'variant':0,'temperature_c':12,'unit':'celsius',
                  'sunrise':'2026-10-22T07:00:00+02:00','sunset':'2026-10-22T19:00:00+02:00'}
            left,first=render_isolated(case)
            right,other=render_isolated({**case,'weather_position':'right'})
            self.assertNotEqual(left,right);self.assertNotEqual(first['signature'],other['signature'])
            clock_left,_=render_isolated({**case,'dashboard_show_clock':True})
            clock_right,_=render_isolated({**case,'dashboard_show_clock':True,'weather_position':'right'})
            self.assertEqual(clock_left,clock_right)
