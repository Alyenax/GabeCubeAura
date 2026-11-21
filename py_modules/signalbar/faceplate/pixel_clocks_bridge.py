# SPDX-License-Identifier: GPL-3.0-only
"""Authenticated local external-clock bridge. No game artwork or serial access.

Routes remain GCA's atomic preferences. Both panels call set_destinations;
source packets are fenced by route revision, context, client boot and model.
"""
import base64
from collections import OrderedDict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import socketserver
import stat
import struct
import subprocess
import tempfile
import threading
import time
from zoneinfo import ZoneInfo
from signalbar import FACEPLATE_GIF_LIMIT
from .scene_renderer import _renderer_environment

PROTOCOL='pixel-clocks-bridge'
VERSION=1
SCENE='pixel-clocks'
DESTINATIONS=('home','game','both','none')
MAX_MESSAGE=131072
LEASE_SECONDS=8
GIF_LIMIT = FACEPLATE_GIF_LIMIT or 81920


class BridgeError(ValueError):
    pass


def runtime_path():
    home=Path(os.environ.get('DECKY_USER_HOME') or Path.home())
    return Path(os.environ.get('GCA_PIXEL_CLOCKS_RUNTIME') or home/'.local/share/gabecubeaura/pixel-clocks')


def _atomic(path,value):
    fd,name=tempfile.mkstemp(prefix='.bridge-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f,separators=(',',':'));f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class PixelClocksBridge:
    def __init__(self,engine,root=None,*,clock=time.monotonic,wall=time.time):
        self.engine=engine;self.root=Path(root) if root else runtime_path()
        self.clock=clock;self.wall=wall;self.lock=threading.RLock()
        self.boot_id=secrets.token_hex(16);self.token=secrets.token_hex(32)
        self.client=None;self.seen=-100.;self.seen_wall=-100.;self.model='';self.models=[]
        self.previous={};self.weather_revision=0;self.packets=[];self.receipts=OrderedDict()
        self.server=None;self.thread=None;self.start_error=''
        self.last_sha='';self.confirmed_sha='';self.last_result='idle'
        self.confirmed_until = None
        self.weather_identity=None
        self.slots=threading.BoundedSemaphore(2)

    def present(self):return bool(self.client and 0<=self.clock()-self.seen<LEASE_SECONDS and 0<=self.wall()-self.seen_wall<LEASE_SECONDS)

    def _routes(self):
        p=self.engine.faceplate_preferences.read()
        return p,{'home':p.home_scene,'game':p.game_scene}

    @staticmethod
    def destination(routes):
        h=routes['home']==SCENE;g=routes['game']==SCENE
        return 'both' if h and g else 'home' if h else 'game' if g else 'none'

    def _save(self):
        if self.root.is_dir():_atomic(self.root/'state.json',dict(previous=self.previous,weather_revision=self.weather_revision))

    def _expire(self):
        if self.client and not self.present():
            self.client=None;self.packets=[]
            self.last_result='disconnected'
            self.engine._faceplate_next_reconcile=0.

    def weather(self):
        values=self.engine.settings.all()
        identity=json.dumps([values.get('weather_location'),values.get('weather_temperature_unit')],sort_keys=True)
        if self.weather_identity is None:self.weather_identity=identity
        elif identity!=self.weather_identity:
            self.weather_identity=identity;self.weather_revision+=1;self.packets=[];self.confirmed_sha=''
            self.engine.faceplate_router.invalidate('pixel-clocks-weather-changed');self.engine._faceplate_next_reconcile=0.
        w=self.engine.weather.status(values,getattr(self.engine._game,'running',False))
        state=w.get('faceplate_weather_state','unavailable')
        if state not in ('fresh','cached'):state='unavailable'
        tz=w.get('timezone') or 'UTC'
        def epoch(value):
            if not value:return None
            try:
                if isinstance(value,(float,int)) and math.isfinite(value):return float(value)
                at=datetime.fromisoformat(str(value));return at.replace(tzinfo=ZoneInfo(tz)).timestamp() if at.tzinfo is None else at.timestamp()
            except (TypeError,ValueError,KeyError):return None
        condition=w.get('condition') if state!='unavailable' else None
        # Unknown provider codes must never masquerade as a cloudy day.
        if w.get('weather_code') not in (0,1,2,3,45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,99):condition=None
        return dict(location=w.get('location'),unit=values.get('weather_temperature_unit','celsius'),
            environment=dict(condition=condition,weather_state=state,
                temperature_c=(w.get('temperature_c') if state=='fresh' else w.get('cached_temperature_c')) if state!='unavailable' else None,
                is_day=w.get('is_day'),sunrise_at=epoch(w.get('sunrise_at')),sunset_at=epoch(w.get('sunset_at')),
                previous_sunset_at=epoch(w.get('previous_sunset_at')),next_sunrise_at=epoch(w.get('next_sunrise_at')),observed_at=epoch(w.get('observed_at')),
                fetched_at=self.wall()-float(w.get('age_s') or 0),timezone=tz))

    def blocked_reason(self):
        e=self.engine;values=e.settings.all()
        if not values.get('faceplate_lab_enabled',True):return 'disabled'
        if getattr(e,'_faceplate_suspended',False):return 'suspended'
        if getattr(getattr(e,'thermal_protection',None),'active',False):return 'thermal-protection'
        control=getattr(e,'faceplate_control',None)
        if control is not None and not control.permitted():return 'ownership-released'
        panel_off=getattr(e,'_display_panel_off',None)
        if callable(panel_off) and panel_off(values):return 'displays-off'
        if getattr(getattr(e,'faceplate',None),'powered',None) is False:return 'display-off'
        if getattr(e,'_faceplate_power_target',None) is not None:return 'power-transition'
        if getattr(e,'_onboarding_applying',False):return 'setup'
        priority=getattr(e,'_assistant_holds_matrix',None)
        if callable(priority) and priority():return 'priority'
        broker=getattr(e,'jsaux_broker_adapter',None)
        if broker is not None and broker.holds_display():return 'priority'
        return ''

    def status(self):
        with self.lock:
            self._expire();weather=self.weather();p,routes=self._routes();context='game' if self.engine._game.running else 'home'
            route=self.engine.faceplate_router.status()
            selected=routes[context]==SCENE
            now=self.wall()
            packet=self.packet_for(context,now) if selected else None
            active=packet is not None
            fallback=selected and packet is None and self.restore_saved_route(now)
            fallback_scene=p.underlying_scene_for(context) if fallback else None
            blocked=self.blocked_reason()
            fallback_current=(fallback and route.get('context')==context
                and route.get('preference_revision')==p.revision
                and route.get('desired_scene')==fallback_scene)
            if fallback_current and route.get('preparation',{}).get('state') in ('error','unconfirmed'):
                fallback_state='fallback-failed'
            elif (fallback_current and route.get('effective_scene')==fallback_scene
                    and route.get('effective_content_key')==route.get('desired_content_key')):
                fallback_state='fallback-route'
            else:
                fallback_state='fallback-pending' if fallback_scene=='native-clock' else 'fallback-route-pending'
            confirmed=bool(not blocked and active and route.get('context')==context and route.get('preference_revision')==p.revision and route.get('effective_scene')==SCENE and route.get('effective_content_key')==route.get('desired_content_key') and self.confirmed_sha)
            return dict(protocol=PROTOCOL,version=VERSION,boot_id=self.boot_id,revision=p.revision,
                weather_revision=self.weather_revision,routes=routes,destination=self.destination(routes),
                context=context,present=self.present(),compatible=self.present(),selected_model=self.model,blocked_reason=blocked,
                active=active,selected_for_context=selected,fallback=fallback_scene,owner='GabeCubeAura',standalone_allowed=False,
                state='overridden' if selected and blocked else fallback_state if fallback else 'disconnected' if not self.present() else 'awaiting-packet' if selected and not active else 'inactive' if not active else 'display-confirmed' if confirmed else self.last_result,
                desired_scene=route.get('desired_scene'),effective_scene=route.get('effective_scene'),
                preparation=route.get('preparation'),accepted_sha256=self.last_sha,
                confirmed_sha256=self.confirmed_sha if confirmed else '',weather=weather,
                source_error=self.start_error,needs_weather=not bool(self.engine.settings.all().get('weather_location')),
                can_adopt_local=not self.previous and self.destination(routes)=='none',
                max_gif_bytes=GIF_LIMIT,next_minute_at=(math.floor(self.wall()/60)+1)*60)

    def restore_saved_route(self, now):
        # A live producer may be rendering the next minute. Only restore GCA's
        # route on lease loss or once a confirmed GIF has run its full lifetime.
        return not self.present() or (self.confirmed_until is not None and now >= self.confirmed_until)

    def set_destinations(self,destination,expected_revision):
        with self.lock:
            if destination not in DESTINATIONS:raise BridgeError('INVALID_DESTINATION')
            if destination!='none' and not self.present():raise BridgeError('CLIENT_UNAVAILABLE')
            p,routes=self._routes()
            if type(expected_revision) is not int or expected_revision!=p.revision:raise BridgeError('REVISION_CONFLICT')
            wanted={'home','game'} if destination=='both' else {destination} if destination!='none' else set()
            target=dict(routes);old_previous=dict(self.previous)
            for context in ('home','game'):
                if context in wanted:
                    if routes[context]!=SCENE:self.previous[context]=routes[context]
                    target[context]=SCENE
                elif routes[context]==SCENE:
                    target[context]=self.previous.get(context,'dashboard' if context=='home' else 'artwork')
            if target==routes:return self.status()
            # Save restoration basis before route commit; crash/retry cannot lose it.
            try:self._save()
            except Exception:self.previous=old_previous;raise
            from .routing import FaceplateRevisionConflict
            try:self.engine.update_faceplate_routing(target['home'],target['game'],expected_revision)
            except FaceplateRevisionConflict:raise BridgeError('REVISION_CONFLICT')
            self.packets=[];self.confirmed_sha='';self.last_result='applied'
            return self.status()

    def configure_weather(self,location,unit,expected_revision,expected_weather_revision):
        with self.lock:
            # Detect a city/unit changed in GCA before applying a stale Pixel choice.
            self.weather()
            p,_=self._routes()
            if type(expected_revision) is not int or type(expected_weather_revision) is not int or expected_revision!=p.revision or expected_weather_revision!=self.weather_revision:raise BridgeError('REVISION_CONFLICT')
            if not isinstance(location,dict) or set(location)-{'name','country','country_code','latitude','longitude','timezone'}:raise BridgeError('INVALID_LOCATION')
            try:
                lat=float(location['latitude']);lon=float(location['longitude'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:raise ValueError()
                if not isinstance(location['name'],str) or not 1<=len(location['name'])<=80:raise ValueError()
                if any(not isinstance(location[k],str) or len(location[k])>80 for k in ('country','country_code','timezone') if k in location):raise ValueError()
                if unit not in ('celsius','fahrenheit'):raise ValueError()
            except (ValueError,TypeError,KeyError):raise BridgeError('INVALID_LOCATION')
            clean={k:v for k,v in location.items() if k in ('name','country','country_code','latitude','longitude')}
            clean.update(latitude=lat,longitude=lon)
            self.engine.settings.update({'weather_location':clean,'weather_temperature_unit':unit})
            self.weather_revision+=1;self.weather_identity=json.dumps([clean,unit],sort_keys=True);self.packets=[];self.confirmed_sha='';self._save();self._configure_weather()
            self.engine._faceplate_next_reconcile=0.
            return self.status()

    def _configure_weather(self):
        values=self.engine.settings.all()
        self.engine.weather.configure(values['weather_location'],values['weather_display'],values['weather_topbar_enabled'],values['night_mode_enabled'],self.present() or self.engine._faceplate_weather_required(values))

    def _auth(self,request):
        if request.get('token')!=self.token:raise BridgeError('AUTH_DENIED')
        if request.get('op')!='hello' and (request.get('boot_id')!=self.boot_id or request.get('client_boot_id')!=self.client or not self.present()):raise BridgeError('SESSION_EXPIRED')

    def handle(self,request):
        request_id=request.get('request_id','') if isinstance(request,dict) else ''
        try:
            if not isinstance(request,dict) or set(request)-{'protocol','version','request_id','op','token','boot_id','client_boot_id','args'} or request.get('protocol')!=PROTOCOL or request.get('version')!=VERSION or not isinstance(request_id,str) or not 1<=len(request_id)<=80:raise BridgeError('INVALID_REQUEST')
            with self.lock:
                self._expire();self._auth(request);op=request.get('op');args=request.get('args',{})
                if not isinstance(args,dict):raise BridgeError('INVALID_REQUEST')
                mutation=op in ('set_destinations','configure_weather','publish')
                identity=(request.get('client_boot_id'),request_id)
                fingerprint=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if mutation and identity in self.receipts:
                    f,result=self.receipts[identity]
                    if f!=fingerprint:raise BridgeError('REQUEST_ID_REUSED')
                    return result
                if op=='hello':
                    client=request.get('client_boot_id');models=args.get('models')
                    if not isinstance(client,str) or not 8<=len(client)<=80 or not isinstance(models,list) or not 1<=len(models)<=32 or any(not isinstance(x,str) or not 1<=len(x)<=64 for x in models):raise BridgeError('INVALID_REQUEST')
                    if self.present() and self.client!=client:raise BridgeError('CLIENT_BUSY')
                    model=args.get('selected_model',models[0])
                    if model not in models:raise BridgeError('INVALID_MODEL')
                    if self.client!=client:self.packets=[];self.confirmed_sha=''
                    self.client=client;self.models=models;self.seen=self.clock();self.seen_wall=self.wall();self.model=model
                    self.last_result='connected';self._configure_weather();value=self.status()
                elif op=='status':
                    model=args.get('selected_model',self.model)
                    if model not in self.models:raise BridgeError('INVALID_MODEL')
                    if model!=self.model:
                        self.model=model;self.packets=[];self.confirmed_sha='';self.last_result='preparing';self.engine.faceplate_router.invalidate('pixel-clocks-model-changed');self.engine._faceplate_next_reconcile=0.
                    self.seen=self.clock();self.seen_wall=self.wall();value=self.status()
                elif op=='set_destinations':
                    self.seen=self.clock();self.seen_wall=self.wall();value=self.set_destinations(args.get('destination'),args.get('expected_revision'))
                elif op=='configure_weather':
                    self.seen=self.clock();self.seen_wall=self.wall();value=self.configure_weather(args.get('location'),args.get('unit'),args.get('expected_revision'),args.get('expected_weather_revision'))
                elif op=='publish':
                    self.seen=self.clock();self.seen_wall=self.wall();value=self.publish(args)
                elif op=='bye':
                    self.client=None;self.packets=[];self.last_result='disconnected';self._configure_weather();value=self.status()
                else:raise BridgeError('OP_UNSUPPORTED')
                result=dict(ok=True,request_id=request_id,boot_id=self.boot_id,result=value)
                if mutation:
                    self.receipts[identity]=(fingerprint,result)
                    while len(self.receipts)>64:self.receipts.popitem(last=False)
                return result
        except (ValueError,TypeError,KeyError,OSError,RuntimeError) as error:
            return dict(ok=False,request_id=request_id,boot_id=self.boot_id,error=dict(code=str(error)[:120]))

    def publish(self,args):
        self.weather()
        p,routes=self._routes();now=self.wall();context=args.get('context');start=args.get('display_at');end=args.get('end_at')
        if args.get('expected_revision')!=p.revision or args.get('weather_revision')!=self.weather_revision:raise BridgeError('REVISION_CONFLICT')
        if context not in ('home','game') or routes[context]!=SCENE:raise BridgeError('ROUTE_INACTIVE')
        if context!=('game' if self.engine._game.running else 'home'):raise BridgeError('CONTEXT_CHANGED')
        if args.get('model')!=self.model:raise BridgeError('MODEL_CHANGED')
        if any(type(x) not in (int,float) or not math.isfinite(x) for x in (start,end)) or not now+2<=start<=now+180 or not start<end<=(math.floor(start/60)+1)*60+16:raise BridgeError('INVALID_DEADLINE')
        encoded=args.get('gif_base64','')
        if not isinstance(encoded,str) or len(encoded)>4*((GIF_LIMIT+2)//3):raise BridgeError('CONTENT_TOO_LARGE')
        try:data=base64.b64decode(encoded,validate=True)
        except ValueError:raise BridgeError('CONTENT_INVALID')
        digest=hashlib.sha256(data).hexdigest()
        if len(data)>GIF_LIMIT:raise BridgeError('CONTENT_TOO_LARGE')
        if digest!=args.get('sha256') or not data:raise BridgeError('CONTENT_INVALID')
        environment = _renderer_environment()
        python = shutil.which('python3', path=environment.get('PATH'))
        if not python:raise BridgeError('VALIDATOR_UNAVAILABLE')
        self.root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='validate-',dir=self.root) as folder:
            source=Path(folder)/'clock.gif';source.write_bytes(data)
            try:result=subprocess.run([python,'-I',str(Path(__file__).with_name('pixel_clocks_gif.py')),str(source)],capture_output=True,timeout=2,check=False,env=environment)
            except subprocess.TimeoutExpired:raise BridgeError('VALIDATION_TIMEOUT')
        try:manifest=json.loads(result.stdout)
        except ValueError:raise BridgeError('CONTENT_INVALID')
        if result.returncode or not manifest.get('ok') or abs(manifest['duration_cs']/100-(end-start))>.011:raise BridgeError('CONTENT_INVALID')
        packet=dict(data=data,manifest=manifest,sha256=digest,display_at=start,end_at=end,renew_at=(math.floor(start/60)+1)*60,revision=p.revision,weather_revision=self.weather_revision,client=self.client,model=self.model,context=context)
        self.packets=[x for x in self.packets if x['display_at']!=start and x['end_at']>now][-1:]+[packet]
        self.last_sha=digest;self.last_result='prepared';self.engine._faceplate_next_reconcile=0.
        return dict(accepted=True,sha256=digest,revision=p.revision,state='prepared',display_confirmed=False)

    def packet_for(self,context,now):
        with self.lock:
            self._expire();self.weather();p,routes=self._routes()
            if not self.present() or routes[context]!=SCENE:return None
            valid=[x for x in self.packets if x['context']==context and x['revision']==p.revision and x['client']==self.client and x['model']==self.model and x['weather_revision']==self.weather_revision and x['end_at']>now]
            future=sorted((x for x in valid if now<x['display_at']),key=lambda x:x['display_at'])
            active=sorted((x for x in valid if x['display_at']<=now),key=lambda x:x['display_at'])
            if future and (not active or now>=future[0]['display_at']-15):return future[0]
            return active[-1] if active else None

    def current(self,packet):
        p,routes=self._routes()
        values=self.engine.settings.all()
        weather_identity=json.dumps([values.get('weather_location'),values.get('weather_temperature_unit')],sort_keys=True)
        return (weather_identity==self.weather_identity and self.delivery_current(packet)
                and p.revision==packet['revision'] and routes[packet['context']]==SCENE)

    def delivery_current(self, packet):
        # The serial owner calls this without taking the bridge or settings locks.
        return (packet['weather_revision']==self.weather_revision and self.present()
                and self.client==packet['client'] and self.model==packet['model']
                and packet['context']==('game' if self.engine._game.running else 'home')
                and any(candidate is packet for candidate in self.packets))

    def has_delivery(self, context):
        now = self.wall()
        return any(packet['context'] == context and packet['end_at'] > now
                   and self.delivery_current(packet) for packet in self.packets)

    def receipt(self,packet,result):
        with self.lock:
            if not self.current(packet):return
            if result.get('synchronized') and not result.get('error'):
                self.confirmed_sha=packet['sha256'];self.last_result='display-confirmed'
                self.confirmed_until=packet['end_at']
            else:self.last_result='unconfirmed' if result.get('sent_unconfirmed') else 'failed'

    def start(self):
        try:
            # Fail closed on foreign files, links, existing live endpoints.
            for ancestor in [*reversed(self.root.absolute().parents),self.root.absolute()]:
                if ancestor.is_symlink():raise BridgeError('UNSAFE_RUNTIME')
            self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
            if any(p.is_symlink() for p in (self.root, *self.root.parents)):
                raise BridgeError('UNSAFE_RUNTIME')
            st=self.root.stat()
            if st.st_uid!=os.geteuid() or stat.S_IMODE(st.st_mode)!=0o700:raise BridgeError('UNSAFE_RUNTIME')
            state_path=self.root/'state.json'
            if state_path.exists() or state_path.is_symlink():
                st=state_path.lstat()
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_nlink!=1 or st.st_mode&0o077 or st.st_size>4096:raise BridgeError('UNSAFE_RUNTIME')
                value=json.loads(state_path.read_text());self.previous={k:v for k,v in value.get('previous',{}).items() if k in ('home','game') and isinstance(v,str)};self.weather_revision=int(value.get('weather_revision',0))
            endpoint=self.root/'control.sock'
            if endpoint.exists() or endpoint.is_symlink():
                st=endpoint.lstat()
                if not stat.S_ISSOCK(st.st_mode) or st.st_uid!=os.geteuid():raise BridgeError('UNSAFE_RUNTIME')
                probe=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);probe.settimeout(.2)
                try:probe.connect(str(endpoint))
                except (ConnectionRefusedError,FileNotFoundError):endpoint.unlink()
                else:raise BridgeError('BRIDGE_ALREADY_RUNNING')
                finally:probe.close()
            bridge=self
            class Handler(socketserver.StreamRequestHandler):
                def handle(self):
                    self.request.settimeout(10)
                    from signalbar.jsaux_broker.server import peer_uid
                    if peer_uid(self.request)!=os.geteuid():return
                    raw=self.rfile.readline(MAX_MESSAGE+1)
                    if len(raw)>MAX_MESSAGE or not raw.endswith(b'\n'):return
                    try:value=json.loads(raw)
                    except ValueError:return
                    response=bridge.handle(value)
                    self.wfile.write(json.dumps(response,separators=(',',':'),allow_nan=False).encode()+b'\n')
            class Server(socketserver.ThreadingUnixStreamServer):
                daemon_threads=True
                request_queue_size=2
                def process_request(self,request,address):
                    if not bridge.slots.acquire(blocking=False):request.close();return
                    try:super().process_request(request,address)
                    except BaseException:bridge.slots.release();raise
                def process_request_thread(self,request,address):
                    try:super().process_request_thread(request,address)
                    finally:bridge.slots.release()
            self.server=Server(str(endpoint),Handler);os.chmod(endpoint,0o600)
            credential=self.root/'credential.json'
            if credential.exists() or credential.is_symlink():
                st=credential.lstat()
                if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_nlink!=1:raise BridgeError('UNSAFE_RUNTIME')
            _atomic(self.root/'credential.json',dict(protocol=PROTOCOL,version=VERSION,token=self.token,boot_id=self.boot_id,socket=str(endpoint)))
            self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},name='pixel-clocks-bridge',daemon=True);self.thread.start()
        except (OSError,ValueError) as error:
            self.start_error=str(error)[:120]
            if self.server:self.server.server_close();self.server=None

    def stop(self,timeout=None):
        if self.server:
            self.server.shutdown();self.server.server_close();self.server=None
            if self.thread:self.thread.join(timeout=.3 if timeout is None else timeout)
            for name in ('control.sock','credential.json'):
                path=self.root/name
                try:
                    st=path.lstat()
                    if st.st_uid==os.geteuid() and (stat.S_ISSOCK(st.st_mode) if name.endswith('.sock') else stat.S_ISREG(st.st_mode)):path.unlink()
                except FileNotFoundError:pass
        self.client=None;self.packets=[]
