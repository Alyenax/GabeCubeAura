"""Clock replanning preserves its playback session, independently of packet jobs."""
import unittest
from unittest.mock import Mock,patch
from signalbar.faceplate.clocks import ClockRuntime
import test_native_clock as native_fixture


class ClockSeamTests(unittest.TestCase):
    def test_solar_status_latency_is_not_a_wall_clock_jump_or_new_playback(self):
        for cadence in ('conservative','minute'):
            fixture=native_fixture.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight')
            fixture.setUp();self.addCleanup(fixture.doCleanups)
            engine=fixture.engine;fixture.settings.update({'faceplate_clock_home':'horizon','faceplate_clock_cadence_home':cadence})
            fixture.prefs.update(home_scene='clock');engine._faceplate_continuity=Mock(return_value=('',False))
            engine.faceplate_worker.submit=Mock(return_value=1)
            appearance={'palette':'amber','format':'24','language':'en'}
            first=engine.clock_runtime.plan('horizon','home',1205,True,monotonic=100,options=appearance,cadence=cadence)
            engine.clock_runtime.receipt(first,{'synchronized':True},1223)
            wall=[1230.];mono=[125.]
            def slow_solar(_):wall[0]+=.75;mono[0]+=.75;return {}
            engine.weather.solar_status=slow_solar
            with patch('signalbar.backend.engine.time.time',side_effect=lambda:wall[0]),patch('signalbar.backend.engine.time.monotonic',side_effect=lambda:mono[0]):
                engine._reconcile_faceplate('periodic',hardware=engine.faceplate.device_status())
            engine.faceplate_worker.submit.assert_not_called()
            self.assertEqual(first,engine.clock_runtime.active)


if __name__=='__main__':unittest.main()
