"""Conservative/fixed-minute clock modes and their saved runtime contracts."""
from datetime import datetime
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import Mock
from signalbar.faceplate.clocks import ClockRuntime,build_packet,clock_period
from signalbar.faceplate.clock_standard import DESIGNS,render_frame
from signalbar.settings import SettingsStore
import test_native_clock as fixture


class CadenceTests(unittest.TestCase):
    def test_both_modes_keep_absolute_deadlines_and_do_not_catch_up_in_bursts(self):
        for mode,period,rate in [('conservative',240,15),('minute',60,60)]:
            runtime=ClockRuntime();now=1000
            request=runtime.plan('horizon','home',now,False,monotonic=now,cadence=mode)
            self.assertEqual(period,clock_period(mode))
            self.assertLessEqual(request['end_at']-request['display_at'],period+10)
            for _ in range(120):
                self.assertEqual(mode,request['cadence'])
                self.assertEqual(0,request['renew_at']%period)
                runtime.receipt(request,{'synchronized':True,'upload_ms':1000,'clock_bytes':1000},request['display_at'])
                target=runtime.active['renew_at']
                self.assertIsNone(runtime.plan('horizon','home',target-10,False,monotonic=target-10,cadence=mode))
                request=runtime.plan('horizon','home',target-9,False,monotonic=target-9,cadence=mode)
                self.assertEqual(target,request['display_at'])
            status=runtime.snapshot('horizon','home',request['display_at'])
            self.assertEqual(rate,status['nominal_transfers_per_hour'])
            self.assertEqual(period,status['packet_seconds'])
            runtime.receipt(request,{'synchronized':True},request['display_at'])
            late=request['end_at']+100
            one=runtime.plan('horizon','home',late,False,monotonic=late,cadence=mode)
            self.assertGreater(one['display_at'],late)
            self.assertIsNone(runtime.plan('horizon','home',late,False,monotonic=late,cadence=mode))

    def test_fixed_minute_holds_time_date_and_am_pm_through_midnight_guard(self):
        start=datetime(2026,10,27,23,59,47,250000).timestamp();end=start+22.75
        for design in DESIGNS:
            request=dict(clock_id=design,display_at=start,end_at=end,cadence='minute',options={'format':'12','language':'fr'})
            packet=build_packet(request)
            self.assertEqual(1,len(packet.frames))
            self.assertEqual(render_frame(design,datetime.fromtimestamp(start),request['options']),packet.frames[0])
            self.assertEqual((2275,),packet.delays_cs)
            self.assertNotEqual(render_frame(design,datetime.fromtimestamp(end),request['options']),packet.frames[0])
            self.assertNotIn(b'NETSCAPE2.0',packet.gif())

    def test_conservative_retains_minute_changes_and_bad_modes_are_rejected(self):
        request=dict(clock_id='horizon',display_at=1000,end_at=1250,cadence='conservative')
        self.assertGreater(len(build_packet(request).frames),1)
        for bad in ('fast','',True,None):
            with self.assertRaises(ValueError):clock_period(bad)
            with self.assertRaises(ValueError):build_packet({**request,'cadence':bad})

    def test_settings_default_persist_independently_reject_and_repair_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json';store=SettingsStore(str(path))
            for context in ('home','game'):self.assertEqual('minute',store.all()['faceplate_clock_cadence_'+context])
            store.update({'faceplate_clock_cadence_home':'conservative'})
            loaded=SettingsStore(str(path)).all()
            self.assertEqual('conservative',loaded['faceplate_clock_cadence_home'])
            self.assertEqual('minute',loaded['faceplate_clock_cadence_game'])
            with self.assertRaises(ValueError):store.update({'faceplate_clock_cadence_home':'bad'})
            value=json.loads(path.read_text());value['faceplate_clock_cadence_home']='bad';path.write_text(json.dumps(value))
            self.assertEqual('minute',SettingsStore(str(path)).all()['faceplate_clock_cadence_home'])

    def test_older_settings_gain_missing_defaults_without_overwriting_saved_cadence(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            path.write_text(json.dumps({'faceplate_clock_cadence_home':'conservative','ui_language':'fr'}))
            store=SettingsStore(str(path));values=store.all()
            self.assertEqual('conservative',values['faceplate_clock_cadence_home'])
            self.assertEqual('minute',values['faceplate_clock_cadence_game'])
            self.assertEqual('fr',values['ui_language'])
            store.update({'faceplate_clock_cadence_game':'conservative'})
            restored=SettingsStore(str(path)).all()
            self.assertEqual('conservative',restored['faceplate_clock_cadence_home'])
            self.assertEqual('conservative',restored['faceplate_clock_cadence_game'])

    def test_inactive_mode_edit_keeps_current_job_and_active_edit_refreshes_only_clock(self):
        f=fixture.NativeSceneTests('test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight')
        f.setUp();self.addCleanup(f.doCleanups)
        f.settings.update({'faceplate_clock_home':'horizon'});f.prefs.update(home_scene='clock')
        engine=f.engine;engine._reconcile_faceplate=Mock()
        pending=engine.clock_runtime.plan('horizon','home',1000,False,monotonic=1000)
        engine.update_settings({'faceplate_clock_cadence_game':'conservative'})
        self.assertEqual(pending,engine.clock_runtime.pending);engine._reconcile_faceplate.assert_not_called()
        engine.update_settings({'faceplate_clock_cadence_home':'conservative'})
        engine._reconcile_faceplate.assert_called_once_with('clock-cadence-change',force=True)
        engine.faceplate_worker.cancel_scene_class.assert_called_with('clock')


if __name__=='__main__':unittest.main()
