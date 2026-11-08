"""Prepared-only playlist, timer, shuffle and Home worker integration."""
import hashlib
import json
from pathlib import Path
import random
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from signalbar.faceplate.home_library import HomeLibrary, inventory
from signalbar.faceplate.coordinator import encode_frame
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate, DASHBOARD_PACK_REVISION
from signalbar.settings import SettingsStore


def prepared(root, appid, colour, stage='prepared', source='grid'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    rgb=bytes(colour)*(64*54);data=encode_frame(rgb)
    record=dict(schema=2,appid=appid,mode='animated',ready=True,frames=1,animated=True,
        asset_kind=source,sha256=hashlib.sha256(data).hexdigest(),dashboard_pack_frames=1,
        dashboard_pack='artwork-dashboard.rgb',dashboard_pack_sha256=hashlib.sha256(rgb).hexdigest(),
        dashboard_pack_revision=DASHBOARD_PACK_REVISION)
    (root/'faceplate.gif').write_bytes(data);(root/'artwork-dashboard.rgb').write_bytes(rgb)
    (root/'manifest.json').write_text(json.dumps(record))
    return record


class HomeLibraryTests(unittest.TestCase):
    def fixture(self, folder):
        library=SteamGridDBFaceplate(Path(folder)/'library')
        for appid,colour in [(620,(100,20,30)),(570,(20,100,30)),(440,(20,30,100))]:
            prepared(library._prepared_root(appid,'animated'),appid,colour)
        return library

    def ready(self, player, **options):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            item=player.current(**options)
            if item is not None:return item
            time.sleep(.002)
        self.fail(player.status())

    def test_inventory_is_prepared_only_deduplicated_filtered_and_never_decodes(self):
        with tempfile.TemporaryDirectory() as folder:
            library=self.fixture(folder)
            prepared(library._prepared_root(620,'static',draft=True),620,(100,20,30))
            prepared(library._prepared_root(999,'animated'),999,(80,80,80),source='other-provider')
            (library.artwork_root/'outside').symlink_to(Path(folder))
            entries=inventory(library,'artwork')
            self.assertEqual(len(entries),3)
            extra=Path(folder)/'independent'/'a';record=prepared(extra,0,(90,30,90));record['creation_id']='a'
            library.independent_creations=SimpleNamespace(entries=lambda:[record],directory=lambda _:extra)
            self.assertEqual(len(inventory(library,'creations')),1)
            self.assertEqual(len(inventory(library,'both')),4)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('No media in metadata inventory')):
                self.assertEqual(len(inventory(library,'both')),4)

    def test_timer_has_all_requested_intervals_and_never_catches_up_in_a_burst(self):
        for interval in (300,900,1800,3600):
            with tempfile.TemporaryDirectory() as folder:
                library=self.fixture(folder);now=[10.]
                player=HomeLibrary(library,clock=lambda:now[0]);self.addCleanup(player.stop)
                first=self.ready(player,interval=interval)
                now[0]+=interval-.01
                self.assertEqual(player.current(interval=interval).key,first.key)
                now[0]+=.01
                second=player.current(interval=interval);self.assertNotEqual(second.key,first.key)
                now[0]+=interval*20
                third=player.current(interval=interval)
                self.assertNotEqual(third.key,second.key)
                self.assertEqual(player.current(interval=interval).key,third.key)

    def test_shuffle_visits_the_bank_and_does_not_repeat_at_a_cycle_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0.];player=HomeLibrary(self.fixture(folder),clock=lambda:now[0],rng=random.Random(4));self.addCleanup(player.stop)
            keys=[self.ready(player,shuffle=True).key]
            for _ in range(8):now[0]+=300;keys.append(player.current(shuffle=True).key)
            for start in (0,3,6):self.assertEqual(len(set(keys[start:start+3])),3)
            self.assertTrue(all(a!=b for a,b in zip(keys,keys[1:])))

    def test_inventory_runs_off_the_caller_thread_and_stale_refresh_cannot_replace_a_new_source(self):
        entered=threading.Event();release=threading.Event();threads=[]
        def load(library,source):
            threads.append(threading.get_ident())
            if source=='artwork':entered.set();release.wait(2)
            return []
        player=HomeLibrary(None,loader=load);self.addCleanup(player.stop)
        self.assertIsNone(player.current());self.assertTrue(entered.wait(1))
        self.assertIsNone(player.current(source='creations'));release.set()
        deadline=time.monotonic()+1
        while player.status()['loading'] and time.monotonic()<deadline:time.sleep(.002)
        self.assertNotIn(threading.get_ident(),threads)
        self.assertEqual(player.options[0],'creations');self.assertEqual(player.status()['count'],0)

    def test_changing_timer_does_not_change_the_visible_picture(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0.];player=HomeLibrary(self.fixture(folder),clock=lambda:now[0]);self.addCleanup(player.stop)
            first=self.ready(player);now[0]=20
            self.assertEqual(player.current(interval=900).key,first.key)
            now[0]=919;self.assertEqual(player.current(interval=900).key,first.key)
            now[0]=920;self.assertNotEqual(player.current(interval=900).key,first.key)

    def test_worker_uses_the_exact_compiled_gif_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            item=inventory(self.fixture(folder),'artwork')[0]
            data,metadata,path=item.load();self.assertEqual(data,path.read_bytes());self.assertEqual(metadata['appid'],0)
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):item.load()

    def test_settings_validate_source_and_every_requested_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'settings.json'))
            self.assertEqual(store.all()['faceplate_home_library_interval'],300)
            for interval in (300,900,1800,3600):
                store.update({'faceplate_home_library_interval':interval})
                self.assertEqual(store.all()['faceplate_home_library_interval'],interval)
            store.update({'faceplate_home_library_interval':1,'faceplate_home_library_source':[]})
            self.assertEqual(store.all()['faceplate_home_library_interval'],300)
            self.assertEqual(store.all()['faceplate_home_library_source'],'artwork')

    def test_home_selection_queues_through_the_existing_worker_with_no_steam_app(self):
        from test_faceplate_display237 import Display237
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);engine,prefs=Display237.engine(self,root)
            library=self.fixture(folder);engine.faceplate.steamgriddb=library
            engine.home_library.stop();engine.home_library=HomeLibrary(library);self.addCleanup(engine.home_library.stop)
            self.ready(engine.home_library)
            prefs.update(home_scene='library')
            engine._reconcile_faceplate('test-library',force=True,hardware=engine.faceplate.status())
            request=engine.faceplate_worker.submit.call_args.args[1]
            self.assertEqual(request['kind'],'artwork');self.assertEqual(request['appid'],0)
            self.assertTrue(request['home_artwork']);self.assertIsNotNone(library.home_selected(0))


if __name__=='__main__':unittest.main()
