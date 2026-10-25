"""GCA runtime ownership: real GIF validation/core, fake USB/Steam clock."""
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import test_jsaux_broker_core as core_fixture
from signalbar.jsaux_broker.core import Broker,BrokerError
from signalbar.jsaux_broker.player_runtime import PlayerRuntime, trusted_origin

class OwnerTests(unittest.TestCase):
    call=core_fixture.CoreTests.call;ok=core_fixture.CoreTests.ok;error=core_fixture.CoreTests.error;content=core_fixture.CoreTests.content
    setUp=core_fixture.CoreTests.setUp;tearDown=core_fixture.CoreTests.tearDown
    def publish(self,mode='async'):
        content,collection=self.content();self.secret='a'*48;self.collection=collection
        self.runtime=self.broker.player_runtime
        self.runtime.publish(self.client,dict(content_id=content,collection_id=collection,mode=mode,token=self.secret,alignment_ms=0))
        self.sequence=0;self.mode=mode;return content
    def player(self,event,**fields):
        self.sequence+=1
        return self.runtime.player(dict(event=event,token=self.secret,session_id='installed-session',collection_id=self.collection,mode=self.mode,sequence=self.sequence,**fields))
    def start(self,mode='async'):
        self.publish(mode);self.player('open')
        self.player('ready',ready_mono_ms=self.broker.now_ms() if mode=='sync' else None,
                    deadline_mono_ms=self.broker.now_ms()+15000 if mode=='sync' else None,clock_uncertainty_ms=1 if mode=='sync' else None)
        lease=self.broker.lease
        self.broker.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        hb=self.player('heartbeat')
        candidate=(hb.get('candidate') or {}).get('candidate_id')
        result=self.player('started',started_mono_ms=self.broker.now_ms() if mode=='sync' else None,outcome='software-coordinated' if mode=='sync' else 'independent',candidate_id=candidate if mode=='sync' else None)
        self.assertTrue(result['gca_owned']);return lease
    def test_legacy_client_schema_and_eight_second_expiry_unchanged(self):
        lease=core_fixture.CoreTests.acquire(self);self.clock.now+=8;self.broker.tick();self.assertEqual(self.broker.lease['reason'],'LEASE_EXPIRED')
    acquire=core_fixture.CoreTests.acquire
    def test_sync_and_async_survive_hours_without_das_requests_or_extra_usb(self):
        for mode in ('async','sync'):
            if mode=='sync':self.tearDown();self.setUp()
            lease=self.start(mode)
            for elapsed in (9,60,1800,7200):
                self.clock.now+=elapsed;self.adapter.state['steam']['observation_age_ms']=0;self.broker.tick()
                self.assertTrue(self.broker.is_valid(lease['operation_id']))
            self.assertEqual(len(self.adapter.jobs),1);self.assertEqual(self.adapter.restorations,[])
            self.player('stop',reason='unloading');self.assertTrue(self.broker.is_valid(lease['operation_id']))
    def test_true_steam_exit_and_unknown_or_old_evidence_stop_without_resurrection(self):
        for state in ({'observed':'inactive'}, {'observed':'unknown'}, {'observation_age_ms':8001}):
            with self.subTest(state=state):
                if self.broker.lease:self.tearDown();self.setUp()
                lease=self.start();self.adapter.state['steam'].update(state);self.broker.tick()
                self.assertEqual(len(self.adapter.restorations),1)
                self.adapter.state['steam'].update(observed='active',observation_age_ms=0);self.broker.tick()
                self.assertFalse(self.broker.is_valid(lease['operation_id']))
    def test_off_suspend_priority_usb_failure_and_broker_stop_still_win(self):
        for change in ({'display_on':False},{'suspended':True},{'thermal_blocked':True},{'priority_active':True}):
            if self.broker.lease:self.tearDown();self.setUp()
            lease=self.start();self.adapter.state['policy'].update(change);self.broker.tick();self.assertFalse(self.broker.is_valid(lease['operation_id']))
        self.tearDown();self.setUp();lease=self.start();self.adapter.report(lease['operation_id'],transfer_state='failed',reason='USB_FAILED');self.assertFalse(self.broker.is_valid(lease['operation_id']))
    def test_no_handoff_before_gate_or_after_deadline_and_no_secret_in_diagnostics(self):
        self.publish();self.player('open')
        with self.assertRaises(BrokerError):self.player('started',started_mono_ms=None,outcome='independent',candidate_id=None)
        self.clock.now+=9;self.broker.tick()
        with self.assertRaises(BrokerError):self.player('heartbeat')
        self.assertNotIn(self.secret,json.dumps(self.runtime.snapshot()))
    def test_binding_persists_revalidates_content_and_never_plays_on_boot(self):
        content=self.publish();root=self.broker.root;self.broker.stop();self.broker.worker.shutdown(wait=True)
        self.broker=Broker(root,self.adapter,clock=self.clock);self.runtime=self.broker.player_runtime
        for _ in range(200):
            if self.broker.contents[content]['metadata'] is not None:break
            time.sleep(.01)
        self.assertEqual(self.adapter.jobs,[]);self.assertEqual(len(self.runtime.bindings),1)
        self.player('open');self.assertEqual(self.adapter.jobs,[])
        self.assertNotIn(self.secret,(root/'installed-players.json').read_text())
    def test_unpublish_preempts_active_and_failed_save_keeps_previous_binding(self):
        lease=self.start();old=copy.deepcopy(self.runtime.bindings)
        with patch.object(self.runtime,'_save',side_effect=OSError(28,'full')):
            with self.assertRaises(BrokerError):self.runtime.remove(dict(token=self.secret))
        self.assertEqual(old,self.runtime.bindings);self.assertTrue(self.broker.is_valid(lease['operation_id']))
        self.runtime.remove(dict(token=self.secret));self.assertFalse(self.broker.is_valid(lease['operation_id']))
    def test_wrong_token_collection_mode_duplicate_and_stale_messages_fail(self):
        self.publish();self.player('open')
        for field,value in (('token','b'*48),('collection_id','0'*64),('mode','sync'),('sequence',1)):
            self.sequence+=1;p=dict(event='heartbeat',token=self.secret,collection_id=self.collection,session_id='installed-session',mode=self.mode,sequence=self.sequence);p[field]=value
            with self.assertRaises(BrokerError):self.runtime.player(p)
        self.assertEqual(self.adapter.jobs,[])
    def test_optional_wire_11_and_legacy_10_negotiate_separately(self):
        self.runtime=self.broker.player_runtime;self.runtime.start(0)
        token=self.broker.connect(os.geteuid())
        value=self.ok('hello',dict(capability=self.broker.capability,client_instance_id=self.client,supported_versions=['1.1','1.0']),token=token)
        self.assertEqual(value['negotiated_version'],'1.1');self.assertEqual(value['contract_revision'],5)
        self.assertTrue(value['capabilities']['autonomous_player'])
        self.error('VERSION_UNSUPPORTED','remove_player',dict(token='a'*48))
        self.assertTrue(self.call('status',{},token=token,version='1.1')['ok'])
    def test_http_origin_host_body_and_token_boundaries(self):
        self.publish();self.runtime.start(0);port=self.runtime.port
        for origin in ('null','https://evil.test','https://other.steamscreensavers.host'):
            c=http.client.HTTPConnection('127.0.0.1',port,timeout=2);c.request('OPTIONS','/jsaux/v1/player',headers={'Origin':origin,'Access-Control-Request-Method':'POST'});r=c.getresponse();self.assertEqual(r.status,403);r.read();c.close()
        c=http.client.HTTPConnection('127.0.0.1',port,timeout=2);c.request('POST','/jsaux/v1/player',body=json.dumps(dict(event='open',token=self.secret,collection_id=self.collection,session_id='from-http',mode='async',sequence=1)),headers={'Origin':'https://decky-animated-screensaver.steamloopback.host','Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,200);self.assertTrue(json.loads(r.read())['accepted']);c.close();self.assertEqual(self.adapter.jobs,[])
