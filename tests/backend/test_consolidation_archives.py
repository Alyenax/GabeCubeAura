"""Install/restore real >32 MiB ZIPs without services, USB or a network."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

from signalbar import updates
from signalbar.archive_policy import MAX_ARCHIVE_BYTES, MAX_UNCOMPRESSED_BYTES
from signalbar.recovery import RecoveryVault
from signalbar.update_helper import run_transaction
from test_updates import (write_archive, write_plugin, FakeResponse, FakeService,
                          fake_exchange)
import test_updates as update_fixtures


class GeneratedResponse:
    def __init__(self, size, length=None, interrupt=False):
        self.remaining = size
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self.closed = False
        self.interrupt = interrupt

    def __enter__(self): return self
    def __exit__(self, *_): self.closed = True
    def read(self, size):
        if self.interrupt:
            self.interrupt = False
            raise OSError("interrupted")
        count = min(size, self.remaining)
        self.remaining -= count
        return b"x" * count


class ArchiveConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def download(self, response, size, **kwargs):
        client = updates.GitHubReleaseClient(opener=lambda *args, **kw: response)
        release = {"archive_url": "https://github.com/Alyenax/GabeCubeAura/releases/download/v1.1.0/a.zip",
                   "archive_size": size}
        return client.download_archive(release, self.root / "archive.zip", "1.0.0", **kwargs)

    def test_actual_byte_count_not_content_length(self):
        for length in (None, 1, 1000):
            response = GeneratedResponse(100, length)
            self.assertEqual(self.download(response, 100), hashlib.sha256(b"x"*100).hexdigest())
            self.assertTrue(response.closed)
        with self.assertRaises(updates.UpdateError): self.download(GeneratedResponse(99), 100)
        self.assertFalse((self.root / "archive.zip.part").exists())

    def test_exact_1gib_and_overflow_in_bounded_chunks(self):
        self.assertEqual(MAX_ARCHIVE_BYTES, 1073741824)
        self.assertEqual(MAX_UNCOMPRESSED_BYTES, 4294967296)
        # Simulated sink, real bounded read/hash loop; no 128-MiB allocation.
        with patch.object(Path, "open") as opened, patch("signalbar.updates.os.fsync"), patch("signalbar.updates.os.replace"):
            class CountingSink:
                total = 0
                largest = 0
                def write(self, chunk): self.total += len(chunk); self.largest = max(self.largest,len(chunk))
                def flush(self): pass
                def fileno(self): return 0
            sink = CountingSink()
            opened.return_value.__enter__.return_value = sink
            self.download(GeneratedResponse(MAX_ARCHIVE_BYTES), MAX_ARCHIVE_BYTES)
            self.assertEqual(sink.total, MAX_ARCHIVE_BYTES)
            self.assertLessEqual(sink.largest, 65536)
            with self.assertRaises(updates.UpdateError):
                self.download(GeneratedResponse(MAX_ARCHIVE_BYTES+1, 1), MAX_ARCHIVE_BYTES)
        response = GeneratedResponse(1, MAX_ARCHIVE_BYTES+1)
        with self.assertRaises(updates.UpdateError): self.download(response, 1)
        self.assertTrue(response.closed)

    def test_interruption_cancellation_and_disk_cleanup(self):
        for response, kwargs in ((GeneratedResponse(100, interrupt=True), {}),
                                 (GeneratedResponse(100), {"cancelled": lambda: True})):
            with self.assertRaises(updates.UpdateError): self.download(response, 100, **kwargs)
            self.assertFalse((self.root / "archive.zip.part").exists())
        with patch("signalbar.archive_policy.shutil.disk_usage", return_value=Mock(free=1)):
            with self.assertRaisesRegex(updates.UpdateError, "free disk space"):
                self.download(GeneratedResponse(100), 100)

    def test_extraction_limits_unsafe_paths_and_existing_stage_are_preserved(self):
        archive = self.root / "a.zip"
        write_archive(archive)
        with patch("signalbar.updates.MAX_UNCOMPRESSED_BYTES", 1):
            with self.assertRaises(updates.UpdateError): updates.validate_and_stage_archive(archive, self.root / "stage", "1.1.0")
        self.assertFalse((self.root / "stage").exists())
        for path in ("/absolute", "GabeCubeAura/../outside", "GabeCubeAura/./main.py", "GabeCubeAura//main.py", "GabeCubeAura/a\\b"):
            with ZipFile(archive, "w") as output: output.writestr(path, b"bad")
            with self.assertRaises(updates.UpdateError): updates.validate_and_stage_archive(archive, self.root / "stage", "1.1.0")
            self.assertFalse((self.root / "stage").exists())
        existing = self.root / "stage"; existing.mkdir(); (existing / "keep").write_text("user")
        with self.assertRaises(updates.UpdateError): updates.validate_and_stage_archive(archive, existing, "1.1.0")
        self.assertTrue((existing / "keep").exists())

    def test_extraction_stream_enforces_actual_not_just_declared_size(self):
        archive = self.root / "a.zip"
        with ZipFile(archive, "w") as output: output.writestr("GabeCubeAura/data", b"x")
        import io
        with patch("signalbar.updates.ZipFile.open", return_value=io.BytesIO(b"xx")):
            with self.assertRaisesRegex(updates.UpdateError, "bounded size"):
                updates.validate_and_stage_archive(archive, self.root / "stage", "1.1.0")
        self.assertFalse((self.root / "stage").exists())

    def test_real_large_archive_download_install_rollback_and_vault(self):
        archive = self.root / "large.zip"
        write_archive(archive)
        with ZipFile(archive, "a", ZIP_DEFLATED) as output:
            with output.open("GabeCubeAura/large-test-resource.bin", "w") as payload:
                for _ in range(33): payload.write(os.urandom(1048576))
        size = archive.stat().st_size
        self.assertGreater(size, 32*1048576)
        self.assertLess(size, MAX_ARCHIVE_BYTES)
        client = updates.GitHubReleaseClient(opener=lambda *args, **kw: archive.open("rb"))
        class FileResponse:
            headers = {}  # exercise absent Content-Length with a real file
            def __enter__(self): self.stream = archive.open("rb"); return self
            def __exit__(self, *_): self.stream.close()
            def read(self, n): return self.stream.read(n)
        client._open = lambda *args, **kw: FileResponse()
        downloaded = self.root / "download.zip"
        digest = client.download_archive({"archive_url":"https://github.com/Alyenax/GabeCubeAura/releases/download/v1.1.0/a.zip", "archive_size":size}, downloaded, "1.0.0")
        self.assertEqual(digest, updates._sha256_file(archive))
        raw = update_fixtures.UpdateTests()._transaction(self.root / "install")
        stage = Path(raw['staged_dir']); import shutil
        shutil.rmtree(stage.parent)  # fixture-owned leaf only
        # Real two-step installation in the same sandbox, not merely asset
        # discovery: compatible small bridge, then the large ZIP.
        bridge = self.root/'compatible-bridge.zip'; write_archive(bridge, '1.0.1')
        bridge_token = 'd'*32
        bridge_stage = Path(raw['runtime_root'])/'staged'/bridge_token
        updates.validate_and_stage_archive(bridge,bridge_stage,'1.0.1')
        bridge_raw = dict(raw, token=bridge_token,to_version='1.0.1',
                          staged_dir=str(bridge_stage/'GabeCubeAura'),
                          health_path=str(Path(raw['runtime_root'])/'health'/f'{bridge_token}.json'))
        self.assertEqual(run_transaction(bridge_raw,FakeService(),lambda *args:True,fake_exchange)['result'],'updated')
        raw['from_version'] = '1.0.1'
        updates.validate_and_stage_archive(downloaded, stage.parent, "1.1.0")
        result = run_transaction(raw, FakeService(), lambda *args: True, fake_exchange)
        self.assertEqual(result['result'], 'updated')
        self.assertEqual((Path(raw['active_dir']) / 'large-test-resource.bin').stat().st_size, 33*1048576)
        # Archive and validate the large installed version as a recovery source.
        vault = RecoveryVault(Path(raw['runtime_root']), self.root / 'settings/config.json', self.root / 'share/gabecubeaura')
        vault.capture('c'*32, '1.1.0', Path(raw['active_dir']))
        metadata, retained, snapshot = vault.current()
        self.assertGreater(retained.stat().st_size, 32*1048576)
        self.assertEqual(metadata['sha256'], updates._sha256_file(retained))
        # Independent installation failure must restore the working code.
        failed = update_fixtures.UpdateTests()._transaction(self.root / "failed")
        result = run_transaction(failed, FakeService(), lambda *args: False, fake_exchange)
        self.assertEqual(result['result'], 'rolled_back')
        self.assertIn('old', (Path(failed['active_dir'])/'main.py').read_text())
        proof = os.environ.get('GABECUBE_LARGE_PROOF_DIR')
        if proof:
            output = Path(proof); output.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive, output/'integration-large-fixture.zip')
            (output/'large-archive-proof.json').write_text(json.dumps({
                'compressed_bytes':size, 'sha256':digest, 'payload_bytes':33*1048576,
                'download':'streamed without Content-Length', 'extraction':'validated',
                'install':'simulated service / directory exchange', 'rollback':'simulated health failure restored old code',
                'recovery_vault':'large archive verified', 'hardware_tested':False,
                'migration':'small compatible bridge installed, then large archive on same installation',
                'production_archive_padded':False}, indent=2)+'\n')

    def test_pinned_recovery_prepares_bridge_without_touching_settings_or_modules(self):
        from signalbar.recover_cli import prepare
        bridge = self.root/'bridge.zip'; write_archive(bridge,'1.1.0')
        active = self.root/'homebrew/plugins/GabeCubeAura'; write_plugin(active,'1.0.0')
        config = self.root/'homebrew/settings/GabeCubeAura/config.json'
        config.parent.mkdir(parents=True); config.write_bytes(b'{"keep":true}')
        user = self.root/'share/gabecubeaura'
        module = user/'gabe-voice-v1/module'; module.parent.mkdir(parents=True); module.write_bytes(b'kept')
        unknown = user/'future-state'; unknown.write_bytes(b'kept')
        raw, transaction = prepare(bridge,updates._sha256_file(bridge),'1.1.0',active,
                                  self.root/'runtime',config,user)
        self.assertTrue(transaction.is_file())
        self.assertEqual(json.loads((active/'package.json').read_text())['version'],'1.0.0')
        result = run_transaction(raw,FakeService(),lambda *args:True,fake_exchange)
        self.assertEqual(result['result'],'updated')
        self.assertEqual(config.read_bytes(),b'{"keep":true}')
        self.assertEqual(module.read_bytes(),b'kept'); self.assertEqual(unknown.read_bytes(),b'kept')
        # This is the concrete old-install -> compatible bridge step. The
        # same modern staging/install path accepts the real large test above.

    def test_disk_corruption_cancel_and_symlink_reject_leave_active_untouched(self):
        archive = self.root/'a.zip'; write_archive(archive)
        for kwargs in ({'cancelled':lambda:True}, {}):
            with patch('signalbar.archive_policy.shutil.disk_usage', return_value=Mock(free=1)):
                with self.assertRaises(updates.UpdateError):
                    updates.validate_and_stage_archive(archive,self.root/'stage','1.1.0',**kwargs)
            self.assertFalse((self.root/'stage').exists())
        archive.write_bytes(b'not a zip')
        with self.assertRaises(updates.UpdateError): updates.validate_and_stage_archive(archive,self.root/'stage','1.1.0')
        link = self.root/'stage'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(updates.UpdateError): updates.validate_and_stage_archive(archive,link,'1.1.0')
        self.assertTrue(link.is_symlink())

    def test_completion_of_another_transaction_never_skips_this_install(self):
        raw = update_fixtures.UpdateTests()._transaction(self.root)
        Path(raw['state_path']).write_text(json.dumps({'last_result':'updated',
            'installed_version':'1.1.0','completed_token':'f'*32}))
        result = run_transaction(raw,FakeService(),lambda *args:True,fake_exchange)
        self.assertEqual(result['result'],'updated')
        self.assertIn('new',(Path(raw['active_dir'])/'main.py').read_text())

    def test_failed_restore_is_never_reported_as_successful_rollback(self):
        raw=update_fixtures.UpdateTests()._transaction(self.root)
        result=run_transaction(raw,FakeService(fail_start=True),lambda *args:True,fake_exchange)
        self.assertEqual(result['result'],'recovery_failed')
        self.assertEqual(json.loads(Path(raw['state_path']).read_text())['phase'],'error')

    def test_manager_cancel_cleans_download_and_stage_without_touching_active(self):
        from signalbar.settings import SettingsStore
        archive=self.root/'candidate.zip'; write_archive(archive,'1.1.0')
        active=self.root/'plugins/GabeCubeAura'; write_plugin(active,'1.0.0')
        client=update_fixtures.FakeClient(archive)
        manager=updates.UpdateManager('1.0.0',SettingsStore(str(self.root/'settings/config.json')),
            str(self.root/'runtime'),str(active),update_fixtures.FakeLogger(),client=client)
        manager.check()
        download=client.download_archive
        def interrupted(*args):
            result=download(*args);manager.cancel_preparation();return result
        client.download_archive=interrupted
        result=manager.prepare()
        self.assertEqual(result['error_category'],'cancelled')
        self.assertFalse(list((manager.root/'downloads').glob('*')))
        self.assertFalse(list((manager.root/'staged').glob('*')))
        self.assertEqual(json.loads((active/'package.json').read_text())['version'],'1.0.0')

    def test_interrupted_preparation_restart_cleans_only_recorded_token(self):
        from signalbar.settings import SettingsStore
        root=self.root/'runtime/updates'; root.mkdir(parents=True)
        token='e'*32
        for family in ('downloads','staged'):
            owned=root/family/token; owned.mkdir(parents=True); (owned/'partial').write_bytes(b'partial')
            other=root/family/('f'*32); other.mkdir(); (other/'keep').write_bytes(b'keep')
        (root/'update-state.json').write_text(json.dumps({'phase':'downloading','preparation_token':token}))
        manager=updates.UpdateManager('1.0.0',SettingsStore(str(self.root/'settings/config.json')),
            str(self.root/'runtime'),str(self.root/'plugins/GabeCubeAura'),update_fixtures.FakeLogger())
        self.assertEqual(manager.status()['error_category'],'interrupted')
        for family in ('downloads','staged'):
            self.assertFalse((root/family/token).exists())
            self.assertEqual((root/family/('f'*32)/'keep').read_bytes(),b'keep')

    def test_partial_component_copy_failure_restores_only_touched_components(self):
        import shutil
        raw = update_fixtures.UpdateTests()._transaction(self.root)
        raw.update(schema=2,components=['plugin','faceplate-service','pixel-studio'],
                   companion_root=str(self.root/'share/gabecubeaura/components'))
        for component in ('faceplate-service','pixel-studio'):
            for parent, version in ((Path(raw['staged_dir'])/'components','1.1.0'), (Path(raw['companion_root']),'1.0.0')):
                directory=parent/component; directory.mkdir(parents=True)
                (directory/'component.json').write_text(json.dumps({'id':component,'version':version}))
                (directory/'keep').write_text(version)
        desktop=self.root/'share/applications/gabecubeaura-pixel-studio.desktop'
        desktop.parent.mkdir(parents=True); desktop.write_text('keep launcher')
        original=shutil.copytree
        def copy(source, target, **kwargs):
            if source.name=='pixel-studio': raise OSError('disk full')
            return original(source,target,**kwargs)
        with patch('signalbar.update_helper.shutil.copytree',side_effect=copy):
            result=run_transaction(raw,FakeService(),lambda *args:True,fake_exchange)
        self.assertEqual(result['result'],'rolled_back')
        for component in ('faceplate-service','pixel-studio'):
            self.assertEqual((Path(raw['companion_root'])/component/'keep').read_text(),'1.0.0')
        self.assertEqual(desktop.read_text(),'keep launcher')

    def test_real_legacy_discovery_rejects_latest_even_if_bridge_is_listed(self):
        # Execute the published source, not a guessed reimplementation.
        source = (Path(__file__).resolve().parents[1]/'fixtures/updater-lab121.py.txt').read_text()
        import types
        legacy = types.ModuleType('signalbar.legacy_updates')
        legacy.__package__ = 'signalbar'
        legacy.__file__ = str(Path(updates.__file__))
        exec(compile(source, legacy.__file__, 'exec'), legacy.__dict__)
        def release(version, size):
            prefix = f'https://github.com/Alyenax/GabeCubeAura/releases/download/v{version}'
            return {'tag_name':'v'+version, 'draft':False, 'prerelease':False,
                'html_url':f'https://github.com/Alyenax/GabeCubeAura/releases/tag/v{version}',
                'assets':[{'name':f'GabeCubeAura-v{version}.zip','size':size,'browser_download_url':prefix+f'/GabeCubeAura-v{version}.zip'},
                          {'name':'SHA256SUMS','size':100,'browser_download_url':prefix+'/SHA256SUMS'}]}
        bridge = release('1.1.0', 1000); large = release('1.2.0', 33*1048576)
        def opener(*args, **kw): return FakeResponse(json.dumps([bridge,large]).encode())
        old = legacy.GitHubReleaseClient(opener=opener, api_url=updates.RELEASES_API_URL)
        with self.assertRaises(legacy.UpdateError): old.latest('1.0.0')
        # Pinning an actual bridge tag works even after a newer release exists.
        old._open = lambda *args, **kw: FakeResponse(json.dumps(bridge).encode())
        old.api_url = 'https://api.github.com/repos/Alyenax/GabeCubeAura/releases/tags/v1.1.0'
        self.assertEqual(old.latest('1.0.0')['version'], '1.1.0')
        modern = updates.GitHubReleaseClient(opener=opener, api_url=updates.RELEASES_API_URL)
        self.assertEqual(modern.latest('1.1.0')['archive_size'], 33*1048576)
