"""Combined DAS exit, missing city and recovery; real packets, simulated MCU."""
import threading
import unittest
from unittest.mock import Mock,patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.faceplate.coordinator import encode_frame
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.broker_adapter import FaceplateBrokerAdapter
from signalbar.faceplate.transport import install_ownership_manager
from signalbar.faceplate.flash import install_manager,default_manager
import test_screensaver_restore148 as fixture

class Recovery244Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Restore148Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.addCleanup(install_manager,default_manager());self.addCleanup(install_ownership_manager,None)
        self.store=SettingsStore(str(self.f.root/'config.json'))
        self.store.update({'faceplate_lab_enabled':True,'weather_location':None})
        self.prefs=FaceplatePreferencesStore(self.f.root/'routes.json');self.prefs.update(home_scene='weather')
        self.engine=Engine(self.store,str(self.f.root/'cache.json'),faceplate=self.f.coordinator,faceplate_preferences=self.prefs)
        self.addCleanup(self.engine.stop)
        self.engine._faceplate_power_target=None
        self.engine._faceplate_continuity=Mock(return_value=('',False))
        self.engine.weather.status=Mock(return_value={'phase':'off','condition':'','sunrise_at':'','sunset_at':'','faceplate_weather_state':'unavailable'})
        self.engine.faceplate_worker=Mock();self.engine.faceplate_worker.status.return_value={'busy':False,'queued':False}
        def dispatch(scene,payload,metadata):
            self.result=self.engine._handle_faceplate_scene({'payload':payload,'metadata':metadata,'_cancelled':threading.Event()});return 1
        self.engine.faceplate_worker.submit.side_effect=dispatch
        self.engine._write_faceplate_runtime_status=Mock()
        self.adapter=FaceplateBrokerAdapter(self.engine,self.f.root/'ownership')
        self.addCleanup(self.adapter.stop)

    def test_das_exit_missing_city_recovery_restart_and_second_das_transfer(self):
        c=self.f.coordinator
        first=c.synchronize_scene(encode_frame(bytes([0,0,8])*3456),'screensaver','das',peak_load=.1,delegated=True)
        self.assertTrue(first['synchronized'])
        self.f.exit()
        self.assertEqual(self.adapter._policy()['reason'],'DISPLAY_OFF')
        self.assertGreater(self.engine._reconcile_faceplate(),0)
        self.assertTrue(self.result['synchronized'],self.result)
        self.assertTrue(c.powered);self.assertFalse(c.restoration_status()['pending'])
        self.assertTrue(self.engine.faceplate_worker.submit.call_args.args[1]['weather_unavailable'])
        self.assertIsNone(self.adapter._policy()['reason'])
        second=c.synchronize_scene(encode_frame(bytes([0,0,8])*3456),'screensaver','das2',peak_load=.1,delegated=True)
        self.assertTrue(second['synchronized'])
        self.f.exit();c=self.f.new_coordinator();self.engine.faceplate=c;self.f.coordinator=c
        self.f.panel.token='reconnected'
        # Real startup power request must defer to replacement, then normal routing recovers.
        self.assertTrue(self.engine._apply_faceplate_power(True,'automatic power recovery')['deferred_to_route'])
        self.engine._reconcile_faceplate()
        self.assertTrue(self.result['synchronized']);self.assertTrue(c.powered)
        self.assertFalse(c.restoration_status()['pending'])

    def test_explicit_off_is_never_recovered_or_ceded_to_das(self):
        self.f.exit();self.engine.set_faceplate_power(False)
        self.f.panel.events.clear()
        for _ in range(8):self.engine._reconcile_faceplate()
        self.assertEqual(self.f.panel.events,[])
        self.assertEqual(self.adapter._policy()['reason'],'DISPLAY_OFF')
        self.engine.faceplate_worker.submit.assert_not_called()

    def test_failure_is_paced_and_capped_without_power_on_or_render_storm(self):
        self.f.exit();now=[100.0]
        self.engine.faceplate_worker.submit.side_effect=lambda *args:1
        with patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:now[0]):
            for attempt in range(3):
                self.assertGreater(self.engine._reconcile_faceplate(),0)
                ticket=self.engine.faceplate_router._active_ticket
                self.engine.faceplate_router.fail(ticket,'simulated pre-transfer failure')
                for _ in range(20):self.assertEqual(self.engine._reconcile_faceplate(),0)
                now[0]+=61
            for _ in range(20):self.assertEqual(self.engine._reconcile_faceplate(),0)
        self.assertEqual(self.engine._faceplate_route_recovery['state'],'exhausted')
        self.assertEqual(self.engine.faceplate_worker.submit.call_count,3)
        self.f.assert_no_on()

    def test_lost_final_ack_does_not_retry_before_the_bounded_delay(self):
        self.f.exit();self.f.panel.lose_end=True
        self.engine._reconcile_faceplate()
        self.assertTrue(self.result['sent_unconfirmed'])
        self.f.panel.events.clear()
        for _ in range(20):self.engine._reconcile_faceplate()
        self.assertEqual(self.f.panel.events,[])
        self.assertEqual(self.engine._faceplate_route_recovery['state'],'retry-waiting')
        self.f.assert_no_on()

    def test_explicit_power_on_can_retry_an_exhausted_replacement(self):
        self.f.exit()
        preferences=self.prefs.read()
        self.engine._faceplate_route_recovery={
            'key':(self.store._commit_serial,preferences.revision,
                   self.engine._game.appid,self.f.coordinator.device_token),
            'attempts':3,'state':'exhausted'}
        self.engine._faceplate_scene_retry_at=float('inf')
        self.engine.set_faceplate_power(True)
        self.assertTrue(self.result['synchronized'],self.result)
        self.assertTrue(self.f.coordinator.powered)
        self.assertFalse(self.f.coordinator.restoration_status()['pending'])
        self.assertEqual(self.engine._faceplate_route_recovery['attempts'],1)
