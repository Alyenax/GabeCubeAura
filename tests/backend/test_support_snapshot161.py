"""A single local document remains available through component/storage failures."""
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from signalbar.support_snapshot import installation,runtime,system_facts
from signalbar.diagnostics import DiagnosticJournal
from signalbar.settings.store import DEFAULTS
from test_cinema_integration import plugin_class

class SnapshotTests(unittest.TestCase):
    def test_partial_install_and_stale_frontend_are_explicit_not_assumed_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp);(r/'package.json').write_text(json.dumps({'version':'1.6.1-beta.1'}));(r/'main.py').write_text('changed')
            (r/'update-manifest.json').write_text(json.dumps({'version':'1.6.1-beta.1','components':[{'id':'plugin','files':[{'path':'main.py','sha256':hashlib.sha256(b'original').hexdigest()}]}]}))
            s=installation(r,'1.6.1-beta.1','1.6.0')
            self.assertFalse(s['frontend_backend_match']);self.assertTrue(s['backend_package_match'])
            self.assertFalse(s['all_checked_files_match']);self.assertNotIn(tmp,json.dumps(s))

    def test_missing_manifest_and_unknown_versions_remain_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=installation(tmp,'1.6.1-beta.1','')
            self.assertIsNone(s['all_checked_files_match']);self.assertEqual(s['frontend_version'],'unknown')
            self.assertIsNone(s['frontend_backend_match'])

    def test_identity_does_not_follow_a_symlink_or_read_oversized_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);outside=root/'secret';outside.write_text('{"version":"private-value"}')
            (root/'package.json').symlink_to(outside)
            self.assertEqual(installation(root,'1.6.1-beta.1')['package_version'],'unknown')
            (root/'package.json').unlink();(root/'package.json').write_bytes(b'x'*1048577)
            self.assertEqual(installation(root,'1.6.1-beta.1')['package_version'],'unknown')

    def test_runtime_snapshot_never_probes_opens_or_uploads(self):
        panel=SimpleNamespace(powered=False,last_transfer={'begin_status':0,'chunks':0,'path':'secret'},restoration_status=lambda:{'held_dark':True})
        settings=SimpleNamespace(all=lambda:dict(DEFAULTS,steamgriddb_api_key='secret',weather_location={'name':'PRIVATE CITY'}))
        engine=SimpleNamespace(settings=settings,faceplate=panel,weather=SimpleNamespace(diagnostic_status=lambda:{'clock_kind':'boottime'}),_faceplate_manual_off=False)
        s=runtime(engine);self.assertFalse(s['power_intent']['manual_off']);self.assertEqual(s['last_transfer']['begin_status'],0)
        self.assertNotIn('secret',json.dumps(s));self.assertNotIn('PRIVATE CITY',json.dumps(s))
        self.assertEqual(s['display_observation'],'not-measured')

class ExportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);root=Path(self.temp.name).resolve()
        self.p=plugin_class()();self.p.diagnostics=DiagnosticJournal(root/'state','1.6.1-beta.1')
        self.p.configuration_export_path=root/'Documents/config.json'
        self.p.engine=SimpleNamespace(display_control_snapshot=lambda:{'available':False})
        self.p._cinema_diagnostic_snapshot=lambda:{};self.p._update_diagnostic_snapshot=lambda:{}
        self.p._append_setup_recovery=lambda report:report.update(setup_recovery={'blocks_runtime':False})

    async def test_one_capture_creates_the_same_private_file_and_copyable_json(self):
        result=await self.p.export_support_diagnostic('1.6.1-beta.1')
        self.assertTrue(result['saved']);path=Path(result['path'])
        self.assertEqual(path.read_text(),result['text']);self.assertEqual(path.stat().st_mode&0o777,0o600)
        d=json.loads(result['text']);self.assertEqual(d['support']['installation']['frontend_version'],'1.6.1-beta.1')
        self.assertFalse(d['privacy']['api_keys_included'])

    async def test_unwritable_export_keeps_the_document_without_repeating_capture(self):
        build=Mock(wraps=self.p.diagnostics.build_report);self.p.diagnostics.build_report=build
        with patch('signalbar.safe_export.write_private_bytes',side_effect=OSError('PRIVATE PATH and credentials')):
            result=await self.p.export_support_diagnostic('1.6.1-beta.1')
        self.assertFalse(result['saved']);self.assertTrue(json.loads(result['text']))
        self.assertEqual(build.call_count,1);self.assertNotIn('PRIVATE PATH',str(result))

    async def test_broken_runtime_sections_do_not_block_the_remaining_report(self):
        self.p.engine=SimpleNamespace(display_control_snapshot=Mock(side_effect=RuntimeError('private')))
        self.p._append_setup_recovery=Mock(side_effect=ValueError('private'))
        self.p._update_diagnostic_snapshot=Mock(side_effect=RuntimeError('private'))
        d=json.loads((await self.p.export_support_diagnostic())['text'])
        self.assertEqual(d['display_control'],{'available':False});self.assertEqual(d['setup_recovery'],{'available':False})
        self.assertIn('installation',d['support'])

    async def test_missing_destination_still_allows_copy(self):
        self.p.configuration_export_path=None
        result=await self.p.export_support_diagnostic();self.assertFalse(result['saved']);self.assertTrue(result['text'])

    async def test_unavailable_optional_cinema_does_not_drop_backend_evidence(self):
        self.p._cinema_diagnostic_snapshot=Mock(side_effect=RuntimeError('private-data'))
        d=json.loads((await self.p.export_support_diagnostic())['text'])
        self.assertEqual(d['cinema'],{'available':False});self.assertIn('installation',d['support'])
        self.assertNotIn('private-data',json.dumps(d))

    async def test_large_history_is_reduced_while_support_evidence_remains_copyable(self):
        base=self.p.diagnostics.build_report()['report']
        base['events']=[{'message':'x'*720} for _ in range(300)]
        base['voice_incidents']=['y'*720]*300
        self.p.diagnostics.build_report=lambda **kwargs:{'report':base}
        text=(await self.p.export_support_diagnostic('1.6.1-beta.1'))['text']
        self.assertLessEqual(len(text.encode()),98304)
        d=json.loads(text);self.assertTrue(d['report_reduced']);self.assertIn('installation',d['support'])
