import asyncio
import base64
import importlib.util
import io
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from signalbar.steam import quick_preview
from signalbar.steam import quick_preview_process


class QuickArtworkTests(unittest.TestCase):
    def setUp(self):
        quick_preview._cache.clear()

    def test_no_pillow_worker_execs_a_native_decoder_without_an_orphan_grandchild(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source with spaces.png'
            Image.new('RGB', (800, 400), 'blue').save(path)
            output = io.BytesIO(); Image.new('RGB', (320, 160), 'blue').save(output, format='JPEG')
            executable = Path(folder) / 'ffmpeg'
            # Test double for the external native decoder. The actual worker
            # runs with -S: no site-packages and therefore no Pillow at all.
            executable.write_text('#!'+sys.executable+'\nimport base64,sys\nsys.stdout.buffer.write(base64.b64decode('+repr(base64.b64encode(output.getvalue()).decode())+'))\n')
            executable.chmod(0o755)
            worker = Path(quick_preview_process.__file__)
            result = subprocess.run([sys.executable, '-S', str(worker), str(path)],
                env={**os.environ, 'PATH': folder}, capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr)
            with Image.open(io.BytesIO(result.stdout)) as image:
                self.assertEqual(image.size, (320, 160)); self.assertEqual(image.format, 'JPEG')

    def test_real_native_first_frame_without_pillow_when_codec_is_available(self):
        codec = os.environ.get('GCA_QUICK_PREVIEW_FFMPEG') or shutil.which('ffmpeg')
        if not codec:
            self.skipTest('Native FFmpeg required for the no-Pillow real decoding test')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'animated-source.png'
            red = Image.new('RGB', (1920, 620), 'red')
            red.save(path, save_all=True, append_images=[Image.new('RGB', (1920, 620), 'blue')], duration=200, loop=0)
            native = Path(folder) / 'ffmpeg'; native.symlink_to(codec)
            result = subprocess.run([sys.executable, '-S', quick_preview_process.__file__, str(path)],
                env={**os.environ, 'PATH': folder+os.pathsep+os.environ.get('PATH','')}, capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr[:200])
            self.assertLess(len(result.stdout), 128*1024)
            with Image.open(io.BytesIO(result.stdout)) as image:
                self.assertEqual(image.format, 'JPEG'); self.assertEqual(getattr(image, 'n_frames', 1), 1)
                self.assertLessEqual(image.width, 320); self.assertLessEqual(image.height, 160)
                r,g,b = image.getpixel((image.width//2, image.height//2))
                self.assertGreater(r, 230); self.assertLess(g, 15); self.assertLess(b, 15)

    def test_native_gstreamer_uses_exactly_one_snapshot_and_preserves_argument_boundaries(self):
        with patch.object(quick_preview_process.shutil, 'which', side_effect=[None, '/usr/bin/gst-launch-1.0']), \
             patch.object(quick_preview_process.os, 'execv', side_effect=OSError('test exec boundary')) as execute:
            with self.assertRaises(OSError):
                quick_preview_process.native_decoder(Path('/source with spaces.png'))
            argv = execute.call_args.args[1]
            self.assertIn('snapshot=true', argv); self.assertIn('jpegenc', argv)
            self.assertIn('location=/source with spaces.png', argv)
            self.assertIn('width=320,height=160', ','.join(argv))
            self.assertIn('add-borders=true', argv)

    def test_missing_native_decoder_has_a_specific_exit_code_not_a_blank_success(self):
        with patch.object(quick_preview_process.shutil, 'which', return_value=None), \
             patch.object(quick_preview_process.os, 'execv') as execute:
            self.assertEqual(quick_preview_process.native_decoder(Path('missing.png')), 2)
            execute.assert_not_called()

    def test_decoder_failure_is_reportable_without_user_paths_or_artwork_payload(self):
        metadata={'found':True,'appid':620,'source':'hero','fingerprint':'missing-codec'}
        with patch.object(quick_preview, 'get_library_artwork', return_value=metadata), \
             patch.object(quick_preview, 'find_library_artwork', return_value=Path('/private/username/source.png')), \
             patch.object(quick_preview.subprocess, 'run', return_value=types.SimpleNamespace(returncode=2,stdout=b'')):
            self.assertFalse(quick_preview.get_quick_artwork(620)['found'])
            self.assertEqual(quick_preview.quick_preview_diagnostic(), {'error':'decoder-unavailable','worker_exit':2})

    def test_static_thumbnail_is_bounded_cached_and_never_a_raw_animation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.png'
            images=[Image.new('RGB',(1920,620),color) for color in ('red','blue','green')]
            images[0].save(path,save_all=True,append_images=images[1:],duration=200,loop=0)
            metadata={'found':True,'appid':620,'fingerprint':'first','source':'hero'}
            run=subprocess.run
            with patch.object(quick_preview,'get_library_artwork',return_value=metadata) as lookup, \
                 patch.object(quick_preview,'find_library_artwork',return_value=path), \
                 patch.object(quick_preview.subprocess,'run',wraps=run) as worker:
                first=quick_preview.get_quick_artwork(620)
                second=quick_preview.get_quick_artwork(620)
                self.assertEqual(first,second); self.assertEqual(worker.call_count,1)
                lookup.assert_called_with(620,'hero',include_data=False)
                data=base64.b64decode(first['data_uri'].split(',')[1])
                self.assertLess(len(data),128*1024)
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.format,'JPEG')
                    self.assertLessEqual(image.width,320); self.assertLessEqual(image.height,160)
                    self.assertEqual(getattr(image,'n_frames',1),1)
                metadata['fingerprint']='replacement'
                quick_preview.get_quick_artwork(620)
                self.assertEqual(worker.call_count,2)

    def test_invalid_inputs_missing_images_and_broken_decoder_fail_without_large_payloads(self):
        for appid in (0,-1,2**32,True,'620',None):
            self.assertFalse(quick_preview.get_quick_artwork(appid)['found'])
        metadata={'found':True,'appid':620,'fingerprint':'broken','source':'hero'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'broken.png'; path.write_bytes(b'not an image')
            with patch.object(quick_preview,'get_library_artwork',return_value=metadata), \
                 patch.object(quick_preview,'find_library_artwork',return_value=path):
                self.assertFalse(quick_preview.get_quick_artwork(620)['found'])
                self.assertFalse(quick_preview._cache)

    def test_timeout_and_four_entry_cache_bound(self):
        metadata={'found':True,'appid':620,'fingerprint':'first','source':'hero'}
        with patch.object(quick_preview,'get_library_artwork',return_value=metadata), \
             patch.object(quick_preview,'find_library_artwork',return_value=Path('selected.png')):
            with patch.object(quick_preview.subprocess,'run',side_effect=subprocess.TimeoutExpired('worker',4)):
                self.assertFalse(quick_preview.get_quick_artwork(620)['found'])
            with patch.object(quick_preview.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=b'JPEG')):
                for index in range(10):
                    metadata['fingerprint']=str(index)
                    quick_preview.get_quick_artwork(620)
                self.assertEqual(len(quick_preview._cache),4)

    def test_rpc_checks_current_game_but_never_gates_preview_on_hardware_or_routing(self):
        root=Path(__file__).resolve().parents[2]
        with patch.dict(sys.modules,{'decky':types.ModuleType('decky')}):
            spec=importlib.util.spec_from_file_location('lab89_preview_main',root/'main.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        plugin=module.Plugin(); plugin.engine=Mock()
        plugin.engine.faceplate_game_snapshot.return_value={'appid':620}
        plugin.engine.faceplate.device_status.return_value={'available':True}
        with patch.object(module,'get_quick_artwork',return_value={'found':True,'appid':620}) as lookup:
            self.assertFalse(asyncio.run(plugin.get_quick_artwork(42))['found'])
            lookup.assert_not_called()
            for available in (True, False):
                plugin.engine.faceplate.device_status.return_value={'available':available}
                self.assertTrue(asyncio.run(plugin.get_quick_artwork(620))['found'])
            self.assertEqual(lookup.call_count,2)
            lookup.assert_called_with(620,'hero')
        plugin.engine.faceplate.device_status.assert_not_called()
        plugin.engine.prepare_artwork.assert_not_called()
        plugin.engine.submit_artwork.assert_not_called()

    def test_missing_hero_falls_back_to_cached_header_without_artwork_generation(self):
        def lookup(appid, source, include_data):
            self.assertFalse(include_data)
            return {'found': source == 'header', 'appid': appid, 'source': source, 'fingerprint': 'header'}
        with patch.object(quick_preview, 'get_library_artwork', side_effect=lookup) as metadata, \
             patch.object(quick_preview, 'find_library_artwork', return_value=Path('header.jpg')) as finder, \
             patch.object(quick_preview.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout=b'JPEG')) as worker:
            result = quick_preview.get_quick_artwork(620)
            self.assertTrue(result['found'])
            self.assertEqual(result['source'], 'header')
            self.assertEqual(metadata.call_count, 2)
            finder.assert_called_once_with(620, 'header')
            self.assertEqual(worker.call_count, 1)

    def test_corrupt_hero_falls_back_to_header_and_keeps_the_single_total_budget(self):
        def lookup(appid, source, include_data):
            return {'found': True, 'appid': appid, 'source': source, 'fingerprint': source}
        with patch.object(quick_preview, 'get_library_artwork', side_effect=lookup), \
             patch.object(quick_preview, 'find_library_artwork', side_effect=lambda appid, source: Path(source+'.jpg')), \
             patch.object(quick_preview.subprocess, 'run', side_effect=[
                 types.SimpleNamespace(returncode=1, stdout=b''),
                 types.SimpleNamespace(returncode=0, stdout=b'JPEG')]) as worker:
            result = quick_preview.get_quick_artwork(620)
            self.assertTrue(result['found'])
            self.assertEqual(result['source'], 'header')
            self.assertEqual(worker.call_count, 2)
            for call in worker.call_args_list:
                self.assertGreater(call.kwargs['timeout'], 0)
                self.assertLessEqual(call.kwargs['timeout'], 4)

    def test_spent_decoder_budget_never_spawns_more_fallback_workers(self):
        metadata={'found':True,'appid':620,'source':'hero','fingerprint':'slow'}
        with patch.object(quick_preview, 'get_library_artwork', return_value=metadata), \
             patch.object(quick_preview, 'find_library_artwork', return_value=Path('hero.jpg')), \
             patch.object(quick_preview.time, 'monotonic', side_effect=[0, 0, 0, 5]), \
             patch.object(quick_preview.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 4)) as worker:
            self.assertFalse(quick_preview.get_quick_artwork(620)['found'])
            self.assertEqual(worker.call_count, 1)
