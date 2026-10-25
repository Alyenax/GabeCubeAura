"""Real stores, sysfs adapter and broker; only I/O faults are injected."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from signalbar.core.profiles import Profiles
from signalbar.settings import SettingsStore
from signalbar.hardware import ValveLedHardware
from signalbar.renderer import Renderer
import test_jsaux_broker_core as fixtures

class PersistenceReauditTests(unittest.TestCase):
    def test_profile_precommit_failure_preserves_library_and_active_overlay(self):
        for operation in ('create','replace','delete'):
            for failure in ('open','replace'):
                with self.subTest(operation=operation,failure=failure),tempfile.TemporaryDirectory() as folder:
                    store=SettingsStore(str(Path(folder)/'config.json'));profiles=Profiles(folder,store,store.set_overlay)
                    profiles.save('Evening',{'light_bar_day_brightness':20});identifier=next(iter(profiles.items));profiles.activate(identifier)
                    memory=copy.deepcopy(profiles.items);disk=profiles.path.read_bytes();overlay=store.all()
                    target='signalbar.core.profiles.tempfile.mkstemp' if failure=='open' else 'signalbar.core.profiles.os.replace'
                    with patch(target,side_effect=OSError('Synthetic ENOSPC')):
                        with self.assertRaises(OSError):
                            if operation=='delete':profiles.delete(identifier)
                            else:profiles.save('Changed',{'light_bar_day_brightness':30},identifier if operation=='replace' else '')
                    self.assertEqual(memory,profiles.items);self.assertEqual(disk,profiles.path.read_bytes())
                    self.assertEqual(memory,Profiles(folder,store,store.set_overlay).items)
                    self.assertEqual(identifier,profiles.active);self.assertEqual(overlay,store.all())
                    self.assertEqual([],list(Path(folder).glob('.ambience-*')))
                    profiles.delete(identifier);self.assertEqual({},profiles.items);self.assertFalse(store.overlay_active())

    def test_real_hardware_restores_latest_external_gain_and_respects_final_owner(self):
        for final_external in (False,True):
            with self.subTest(final_external=final_external),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);paths=[]
                for n in range(17):
                    leaf=root/f'valve-leds[{n}]';leaf.mkdir();(leaf/'multi_intensity').write_text('0 0 0');(leaf/'brightness').write_text('255');paths.append(str(leaf))
                first=Path(paths[0]);(first/'effect').write_text('normal');(first/'enabled').write_text('1');(first/'brightness_scale').write_text('78')
                hw=ValveLedHardware(paths);now=[1.];journal=root/'gain.json';r=Renderer(hw,clock=lambda:now[0],brightness_recovery_path=str(journal))
                r.set_output_brightness_scale(9);r.render([(1,2,3)]*17)
                for external,reference in ((31,9),(42,4),(31,9)):
                    first.joinpath('brightness_scale').write_text(str(external));now[0]+=.2;r.set_output_brightness_scale(reference);r.render([(2,3,4)]*17,force=True)
                self.assertEqual(31,json.loads(journal.read_text())['saved_brightness_scale'])
                if final_external:first.joinpath('brightness_scale').write_text('55')
                r.relinquish(True)
                self.assertEqual(55 if final_external else 31,hw.read_brightness_scale());self.assertFalse(journal.exists())

    def test_broker_replace_chmod_and_cleanup_faults_free_validation_slot(self):
        for failure in ('replace','chmod','cleanup'):
            with self.subTest(failure=failure):
                f=fixtures.CoreTests();f.setUp()
                try:
                    b=f.broker;data=fixtures.gif();sha=hashlib.sha256(data).hexdigest();collection=hashlib.sha256(b'collection').hexdigest()
                    upload=f.ok('register_content',dict(sha256=sha,size_bytes=len(data),collection_id=collection))['upload_id']
                    f.ok('content_chunk',dict(upload_id=upload,offset=0,data_base64=base64.b64encode(data).decode()))
                    worker_errors=[]
                    def submit(fn,*args):
                        try:fn(*args)
                        except Exception as error:worker_errors.append(type(error).__name__)
                    b.worker.submit=submit
                    target={'replace':'signalbar.jsaux_broker.core.os.replace','chmod':'signalbar.jsaux_broker.core.os.chmod','cleanup':'pathlib.Path.unlink'}[failure]
                    with patch.object(b,'validator',return_value={}),patch(target,side_effect=OSError('Synthetic EIO')):
                        validation=f.ok('commit_content',dict(upload_id=upload))['validation_id']
                    self.assertEqual('ready' if failure=='cleanup' else 'rejected',b.validations[validation]['state'])
                    self.assertEqual({},b.uploads);self.assertEqual([],f.adapter.jobs)
                    b.tick();self.assertEqual([],list(b.staging_dir.iterdir()))
                    self.assertTrue(f.call('register_content',dict(sha256='b'*64,size_bytes=len(data),collection_id=collection))['ok'])
                finally:f.tearDown()

    def test_profile_postcommit_cleanup_failure_is_identified_and_memory_matches_disk(self):
        from signalbar.core.profiles import ProfilesCommittedError
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'config.json'));profiles=Profiles(folder,store,store.set_overlay)
            with patch('signalbar.core.profiles.os.unlink',side_effect=OSError('Synthetic cleanup EIO')):
                with self.assertRaises(ProfilesCommittedError) as error:profiles.save('Evening',{'light_bar_day_brightness':20})
            self.assertTrue(error.exception.committed)
            self.assertEqual(profiles.items,Profiles(folder,store,store.set_overlay).items)
