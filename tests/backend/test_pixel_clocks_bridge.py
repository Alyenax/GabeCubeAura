"""Actual authenticated socket/policy/GIF contract tests; no hardware claims."""
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs,urlsplit

from signalbar.faceplate.pixel_clocks_bridge import PixelClocksBridge,PROTOCOL,BridgeError,GIF_LIMIT
from signalbar.faceplate.pixel_clocks_gif import inspect
from signalbar.faceplate.routing import FaceplatePreferencesStore,FaceplateSceneRouter
from signalbar.faceplate.gif import encode
from signalbar.providers.weather import fetch_current


class Settings:
    def __init__(self):self.values=dict(weather_location=None,weather_temperature_unit='celsius',weather_display='off',weather_topbar_enabled=False,night_mode_enabled=False)
    def all(self):return dict(self.values)
    def update(self,changes):self.values.update(changes)


class Engine:
    def __init__(self,folder):
        self.faceplate_preferences=FaceplatePreferencesStore(Path(folder)/'routes.json')
        self.faceplate_router=FaceplateSceneRouter(self.faceplate_preferences)
        self.settings=Settings();self._game=SimpleNamespace(running=False)
        self.weather=SimpleNamespace(status=lambda *a:dict(location=self.settings.all()['weather_location'],faceplate_weather_state='fresh',weather_code=2,condition='breaks',temperature_c=14.,is_day=True,timezone='Europe/Paris',age_s=2.,sunrise_at='2026-11-08T07:00',sunset_at='2026-11-08T17:00',previous_sunset_at='2026-11-07T17:01',next_sunrise_at='2026-11-09T07:02'),configure=Mock())
        self._faceplate_next_reconcile=99.
    def _faceplate_weather_required(self,values):return False
    def update_faceplate_routing(self,home,game,revision):
        self.faceplate_preferences.update(home_scene=home,game_scene=game,expected_revision=revision)
        self.faceplate_router.reconcile(game_running=self._game.running,content_key='changed',reason='test')


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='/private/tmp');self.engine=Engine(self.temp.name)
        self.now=1000.;self.wall=1794124800.
        self.b=PixelClocksBridge(self.engine,Path(self.temp.name)/'bridge',clock=lambda:self.now,wall=lambda:self.wall)
        self.b.start();self.assertFalse(self.b.start_error,self.b.start_error)
        self.seq=0;self.client='pixel-test-client-boot'
    def tearDown(self):self.b.stop();self.temp.cleanup()
    def call(self,op,args=None,**changes):
        self.seq+=1
        r=dict(protocol=PROTOCOL,version=1,request_id=str(self.seq),op=op,token=self.b.token,boot_id=self.b.boot_id,client_boot_id=self.client,args=args or {})
        r.update(changes)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(10);sock.connect(str(self.b.root/'control.sock'));sock.sendall(json.dumps(r).encode()+b'\n')
            with sock.makefile('rb') as f:return json.loads(f.readline(131073))
    def hello(self):return self.call('hello',{'models':['mario','zelda'],'selected_model':'mario'})['result']
    def test_auth_and_presence_are_handshake_not_folder(self):
        self.assertFalse(self.b.status()['present'])
        self.assertFalse(self.call('hello',token='bad')['ok'])
        self.assertTrue(self.hello()['present'])
        self.now+=9
        self.assertFalse(self.b.status()['present'])
        self.assertEqual('SESSION_EXPIRED',self.call('status')['error']['code'])
    def test_atomic_reversible_and_manual_route_preserved(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='both',expected_revision=s['revision']))['result']
        self.assertEqual({'home':'pixel-clocks','game':'pixel-clocks'},s['routes'])
        self.engine.update_faceplate_routing('weather','pixel-clocks',s['revision'])
        s=self.call('status')['result'];self.assertEqual('game',s['destination'])
        s=self.call('set_destinations',dict(destination='none',expected_revision=s['revision']))['result']
        self.assertEqual({'home':'weather','game':'artwork'},s['routes'])
    def test_stale_revision_and_retry_idempotence(self):
        s=self.hello();args=dict(destination='both',expected_revision=s['revision'])
        first=self.call('set_destinations',args,request_id='same')
        self.assertEqual(first,self.call('set_destinations',args,request_id='same'))
        self.assertEqual('REQUEST_ID_REUSED',self.call('set_destinations',dict(args,destination='none'),request_id='same')['error']['code'])
        self.assertEqual('REVISION_CONFLICT',self.call('set_destinations',dict(destination='home',expected_revision=s['revision']))['error']['code'])
        self.assertEqual('both',self.call('status')['result']['destination'])
    def test_disconnect_does_not_undo_routes_or_allow_usb_claim(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='both',expected_revision=s['revision']))['result']
        s=self.call('bye')['result']
        self.assertEqual('both',s['destination']);self.assertFalse(s['standalone_allowed']);self.assertFalse(s['present'])
        # GCA can explicitly undo an absent companion, from its own panel.
        self.assertEqual('none',self.b.set_destinations('none',s['revision'])['destination'])
    def test_restore_basis_survives_bridge_restart(self):
        s=self.hello();self.call('set_destinations',dict(destination='both',expected_revision=s['revision']))
        old_boot=self.b.boot_id;self.b.stop()
        self.b=PixelClocksBridge(self.engine,Path(self.temp.name)/'bridge',clock=lambda:self.now,wall=lambda:self.wall);self.b.start()
        self.assertNotEqual(old_boot,self.b.boot_id)
        self.assertEqual('SESSION_EXPIRED',self.call('status',boot_id=old_boot)['error']['code'])
        s=self.hello();s=self.call('set_destinations',dict(destination='none',expected_revision=s['revision']))['result']
        self.assertEqual({'home':'dashboard','game':'artwork'},s['routes'])
    def test_shared_weather_starts_without_weather_route_and_city_changes(self):
        s=self.hello();self.assertTrue(self.engine.weather.configure.call_args.args[-1])
        self.assertEqual(0,self.engine.settings.values['weather_topbar_enabled'])
        s=self.call('configure_weather',dict(expected_revision=s['revision'],expected_weather_revision=s['weather_revision'],location=dict(name='Paris',country='France',latitude=48.85,longitude=2.35),unit='fahrenheit'))['result']
        self.assertEqual('Paris',s['weather']['location']['name']);self.assertEqual('fahrenheit',s['weather']['unit'])
        self.assertIsNotNone(s['weather']['environment']['previous_sunset_at'])
        self.assertIsNotNone(s['weather']['environment']['next_sunrise_at'])
        rev=s['weather_revision'];self.engine.settings.update(dict(weather_temperature_unit='celsius'))
        self.assertEqual(rev+1,self.call('status')['result']['weather_revision'])
    def packet(self,state):
        start=self.wall+60;data=encode(64,54,[(1,2,3)],[bytes(3456),bytes(3456)],delay_cs=3800,loop=False)
        return dict(expected_revision=state['revision'],weather_revision=state['weather_revision'],context='home',model='mario',display_at=start,end_at=start+76,sha256=hashlib.sha256(data).hexdigest(),gif_base64=base64.b64encode(data).decode())
    def test_real_publish_then_context_model_revision_fences(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='both',expected_revision=s['revision']))['result']
        args=self.packet(s);result=self.call('publish',args)
        self.assertTrue(result['ok'],result);self.assertFalse(result['result']['display_confirmed'])
        packet=self.b.packet_for('home',self.wall);self.assertTrue(self.b.current(packet))
        self.engine._game.running=True;self.assertFalse(self.b.current(packet))
        self.engine._game.running=False
        self.call('status',dict(selected_model='zelda'));self.assertFalse(self.b.current(packet));self.assertIsNone(self.b.packet_for('home',self.wall))
        self.assertEqual('MODEL_CHANGED',self.call('publish',args)['error']['code'])
    def test_untrusted_loop_payload_and_wrong_digest_rejected(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='home',expected_revision=s['revision']))['result']
        args=self.packet(s);args['sha256']='0'*64
        self.assertEqual('CONTENT_INVALID',self.call('publish',args)['error']['code'])
        loop=encode(64,54,[(0,0,0)],[bytes(3456),bytes(3456)],delay_cs=3800,loop=True)
        args.update(sha256=hashlib.sha256(loop).hexdigest(),gif_base64=base64.b64encode(loop).decode())
        self.assertEqual('CONTENT_INVALID',self.call('publish',args)['error']['code'])
    def test_light_bridge_rejects_packet_above_the_edition_limit(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='home',expected_revision=s['revision']))['result']
        self.assertEqual(s['max_gif_bytes'],32767)
        args=self.packet(s)
        data=b'x'*(GIF_LIMIT+1)
        args.update(sha256=hashlib.sha256(data).hexdigest(),gif_base64=base64.b64encode(data).decode())
        self.assertEqual('CONTENT_TOO_LARGE',self.call('publish',args)['error']['code'])

    def test_finite_decode_exact_and_malformed_native_rejected(self):
        good=encode(64,54,[(255,0,0),(0,255,0)],[bytes(3456),bytes([1])*3456],delay_cs=[3000,4600],loop=False)
        self.assertEqual({'frames':2,'duration_cs':7600,'peak_load':1/3},inspect(good))
        for bad in (good[:-1],good+b'bad',good[:6]+b'\x41'+good[7:],b'GIF89a'):
            with self.assertRaises(ValueError):inspect(bad)
    def test_receipt_never_claims_display_when_power_or_priority_changed(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='home',expected_revision=s['revision']))['result']
        self.call('publish',self.packet(s));packet=self.b.packet_for('home',self.wall)
        ticket=self.engine.faceplate_router.reconcile(game_running=False,content_key='pixel-clocks:'+packet['sha256'],reason='test')
        self.engine.faceplate_router.mark_preparing(ticket);self.engine.faceplate_router.mark_prepared(ticket);self.engine.faceplate_router.commit(ticket)
        self.b.receipt(packet,dict(synchronized=True))
        self.assertEqual('display-confirmed',self.b.status()['state'])
        self.engine.faceplate=SimpleNamespace(powered=False)
        value=self.b.status();self.assertEqual('overridden',value['state']);self.assertEqual('',value['confirmed_sha256'])
        self.assertEqual('display-off',value['blocked_reason'])

    def test_real_settings_store_persists_city_and_unit_without_route_or_topbar_changes(self):
        from signalbar.settings.store import SettingsStore
        self.engine.settings=SettingsStore(str(Path(self.temp.name)/'settings.json'))
        self.engine.settings.update({'weather_topbar_enabled':False,'weather_display':'off'})
        s=self.hello();before=dict(s['routes'])
        result=self.call('configure_weather',dict(expected_revision=s['revision'],expected_weather_revision=s['weather_revision'],location=dict(name='Paris',country='France',country_code='FR',latitude=48.85,longitude=2.35),unit='fahrenheit'))
        self.assertTrue(result['ok'],result)
        reloaded=SettingsStore(str(Path(self.temp.name)/'settings.json')).all()
        self.assertEqual('fahrenheit',reloaded['weather_temperature_unit'])
        self.assertEqual('Paris',reloaded['weather_location']['name'])
        self.assertFalse(reloaded['weather_topbar_enabled']);self.assertEqual('off',reloaded['weather_display'])
        self.assertEqual(before,result['result']['routes'])

    def test_weather_change_fences_a_packet_before_next_poll(self):
        s=self.hello();s=self.call('set_destinations',dict(destination='home',expected_revision=s['revision']))['result']
        self.call('publish',self.packet(s));packet=self.b.packet_for('home',self.wall)
        self.assertTrue(self.b.current(packet))
        self.engine.settings.update(dict(weather_temperature_unit='fahrenheit'))
        result=self.call('configure_weather',dict(expected_revision=s['revision'],expected_weather_revision=s['weather_revision'],location=dict(name='Paris',latitude=48.85,longitude=2.35),unit='celsius'))
        self.assertEqual('REVISION_CONFLICT',result['error']['code'])
        self.assertEqual('fahrenheit',self.engine.settings.all()['weather_temperature_unit'])
        self.assertFalse(self.b.current(packet))
        self.assertIsNone(self.b.packet_for('home',self.wall))

    def test_solar_today_not_yesterday_after_past_days_added(self):
        seen=[]
        def read(url):
            seen.append(parse_qs(urlsplit(url).query))
            return dict(current=dict(weather_code=0,is_day=0,temperature_2m=10,time='2026-11-08T22:00'),daily=dict(sunrise=['2026-11-07T07:00','2026-11-08T07:01','2026-11-09T07:02'],sunset=['2026-11-07T17:01','2026-11-08T17:00','2026-11-09T16:59']))
        sample=fetch_current(dict(latitude=48.,longitude=2.),read)
        self.assertEqual(['1'],seen[0]['past_days']);self.assertEqual('2026-11-08T07:01',sample['sunrise_at'])
        self.assertEqual('2026-11-07T17:01',sample['previous_sunset_at']);self.assertEqual('2026-11-09T07:02',sample['next_sunrise_at'])
        self.assertEqual('2026-11-09T07:02',sample['next_solar_transition_at'])


if __name__=='__main__':unittest.main()

class ScheduledCommitTests(unittest.TestCase):
    def test_end_never_early_and_cancel_never_sends_end(self):
        from unittest.mock import patch
        from signalbar.faceplate.transport import Link,TransferCancelled
        from signalbar.faceplate import protocol
        wall=[100.];writes=[]
        link=Link('/unused');link.write=lambda data:writes.append((data,wall[0]))
        link.read_replies=lambda timeout:[protocol.Reply(protocol.TYPE_CONTROL,protocol.CMD_GIF_END,b'\x01')]
        link.clock_commit_at=102.;link.clock_commit_valid=lambda:True
        with patch('signalbar.faceplate.transport.time.time',side_effect=lambda:wall[0]),patch('signalbar.faceplate.transport.time.sleep',side_effect=lambda seconds:wall.__setitem__(0,wall[0]+seconds)):
            link.command(protocol.gif_end(),retries=1)
        self.assertEqual(1,len(writes));self.assertGreaterEqual(writes[0][1],102.)
        link.clock_commit_at=104.;link.clock_commit_valid=lambda:False;writes.clear()
        with patch('signalbar.faceplate.transport.time.time',return_value=103.),self.assertRaises(TransferCancelled):link.command(protocol.gif_end(),retries=1)
        self.assertEqual([],writes)
    def test_coordinator_clears_scheduling_after_success_and_cancellation(self):
        from contextlib import nullcontext
        from unittest.mock import patch
        from signalbar.faceplate.coordinator import FaceplateCoordinator,encode_frame
        from signalbar.faceplate.transport import TransferCancelled
        with tempfile.TemporaryDirectory(dir='/private/tmp') as folder:
            coordinator=FaceplateCoordinator(Path(folder)/'assets',Path(folder)/'state.json',port_finder=lambda:'/test',identity_reader=lambda _:'test')
            coordinator.configure(True,100)
            data=encode_frame(bytes([1,2,3])*3456)
            link=SimpleNamespace(last_transfer_timings={})
            seen=[]
            def send(*args,**kwargs):
                seen.append((link.clock_commit_at,link.clock_commit_valid()))
                if len(seen)==2:raise TransferCancelled('superseded')
                return True
            with patch.object(coordinator,'_upload_link',side_effect=lambda *a,**k:nullcontext(link)),patch.object(coordinator,'_write_brightness'),patch.object(coordinator,'_begin_scene_power'),patch.object(coordinator,'_finish_scene_power'),patch.object(coordinator,'_send_protected',side_effect=send):
                result=coordinator.synchronize_scene(data,'clock','first',clock_commit_at=102.,prepared_orientation=True)
                self.assertTrue(result['synchronized']);self.assertIsNone(link.clock_commit_at);self.assertIsNone(link.clock_commit_valid)
                result=coordinator.synchronize_scene(data,'clock','second',clock_commit_at=104.,prepared_orientation=True)
                self.assertTrue(result['cancelled']);self.assertIsNone(link.clock_commit_at);self.assertIsNone(link.clock_commit_valid)
            self.assertEqual([(102.,True),(104.,True)],seen)

    def test_partial_local_palette_rotation_preserves_decoded_rgb_and_delays(self):
        import io
        from PIL import Image,ImageSequence
        from signalbar.faceplate.pixel_clocks_gif import rotate
        frames=[]
        for n in range(3):
            im=Image.new('RGB',(64,54),(28,40,80));im.paste((200,30+n*50,90),(5+n,12,16+n,23));frames.append(im)
        stream=io.BytesIO();frames[0].save(stream,format='GIF',save_all=True,append_images=frames[1:],duration=[1000,1000,74000],disposal=1,optimize=True)
        original=stream.getvalue();rotated=rotate(original)
        a=Image.open(io.BytesIO(original));b=Image.open(io.BytesIO(rotated))
        self.assertEqual(3,b.n_frames)
        for left,right in zip(ImageSequence.Iterator(a),ImageSequence.Iterator(b)):
            self.assertEqual(left.info['duration'],right.info['duration'])
            self.assertEqual(left.convert('RGB').transpose(Image.Transpose.ROTATE_180).tobytes(),right.convert('RGB').tobytes())
