"""Clock image projection and same-session renewal; no physical playback claim."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from signalbar.faceplate.clocks import ClockPacket
from signalbar.faceplate.source_projection import background_key, clock_projection, project_backgrounds
from signalbar.faceplate.scene_renderer import render_isolated
from signalbar.faceplate import protocol
from signalbar.providers.faceplate_extension import FaceplateExtension
from signalbar.models import GameState
import test_faceplate_extension as extension_fixture
import test_native_clock as native_fixture


class ClockProjectionTests(unittest.TestCase):
    def test_duration_weighting_and_black_pixels_are_preserved(self):
        a=bytes((255,0,0))*3456;b=bytes((0,0,255))*3456
        source=clock_projection((a,b),(1,3))
        self.assertEqual('clock-strip',source['kind'])
        for colours in source['colours'].values():self.assertEqual([(64,0,191)]*17,colours)
        self.assertEqual([(0,0,0)]*17,clock_projection((bytes(10368),),(1,))['colours']['whole'])

    def test_all_mappings_match_independent_area_reducer_and_rotation(self):
        a=extension_fixture.frame(lambda x,y:(x*4,y*4,40))
        b=extension_fixture.frame(lambda x,y:(255-x*4,100,y*4))
        source=clock_projection((a,b),(2,3))
        for mapping in ('bottom','whole'):
            for rotated in (False,True):
                self.assertEqual(project_backgrounds((a,a,b,b,b),mapping,rotated),
                    source['colours'][mapping+('-rotated' if rotated else '')])

    def test_local_diagnostic_export_keeps_the_clock_action_but_drops_source_hashes(self):
        from signalbar.diagnostics import DiagnosticJournal
        journal=DiagnosticJournal.__new__(DiagnosticJournal)
        result=journal._upload_observability_snapshot({'journal':[{
            'scene':'clock','outcome':'written','clock_power_on_skipped':True,
            'sha256':'private-source-hash','serial_path':'/private/device'}]})
        self.assertNotIn('clock_power_on_skipped',result['journal'][0])
        self.assertNotIn('sha256',result['journal'][0])
        self.assertNotIn('serial_path',result['journal'][0])

    def test_malformed_timelines_remain_ineligible(self):
        good=bytes(10368)
        for frames,delays in [((),()),((b'bad',),(1,)),((good,),(0,)),((good,),(25001,)),((good,),()),((good,),(True,))]:
            with self.assertRaises(ValueError):clock_projection(frames,delays)

    def test_route_identity_tracks_native_clock_and_context_without_dashboard_fields(self):
        p=dict(kind='clock',clock_id='horizon',display_at=1000,end_at=1210,night=False,
               options={'palette':'rose','language':'fr','format':'12'})
        key=background_key(p,'home',0);self.assertIsNotNone(key)
        self.assertEqual(key,background_key({**p,'temperature_c':90,'battery':40},'home',0))
        for changes in ({'clock_id':'week'},{'display_at':1200},{'night':True},{'options':{'palette':'sage'}}):
            self.assertNotEqual(key,background_key({**p,**changes},'home',0))
        self.assertNotEqual(key,background_key(p,'game',620))

    def test_real_isolated_clock_supplies_projection_without_second_decoder(self):
        request=dict(kind='clock',clock_id='horizon',display_at=1000,end_at=1210,
                     night=False,options={'palette':'rose','format':'12','language':'fr'})
        _,manifest=render_isolated(request)
        from signalbar.faceplate.clocks import build_packet
        packet=build_packet(request)
        expected=clock_projection(packet.frames,packet.delays_cs)
        self.assertEqual(expected['sha256'],manifest['projection_source']['sha256'])
        with tempfile.TemporaryDirectory() as folder:
            provider=FaceplateExtension(folder);self.addCleanup(provider.stop)
            for mapping in ('bottom','whole'):
                for rotated in (False,True):
                    with patch('signalbar.providers.faceplate_extension.subprocess.Popen',side_effect=AssertionError('extra renderer')):
                        provider.configure(True,manifest['projection_source'],mapping,rotated)
                        extension_fixture.wait_ready(provider)
                    self.assertEqual(expected['colours'][mapping+('-rotated' if rotated else '')],provider.status()['colours'])


class ClockEngineTests(unittest.TestCase):
    def setUp(self):
        fixture=native_fixture.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight')
        fixture.setUp();self.addCleanup(fixture.doCleanups);self.fixture=fixture;self.engine=fixture.engine
        fixture.settings.update({'faceplate_clock_home':'horizon','faceplate_clock_game':'week'})
        fixture.prefs.update(home_scene='clock',game_scene='clock')
        self.engine.faceplate_worker.submit=Mock(return_value=1)
        self.engine._faceplate_extension_present=True
        self.wall=[1000.];self.mono=[100.]
        self.engine._stop=Mock();self.engine._stop.is_set.return_value=False
        def wait(seconds):self.wall[0]+=seconds;self.mono[0]+=seconds
        self.engine._stop.wait.side_effect=wait
        from signalbar.backend import Engine
        self.engine._render_faceplate_scene=lambda p,t:Engine._render_faceplate_scene(self.engine,p,t)

    def plan(self,game=GameState()):
        self.engine._game=game
        with patch('signalbar.backend.engine.time.time',side_effect=lambda:self.wall[0]),patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:self.mono[0]):
            self.engine._reconcile_faceplate('test-clock-extension',force=True,hardware=self.engine.faceplate.status())
        payload=self.engine.faceplate_worker.submit.call_args.args[1]
        self.assertTrue(payload['_extension_background_key'])
        return payload

    def test_home_and_game_clock_reach_real_projection_and_reject_stale_context(self):
        home=self.plan()
        with patch('signalbar.backend.engine.time.time',side_effect=lambda:self.wall[0]),patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:self.mono[0]),patch('signalbar.faceplate.transport.time.sleep'):
            result=self.engine._handle_faceplate_scene({'payload':home,'metadata':{},'_cancelled':None})
        self.assertTrue(result['synchronized'])
        self.assertEqual('clock-strip',self.engine._faceplate_extension_source['kind'])
        values=self.engine.settings.all()
        self.engine._faceplate_extension_output(values,GameState(),'faceplate_extension',self.mono[0])
        extension_fixture.wait_ready(self.engine.faceplate_extension)
        output=self.engine._faceplate_extension_output(values,GameState(),'faceplate_extension',self.engine.faceplate_extension.ready_at+1)
        self.assertEqual('faceplate-extension:clock-strip',output.provider)
        self.assertTrue(self.engine._faceplate_extension_status()['faceplate_confirmed'])
        game=self.plan(GameState(620,'Example'))
        self.assertFalse(self.engine._publish_faceplate_extension_source(home,home['ticket'],{},result['projection_source'],prepared=True))
        # Prepared colours are independent of the hardware receipt.
        self.assertTrue(self.engine._publish_faceplate_extension_source(game,game['ticket'],{},result['projection_source'],prepared=True))
        self.assertFalse(self.engine._faceplate_extension_status()['faceplate_confirmed'])

    def send(self):
        raw=native_fixture.encode_frame(bytes((40,20,10))*3456)
        with patch('signalbar.faceplate.transport.time.sleep'):
            return self.fixture.faceplate.synchronize_scene(raw,'clock','clock-test')

    def test_confirmed_baseline_renewal_does_not_send_power_on_or_add_a_body(self):
        first=self.send();self.assertTrue(first['synchronized'])
        self.assertIn(protocol.power(True),self.fixture.calls)
        self.fixture.calls.clear();second=self.send()
        self.assertTrue(second['synchronized']);self.assertTrue(second['transfer']['clock_power_on_skipped'])
        self.assertNotIn(protocol.power(True),self.fixture.calls)
        self.assertEqual(1,sum(c[2:4]==b'\x01\x04' for c in self.fixture.calls))
        self.assertEqual(1,sum(c[2:4]==b'\x01\x0b' for c in self.fixture.calls))

    def test_reconnect_off_unconfirmed_and_other_scene_keep_activation(self):
        for state in ('reconnect','off','unconfirmed','other-scene','delegate-pending','vendor'):
            with self.subTest(state=state):
                self.send();panel=self.fixture.faceplate
                if state=='reconnect':self.fixture.token+='-new'
                elif state=='off':panel.powered=False
                elif state=='unconfirmed':panel.last_synchronized=False
                elif state=='other-scene':panel.delivery['scene']='artwork'
                elif state=='delegate-pending':panel._delegated_gif_activation_pending=True
                else:
                    factory=panel.link_factory
                    panel.link_factory=lambda **kwargs:factory(transport_profile='vendor',**kwargs)
                self.fixture.calls.clear();result=self.send()
                self.assertFalse(result['transfer']['clock_power_on_skipped'])
                self.assertIn(protocol.power(True),self.fixture.calls)
                panel._delegated_gif_activation_pending=False


if __name__=='__main__':unittest.main()
