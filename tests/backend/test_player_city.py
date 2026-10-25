"""Player City: native pixels, Steam fencing, durable cadence and real serial admission."""
from io import BytesIO
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image

from signalbar.providers.current_players import CurrentPlayers, PlayerCountError, validate_response, fetch_current_players
from signalbar.faceplate.player_city import (ROOT, TIERS, WEATHER, SMILE, build_player_city,
    native_rgb, population_tier, rail_layout, phase_for_weather, PlayerCityCadence, REVISION)
from signalbar.faceplate.player_city_animation import animated_rgb, animation_manifest, DELAYS_CS
from signalbar.faceplate.flash import FlashWearProtection, UploadDeferred, identity
from signalbar.faceplate.coordinator import FaceplateCoordinator
from signalbar.faceplate.transport import Link
from signalbar.faceplate import protocol
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.scene_renderer import render_isolated
from test_flash_protection import Clock, Panel


class PlayerCityPixels(unittest.TestCase):

    def test_all72_approved_animations_are_lossless_x2_and_keep_the_count_fixed(self):
        manifest=animation_manifest()
        self.assertEqual((manifest['frames'],manifest['speed'],manifest['rain_style']),(192,2,'inclined-home-trails-surface-impacts'))
        self.assertEqual(manifest['style'],'architectural-pixel-3d')
        self.assertEqual(manifest['source_revision'],'steam-player-city-greenery-v1')
        self.assertEqual(manifest['size'],[64,45])
        self.assertEqual(manifest['loop_duration_cs'],2400)
        expected={(weather,phase,tier) for weather in set(WEATHER.values())
                  for phase in ('day','night') for tier in TIERS}
        self.assertEqual(len(manifest['images']),72)
        self.assertEqual({(r['weather'],r['phase'],r['tier']) for r in manifest['images']},expected)
        self.assertEqual(tuple(manifest['delays_cs']),DELAYS_CS)
        self.assertEqual(sum(DELAYS_CS),2400)
        sizes=[]
        for row in manifest['images']:
            with self.subTest(weather=row['weather'],phase=row['phase'],tier=row['tier']):
                count=(1,10,100,1000,10000,4294967295)[TIERS.index(row['tier'])]
                scene=build_player_city(row['weather'],row['phase'],count)
                self.assertEqual(len(scene.frames),192)
                art=animated_rgb(row['weather'],row['phase'],row['tier'])
                self.assertGreater(len(set(art)),1,'Every scene must animate')
                payload=scene.gif();sizes.append(len(payload))
                decoded=Image.open(BytesIO(payload))
                self.assertEqual(decoded.size,(64,54));self.assertEqual(decoded.n_frames,192)
                self.assertEqual(decoded.info['loop'],0)
                for n,frame in enumerate(scene.frames):
                    decoded.seek(n)
                    self.assertEqual(decoded.convert('RGB').tobytes(),frame)
                    self.assertEqual(decoded.info['duration'],scene.delays_cs[n]*10)
                    self.assertEqual(frame[:45*64*3],art[n])
                    self.assertEqual(frame[45*64*3:],scene.frames[0][45*64*3:])
                from signalbar.faceplate.gif_transform import rotate_gif
                rotated=rotate_gif(payload)
                self.assertLessEqual(len(rotated),196608)
                decoded=Image.open(BytesIO(rotated))
                self.assertEqual(decoded.n_frames,192)
                for n,frame in enumerate(scene.frames):
                    decoded.seek(n)
                    expected=Image.frombytes('RGB',(64,54),frame).transpose(Image.Transpose.ROTATE_180)
                    self.assertEqual(decoded.convert('RGB').tobytes(),expected.tobytes())
                    self.assertEqual(decoded.info['duration'],scene.delays_cs[n]*10)
        self.assertLessEqual(max(sizes),196608)

    def test_approved_night_house_presence_changes_rooms_without_flashing_the_walls(self):
        art=animated_rgb('SUN','night','01_09')
        def pixel(frame,x,y):
            offset=(y*64+x)*3
            return frame[offset:offset+3]
        # Two independently occupied rooms in the approved front-facing house.
        # Clear weather isolates the light switches from precipitation effects.
        rooms=[]
        for x in (8,21):
            values=[pixel(frame,x,32) for frame in art]
            self.assertEqual(len(set(values)),2)
            switches=[n for n in range(192) if values[n]!=values[n-1]]
            self.assertEqual(len(switches),2)
            intervals=[(switches[(n+1)%2]-switches[n])%192 for n in range(2)]
            self.assertTrue(all(64<=duration<=128 for duration in intervals))
            self.assertEqual(len({values[n] for n in (190,191,0,1)}),1)
            rooms.append(switches)
        self.assertNotEqual(rooms[0],rooms[1])
        for x,y in ((6,30),(15,29),(23,30)):
            self.assertEqual(len({pixel(frame,x,y) for frame in art}),1,
                             'Window frames and masonry remain stationary')

    def test_tiers_and_exact_large_counts_fit_without_scaling(self):
        for index,(lo,hi) in enumerate(((1,9),(10,99),(100,999),(1000,9999),(10000,99999),(100000,0xffffffff))):
            self.assertEqual(population_tier(lo),TIERS[index]);self.assertEqual(population_tier(hi),TIERS[index])
        self.assertIsNone(population_tier(0))
        for bad in (-1,True,1.,'10',None,0x100000000):
            with self.assertRaises(ValueError):population_tier(bad)
        for n in (1,9,10,99,999,1000,9999,10000,32809,99999,100000,1234567,4294967295):
            text,width = rail_layout(n)
            from signalbar.faceplate.player_city_row import compact_players
            self.assertEqual(text,format(n,','));self.assertLessEqual(width,48)
            scene = build_player_city('STR','night',n)
            self.assertEqual(Image.open(BytesIO(scene.gif())).convert('RGB').tobytes(),scene.frames[0])
            rail = scene.frames[0][45*64*3:]
            self.assertIn(bytes((255,210,72)),rail)
        self.assertEqual(rail_layout(4294967295),('4,294,967,295',48))
        self.assertLessEqual(len(SMILE),7)
        with self.assertRaises(ValueError):build_player_city('SUN','day',0)

    def test_existing_weather_and_solar_boundaries(self):
        from signalbar.providers.weather import condition_for_code
        expected = {0:'SUN',1:'SUN',2:'CLR',3:'CLD',45:'CLD',61:'RAN',71:'SNW',95:'STR',999:'CLD'}
        for code,weather in expected.items():
            for day in (True,False):self.assertEqual(WEATHER[condition_for_code(code,day)],weather)
        for phase,time,expected in [('dawn','06:59','night'),('dawn','07:00','day'),('dusk','18:59','day'),('dusk','19:00','night')]:
            self.assertEqual(phase_for_weather(dict(phase=phase,now='2026-10-23T'+time,sunrise='2026-10-23T07:00',sunset='2026-10-23T19:00')),expected)

    def test_real_isolated_renderer_uses_the_approved_animation(self):
        with tempfile.TemporaryDirectory() as folder:
            data,manifest = render_isolated(dict(kind='player-city',appid=620,weather='STR',phase='night',players=32809),temporary_root=folder)
        self.assertEqual(manifest['players'],32809)
        self.assertEqual((manifest['frames'],manifest['duration_ms'],manifest['animation_speed'],manifest['rain_style']),
                         (192,24000,2,'inclined-home-trails-surface-impacts'))
        self.assertEqual(manifest['style'],'architectural-pixel-3d')
        self.assertEqual(manifest['source_revision'],'steam-player-city-greenery-v1')
        self.assertEqual(Image.open(BytesIO(data)).convert('RGB').tobytes(),build_player_city('STR','night',32809).frames[0])


class PlayerCitySteam(unittest.TestCase):
    def test_decky_transport_has_one_lease_no_python_worker_and_strict_results(self):
        clock = Clock()
        provider = CurrentPlayers(lambda appid:self.fail('Decky mode must not open Python HTTPS'),
                                  transport='decky', clock=clock, wall_clock=clock.wall)
        self.assertIsNone(provider.claim())
        provider.configure(367520)
        self.assertIsNone(provider.thread)
        self.assertFalse(provider.poll())
        lease = provider.claim()
        self.assertEqual(lease['appid'],367520)
        self.assertIsNone(provider.claim())
        self.assertFalse(provider.complete('wrong-id',367520,{}))
        self.assertTrue(provider.status()['in_flight'])
        body = {'response':{'result':1,'player_count':5636}}
        self.assertTrue(provider.complete(lease['request_id'],367520,body))
        self.assertEqual(provider.status()['players'],5636)
        self.assertEqual(provider.status()['transport'],'decky')
        self.assertIsNone(provider.claim())
        clock.advance(300)
        lease = provider.claim()
        self.assertTrue(provider.complete(lease['request_id'],367520,{'response':{'result':True,'player_count':0}}))
        self.assertEqual(provider.status()['state'],'unavailable')
        self.assertFalse(provider.status()['usable'])
        self.assertEqual(provider.status()['players'],5636)
        provider.stop()

    def test_decky_late_game_and_stopped_mode_replies_are_discarded_and_release_lease(self):
        provider = CurrentPlayers(transport='decky')
        provider.configure(367520);lease=provider.claim()
        provider.configure(620)
        self.assertIsNone(provider.claim())
        self.assertFalse(provider.complete(lease['request_id'],367520,{'response':{'result':1,'player_count':5636}}))
        self.assertNotIn(367520,provider.cache)
        next_lease=provider.claim();self.assertEqual(next_lease['appid'],620)
        provider.configure(0)
        self.assertFalse(provider.complete(next_lease['request_id'],620,{'response':{'result':1,'player_count':1}}))
        self.assertFalse(provider.status()['in_flight'])
        self.assertEqual(provider.status()['state'],'inactive')
        self.assertIsNone(provider.claim());provider.stop()

    def test_decky_lost_frontend_expires_without_two_second_retry_loop(self):
        clock=Clock();provider=CurrentPlayers(transport='decky',clock=clock,wall_clock=clock.wall)
        provider.configure(367520);lease=provider.claim()
        clock.advance(31)
        self.assertIsNone(provider.claim())
        self.assertEqual(provider.status()['error_code'],'timeout')
        self.assertFalse(provider.complete(lease['request_id'],367520,{'response':{'result':1,'player_count':5636}}))
        clock.advance(269)
        self.assertIsNotNone(provider.claim());provider.stop()

    def test_safe_network_reason_reaches_status_without_exception_text(self):
        import socket
        from urllib.error import URLError, HTTPError
        from unittest.mock import Mock
        from signalbar.providers import current_players as module
        for error, expected in ((URLError(socket.gaierror('private-host')), 'dns'),
                                (URLError(TimeoutError('private-url')), 'timeout'),
                                (HTTPError('https://private.invalid', 403, 'private-header', {}, None), 'http_403')):
            opener = Mock(); opener.open.side_effect = error
            provider = CurrentPlayers(fetch_current_players)
            provider.configure(367520, start=False)
            with patch.object(module, 'build_opener', return_value=opener):
                provider.poll()
            state = provider.status()
            self.assertEqual(state['error_code'], expected)
            self.assertNotIn('private', json.dumps(state))
            self.assertIsNone(state['players'])
            provider.stop()

    def test_strict_response_success_zero_and_failures(self):
        for count in (0,1,32809,4294967295):
            self.assertEqual(validate_response({'response':{'result':1,'player_count':count}}),count)
        for count in (True,-1,1.,'10',None,4294967296):
            with self.assertRaises(PlayerCountError):validate_response({'response':{'result':1,'player_count':count}})
        for body in ({},[],{'response':{'result':True,'player_count':1}},{'response':{'result':2,'player_count':1}}):
            with self.assertRaises(PlayerCountError):validate_response(body)

    def test_official_bounded_https_without_key(self):
        class Response(BytesIO):pass
        for body,state in ((b'{"response":{"result":1,"player_count":32809}}',None),(b'x'*8193,'unavailable')):
            requests=[]
            class Opener:
                def open(self,request,timeout):
                    requests.append((request.full_url,timeout));return Response(body)
            with patch('signalbar.providers.current_players.build_opener',return_value=Opener()):
                if state:
                    with self.assertRaises(PlayerCountError):fetch_current_players(620)
                else:self.assertEqual(fetch_current_players(620),32809)
            self.assertEqual(requests,[('https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=620',6)])

    def test_single_inflight_late_game_response_is_discarded(self):
        entered,release = threading.Event(),threading.Event()
        def fetch(appid):entered.set();release.wait(1);return 32809
        provider = CurrentPlayers(fetch)
        provider.configure(620,start=False)
        worker = threading.Thread(target=provider.poll);worker.start();self.assertTrue(entered.wait(1))
        self.assertFalse(provider.poll())
        provider.configure(570,start=False);release.set();worker.join(1)
        self.assertEqual(provider.status()['appid'],570);self.assertIsNone(provider.status()['players'])
        self.assertNotIn(620,provider.cache)
        provider.configure(0,start=False);self.assertFalse(provider.poll());provider.stop()

    def test_cache_freshness_error_and_stop_fences(self):
        clock=Clock();calls=[];values=iter([0,PlayerCountError('network_error'),42])
        def fetch(appid):
            calls.append(appid);value=next(values)
            if isinstance(value,Exception):raise value
            return value
        provider=CurrentPlayers(fetch,clock=clock,wall_clock=clock.wall)
        provider.configure(620,start=False);provider.poll()
        self.assertEqual(provider.status()['state'],'zero')
        provider.configure(0,start=False);provider.configure(620,start=False)
        self.assertFalse(provider.poll());self.assertEqual(calls,[620])
        clock.advance(300);provider.poll();self.assertEqual(provider.status()['state'],'network_error')
        self.assertFalse(provider.status()['usable']);self.assertEqual(provider.status()['players'],0)
        clock.advance(300);provider.poll();self.assertEqual(provider.status()['players'],42)
        clock.advance(901);self.assertEqual(provider.status()['state'],'stale')
        provider.stop();self.assertFalse(provider.poll())


class PlayerCityCadenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.clock=Clock();self.path=Path(self.temp.name)/'city.json'
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
    def sample(self,n=32809):return dict(appid=620,usable=True,state='zero' if n==0 else 'ready',players=n,sampled_at=self.clock.wall())
    def weather(self,condition='clear_day'):return dict(condition=condition,phase='day')
    def confirm(self,payload):self.city.reserve(payload);self.city.receipt(payload,{'synchronized':True})

    def legacy_still(self):
        self.confirm(self.city.plan(620,self.sample(6176),self.weather()))
        saved=json.loads(self.path.read_text())
        saved['confirmed'].pop('render_revision',None)
        saved['attempt'].pop('render_revision',None)
        self.path.write_text(json.dumps(saved))
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)

    def test_existing_still_upgrades_once_without_reset_or_new_count_cadence_bypass(self):
        self.legacy_still();original_at=self.city.confirmed['at']
        self.clock.advance(60)
        upgrade=self.city.plan(620,self.sample(6200),self.weather('rain'))
        self.assertTrue(upgrade['_confirmed_restore'])
        self.assertEqual((upgrade['players'],upgrade['weather']),(6176,'SUN'))
        self.confirm(upgrade)
        self.assertEqual(self.city.confirmed['at'],original_at)
        self.assertIsNone(self.city.plan(620,self.sample(6200),self.weather('rain')))
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
        self.assertIsNone(self.city.plan(620,self.sample(6200),self.weather('rain')))
        self.clock.advance(3540)
        self.assertEqual(self.city.plan(620,self.sample(6200),self.weather('rain'))['players'],6200)

    def test_previous_animation_upgrades_once_and_keeps_its_count_and_hourly_anchor(self):
        self.confirm(self.city.plan(620,self.sample(6176),self.weather()))
        saved=json.loads(self.path.read_text())
        for key in ('confirmed','attempt'):
            saved[key]['render_revision']='player-city-animated-dense-x2-1'
        self.path.write_text(json.dumps(saved))
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
        original_at=self.city.confirmed['at']
        original_sampled_at=self.city.confirmed['sampled_at']
        self.clock.advance(60)
        upgrade=self.city.plan(620,self.sample(32809),self.weather('rain'))
        self.assertEqual((upgrade['players'],upgrade['weather'],upgrade['phase']),(6176,'SUN','day'))
        self.assertEqual(upgrade['sampled_at'],original_sampled_at)
        self.assertTrue(upgrade['_confirmed_restore'])
        self.confirm(upgrade)
        self.assertEqual(self.city.confirmed['render_revision'],REVISION)
        self.assertEqual(self.city.confirmed['at'],original_at)
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
        self.assertIsNone(self.city.plan(620,self.sample(32809),self.weather('rain')))
        self.assertEqual(self.city.status()['next_refresh_s'],3540)
        self.clock.advance(3540)
        self.assertEqual(self.city.plan(620,self.sample(32809),self.weather('rain'))['players'],32809)

    def test_failed_still_upgrade_retries_hourly_without_a_per_poll_transfer(self):
        self.legacy_still()
        upgrade=self.city.plan(620,self.sample(),self.weather())
        self.city.reserve(upgrade);self.city.receipt(upgrade,{'error':'USB disconnected'})
        for _ in range(59):
            self.clock.advance(60)
            self.assertIsNone(self.city.plan(620,self.sample(),self.weather()))
        self.clock.advance(60)
        self.assertEqual(self.city.plan(620,self.sample(),self.weather())['players'],32809,
                         'The due retry combines the current measurement and animation upgrade')

    def test_due_measurement_and_animation_upgrade_share_one_upload(self):
        self.legacy_still();self.clock.advance(3600)
        upgrade=self.city.plan(620,self.sample(6200),self.weather('rain'))
        self.assertEqual((upgrade['players'],upgrade['weather']),(6200,'RAN'))
        self.assertNotIn('_confirmed_restore',upgrade)
        self.confirm(upgrade)
        self.assertIsNone(self.city.plan(620,self.sample(6200),self.weather('rain')))

    def test_hourly_numeric_refresh_tiers_and_restart(self):
        first=self.city.plan(620,self.sample(),self.weather());self.confirm(first)
        for minute in range(1,60):
            self.clock.advance(60)
            self.assertIsNone(self.city.plan(620,self.sample(32809+minute),self.weather()))
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
        self.clock.advance(60)
        self.assertEqual(self.city.plan(620,self.sample(32999),self.weather())['players'],32999)
        self.assertEqual(self.city.plan(620,self.sample(100000),self.weather())['players'],100000)
        self.assertEqual(self.city.plan(620,self.sample(32999),self.weather('rain'))['weather'],'RAN')

    def test_weather_phase_and_tier_changes_also_wait_one_hour(self):
        first=self.city.plan(620,self.sample(),self.weather());self.confirm(first)
        for minute in range(1,60):
            self.clock.advance(60)
            self.assertIsNone(self.city.plan(620,self.sample(100000),dict(condition='rain',phase='night')))
        self.clock.advance(60)
        fresh=self.city.plan(620,self.sample(100000),dict(condition='rain',phase='night'))
        self.assertEqual((fresh['players'],fresh['weather'],fresh['phase']),(100000,'RAN','night'))

    def test_screensaver_authorizes_one_fresh_city_without_waiting_for_the_hour(self):
        self.confirm(self.city.plan(620,self.sample(),self.weather()))
        self.clock.advance(60)
        self.city.allow_screensaver_refresh(620)
        fresh=self.city.plan(620,self.sample(32999),self.weather('rain'),restore=True)
        self.assertEqual(fresh['players'],32999)
        self.confirm(fresh)
        self.assertIsNone(self.city.plan(620,self.sample(33000),self.weather('storm')))
        self.clock.advance(3600)
        self.assertEqual(self.city.plan(620,self.sample(33000),self.weather())['players'],33000)

    def test_legacy_deferred_attempt_and_failed_storage_never_block_initial_display(self):
        payload=self.city.plan(620,self.sample(6176),self.weather())
        self.path.write_text(json.dumps(dict(schema=1,confirmed=None,attempt={**payload,'at':self.clock.wall(),'outcome':'deferred'})))
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
        fresh=self.city.plan(620,self.sample(6176),self.weather())
        self.assertIsNotNone(fresh)
        with patch.object(self.city,'_save',side_effect=OSError('read only')):
            self.confirm(fresh)
        self.assertEqual(self.city.status()['displayed']['players'],6176)
        self.assertEqual(self.city.status()['reason'],'confirmed')
        self.assertEqual(self.city.status()['storage_error'],'journal_unavailable')

    def test_zero_errors_missing_weather_preserve_image_and_restore_old_measurement(self):
        first=self.city.plan(620,self.sample(),self.weather());self.confirm(first);self.clock.advance(600)
        for sample,weather,reason in [(self.sample(0),self.weather(),'zero'),
                ({'appid':620,'state':'network_error'},self.weather(),'network_error'),(self.sample(),None,'weather_unavailable')]:
            self.assertIsNone(self.city.plan(620,sample,weather));self.assertEqual(self.city.status()['reason'],reason)
            self.assertEqual(self.city.status()['displayed']['players'],32809)
        restored=self.city.plan(620,self.sample(32999),self.weather(),restore=True)
        self.assertEqual(restored['players'],32809,'Restore cannot bypass hourly number cadence')
        self.assertIsNone(self.city.plan(570,{'appid':570,'state':'waiting'},self.weather(),restore=True))

    def test_corrupt_cadence_journal_cannot_prevent_plugin_construction(self):
        for payload in ([],None,True,{'schema':2},{'schema':1,'confirmed':[]}):
            self.path.write_text(json.dumps(payload))
            city=PlayerCityCadence(self.path,clock=self.clock.wall)
            self.assertEqual(city.status()['storage_error'],'journal_unavailable')
            self.assertIsNotNone(city.plan(620,self.sample(),self.weather()))

    def test_status_read_does_not_wait_for_worker_journal_lock(self):
        self.city.status()
        entered,release,timed_out=threading.Event(),threading.Event(),threading.Event()
        def hold():
            with self.city.lock:
                entered.set()
                if not release.wait(2):timed_out.set()
        worker=threading.Thread(target=hold);worker.start();self.assertTrue(entered.wait(1))
        try:self.city.status();self.assertFalse(timed_out.is_set())
        finally:release.set();worker.join(1)

    def test_immediate_restore_after_ack_uses_confirmed_snapshot_not_a_new_count(self):
        first=self.city.plan(620,self.sample(),self.weather());self.confirm(first)
        self.clock.advance(1)
        restored=self.city.plan(620,self.sample(32999),self.weather(),restore=True)
        self.assertEqual(restored['players'],32809)
        self.confirm(restored)
        self.assertIsNone(self.city.plan(620,self.sample(),self.weather('rain')),'The single hourly cadence also applies to weather')
        self.clock.advance(3599)
        self.assertEqual(self.city.plan(620,self.sample(32999),self.weather())['players'],32999)
        # Repeated temporary returns cannot keep the exact-number update overdue.
        restored=self.city.plan(620,self.sample(32999),self.weather(),restore=True)
        self.confirm(restored)
        self.assertEqual(self.city.plan(620,self.sample(32999),self.weather())['players'],32999)

    def test_uncertain_ack_and_pending_restart_retry_on_the_next_hour(self):
        first=self.city.plan(620,self.sample(),self.weather());self.city.reserve(first)
        self.city=PlayerCityCadence(self.path,clock=self.clock.wall);self.clock.advance(3600)
        self.assertIsNotNone(self.city.plan(620,self.sample(),self.weather()))
        self.assertIsNone(self.city.status()['displayed'])

    def test_route_persistence_is_game_only_and_revision_shared(self):
        store=FaceplatePreferencesStore(Path(self.temp.name)/'prefs.json')
        next=store.update(game_scene='player-city',expected_revision=0)
        self.assertEqual(FaceplatePreferencesStore(store.path).read().game_scene,'player-city')
        self.assertEqual(next.home_scene,'dashboard')
        with self.assertRaises(ValueError):store.update(home_scene='player-city')

    def test_24_hour_churn_is_limited_only_by_hourly_cadence_and_survives_restart(self):
        guard=FlashWearProtection(Path(self.temp.name)/'flash.json',monotonic=self.clock,wall_clock=self.clock.wall)
        attempts=0
        for minute in range(24*60):
            sample=self.sample(10 if minute%2 else 100000)
            payload=self.city.plan(620,sample,self.weather('rain' if minute%2 else 'storm'))
            if payload:
                self.city.reserve(payload);data=json.dumps(payload).encode();wanted=guard.preflight(data,'player-city')
                try:
                    guard.reserve_body(wanted,'player-city');guard.receipt(wanted,wrote=True);attempts+=1
                    self.city.receipt(payload,{'synchronized':True})
                except UploadDeferred:self.city.receipt(payload,{'deferred':True})
            if minute==720:
                guard.flush(force=True)
                guard=FlashWearProtection(guard.path,monotonic=self.clock,wall_clock=self.clock.wall)
                self.city=PlayerCityCadence(self.path,clock=self.clock.wall)
            self.clock.advance(60)
        self.assertEqual(attempts,24)
        self.assertEqual(guard.status()['attempts_last_day'],23,'The first reservation expires exactly at 24h')


class PlayerCitySerial(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.clock=Clock();self.panel=Panel()
        self.sleep=patch('signalbar.faceplate.transport.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
        panel=self.panel
        class ContextLink(Link):
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def command(self,data,**kwargs):return panel.command(data,**kwargs)
            def write(self,data):pass
        self.coordinator=FaceplateCoordinator(self.temp.name,Path(self.temp.name)/'state.json',
            link_factory=ContextLink,port_finder=lambda:'/dev/null',identity_reader=lambda _:'device',
            monotonic=self.clock,wall_clock=self.clock.wall)
        self.coordinator.configure(True,75)

    def send(self,n):
        scene=build_player_city('SUN','day',n)
        return self.coordinator.synchronize_scene(scene.gif(),'player-city',scene.signature)

    def test_user_case_6176_players_uploads_despite_all_old_limits_and_manual_brightness_is_unchanged(self):
        guard=self.coordinator.flash
        guard.tokens=0
        guard.attempts.extend([self.clock()]*120)
        guard.daily_attempts.extend([self.clock()]*128)
        guard.background_attempts.extend([self.clock()]*24)
        guard.history_state='lost'
        self.assertTrue(self.send(6176)['synchronized'])
        bodies=self.panel.bodies;brightness=self.coordinator.command_counts['brightness']
        self.assertFalse(self.send(6176)['wrote'])
        self.assertEqual(self.panel.bodies,bodies)
        self.assertTrue(self.send(6177)['synchronized'])
        self.assertEqual(self.coordinator.brightness,75)
        self.assertEqual(self.coordinator.command_counts['brightness'],brightness)
        for priority in ('background','player-city','player-city-restore','assistant','restore'):
            self.assertEqual(guard.delay(priority),0)
        self.assertEqual(guard.status()['player_city']['retry_after_seconds'],0)

    def test_unknown_or_unwritable_flash_history_never_blocks_city(self):
        guard=self.coordinator.flash
        guard.history_state='corrupt'
        with patch.object(guard,'flush',return_value=False):
            self.assertTrue(self.send(6176)['synchronized'])
        self.assertGreater(self.panel.bodies,0)
        self.assertEqual(guard.session['confirmed'],1)

    def test_history_loss_does_not_reintroduce_a_wait_after_restart(self):
        path=Path(self.temp.name)/'lost-flash.json'
        guard=FlashWearProtection(path,monotonic=self.clock,wall_clock=self.clock.wall)
        guard.marker.write_text('known device')
        guard=FlashWearProtection(path,monotonic=self.clock,wall_clock=self.clock.wall)
        self.assertEqual(guard.delay('player-city'),0)
        restarted=FlashWearProtection(path,monotonic=self.clock,wall_clock=self.clock.wall)
        self.assertEqual(restarted.delay('player-city'),0)

    def test_cancelled_request_never_sends_a_body(self):
        scene=build_player_city('STR','night',32809)
        result=self.coordinator.synchronize_scene(scene.gif(),'player-city',scene.signature,cancelled=lambda:True)
        self.assertTrue(result['superseded']);self.assertEqual(self.panel.bodies,0)

    def test_rotated_city_sends_one_autonomous_animation_and_deduplicates(self):
        self.coordinator.rotate_180=True
        scene=build_player_city('RAN','night',6176)
        payload=scene.gif()
        rotated=self.coordinator._orient_gif(payload)
        decoded=Image.open(BytesIO(rotated))
        self.assertEqual(decoded.n_frames,192)
        for n,frame in enumerate(scene.frames):
            decoded.seek(n)
            expected=Image.frombytes('RGB',(64,54),frame).transpose(Image.Transpose.ROTATE_180)
            self.assertEqual(decoded.convert('RGB').tobytes(),expected.tobytes())
            self.assertEqual(decoded.info['duration'],scene.delays_cs[n]*10)
        self.assertTrue(self.coordinator.synchronize_scene(payload,'player-city',scene.signature)['synchronized'])
        self.assertEqual(self.panel.calls.count((protocol.TYPE_CONTROL,protocol.CMD_GIF_END)),1,
                         'One GIF transaction, never one transfer per animation frame')
        chunks=self.panel.bodies
        self.assertEqual(chunks,(len(rotated)+protocol.CHUNK_SIZE-1)//protocol.CHUNK_SIZE)
        self.assertFalse(self.coordinator.synchronize_scene(payload,'player-city',scene.signature)['wrote'])
        self.assertEqual(self.panel.bodies,chunks)

    def test_animation_pack_corruption_is_reported_before_serial(self):
        from signalbar.faceplate import player_city_animation as animation
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'manifest.json').write_bytes((animation.ROOT/'manifest.json').read_bytes())
            row=animation_manifest()['images'][0]
            (root/row['file']).write_bytes(b'corrupt')
            animated_rgb.cache_clear();animation_manifest.cache_clear()
            try:
                with patch.object(animation,'ROOT',root),self.assertRaisesRegex(ValueError,'pack integrity'):
                    build_player_city(row['weather'],row['phase'],1)
            finally:
                animated_rgb.cache_clear();animation_manifest.cache_clear()
        self.assertEqual(self.panel.bodies,0)


class PlayerCityEngineIntegration(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        from signalbar.backend import Engine
        from signalbar.settings import SettingsStore
        from signalbar.models import GameState
        PlayerCitySerial.setUp(self)
        settings=SettingsStore(str(Path(self.temp.name)/'settings.json'))
        settings.update({'signalbar_enabled':True,'faceplate_lab_enabled':True,'faceplate_brightness':75})
        prefs=FaceplatePreferencesStore(Path(self.temp.name)/'routes.json')
        prefs.update(game_scene='player-city')
        self.engine=Engine(settings,str(Path(self.temp.name)/'cache.json'),faceplate=self.coordinator,faceplate_preferences=prefs)
        self.addCleanup(self.engine.stop)
        self.engine.current_players.stop()
        self.sample=dict(appid=620,state='ready',usable=True,players=32809,sampled_at=self.clock.wall())
        self.engine.current_players=Mock()
        self.engine.current_players.status.side_effect=lambda:dict(self.sample)
        self.engine.player_city=PlayerCityCadence(Path(self.temp.name)/'city.json',clock=self.clock.wall)
        self.engine._game=GameState(620,'Portal 2')
        self.engine._faceplate_weather_payload=Mock(return_value=(dict(condition='clear_day',phase='day'),{},''))
        self.engine.faceplate_worker=Mock()
        self.engine.faceplate_worker.status.return_value={'busy':False,'queued':False}
        def dispatch(scene,payload,metadata):
            self.result=self.engine._handle_faceplate_scene({'payload':payload,'metadata':metadata,'_cancelled':threading.Event()})
            return 1
        self.engine.faceplate_worker.submit.side_effect=dispatch
        self.engine._write_faceplate_runtime_status=Mock()

    def test_actual_engine_prepares_acknowledges_and_does_not_write_each_new_count(self):
        self.engine._reconcile_faceplate('routing-change',force=True)
        self.assertTrue(self.result['synchronized'])
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'],'player-city')
        self.assertEqual(self.engine.player_city.status()['displayed']['players'],32809)
        before=self.panel.bodies
        for n in range(20):
            self.sample['players']+=1
            self.engine._reconcile_faceplate()
        self.assertEqual(self.panel.bodies,before)
        self.assertEqual(self.engine.current_players.configure.call_args.args,(620,))
        self.engine._reconcile_faceplate(hardware={'available':False})
        self.assertEqual(self.engine.current_players.configure.call_args.args,(0,))
        self.engine.faceplate_worker.cancel_scene_class.assert_called_with('player-city')

    def test_waiting_for_steam_exposes_game_route_and_fences_previous_home_ticket(self):
        home = self.engine.faceplate_router.reconcile(game_running=False, content_key='home-image')
        self.engine.faceplate_router.commit(home)
        self.sample.update(state='waiting', usable=False, players=None)
        self.engine._reconcile_faceplate('automatic-game-change')
        route = self.engine.faceplate_router.status()
        self.assertEqual(route['context'], 'game')
        self.assertEqual(route['desired_scene'], 'player-city')
        self.assertEqual(route['effective_scene'], 'dashboard')
        self.assertEqual(route['preparation']['state'], 'pending')
        self.assertFalse(self.engine.faceplate_router.commit(home))
        self.engine.faceplate_worker.submit.assert_not_called()
        self.engine._write_faceplate_runtime_status.assert_called()
        generation = route['generation']
        self.sample['state'] = 'tls_error'
        self.engine._reconcile_faceplate()
        self.assertEqual(self.engine.faceplate_router.status()['generation'], generation)
        self.assertEqual(self.engine.player_city.status()['reason'], 'tls_error')
        self.sample.update(state='ready', usable=True, players=5636)
        self.engine._reconcile_faceplate()
        self.assertTrue(self.result['synchronized'])
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'], 'player-city')

    def test_actual_engine_decky_rpc_receives_measurement_then_renders_and_acknowledges(self):
        self.engine.current_players=CurrentPlayers(transport='decky',clock=self.clock,wall_clock=self.clock.wall)
        self.engine._reconcile_faceplate('automatic-game-change')
        self.engine.faceplate_worker.submit.assert_not_called()
        lease=self.engine.claim_player_city_poll()
        self.assertEqual(lease['appid'],620)
        self.assertIsNone(self.engine.current_players.thread)
        self.assertIsNone(self.engine.claim_player_city_poll())
        self.assertTrue(self.engine.complete_player_city_poll(lease['request_id'],620,
            {'response':{'result':1,'player_count':5636}}))
        self.assertTrue(self.result['synchronized'])
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'],'player-city')
        self.assertEqual(self.engine.player_city.status()['displayed']['players'],5636)
        self.assertEqual(self.coordinator.brightness,75)

    def test_engine_restores_acknowledged_count_without_promoting_latest_measurement(self):
        self.engine._reconcile_faceplate('routing-change',force=True)
        self.clock.advance(1);self.sample['players']=32999
        self.panel.stored=None
        self.engine._reconcile_faceplate('current-route-restore',force=True)
        self.assertEqual(self.engine.faceplate_worker.submit.call_args.args[1]['players'],32809)
        self.assertTrue(self.engine.faceplate_worker.submit.call_args.args[2]['player_city_restore'])
        self.assertEqual(self.coordinator._upload_priority('player-city','player-city-confirmed-restore'),'player-city-restore')
        self.clock.advance(3600)
        self.engine._reconcile_faceplate('periodic')
        self.assertEqual(self.engine.faceplate_worker.submit.call_args.args[1]['players'],32999)
        self.assertFalse(self.engine.faceplate_worker.submit.call_args.args[2]['player_city_restore'])

    def test_steam_screensaver_grants_fresh_return_once_without_competing_with_its_owner(self):
        from unittest.mock import Mock
        self.engine._reconcile_faceplate('routing-change',force=True)
        self.clock.advance(60);self.sample['players']=32999
        self.engine.jsaux_broker_adapter=Mock()
        self.engine.jsaux_broker_adapter.holds_display.return_value=True
        self.engine.set_screen_sync_context('steam-screensaver',True)
        self.engine.set_screen_sync_context('steam-screensaver',True)
        previous=self.engine.faceplate_worker.submit.call_count
        self.engine._reconcile_faceplate()
        self.assertEqual(self.engine.faceplate_worker.submit.call_count,previous)
        self.engine.set_screen_sync_context('steam-screensaver',False)
        self.engine.jsaux_broker_adapter.holds_display.return_value=False
        self.engine._reconcile_faceplate('current-route-restore',force=True)
        self.assertEqual(self.engine.player_city.status()['displayed']['players'],32999)
        self.sample['players']=33000
        self.engine._reconcile_faceplate()
        self.assertEqual(self.engine.faceplate_worker.submit.call_count,previous+1)

    def test_game_change_after_render_never_enters_serial(self):
        from signalbar.models import GameState
        original=self.engine._render_faceplate_scene
        def delayed(payload,ticket):
            result=original(payload,ticket)
            self.engine._game=GameState(570,'Dota 2')
            return result
        self.engine._render_faceplate_scene=delayed
        self.engine._reconcile_faceplate('routing-change',force=True)
        self.assertTrue(self.result['superseded']);self.assertEqual(self.panel.bodies,0)
        self.assertIsNone(self.engine.player_city.status()['displayed'])

    def test_external_screensaver_and_assistant_keep_priority(self):
        from unittest.mock import Mock
        self.engine._assistant_holds_matrix=Mock(return_value=True)
        self.engine._reconcile_faceplate('routing-change',force=True)
        self.engine.faceplate_worker.submit.assert_not_called()
        self.engine._assistant_holds_matrix.return_value=False
        self.engine.jsaux_broker_adapter=Mock()
        self.engine.jsaux_broker_adapter.holds_display.return_value=True
        self.engine._reconcile_faceplate('routing-change',force=True)
        self.engine.faceplate_worker.submit.assert_not_called()
        self.engine.jsaux_broker_adapter.holds_display.return_value=False
        self.engine._reconcile_faceplate('current-route-restore',force=True)
        self.assertTrue(self.result['synchronized'])
