# SPDX-License-Identifier: GPL-3.0-only
# Copyright 2026 Alyenax; see LICENSING.md for scope and prior rights.
"""Installed-player rendezvous owned by GCA. No media/USB/remote-network route.

The Studio publishes immutable identities through authenticated Unix control.
A per-export secret authorizes only the installed player's short startup exchange.
After TV start, GCA's independent Steam observation owns display lifetime.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .core import BrokerError, digest, ident, integer
from .player_batches import PlayerBatches,valid_rows

PORT=37680
PATH='/jsaux/v1/player'
CLIENT='gca-installed-player'
ENDS={'player-ended','visibility-hidden','unloading','frozen','destroyed','manual-pause','catalog-replaced','coordinated-ended','broker-refused','transport-lost','lease-expired'}
BASE={'event','token','collection_id','session_id','mode','sequence'}
EXTRA={'open':set(),'clock':set(),'heartbeat':set(),'ready':{'ready_mono_ms','deadline_mono_ms','clock_uncertainty_ms'},'started':{'started_mono_ms','outcome','candidate_id'},'stop':{'reason'}}

def trusted_origin(value):
    try:
        if not isinstance(value,str) or not value.isascii() or len(value)>253:return False
        u=urlsplit(value);host=u.hostname or ''
        return value=='https://'+host and not u.port and (host in ('uioverride-decky-animated-screensaver.steamscreensavers.host','decky-animated-screensaver.steamscreensavers.host') or re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*steamloopback\.host',host) is not None)
    except (ValueError,AttributeError):return False

class PlayerRuntime:
    def __init__(self,broker):
        self.broker=broker;self.path=broker.root/'installed-players.json'
        self.bindings={};self.sessions={};self.server=None;self.thread=None
        self.events=[];self.port=PORT;self.slots=threading.BoundedSemaphore(4)
        self.tokens=40.;self.refilled=time.monotonic()
        self._load()
        self.batches=PlayerBatches(self)

    def _event(self,event,reason=''):
        self.events=(self.events+[dict(at=int(time.time()),event=event,reason=reason)])[-24:]

    def _read(self):
        if not self.path.exists() and not self.path.is_symlink():return {}
        st=self.path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_nlink!=1 or stat.S_IMODE(st.st_mode)!=0o600 or st.st_size>1024**2:raise ValueError('unsafe binding file')
        fd=os.open(self.path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            if os.fstat(fd).st_ino!=st.st_ino:raise ValueError('binding changed')
            with os.fdopen(fd,'r',closefd=False) as f:return json.load(f)
        finally:os.close(fd)

    def _load(self):
        try:
            saved=self._read()
            if not isinstance(saved,dict) or len(saved)>4:raise ValueError()
            for key,b in saved.items():
                if not digest(key) or not isinstance(b,dict) or set(b) not in ({'content_id','collection_id','mode','alignment_ms'},{'content_id','collection_id','mode','alignment_ms','batches'}) or not digest(b['content_id']) or not digest(b['collection_id']) or b['mode'] not in ('sync','async') or type(b['alignment_ms']) is not int or not -10000<=b['alignment_ms']<=10000 or b['alignment_ms']%100:raise ValueError()
                if 'batches' in b and (b['mode']!='async' or not valid_rows(b['batches']) or b['content_id']!=b['batches'][0]['content_id']):raise ValueError()
            self.bindings=saved
        except (OSError,ValueError,TypeError):self._event('binding-load-failed','CONTENT_INVALID')

    def _save(self,value):
        # Existing metadata is checked before replacement; failures preserve RAM/disk.
        self._read()
        temp=self.path.with_name('installed-players-'+os.urandom(8).hex()+'.tmp')
        try:
            fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f:
                json.dump(value,f,separators=(',',':'));f.flush();os.fsync(f.fileno())
            os.replace(temp,self.path)
        finally:temp.unlink(missing_ok=True)
        self.bindings=value

    def publish(self,client,args):
        b=self.broker
        if not ident(args['token']) or len(args['token'])<32 or args['mode'] not in ('sync','async') or not digest(args['content_id']) or not digest(args['collection_id']) or type(args['alignment_ms']) is not int or not -10000<=args['alignment_ms']<=10000 or args['alignment_ms']%100:raise BrokerError('INVALID_REQUEST')
        content=b.contents.get(args['content_id'])
        if not content or content['metadata'] is None or (client,args['content_id'],args['collection_id']) not in b.registration:raise BrokerError('CONTENT_MISSING')
        key=hashlib.sha256(args['token'].encode()).hexdigest();value={k:v for k,v in args.items() if k!='token'}
        if key in self.bindings and self.bindings[key]!=value:raise BrokerError('REQUEST_CONFLICT')
        if key not in self.bindings and len(self.bindings)>=4:raise BrokerError('CACHE_FULL')
        try:self._save({**self.bindings,key:value})
        except (OSError,ValueError,TypeError):raise BrokerError('CONTENT_INVALID') from None
        self._event('studio-published')
        return self.descriptor()

    def descriptor(self):
        return dict(controller='GabeCubeAura',relay=dict(kind='http-loopback-v1',url=f'http://127.0.0.1:{self.port}{PATH}'))

    def remove(self,args):
        if not ident(args['token']):raise BrokerError('INVALID_REQUEST')
        key=hashlib.sha256(args['token'].encode()).hexdigest();value=dict(self.bindings);value.pop(key,None)
        try:self._save(value)
        except (OSError,ValueError,TypeError):raise BrokerError('CONTENT_INVALID') from None
        for s in self.sessions.values():
            if s['binding']==key:
                lease=self.broker.operations.get(s['operation_id'])
                if lease and lease['lease_state'] not in {'released','expired','preempted','rejected','revoking'}:self.broker._revoke(lease,'USER_DISABLED','released')
        self.batches.remove(key)
        self._event('studio-removed');return dict(removed=True)

    def calibrate(self,args):
        if not ident(args['token']) or type(args['alignment_ms']) is not int or not -10000<=args['alignment_ms']<=10000 or args['alignment_ms']%100:raise BrokerError('INVALID_REQUEST')
        key=hashlib.sha256(args['token'].encode()).hexdigest()
        if key not in self.bindings:raise BrokerError('CONTENT_MISSING')
        value=dict(self.bindings);value[key]={**value[key],'alignment_ms':args['alignment_ms']}
        try:self._save(value)
        except (OSError,ValueError):raise BrokerError('CONTENT_INVALID') from None
        return dict(saved=True)

    def state(self,args):
        if not ident(args['token']):raise BrokerError('INVALID_REQUEST')
        key=hashlib.sha256(args['token'].encode()).hexdigest()
        sessions=[s for s in self.sessions.values() if s['binding']==key]
        lease=self.broker.operations.get(sessions[-1]['operation_id']) if sessions else None
        terminal=not lease or lease['lease_state'] in {'released','expired','preempted','rejected','revoking'}
        return dict(controller='GabeCubeAura',published=key in self.bindings,first_player=bool(sessions),
            phase=('restoring' if lease and lease['restore_state'] in {'pending','deferred'} else 'idle') if terminal else 'active' if lease.get('gca_owned') else 'transferring',
            reason=lease['reason'] if lease else '',last_transfer=lease['transfer_state'] if lease else 'not-started',
            restore_state=lease['restore_state'] if lease else 'not-needed',
            batch_index=lease.get('batch_index',0) if lease else 0,batch_count=len(self.bindings.get(key,{}).get('batches',[])),
            batch_error=lease.get('batch_error','') if lease else '')

    def pinned(self,key):return any(b['content_id']==key and 'batches' not in b for b in self.bindings.values())
    def snapshot(self):
        lease=self.broker.lease
        return dict(controller='GabeCubeAura',available=self.server is not None,published=len(self.bindings),
                    steam_owned=bool(lease and lease.get('gca_owned') and lease['lease_state'] not in {'released','expired','preempted','rejected','revoking'}),events=list(self.events))

    def player(self,p):
        b=self.broker
        event=p.get('event') if isinstance(p,dict) else None
        if event not in EXTRA or set(p)!=BASE|EXTRA[event] or not ident(p['token']) or not ident(p['session_id']) or not integer(p['sequence'],1) or not digest(p['collection_id']):raise BrokerError('INVALID_REQUEST')
        if event=='stop' and p['reason'] not in ENDS:raise BrokerError('INVALID_REQUEST')
        binding=hashlib.sha256(p['token'].encode()).hexdigest()
        with b.lock:
            now=time.monotonic();self.tokens=min(40.,self.tokens+max(0,now-self.refilled)*20);self.refilled=now
            if self.tokens<1:raise BrokerError("RATE_LIMITED")
            self.tokens-=1
            b.tick();published=self.bindings.get(binding)
            if not published:raise BrokerError('AUTH_DENIED')
            if published['collection_id']!=p['collection_id'] or published['mode']!=p['mode']:raise BrokerError('CONTENT_MISSING')
            key=(binding,p['session_id']);session=self.sessions.get(key)
            if event=='open':
                if session:raise BrokerError('STALE_GENERATION')
                if 'batches' in published:self.batches.first(binding,published)
                content=b.contents.get(published['content_id'])
                if not content or content['metadata'] is None:raise BrokerError('CONTENT_MISSING')
                b.registration[(CLIENT,published['content_id'],published['collection_id'])]=True
                steam=b._policy(flash=False)['steam']
                lease=b._acquire_display(CLIENT,dict(activation_id=steam['activation_id'],session_id=p['session_id'],content_id=published['content_id'],collection_id=published['collection_id'],mode=published['mode']))
                session=dict(binding=binding,sequence=p['sequence'],operation_id=lease['operation_id'],lease_id=lease['lease_id'],generation=lease['generation'],alignment_attempt_id=lease.get('alignment_attempt_id'),renew=0)
                self.sessions[key]=session
                for old in list(self.sessions):
                    if len(self.sessions)<=32:break
                    if self.sessions[old]['operation_id']!=lease['operation_id']:del self.sessions[old]
                self._event('player-open');return dict(accepted=True,alignment_ms=published['alignment_ms'],lease_remaining_ms=lease['expires_in_ms'])
            if not session or p['sequence']<=session['sequence']:raise BrokerError('STALE_GENERATION')
            session['sequence']=p['sequence'];lease=b.operations.get(session['operation_id'])
            if not lease:raise BrokerError('OPERATION_UNKNOWN')
            common=dict(lease_id=session['lease_id'],generation=session['generation'])
            if lease.get('gca_owned'):
                if lease['lease_state'] in {'released','expired','preempted','rejected','revoking'}:raise BrokerError(lease['reason'] or 'LEASE_EXPIRED')
                # Browser visibility, closing or losing its relay cannot end a Steam-owned display.
                return dict(accepted=True,gca_owned=True)
            if event=='stop':return dict(accepted=True,**b._release_display(CLIENT,{**common,'reason':'player-ended'}))
            if lease['lease_state'] in {'released','expired','preempted','rejected','revoking'}:raise BrokerError(lease['reason'] or 'LEASE_EXPIRED')
            if event=='clock':return dict(accepted=True,broker_mono_ms=b.now_ms())
            if event=='ready':
                # Current preparations use 15s; an already prepared 2.5s export
                # may be installed again without encoding its media a second time.
                if published['mode']=='sync' and (not integer(p['deadline_mono_ms']) or not integer(p['ready_mono_ms']) or p['deadline_mono_ms']-p['ready_mono_ms'] not in (2500,15000)):raise BrokerError('INVALID_REQUEST')
                return b._player_ready(CLIENT,{**common,'alignment_attempt_id':session['alignment_attempt_id'],**{k:p[k] for k in EXTRA[event]}})
            if event=='heartbeat':
                session['renew']+=1;b._renew_display(CLIENT,{**common,'sequence':session['renew']})
                value=b._operation_status(CLIENT,dict(operation_id=session['operation_id']))
                candidate=value.get('candidate');result=dict(accepted=True,lease_remaining_ms=value['expires_in_ms'])
                if candidate:
                    result.update(candidate=candidate,timing=dict(reference_mono_ms=lease['events']['candidate'],uncertainty_ms=1,basis='broker-confirmation-event'))
                return result
            if event=='started':
                b._policy(lease['activation_id'],flash=False,continuity=True)
                if lease['gate'] is None:raise BrokerError('GATE_CONFLICT')
                b._tv_started(CLIENT,{**common,'alignment_attempt_id':session['alignment_attempt_id'],**{k:p[k] for k in EXTRA[event]}})
                if p['outcome']=='tv-only':return dict(accepted=True)
                lease['gca_owned']=True;self.batches.attach(lease,binding);self._event('steam-handoff')
                return dict(accepted=True,gca_owned=True)
        raise BrokerError('INVALID_REQUEST')

    def start(self,port=PORT):
        if self.server:return
        runtime=self
        class Server(ThreadingHTTPServer):
            daemon_threads=True;block_on_close=False;allow_reuse_address=True;request_queue_size=4
            def get_request(self):
                s,a=super().get_request();s.settimeout(3);return s,a
            def process_request(self,s,a):
                if not runtime.slots.acquire(False):self.shutdown_request(s);return
                try:super().process_request(s,a)
                except BaseException:runtime.slots.release();raise
            def process_request_thread(self,s,a):
                try:super().process_request_thread(s,a)
                finally:runtime.slots.release()
            def handle_error(self,*args):pass
        class Handler(BaseHTTPRequestHandler):
            server_version='GCAPlayer/1';sys_version=''
            def log_message(self,*args):pass
            def reply(self,status,value,origin=None):
                data=json.dumps(value,separators=(',',':')).encode();self.send_response(status)
                for k,v in [('Content-Type','application/json'),('Content-Length',str(len(data))),('Cache-Control','no-store'),('Connection','close')]:self.send_header(k,v)
                if origin:
                    for k,v in [('Access-Control-Allow-Origin',origin),('Vary','Origin'),('Access-Control-Allow-Methods','POST, OPTIONS'),('Access-Control-Allow-Headers','Content-Type'),('Access-Control-Allow-Private-Network','true')]:self.send_header(k,v)
                self.end_headers();self.wfile.write(data)
            def boundary(self):
                origins=self.headers.get_all('Origin',[])
                if self.path!=PATH or self.headers.get_all('Host',[])!=[f'127.0.0.1:{runtime.port}'] or len(origins)!=1 or not trusted_origin(origins[0]):return None
                return origins[0]
            def do_OPTIONS(self):
                origin=self.boundary()
                valid=origin and self.headers.get('Access-Control-Request-Method')=='POST' and {v.strip().lower() for v in self.headers.get('Access-Control-Request-Headers','').split(',') if v.strip()}<={'content-type'}
                self.reply(204 if valid else 403,{},origin if valid else None)
            def do_POST(self):
                origin=self.boundary()
                if not origin:self.reply(403,{});return
                lengths=self.headers.get_all('Content-Length',[])
                if len(lengths)!=1 or not re.fullmatch(r'[0-9]{1,4}',lengths[0]) or not 1<=int(lengths[0])<=4096 or self.headers.get('Transfer-Encoding') is not None or self.headers.get('Content-Type','').split(';')[0]!='application/json':self.reply(400,{},origin);return
                try:
                    from .server import decode_message
                    raw=self.rfile.read(int(lengths[0]));
                    if len(raw)!=int(lengths[0]):raise ValueError()
                    p=decode_message(raw+b'\n')
                    # Wait for independent GCA observation/content revalidation, never retry acquisition.
                    if p.get('event')=='open':
                        until=time.monotonic()+2.2
                        while time.monotonic()<until:
                            with runtime.broker.lock:
                                snap=runtime.broker._snapshot()['steam'];ready=all(c['metadata'] is not None for c in runtime.broker.contents.values())
                            if snap['observed']=='active' and snap.get('activation_closed'):break
                            if snap['observed']=='active' and ready:break
                            time.sleep(.05)
                    value=runtime.player(p)
                except BrokerError as e:value=dict(accepted=False,reason=e.code)
                except (ValueError,OSError,KeyError,TypeError):self.reply(400,{},origin);return
                except Exception:runtime._event('player-error','INTERNAL_ERROR');self.reply(503,{},origin);return
                self.reply(200,value,origin)
        self.server=Server(('127.0.0.1',port),Handler);self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs=dict(poll_interval=.1),name='gca-player',daemon=True);self.thread.start()

    def close(self):
        if self.server:self.server.shutdown();self.server.server_close();self.server=None
        if self.thread and self.thread is not threading.current_thread():self.thread.join(1)
