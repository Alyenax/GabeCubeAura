"""Home prepared images reach the original-image LED projection without AppID."""
from pathlib import Path
import tempfile
import time
import unittest

from signalbar.faceplate.home_library import HomeLibrary
from signalbar.faceplate.source_projection import background_key
from signalbar.models import GameState
import test_faceplate_display237 as display_fixture
import test_home_library as home_fixture


class HomeExtensionTests(unittest.TestCase):
    def test_home_zero_id_requires_a_verified_original_and_home_scope(self):
        for kind,flag in [('artwork','home_artwork'),('artwork-dashboard','home_dashboard')]:
            payload={'kind':kind,'appid':0,flag:True}
            key=background_key(payload,'home',0,'source-a')
            self.assertIsNotNone(key)
            self.assertEqual(key,background_key({**payload,'battery':{'percent':50},'display_at':'another minute'},'home',0,'source-a'))
            self.assertNotEqual(key,background_key(payload,'home',0,'source-b'))
            self.assertIsNone(background_key(payload,'game',620,'source-a'))
            self.assertIsNone(background_key(payload,'home',0,''))
            self.assertIsNone(background_key({'kind':kind,'appid':0},'home',0,'source-a'))

    def fixture(self, root):
        engine,prefs=display_fixture.Display237.engine(self,root)
        library=home_fixture.HomeLibraryTests.fixture(self,root)
        engine.faceplate.steamgriddb=library
        engine.home_library.stop();engine.home_library=HomeLibrary(library)
        home_fixture.HomeLibraryTests.ready(self,engine.home_library)
        prefs.update(home_scene='library')
        engine.faceplate.port_finder=lambda:None
        engine._faceplate_extension_present=True
        return engine,prefs,library

    def test_real_home_playlist_publishes_original_before_ack_and_real_projection_works(self):
        with tempfile.TemporaryDirectory() as folder:
            engine,_,_=self.fixture(Path(folder))
            engine._reconcile_faceplate('test-home-projection',force=True,hardware=engine.faceplate.status())
            payload=engine.faceplate_worker.submit.call_args.args[1]
            self.assertEqual(0,payload['appid']);self.assertTrue(payload['_extension_background_key'])
            ticket=payload['ticket'];engine.faceplate_router.mark_preparing(ticket)
            result=engine._synchronize_artwork_with_projection(payload,ticket,None)
            self.assertFalse(result.get('synchronized'))  # No device; no physical claim.
            self.assertTrue(engine._faceplate_extension_source['prepared'])
            engine.faceplate.powered=True
            values=engine.settings.all()
            engine._faceplate_extension_output(values,GameState(),'faceplate_extension',time.monotonic())
            provider=engine.faceplate_extension
            with provider.condition:
                self.assertTrue(provider.condition.wait_for(lambda:provider.phase in ('ready','error'),timeout=5),provider.status())
            self.assertEqual('ready',provider.status()['phase'])
            output=engine._faceplate_extension_output(values,GameState(),'faceplate_extension',time.monotonic()+1)
            # Sorted Home library starts with the 440 fixture's blue image.
            self.assertEqual(((20,30,100),)*17,output.frame)
            self.assertFalse(engine._faceplate_extension_status()['faceplate_confirmed'])

    def test_old_home_preparation_cannot_replace_a_new_home_image(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);engine,_,library=self.fixture(root)
            engine._reconcile_faceplate('first',force=True,hardware=engine.faceplate.status())
            old=engine.faceplate_worker.submit.call_args.args[1]
            _,_,source=engine._dashboard_background(0,home=True)
            item=library.home_library_entry
            home_fixture.prepared(item.path.parent,440,(90,10,20))
            # Refresh metadata explicitly, without relying on a wall-clock wait.
            engine.home_library.items=[];engine.home_library.loaded=False
            home_fixture.HomeLibraryTests.ready(self,engine.home_library)
            engine._reconcile_faceplate('new-image',force=True,hardware=engine.faceplate.status())
            newer=engine.faceplate_worker.submit.call_args.args[1]
            self.assertNotEqual(old['_extension_background_key'],newer['_extension_background_key'])
            self.assertFalse(engine._publish_faceplate_extension_source(old,old['ticket'],{},source,prepared=True))


if __name__=='__main__':unittest.main()
