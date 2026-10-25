from datetime import datetime
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from signalbar.faceplate.artwork_layout import compose_frame,Logo
from signalbar.faceplate.artwork_dashboard import build_artwork_dashboard
from signalbar.faceplate.coordinator import FaceplateCoordinator
from signalbar.faceplate.broker_adapter import FaceplateBrokerAdapter
from test_faceplate import FakeLink,ASSET_ROOT,StaticFirstSteamGridDB

class ArtworkReauditTests(unittest.TestCase):
    def test_logo_replaces_rail_through_actual_compositor_and_signature(self):
        for animated in (False,True):
            for placement in ('bottom_rail','bottom'):
                with self.subTest(animated=animated,placement=placement):
                    frame=bytes(64*54*3);logo=Logo(20,16,tuple((x,y,1.0,(255,255,255)) for y in range(16) for x in range(20)))
                    composed=compose_frame(frame,logo,style='logo',position=placement)
                    raw=composed.tobytes() if hasattr(composed,'tobytes') else composed
                    backgrounds=[raw]* (2 if animated else 1)
                    kw=dict(show_clock=False,show_weather_notch=False,bottom_mode='controllers',show_game_session=False,background_signature='test')
                    hidden=build_artwork_dashboard(backgrounds,datetime(2026,10,21),0,show_status_rail=False,**kw)
                    visible=build_artwork_dashboard(backgrounds,datetime(2026,10,21),0,show_status_rail=True,**kw)
                    self.assertNotEqual(hidden.signature,visible.signature)
                    for out in hidden.frames:self.assertEqual(raw,out)
                    if placement=='bottom_rail':self.assertNotEqual(hidden.frames,visible.frames)

    def test_broker_exit_artwork_receipt_restores_power_and_next_admission(self):
        for wrote in (True,False):
            with self.subTest(wrote=wrote),tempfile.TemporaryDirectory() as folder:
                record=[];panel=FaceplateCoordinator(ASSET_ROOT,Path(folder)/'panel.json',steamgriddb=StaticFirstSteamGridDB(),
                    link_factory=lambda **kw:FakeLink(record,wrote,**kw),port_finder=lambda:'/dev/fake',identity_reader=lambda _:'fake')
                panel.configure(True,50)
                engine=SimpleNamespace(settings=Mock(),faceplate=panel,_faceplate_power_target=None,_faceplate_suspended=False,_stop=threading.Event(),
                    thermal_protection=SimpleNamespace(active=False),_display_panel_off=lambda _:False,_broker_allowed=lambda _:True)
                engine.settings.all.return_value={'faceplate_lab_enabled':True}
                adapter=FaceplateBrokerAdapter(engine,ownership_root=Path(folder)/'ownership')
                panel.set_power(False,reason='screensaver-exit');self.assertEqual('DISPLAY_OFF',adapter._policy()['reason'])
                with patch('signalbar.faceplate.coordinator.artwork_render.artwork',return_value=(bytes((20,40,60))*(64*54),'/fake/42.png','hero')):
                    result=panel.synchronize_artwork(42)
                self.assertTrue(result['synchronized']);self.assertTrue(panel.powered)
                self.assertFalse(panel._screensaver_exit_blank);self.assertIsNone(adapter._policy()['reason'])
