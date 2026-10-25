import json
import os
import signal
import select
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from signalbar.arbiter.guard import ManualClock
from signalbar.backend import Engine
from signalbar.providers.screen_sync import ScreenCaptureService, FRAME_BYTES
from signalbar.screen_sync_trace import ScreenSyncTrace, MAX_TRACE_FILE_BYTES, MAX_TRACE_REPORT_BYTES
from signalbar.settings import SettingsStore
from test_lab101_runtime_ack import FakeHardware
import test_screen_sync_evidence208 as evidence


class TraceWriterTests(unittest.TestCase):
    def test_preview_survives_expiration_later_activity_and_backend_restart_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = ManualClock(100)
            trace = ScreenSyncTrace(folder, clock=clock)
            trace.begin_preview(15, enabled=True)
            trace.record("gstreamer-stage", stage="waiting-streaming",
                message="/home/alice/private token=secretvalue Bearer abcdefghijklm12345")
            clock.advance(16)
            trace.end_preview()
            trace.record("capture-stopped", exit_code_after_stop=-15)
            clock.advance(20)
            for number in range(600):
                trace.record("later-game-capture", number=number)
            snapshot = trace.snapshot()
            events = [row['event'] for row in snapshot['records']]
            self.assertIn('preview-request', events)
            self.assertIn('preview-end', events)
            self.assertIn('capture-stopped', events)
            self.assertNotIn('later-game-capture', events)
            self.assertLessEqual(len(json.dumps(snapshot).encode()), MAX_TRACE_REPORT_BYTES)
            trace.close(3)
            saved = Path(folder) / 'screen-sync-preview.json'
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            raw = saved.read_text()
            self.assertNotIn('secretvalue', raw)
            self.assertNotIn('/home/alice', raw)
            restored = ScreenSyncTrace(folder).snapshot()
            self.assertEqual(restored['scope'], 'previous-backend-preview')
            self.assertIn('capture-stopped', [r['event'] for r in restored['records']])
            restarted = ScreenSyncTrace(folder)
            restarted.record('capture-routing', requested=False)
            self.assertEqual(restarted.snapshot()['previous_preview']['scope'], 'previous-backend-preview')
            restarted.close(3)

    def test_graceful_stop_targets_only_marked_gstreamer_descendant_of_runuser(self):
        from signalbar.providers.screen_sync import CAPTURE_PROCESS_MARKER
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            children=root/'400/task/400';children.mkdir(parents=True);(children/'children').write_text('501 502 503')
            for pid,args in ((501,['/usr/bin/gst-launch-1.0',CAPTURE_PROCESS_MARKER]),
                             (502,['/usr/bin/gst-launch-1.0','client-name=Other-App']),
                             (503,['/usr/bin/pw-record','--target=audio'])):
                path=root/str(pid);path.mkdir();(path/'cmdline').write_bytes(b'\0'.join(a.encode() for a in args)+b'\0')
            process=SimpleNamespace(pid=400,args=['/usr/bin/runuser','-u','deck','--','gst-launch-1.0',CAPTURE_PROCESS_MARKER],
                poll=lambda:None,wait=Mock(return_value=0))
            targets=ScreenCaptureService._graceful_capture_pids(process,root)
            self.assertEqual(targets,[501])
            with patch.object(ScreenCaptureService,'_graceful_capture_pids',return_value=targets), \
                    patch('signalbar.providers.screen_sync.os.kill') as send, \
                    patch('signalbar.providers.screen_sync.os.killpg') as group:
                self.assertEqual(ScreenCaptureService._terminate_process(process),'sigint')
            send.assert_called_once_with(501,signal.SIGINT)
            group.assert_not_called()

    def test_hung_graceful_stop_escalates_within_original_budget(self):
        process=SimpleNamespace(pid=400,args=['/usr/bin/gst-launch-1.0'],poll=lambda:None,
            wait=Mock(side_effect=[subprocess.TimeoutExpired('gst',.6),subprocess.TimeoutExpired('gst',.6),0]))
        with patch('signalbar.providers.screen_sync.os.kill') as send, \
                patch('signalbar.providers.screen_sync.os.killpg') as group:
            self.assertEqual(ScreenCaptureService._terminate_process(process),'sigkill')
        send.assert_called_once_with(400,signal.SIGINT)
        self.assertEqual([call.args[1] for call in group.call_args_list],[signal.SIGTERM,signal.SIGKILL])
        self.assertEqual(process.wait.call_count,3)

    def test_parallel_stop_sends_one_interrupt_and_drains_shutdown_log_burst(self):
        with tempfile.TemporaryDirectory() as folder:
            counter=Path(folder)/'interrupts.txt'
            code=('import os,signal,time\n'
                'def stop(signum,frame):\n'
                f' with open({str(counter)!r},"a") as f: f.write("INT\\n")\n'
                ' for i in range(2400): os.write(2,b"DEBUG pipewiresrc shutdown metadata burst\\n")\n'
                ' os.write(2,b"GST_STATES <pipeline0> completed state change to NULL\\n")\n'
                ' time.sleep(.1)\n'
                ' raise SystemExit(0)\n'
                'signal.signal(signal.SIGINT,stop)\n'
                'os.write(1,b"ready\\n")\n'
                'while True: time.sleep(.1)\n')
            child=subprocess.Popen([sys.executable,'-u','-c',code],stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,start_new_session=True)
            capture=ScreenCaptureService()
            barrier=threading.Barrier(3);strategies=[]
            def stop():
                barrier.wait();strategies.append(capture._stop_capture_process(child))
            threads=[threading.Thread(target=stop) for _ in range(2)]
            try:
                self.assertTrue(select.select([child.stdout],[],[],2)[0])
                self.assertEqual(child.stdout.readline(),b'ready\n')
                with patch.object(ScreenCaptureService,'_graceful_capture_pids',return_value=[child.pid]):
                    for thread in threads:thread.start()
                    barrier.wait()
                    for thread in threads:thread.join(3)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(sorted(strategies),['already-exited','sigint'])
                self.assertEqual(counter.read_text(),'INT\n')
                self.assertEqual(child.returncode,0)
                self.assertIn('pipeline-null',capture._trace_stages)
            finally:
                if child.poll() is None:child.kill()
                child.wait(timeout=2)
                for thread in threads:
                    if thread.ident is not None:thread.join(2)
                child.stdout.close();child.stderr.close()

    def test_log_rotation_is_bounded_and_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = ScreenSyncTrace(folder)
            for number in range(450):
                trace._append([{'seq': number, 'message': 'x' * 700}])
            for path in Path(folder).glob('*.jsonl'):
                self.assertLessEqual(path.stat().st_size, MAX_TRACE_FILE_BYTES)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue((Path(folder) / 'screen-sync-trace.previous.jsonl').exists())
            target = Path(folder) / 'unrelated.txt'; target.write_text('untouched')
            log = Path(folder) / 'screen-sync-trace.jsonl'; log.unlink(); log.symlink_to(target)
            with self.assertRaises(OSError):
                trace._append([{'event': 'must-not-follow'}])
            self.assertEqual(target.read_text(), 'untouched')

    def test_blocked_writer_cannot_block_capture_producer_and_reports_drops(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = ScreenSyncTrace(folder)
            entered, release, done = threading.Event(), threading.Event(), threading.Event()
            def blocked(_rows):
                entered.set(); release.wait(3)
            def produce():
                for number in range(1000):
                    trace.record('capture-progress', number=number)
                done.set()
            with patch.object(trace, '_append', side_effect=blocked):
                trace.record('first')
                self.assertTrue(entered.wait(1))
                producer = threading.Thread(target=produce); producer.start()
                try:
                    self.assertTrue(done.wait(1), 'capture producer waited for disk I/O')
                    self.assertGreater(trace.snapshot()['dropped_records'], 0)
                finally:
                    release.set(); producer.join(3); trace.close(3)

    def test_split_stderr_lines_retain_negotiation_and_stream_state(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, 'rb', buffering=0) as stderr:
            process = SimpleNamespace(stderr=stderr, poll=lambda: None)
            capture = ScreenCaptureService()
            try:
                os.write(write_fd, b'DEBUG pipewiresrc got stream st')
                capture._read_stderr(process)
                self.assertEqual(capture.status()['stderr_tail'], [])
                os.write(write_fd, b'ate paused\nINFO pipewiresrc set format video/x-raw,format=BGRx,framerate=0/1\n')
                capture._read_stderr(process)
                stages = [r['fields'].get('stage') for r in capture.trace.snapshot()['records']]
                self.assertIn('pipewire-state-paused', stages)
                self.assertIn('negotiated-format', stages)
                self.assertIn('framerate=0/1', json.dumps(capture.trace.snapshot()))
            finally:
                os.close(write_fd)

    def test_graph_names_linked_and_targeted_video_clients_but_excludes_microphone(self):
        rows = [
            {'id':54,'type':'PipeWire:Interface:Node','info':{'state':'running','props':{'object.serial':1000}}},
            {'id':11,'type':'PipeWire:Interface:Client','info':{'props':{
                'application.name':'OBS Studio','application.process.binary':'/usr/bin/obs'}}},
            {'id':60,'type':'PipeWire:Interface:Node','info':{'props':{'client.id':11,'media.class':'Stream/Input/Video'}}},
            {'id':61,'type':'PipeWire:Interface:Node','info':{'props':{'target.object':'1000',
                'application.name':'pending-video','media.class':'Stream/Input/Video'}}},
            {'id':62,'type':'PipeWire:Interface:Node','info':{'props':{'target.object':'gamescope',
                'application.name':'Voice microphone','media.class':'Stream/Input/Audio'}}},
            {'type':'PipeWire:Interface:Link','info':{'output-node-id':54,'input-node-id':60,'state':'active'}},
        ]
        consumers = ScreenCaptureService.capture_clients(rows, 54)
        self.assertEqual(len(consumers), 2)
        self.assertEqual(consumers[0]['application'], 'OBS Studio')
        self.assertEqual(consumers[0]['binary'], 'obs')
        self.assertTrue(consumers[0]['linked'])
        self.assertFalse(consumers[1]['linked'])
        self.assertTrue(consumers[1]['targeted'])
        capture = ScreenCaptureService()
        capture._trace_pipewire(rows, 54); capture._trace_pipewire(rows, 54)
        capture._trace_pipewire([], 54)
        snapshots = [r['fields'] for r in capture.trace.snapshot()['records']]
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(snapshots[0]['producer_present'])
        self.assertFalse(snapshots[1]['producer_present'])

    def test_failed_selector_cycle_stops_reconnecting_until_explicit_retry(self):
        processes, commands = [], []
        def popen(command, **_kwargs):
            commands.append(command)
            child = SimpleNamespace(stdout=tempfile.TemporaryFile(), stderr=tempfile.TemporaryFile(), poll=lambda:1)
            processes.append(child)
            return child
        service = ScreenCaptureService(popen=popen); service._active = True
        waits = [0]
        def wait(_seconds):
            waits[0] += 1
            if waits[0] == 8:
                service._stop.set()
        try:
            with evidence.CaptureEvidenceTests().capture_context(service), patch.object(service, '_wait', side_effect=wait):
                service._supervise()
            self.assertEqual(len(commands), 3)
            self.assertTrue(service.status()['retry_paused'])
            self.assertEqual(service.status()['capture_sessions_released'], 3)
            service.request_retry()
            self.assertFalse(service.status()['retry_paused'])
            service._stop.clear(); waits[0] = 0
            with evidence.CaptureEvidenceTests().capture_context(service), patch.object(service, '_wait', side_effect=wait):
                service._supervise()
            self.assertEqual(len(commands), 6)
        finally:
            for child in processes:
                child.stdout.close(); child.stderr.close()

    def test_real_engine_preview_traces_activation_capture_display_and_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = SettingsStore(str(root / 'settings.json'))
            settings.update({'signalbar_enabled':True,'home_display':'customization',
                             'valve_ownership_policy':'critical','faceplate_lab_enabled':False})
            trace = ScreenSyncTrace(root / 'logs')
            engine = Engine(settings, str(root / 'cache'), hardware_factory=FakeHardware, screen_sync_trace=trace)
            engine._reconcile_faceplate = Mock(return_value=0)
            engine._write_faceplate_runtime_status = Mock()
            engine.faceplate_worker = Mock(); engine.faceplate_worker.status.return_value = {}
            capture = engine.screen_sync.capture
            command = [sys.executable, '-u', '-c', 'import os,time\n'
                       'for i in range(1800): os.write(2,b"DEBUG pipewiresrc bounded metadata burst during startup\\n")\n'
                       'os.write(2,b"DEBUG pipewiresrc got stream state streaming\\n")\n'
                       f'for i in range(100):\n os.write(1,bytes([120])*{FRAME_BYTES}); time.sleep(.1)\n']
            try:
                with evidence.CaptureEvidenceTests().capture_context(capture), \
                        patch.object(capture, '_capture_command', return_value=command):
                    engine.start()
                    self.assertTrue(engine.preview_screen_sync(3))
                    deadline = time.monotonic() + 7
                    recording_started = False
                    while time.monotonic() < deadline:
                        current = trace.snapshot()['records']
                        events = [r['event'] for r in current]
                        if not recording_started and any(r['event']=='capture-display-decision'
                                and r['fields']['provider']=='screen-sync' for r in current):
                            engine.trigger_event('record-start')
                            recording_started = True
                        if 'preview-end' in events and 'capture-stopped' in events:
                            break
                        time.sleep(.02)
                    records = trace.snapshot()['records']; events = [r['event'] for r in records]
                    for event in ('preview-request','capture-routing','capture-launch','capture-first-bytes',
                                  'capture-first-frame','capture-display-decision','preview-end','capture-stopped'):
                        self.assertIn(event, events)
                    decisions = [r['fields'] for r in records if r['event']=='capture-display-decision']
                    self.assertTrue(any(r['provider']=='screen-sync' and not r['fallback'] for r in decisions), decisions)
                    self.assertTrue(any(r['event']=='capture-routing' and r['fields']['recording']
                        and not r['fields']['capture_active'] for r in records))
                    self.assertGreater(trace.snapshot()['dropped_records'],0)
            finally:
                engine.stop()

    def test_repeated_one_frame_then_stalled_sessions_also_pause(self):
        clock=ManualClock(100)
        children=[]
        def popen(*_args,**_kwargs):
            child=SimpleNamespace(stdout=tempfile.TemporaryFile(),stderr=tempfile.TemporaryFile(),poll=lambda:None)
            child.stdout.write(bytes(FRAME_BYTES));child.stdout.seek(0)
            children.append(child)
            return child
        capture=ScreenCaptureService(clock=clock,popen=popen);capture._active=True
        waits=[0]
        def select_frame(*_args):
            clock.advance(.4)
            return [children[-1].stdout.fileno()],[],[]
        def wait(_seconds):
            waits[0]+=1
            if waits[0]>=7:capture._stop.set()
        try:
            with evidence.CaptureEvidenceTests().capture_context(capture), \
                    patch('signalbar.providers.screen_sync.select.select',side_effect=select_frame), \
                    patch.object(capture,'_terminate_process'),patch.object(capture,'_wait',side_effect=wait):
                capture._supervise()
            self.assertEqual(len(children),3)
            self.assertTrue(capture.status()['retry_paused'])
            self.assertEqual(capture.status()['unhealthy_sessions'],3)
            self.assertTrue(all(row['frames_received']==1 for row in capture.status()['recent_failures']))
        finally:
            for child in children:child.stdout.close();child.stderr.close()


if __name__ == '__main__':
    unittest.main()
