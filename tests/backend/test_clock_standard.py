"""Native standard clocks, scheduling revisions and saved appearance contracts."""
from datetime import datetime
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from signalbar.faceplate.clock_standard import DESIGNS, PALETTES, build_packet, render_frame
from signalbar.faceplate.clocks import ClockRuntime, catalog
from signalbar.settings import SettingsStore


class StandardClockTests(unittest.TestCase):
    def test_both_channels_offer_exactly_the_nine_approved_standards(self):
        for version in ('1.5.1-beta.22','1.5.1-lab.264'):
            self.assertEqual(set(DESIGNS),{c['id'] for c in catalog(version) if not c['private']})
        self.assertNotIn('steps',DESIGNS)
        with self.assertRaises(ValueError): render_frame('steps',datetime(2026,10,27))

    def test_every_colour_preserves_the_native_shape(self):
        for design in DESIGNS:
            silhouettes=[];frames=[]
            for palette in PALETTES:
                frame=render_frame(design,datetime(2026,10,27,17,42),{'palette':palette})
                self.assertEqual(64*54*3,len(frame));frames.append(frame)
                silhouettes.append(bytes(bool(frame[i:i+3].strip(b'\0')) for i in range(0,len(frame),3)))
            self.assertEqual(1,len(set(silhouettes)));self.assertEqual(6,len(set(frames)))

    def test_minute_and_midnight_are_anchored_to_local_system_time(self):
        start=datetime(2026,10,27,23,59,47,250000).timestamp()
        request={'clock_id':'horizon','display_at':start,'end_at':start+250,
                 'options':{'palette':'rose','format':'12','language':'fr'}}
        packet=build_packet(request)
        self.assertEqual(1275,packet.delays_cs[0]);self.assertEqual(25000,sum(packet.delays_cs))
        cursor=start
        for frame,delay in zip(packet.frames,packet.delays_cs):
            self.assertEqual(render_frame('horizon',datetime.fromtimestamp(cursor),request['options']),frame)
            cursor+=delay/100
        data=packet.gif();self.assertLess(len(data),81920);self.assertNotIn(b'NETSCAPE2.0',data)

    def test_packet_signature_tracks_appearance_and_bounds(self):
        base={'clock_id':'halo','display_at':1000.12,'end_at':1200}
        a=build_packet(base);b=build_packet({**base,'options':{'palette':'sage'}})
        self.assertNotEqual(a.signature,b.signature)
        for changes in ({'end_at':1300.13},{'clock_id':'steps'},{'options':{'palette':'invalid'}},
                        {'options':{'format':'13'}},{'options':{'language':'auto'}}):
            with self.assertRaises(ValueError): build_packet({**base,**changes})

    def test_appearance_change_cannot_accept_an_old_pending_receipt(self):
        r=ClockRuntime();a=r.plan('halo','home',1000,False,monotonic=1000,options={'palette':'rose'})
        b=r.plan('halo','home',1001,False,monotonic=1001,options={'palette':'sage'})
        r.receipt(a,{'synchronized':True},1002)
        self.assertEqual(b,r.pending);self.assertIsNone(r.active)
        self.assertEqual('sage',b['options']['palette'])

    def test_palettes_formats_roundtrip_independently_and_reject_bad_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';s=SettingsStore(str(path))
            s.update({'faceplate_clock_home':'halo','faceplate_clock_game':'week',
                      'faceplate_clock_palette_home':'rose','faceplate_clock_palette_game':'glacier',
                      'faceplate_clock_format_home':'12','faceplate_clock_format_game':'24'})
            loaded=SettingsStore(str(path)).all()
            self.assertEqual('rose',loaded['faceplate_clock_palette_home'])
            self.assertEqual('glacier',loaded['faceplate_clock_palette_game'])
            self.assertEqual('12',loaded['faceplate_clock_format_home'])
            for key,value in [('faceplate_clock_palette_home','blue'),('faceplate_clock_format_game','13')]:
                with self.assertRaises(ValueError): s.update({key:value})
            self.assertEqual('rose',s.all()['faceplate_clock_palette_home'])


class StandardClockEngineTests(unittest.TestCase):
    def setUp(self):
        import test_native_clock as fixture
        self.fixture=fixture.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.engine=self.fixture.engine
        self.fixture.settings.update({'faceplate_clock_home':'halo','faceplate_clock_game':'week'})
        self.fixture.prefs.update(home_scene='clock')
        self.engine._reconcile_faceplate=Mock()

    def test_inactive_appearance_keeps_pending_work_but_active_edit_cancels_it(self):
        p=self.engine.clock_runtime.plan('halo','home',1000,False,monotonic=1000,options={'palette':'rose'})
        self.engine.update_settings({'faceplate_clock_palette_game':'glacier'})
        self.assertEqual(p,self.engine.clock_runtime.pending)
        self.engine._reconcile_faceplate.assert_not_called()
        self.engine.update_settings({'faceplate_clock_palette_home':'sage'})
        self.assertIsNone(self.engine.clock_runtime.pending)
        self.engine._reconcile_faceplate.assert_called_once_with('clock-selection-change',force=True)

    def test_gca_language_change_invalidates_old_date_glyphs(self):
        self.engine.clock_runtime.plan('halo','home',1000,False,monotonic=1000,options={'language':'en'})
        self.engine.update_settings({'ui_language':'fr'})
        self.assertIsNone(self.engine.clock_runtime.pending)
        self.engine._reconcile_faceplate.assert_not_called()
        self.assertEqual(0,self.engine._faceplate_next_reconcile)


if __name__=='__main__': unittest.main()
