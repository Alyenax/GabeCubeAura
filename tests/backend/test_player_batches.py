"""Real validator, cache and GCA-owned playlist; fake USB and monotonic clock."""
import hashlib
import json
import os
import time
import threading
import unittest
from unittest.mock import patch
import test_jsaux_broker_core as fixture
from signalbar.jsaux_broker.core import Broker,BrokerError

class PlayerBatchTests(unittest.TestCase):
    setUp=fixture.CoreTests.setUp;tearDown=fixture.CoreTests.tearDown
    call=fixture.CoreTests.call;ok=fixture.CoreTests.ok;error=fixture.CoreTests.error;content=fixture.CoreTests.content

    def publish(self,count=7):
        self.runtime=self.broker.player_runtime;self.secret='p'*48;self.collection='c'*64;self.sequence=0
        self.ids=[]
        for index in range(count):
            content,_=self.content(seed=index+1);self.ids.append(content)
            self.broker._registered(self.client,content,self.collection)
            result=self.runtime.batches.publish(self.client,dict(token=self.secret,content_id=content,collection_id=self.collection,alignment_ms=0,index=index,count=count))
            self.assertEqual(result['published'],index==count-1)
            if index<count-1:self.assertFalse(self.runtime.bindings)
        self.assertEqual(len(self.broker.contents),4 if count>=4 else count)
        self.key=hashlib.sha256(self.secret.encode()).hexdigest()
        return result

    def player(self,event,**fields):
        self.sequence+=1
        return self.runtime.player(dict(event=event,token=self.secret,collection_id=self.collection,session_id='batch-session',mode='async',sequence=self.sequence,**fields))

    def start(self):
        self.player('open');self.player('ready',ready_mono_ms=None,deadline_mono_ms=None,clock_uncertainty_ms=None)
        lease=self.broker.lease;self.adapter.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        self.player('started',started_mono_ms=None,outcome='independent',candidate_id=None)
        def replace(job,report):self.adapter.jobs.append(job);self.adapter.report=report;return True
        self.adapter.replace=replace
        return lease

    def advance(self,lease):
        self.clock.now+=60;self.broker.tick()
        for _ in range(300):
            if not lease.get('batch_advancing'):break
            time.sleep(.01)
        self.assertFalse(lease.get('batch_advancing'))

    def test_more_than_four_batches_publish_atomically_and_rotate_without_home_or_browser(self):
        self.publish();self.assertIn(self.ids[0],self.broker.contents)
        lease=self.start();operation=lease['operation_id'];generation=lease['generation']
        for index in range(1,9):
            self.advance(lease)
            self.assertEqual(lease['content_id'],self.ids[index%7]);self.assertEqual(lease['batch_index'],index%7)
            self.assertEqual((lease['operation_id'],lease['generation']),(operation,generation))
            self.assertEqual(len(self.broker.contents),4)
            self.adapter.report(operation,transfer_state='confirmed',fresh_ack=True)
            self.player('stop',reason='unloading')
        self.assertEqual(self.adapter.restorations,[])
        self.assertEqual(len(self.adapter.reservations),1)
        self.assertEqual(len(self.adapter.jobs),9)
        self.assertNotIn(self.secret,json.dumps(self.runtime.snapshot()))
        self.assertNotIn(self.secret,self.runtime.path.read_text())

    def test_exit_or_priority_fences_pending_rotation_and_late_ack(self):
        self.publish(2);lease=self.start();old_report=self.adapter.report
        self.advance(lease);self.assertEqual(lease['transfer_state'],'queued')
        old_report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        self.assertEqual(lease['transfer_state'],'queued','Old batch ACK cannot confirm the new batch')
        self.adapter.state['steam']['observed']='inactive';self.broker.tick()
        self.assertFalse(self.broker.is_valid(lease['operation_id']))
        self.adapter.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        self.adapter.state['steam']['observed']='active';before=len(self.adapter.jobs);self.advance(lease)
        self.assertEqual(len(self.adapter.jobs),before);self.assertEqual(len(self.adapter.restorations),1)

    def test_restart_reloads_complete_playlist_without_starting_display(self):
        self.publish();root=self.broker.root;self.broker.stop();self.broker.worker.shutdown(wait=True)
        self.broker=Broker(root,self.adapter,clock=self.clock);self.runtime=self.broker.player_runtime
        for _ in range(300):
            if self.broker.contents.get(self.ids[0],{}).get('metadata') is not None:break
            time.sleep(.01)
        self.assertEqual(len(self.runtime.bindings[self.key]['batches']),7)
        self.assertEqual(self.adapter.jobs,[])
        self.start();self.advance(self.broker.lease)
        self.assertEqual(self.broker.lease['content_id'],self.ids[1])

    def test_failed_final_save_preserves_bindings_and_cleans_new_playlist(self):
        self.runtime=self.broker.player_runtime;content,collection=self.content()
        with patch.object(self.runtime,'_save',side_effect=OSError('full')):
            with self.assertRaises(BrokerError):self.runtime.batches.publish(self.client,dict(token='x'*48,content_id=content,collection_id=collection,alignment_ms=0,index=0,count=1))
        self.assertEqual(self.runtime.bindings,{})
        self.assertEqual(list(self.runtime.batches.root.iterdir()),[])

    def test_wrong_registration_sequence_and_count_cannot_borrow_content(self):
        runtime=self.broker.player_runtime;content,collection=self.content()
        base=dict(token='z'*48,content_id=content,collection_id=collection,alignment_ms=0,index=0,count=2)
        for args in ({**base,'index':1},{**base,'count':513},{**base,'count':True},{**base,'alignment_ms':100},{**base,'collection_id':'f'*64}):
            with self.assertRaises(BrokerError):runtime.batches.publish(self.client,args)
        with self.assertRaises(BrokerError):runtime.batches.publish('other-client',base)
        self.assertFalse(runtime.bindings);self.assertEqual(self.adapter.jobs,[])

    def test_wire_12_is_opt_in_and_does_not_change_legacy_capabilities(self):
        self.broker.player_runtime.start(0);token=self.broker.connect(os.geteuid())
        hello=self.ok('hello',dict(capability=self.broker.capability,client_instance_id=self.client,supported_versions=['1.2','1.1','1.0']),token=token)
        self.assertEqual((hello['negotiated_version'],hello['contract_revision']),('1.2',6))
        self.assertTrue(hello['capabilities']['autonomous_batches'])
        self.error('VERSION_UNSUPPORTED','publish_player_batch',{})

    def test_corrupt_next_batch_holds_current_display_and_records_failure(self):
        self.publish(2);lease=self.start()
        path=self.runtime.batches.root/self.key/(self.ids[1]+'.gif');path.chmod(0o600);path.write_bytes(b'corrupt')
        self.advance(lease)
        self.assertEqual(lease['content_id'],self.ids[0]);self.assertEqual(lease['batch_error'],'CONTENT_INVALID')
        self.assertEqual(len(self.adapter.jobs),1);self.assertEqual(self.adapter.restorations,[])

    def test_rotation_cooldown_keeps_previous_lot_without_home_then_retries(self):
        self.publish(2);lease=self.start();self.advance(lease)
        self.adapter.report(lease['operation_id'],transfer_state='deferred',reason='FLASH_DEFERRED',retry_after_ms=10000)
        self.assertEqual(lease['content_id'],self.ids[0]);self.assertEqual(lease['batch_index'],0)
        self.assertEqual(lease['transfer_state'],'confirmed');self.assertEqual(self.adapter.restorations,[])
        self.advance(lease);self.assertEqual(lease['content_id'],self.ids[1])

    def test_evicted_first_batch_is_reloaded_on_next_activation(self):
        self.publish();first=self.ids[0]
        self.content(seed=20);self.content(seed=21);self.content(seed=22);self.content(seed=23)
        self.assertNotIn(first,self.broker.contents)
        self.start();self.assertEqual(self.broker.lease['content_id'],first)
        self.advance(self.broker.lease);self.assertEqual(self.broker.lease['content_id'],self.ids[1])

    def test_exit_while_next_batch_is_being_read_cannot_queue_late_usb(self):
        self.publish(2);lease=self.start();entered=threading.Event();release=threading.Event()
        original=self.runtime.batches._data
        def read(*args):
            entered.set();self.assertTrue(release.wait(2));return original(*args)
        with patch.object(self.runtime.batches,'_data',side_effect=read):
            self.clock.now+=60;self.broker.tick();self.assertTrue(entered.wait(1))
            self.adapter.state['steam']['observed']='inactive';self.broker.tick();release.set()
            for _ in range(200):
                if not lease.get('batch_advancing'):break
                time.sleep(.01)
        self.assertEqual(len(self.adapter.jobs),1);self.assertEqual(len(self.adapter.restorations),1)
        self.assertFalse(self.broker.is_valid(lease['operation_id']))

    def test_restart_removes_only_unpublished_owned_playlist_files(self):
        self.publish(2);root=self.runtime.batches.root
        orphan=root/('a'*64);orphan.mkdir(mode=0o700);(orphan/('b'*64+'.gif')).write_bytes(b'owned')
        foreign=root/('d'*64);foreign.mkdir(mode=0o700);(foreign/'keep.txt').write_text('keep')
        self.broker.stop();self.broker.worker.shutdown(wait=True)
        self.broker=Broker(self.broker.root,self.adapter,clock=self.clock);self.runtime=self.broker.player_runtime
        self.assertFalse(orphan.exists());self.assertTrue((root/self.key).is_dir())
        self.assertEqual((foreign/'keep.txt').read_text(),'keep')

    def test_unpublish_cancels_playlist_and_removes_its_private_files(self):
        self.publish(2);lease=self.start();self.runtime.remove(dict(token=self.secret))
        self.assertFalse((self.runtime.batches.root/self.key).exists())
        self.assertFalse(self.broker.is_valid(lease['operation_id']))
