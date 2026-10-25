"""Missing-city recovery uses real routing/serial ACKs; hardware remains simulated."""
import unittest
from io import BytesIO
from PIL import Image
from unittest.mock import Mock,patch
import test_native_clock as native
import test_screensaver_restore148 as restore
from signalbar.faceplate.scenes import build_weather_unavailable

class MissingWeather242(unittest.TestCase):
    def test_removed_city_reaches_real_serial_for_each_weather_dependent_home_route(self):
        for route in ('weather','dashboard','artwork-dashboard','artwork'):
            with self.subTest(route=route):
                f=native.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight');f.setUp()
                try:
                    f.prefs.update(home_scene=route)
                    f.engine._faceplate_power_target=None
                    f.engine.weather.status=Mock(return_value={'phase':'off','condition':'','sunrise_at':'','sunset_at':'','faceplate_weather_state':'unavailable'})
                    f.engine._faceplate_continuity=Mock(return_value=('',False))
                    f.engine._reconcile_faceplate('current-route-restore',force=True)
                    self.assertTrue(f.result.get('synchronized'),f.result)
                    self.assertEqual(f.engine.faceplate_router.status()['effective_scene'],route)
                    payload=f.engine.faceplate_worker.submit.call_args.args[1]
                    self.assertTrue(payload['weather_unavailable'])
                    self.assertNotIn('Invalid isoformat',f.engine.faceplate_router.status()['preparation']['error'])
                    f.engine._render_faceplate_scene.assert_not_called()
                    f.engine.faceplate_worker.submit.reset_mock()
                    for _ in range(5):f.engine._reconcile_faceplate()
                    f.engine.faceplate_worker.submit.assert_not_called()
                    self.assertEqual(f.prefs.read().home_scene,route)
                finally:f.doCleanups()

    def test_restart_and_reconnect_never_power_old_screensaver_on_before_replacement_ack(self):
        f=restore.Restore148Tests('test_acked_exit_old_automatic_on_is_deferred_without_usb_or_false_ack');f.setUp()
        try:
            # Firmware starts with autonomous DAS GIF, host has no confirmed route.
            c=f.coordinator
            self.assertEqual(c.delivery['state'],'idle')
            result=c.set_power(True,'automatic power recovery')
            self.assertTrue(result['deferred_to_route']);f.assert_no_on()
            c=f.new_coordinator();f.coordinator=c
            self.assertTrue(c.restoration_status()['pending'])
            self.assertTrue(c.set_power(True,'automatic power recovery')['deferred_to_route']);f.assert_no_on()
            self.assertTrue(f.restore()['synchronized']);self.assertEqual(Image.open(BytesIO(f.panel.visible)).convert('RGB').tobytes(),Image.open(BytesIO(restore.HOME)).convert('RGB').tobytes())
            self.assertFalse(c.restoration_status()['pending'])
            # Even an earlier normal-route ACK cannot authorize a later
            # delegated GIF retained across a client failure.
            c._persist_delegated_pending(True)
            f.panel.events.clear()
            self.assertTrue(c.set_power(True,'automatic power recovery')['deferred_to_route']);f.assert_no_on()
            self.assertTrue(f.restore()['synchronized'])
            f.panel.events.clear();f.panel.token='usb-reconnected'
            self.assertTrue(c.set_power(True,'automatic power recovery')['deferred_to_route']);f.assert_no_on()
            self.assertTrue(f.restore()['synchronized']);self.assertEqual(Image.open(BytesIO(f.panel.visible)).convert('RGB').tobytes(),Image.open(BytesIO(restore.HOME)).convert('RGB').tobytes())
        finally:f.doCleanups()

    def test_missing_weather_preserves_unknown_facts_and_clock_opt_in(self):
        for clock in (False,True):
            payload={'display_at':'2026-10-25T12:00:00+01:00','dashboard_show_clock':clock,'forecast':{'next_hour_temperature_c':99}}
            r=build_weather_unavailable(payload)
            self.assertLess(len(r.gif()),196608);self.assertEqual(len(r.frames),1)
            self.assertTrue(any(r.frames[0]))
            self.assertEqual(r.frames,build_weather_unavailable(payload).frames)
