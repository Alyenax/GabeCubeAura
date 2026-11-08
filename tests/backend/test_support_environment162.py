"""Passive evidence is bounded, attributable and excludes raw process/log data."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from signalbar import support_environment as env
from signalbar.diagnostics import DiagnosticJournal
from signalbar.support_snapshot import runtime
import test_screensaver_restore148 as fixture
import test_support_snapshot161 as snapshot_tests


class CoherentExportTests(unittest.IsolatedAsyncioTestCase):
    setUp = snapshot_tests.ExportTests.setUp
    async def test_one_capture_replaces_stale_runtime_with_same_live_snapshot(self):
        from signalbar.settings.store import DEFAULTS
        state=dict(available=True,captured_at_unix_s=1234,powered=False,
                   restoration={'failed':True,'held_dark':True},
                   last_transfer={'begin_attempted':True,'begin_status':0,'chunks':0})
        self.p.engine=SimpleNamespace(settings=SimpleNamespace(all=lambda:dict(DEFAULTS)),
            faceplate=SimpleNamespace(passive_diagnostic_snapshot=lambda:state),
            display_control_snapshot=lambda:{})
        self.p.diagnostics.state_dir.mkdir(parents=True,exist_ok=True)
        self.p.diagnostics.faceplate_runtime_path.write_text(json.dumps({'device':{'restoration':{'failed':False}}}))
        with patch('signalbar.support_environment.capture',return_value={'available':False,'reason':'test'}) as collect:
            result=await self.p.export_support_diagnostic('1.6.1-beta.2')
        document=json.loads(result['text']);live=document['support']['runtime']
        self.assertEqual(document['faceplate_runtime']['device']['restoration'],live['restoration'])
        self.assertTrue(live['restoration']['failed'])
        self.assertEqual(document['faceplate_runtime']['device']['snapshot'],live['snapshot'])
        collect.assert_called_once();self.assertEqual(Path(result['path']).read_text(),result['text'])


class EvidenceTests(unittest.TestCase):
    def test_process_owner_is_identified_without_leaking_arguments_or_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for pid,command,owns in [(10,'/usr/bin/jsaux-pixel\0--password=PRIVATE',True),
                                     (11,'python\0/home/PRIVATE/plugins/GabeCubeAura/main.py',False),
                                     (12,'python\0/home/PRIVATE/plugins/Pixel-Faceplate/main.py',True)]:
                d=root/str(pid);(d/'fd').mkdir(parents=True);(d/'cmdline').write_text(command)
                if owns:(d/'fd/4').symlink_to('/dev/ttyUSB0')
            result=env.processes('/dev/ttyUSB0',proc_root=root,budget=2)
            self.assertTrue(result['complete'])
            self.assertEqual([p['category'] for p in result['port_holders']],['jsaux','pixel-faceplate'])
            self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('/home/',json.dumps(result))
            self.assertEqual(result['candidates'][1]['category'],'gabecubeaura')

    def test_partial_process_scan_never_claims_no_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'1').mkdir()
            result=env.processes('/dev/ttyUSB0',proc_root=tmp,budget=0)
            self.assertFalse(result['complete']);self.assertEqual(result['reason'],'time-budget')

    def test_usb_reports_declared_power_not_measured_current_or_panel_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);device=root/'devices/usb1/1-3';node=device/'1-3:1.0/ttyUSB0'
            node.mkdir(parents=True);(root/'class/tty/ttyUSB0').mkdir(parents=True)
            (root/'class/tty/ttyUSB0/device').symlink_to(node)
            driver=root/'drivers/ch341';driver.mkdir(parents=True);(node/'driver').symlink_to(driver)
            for name,value in {'idVendor':'1a86','idProduct':'7523','bcdDevice':'0264',
                               'bMaxPower':'500mA','speed':'12','power/control':'auto',
                               'power/runtime_status':'active','power/autosuspend_delay_ms':'2000'}.items():
                p=device/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            result=env.usb('/dev/ttyUSB0',sys_root=root)
            self.assertTrue(result['available']);self.assertEqual(result['serial_driver'],'ch341')
            self.assertEqual(result['declared_max_power_ma'],500)
            self.assertFalse(result['declared_power_is_measurement'])
            self.assertEqual(result['current'],'not-measured');self.assertEqual(result['panel_upload_limit'],'not-measured')
            self.assertEqual(result['bridge_revision'],'0264');self.assertNotIn(tmp,json.dumps(result))

    def test_kernel_log_is_classified_not_exported_and_not_assigned_to_wrong_device(self):
        raw='\n'.join(json.dumps(dict(MESSAGE=m,__REALTIME_TIMESTAMP='1794160000000000')) for m in
            ('usb 1-3: over-current PRIVATE SERIAL', 'ch341 ttyUSB0: usb disconnected PRIVATE',
             'unrelated PRIVATE message'))
        with patch.object(env,'_command',return_value=(raw,'')):
            result=env.kernel_events('/dev/ttyUSB0')
        self.assertEqual([r['kind'] for r in result['events']],['over-current','usb-disconnect'])
        self.assertEqual(result['events'][0]['association'],'host-event-not-attributed')
        self.assertEqual(result['events'][1]['association'],'same-tty')
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('SERIAL',json.dumps(result))

    def test_service_queries_only_list_and_unknown_access_remains_unknown(self):
        calls=[]
        def command(args,timeout,extra_env=None):
            calls.append(args)
            return ('jsaux-private.service loaded active running PRIVATE\n', '') if '--system' in args else (None,'unavailable-or-denied')
        with patch.object(env,'_command',side_effect=command):result=env.services()
        self.assertEqual(result['scopes'][0]['matches'][0]['category'],'jsaux')
        self.assertTrue(all('list-units' in args for args in calls))
        self.assertFalse(result['scopes'][1]['available']);self.assertNotIn('PRIVATE',json.dumps(result))

    def test_failure_observer_is_rate_limited_and_never_opens_a_usb_device(self):
        with env._lock:env._history.clear();env._last_failure=0
        with patch.object(env,'processes',return_value={'complete':True}) as proc, patch.object(env,'usb',return_value={}), patch.object(env.time,'monotonic',return_value=100):
            env.observe_failure('/dev/ttyUSB0',{'begin_status':0,'expected_bytes':76006,'secret':'PRIVATE'})
            env.observe_failure('/dev/ttyUSB0',{'begin_status':0})
        proc.assert_called_once();self.assertEqual(len(env._history),1)
        self.assertNotIn('PRIVATE',json.dumps(list(env._history)))

    def test_diagnostic_failure_cannot_replace_transfer_failure(self):
        with env._lock:env._last_failure=0
        with patch.object(env,'processes',side_effect=RuntimeError('PRIVATE')):
            env.observe_failure('/dev/ttyUSB0',{'begin_status':0})

    def test_size_evidence_does_not_equate_stored_reuse_with_new_write_or_capacity(self):
        panel=SimpleNamespace(state={'observability':{'journal':[
            {'outcome':'written','size_bytes':646}, {'outcome':'identical','size_bytes':4636},
            {'outcome':'failed','begin_status':0,'size_bytes':60081},
            {'outcome':'failed','begin_status':1,'failure_stage':'end','size_bytes':1000}]}})
        result=env.size_evidence(panel)
        self.assertEqual(result['newly_acked_bytes'],[646]);self.assertEqual(result['reused_bytes'],[4636])
        self.assertEqual(result['begin_refused_bytes'],[60081]);self.assertEqual(result['capacity'],'not-inferred')

    def test_missing_runtime_data_is_unknown_not_a_false_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=DiagnosticJournal(Path(tmp)/'state','1.6.1-beta.2');j.state_dir.mkdir()
            j.faceplate_runtime_path.write_text(json.dumps({'device':{'phase':'error'}}))
            result=j._faceplate_runtime_snapshot()['device']
            self.assertIsNone(result['restoration']['failed']);self.assertIsNone(result['last_transfer']['begin_attempted'])

    def test_kernel_and_controlled_field_names_survive_but_credentials_do_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=DiagnosticJournal(tmp,'1.6.1-beta.2')
            value={'kernel':'7.2.0-valve20-1-neptune-793e23ff9a65',
                   'performance_activations_session':2,'api_key':'ghu_'+'x'*40,
                   'message':'Bearer '+'x'*40,'private_path':'/home/PRIVATE/secret'}
            result=j._sanitize(value)
            self.assertEqual(result['kernel'],value['kernel']);self.assertEqual(result['performance_activations_session'],2)
            text=json.dumps(result);self.assertNotIn('x'*40,text);self.assertNotIn('PRIVATE',text)

    def test_passive_coordinator_snapshot_does_not_wait_or_touch_serial(self):
        f=fixture.Restore148Tests();f.setUp();self.addCleanup(f.doCleanups)
        f.exit();f.panel.refuse_begin=True;f.restore()
        engine=SimpleNamespace(faceplate=f.coordinator,settings=SimpleNamespace(all=lambda:{}))
        before=list(f.panel.events);result=runtime(engine)
        self.assertTrue(result['snapshot']['available']);self.assertTrue(result['restoration']['failed'])
        self.assertEqual(result['last_transfer']['begin_status'],0)
        self.assertEqual(before,f.panel.events)
        with f.coordinator.lock:
            busy=runtime(engine)
        self.assertFalse(busy['snapshot']['available']);self.assertIsNone(busy['power_intent']['last_confirmed_power'])

    def test_storage_inspection_never_follows_link_to_private_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'link').symlink_to('/unavailable/PRIVATE')
            result=env.storage(SimpleNamespace(settings=SimpleNamespace(path=root/'link')))
            self.assertEqual(result[0]['kind'],'symlink');self.assertNotIn('free_bytes',result[0])
            self.assertNotIn('PRIVATE',json.dumps(result))


if __name__ == '__main__':unittest.main()
