import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from signalbar.safe_export import write_private_bytes
from signalbar.screen_sync_trace import ScreenSyncTrace
from signalbar.backend import Engine
from signalbar.settings import SettingsStore

ROOT=Path(__file__).resolve().parents[2]

class CandidateSafety(unittest.TestCase):
    def test_private_export_rejects_destination_and_parent_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();secret=root/'keep';secret.write_text('original')
            (root/'report').symlink_to(secret)
            with self.assertRaises(ValueError):write_private_bytes(root/'report',b'bad')
            (root/'linked').symlink_to(root, target_is_directory=True)
            with self.assertRaises((OSError,ValueError)):write_private_bytes(root/'linked/report2',b'bad')
            self.assertEqual(secret.read_text(),'original')

    def test_export_creates_private_documents_and_private_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();target=root/'Documents/report.json'
            observed=[];real_replace=os.replace
            def replace(source,target,**kwargs):
                info=os.stat(source,dir_fd=kwargs['src_dir_fd']);observed.append(info.st_mode&0o777)
                return real_replace(source,target,**kwargs)
            with patch('signalbar.safe_export.os.replace',side_effect=replace):write_private_bytes(target,b'{"safe":true}')
            self.assertEqual(observed,[0o600]);self.assertEqual(target.stat().st_mode&0o777,0o600)
            self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            self.assertEqual(list(target.parent.glob('.*.tmp')),[])

    def test_root_export_assigns_home_user_before_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();target=root/'Documents/report.json'
            with patch('signalbar.safe_export.os.geteuid',return_value=0),patch('signalbar.safe_export.os.fchown') as chown,patch.dict(os.environ,{'DECKY_USER_HOME':str(root)}):
                write_private_bytes(target,b'ok')
            self.assertTrue(chown.called)
            self.assertTrue(all(call.args[1:]==(root.stat().st_uid,root.stat().st_gid) for call in chown.call_args_list))

    def test_old_command_is_archived_without_changing_brightness_or_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();store=SettingsStore(str(root/'config.json'));store.update({'faceplate_brightness':71})
            engine=Engine(store,str(root/'cache.json'),faceplate_runtime_path=root/'faceplate-runtime.json')
            try:
                command=root/'faceplate-control.json';command.write_text('{"id":"old","brightness":5,"powered":true}')
                engine.faceplate_worker.submit=Mock()
                self.assertEqual(engine._consume_faceplate_control(),0)
                self.assertFalse(command.exists());self.assertEqual(store.all()['faceplate_brightness'],71)
                engine.faceplate_worker.submit.assert_not_called()
                self.assertEqual(len(list(root.glob('faceplate-control.retired-*.json'))),1)
            finally:engine.stop()

    def test_capture_detail_expires_and_does_not_reenable_itself(self):
        clock=[0];trace=ScreenSyncTrace(clock=lambda:clock[0])
        self.assertFalse(trace.detailed());trace.enable_detail(999)
        clock[0]=299;self.assertTrue(trace.detailed());clock[0]=301;self.assertFalse(trace.detailed())
        trace.enable_detail(0);self.assertFalse(trace.detailed())

    def test_candidate_identity_and_runtime_allowlist_have_no_voice_or_private_delivery(self):
        from signalbar import __version__
        from signalbar.distribution import supports_private_tools
        self.assertEqual(__version__,json.loads((ROOT/'package.json').read_text())['version']);self.assertFalse(supports_private_tools(__version__))
        entries=json.loads((ROOT/'scripts/runtime-files.json').read_text())
        self.assertFalse(any('/assistant/' in p or '/studio/' in p or '/cinema/' in p for p in entries))
        self.assertFalse(any('RELEASE_NOTES_' in p for p in entries))
        settings=SettingsStore(str(Path(tempfile.mkdtemp()).resolve()/'config.json'))
        self.assertTrue(settings.all()['updates_auto_check']);self.assertFalse(settings.all()['updates_auto_install'])
        policy=json.loads((ROOT/'licenses/faceplate-scope.json').read_text())
        self.assertEqual(policy['publish_clearance'],'CLEARED')

class LargerUpdates(unittest.TestCase):
    def test_new_limits_and_large_manifest_use_the_real_stager(self):
        import hashlib
        from zipfile import ZipFile, ZIP_DEFLATED
        from signalbar import archive_policy
        from signalbar.updates import validate_and_stage_archive, read_bundle_contract
        from test_updates import write_plugin
        self.assertEqual(archive_policy.MAX_ARCHIVE_BYTES,1024**3)
        self.assertEqual(archive_policy.MAX_UNCOMPRESSED_BYTES,4*1024**3)
        self.assertEqual(archive_policy.MAX_ARCHIVE_ENTRIES,32768)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();plugin=root/'source/GabeCubeAura';write_plugin(plugin,'1.4.2')
            rows=[]
            for p in plugin.rglob('*'):
                if p.is_file():rows.append({'path':str(p.relative_to(plugin)),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
            payload=b'future-resource';digest=hashlib.sha256(payload).hexdigest()
            extras=[{'path':f'assets/future/{n:05d}.dat','size':len(payload),'sha256':digest} for n in range(6000)]
            manifest={'schema':1,'product':'GabeCubeAura','version':'1.4.2','components':[{'id':'plugin','version':'1.4.2','required':True,'executables':[],'files':rows+extras}]}
            data=json.dumps(manifest).encode();self.assertGreater(len(data),512*1024)
            archive=root/'future.zip'
            with ZipFile(archive,'w',ZIP_DEFLATED) as z:
                for p in plugin.rglob('*'):
                    if p.is_file():z.write(p,'GabeCubeAura/'+str(p.relative_to(plugin)))
                for row in extras:z.writestr('GabeCubeAura/'+row['path'],payload)
                z.writestr('GabeCubeAura/update-manifest.json',data)
            staged=validate_and_stage_archive(archive,root/'stage','1.4.2')
            contract=read_bundle_contract(staged,'1.4.2')
            self.assertEqual(len(contract['components'][0]['files']),len(rows)+6000)
