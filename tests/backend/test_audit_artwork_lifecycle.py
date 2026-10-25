"""GH-01/GH-02: actual coordinator, engine tickets and fake USB only."""
from itertools import product
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from signalbar.backend import Engine
from signalbar.faceplate.coordinator import FaceplateCoordinator
from signalbar.settings import SettingsStore
from test_faceplate import ASSET_ROOT, FakeLink, StaticFirstSteamGridDB

class ArtworkLifecycleTests(unittest.TestCase):
    def test_blocked_render_cannot_outlive_off_stop_or_route_replacement(self):
        for transition,kind in product(('off', 'stop', 'replace', 'cancel'),('artwork','artwork-dashboard')):
            with self.subTest(transition=transition,kind=kind), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); record=[]; entered=threading.Event(); release=threading.Event()
                engine=Engine(SettingsStore(str(root/'config.json')),str(root/'cache'))
                coordinator=FaceplateCoordinator(ASSET_ROOT,root/'panel.json',steamgriddb=StaticFirstSteamGridDB(),
                    link_factory=lambda **kw:FakeLink(record,True,**kw),port_finder=lambda:'/dev/fake',identity_reader=lambda _: 'fake')
                coordinator.configure(True,50);engine.faceplate=coordinator;engine.assistant=Mock(active=False)
                engine.faceplate_worker=Mock()
                engine._write_faceplate_runtime_status=lambda:None
                engine._dashboard_background=lambda *args,**kwargs:None
                ticket=engine.faceplate_router.reconcile(game_running=kind=='artwork',content_key='A',force=True)
                cancelled=threading.Event()
                def render(*args,**kwargs):
                    entered.set();assert release.wait(2)
                    return bytes((20,40,60))*(64*54),'/fake/42.png','hero'
                result=[]
                with patch('signalbar.faceplate.coordinator.artwork_render.artwork',side_effect=render):
                    worker=threading.Thread(target=lambda:result.append(engine._handle_faceplate_scene(
                        {'payload':{'kind':kind,'ticket':ticket,'appid':42,'home_dashboard':kind=='artwork-dashboard'},'_cancelled':cancelled})))
                    worker.start();self.assertTrue(entered.wait(2))
                    if transition=='off':self.assertTrue(engine.set_faceplate_power(False)['ok'])
                    elif transition=='stop':engine._stop.set()
                    elif transition=='replace':engine.faceplate_router.reconcile(game_running=True,content_key='B',force=True)
                    else:cancelled.set()
                    before=len(record);release.set();worker.join(2)
                self.assertFalse(worker.is_alive());self.assertTrue(result[0].get('superseded',False))
                self.assertEqual(record[before:],[])
                self.assertNotEqual('A',engine.faceplate_router.status()['effective_content_key'])

    def test_confirmed_or_already_stored_receipt_closes_broker_return(self):
        for wrote in (True, False):
            with self.subTest(wrote=wrote),tempfile.TemporaryDirectory() as directory:
                record=[];root=Path(directory)
                coordinator=FaceplateCoordinator(ASSET_ROOT,root/'panel.json',steamgriddb=StaticFirstSteamGridDB(),
                    link_factory=lambda **kw:FakeLink(record,wrote,**kw),port_finder=lambda:'/dev/fake',identity_reader=lambda _:'fake')
                coordinator.configure(True,50)
                with patch('signalbar.faceplate.coordinator.artwork_render.artwork',return_value=(bytes((20,40,60))*(64*54),'/fake/42.png','hero')):
                    result=coordinator.synchronize_artwork(42)
                self.assertTrue(result.get('synchronized',False));self.assertTrue(result['found'])
                self.assertEqual(wrote,result['wrote'])
