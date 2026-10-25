"""Logo sizing through actual RGB composition, preparation, worker and Decky RPC."""
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile
from signalbar.faceplate.artwork_layout import FRAME_BYTES, Logo, compose_frame, _resize_logo
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate, compile_source
from signalbar.faceplate.artwork_jobs import ArtworkPreparationJobs
from signalbar.faceplate.creation_transfer import creation_archive
from signalbar.faceplate import prepare_worker
import test_faceplate_artwork_jobs as jobs_fixture
ROOT=Path(__file__).resolve().parents[2]

def solid_logo(width=20,height=10,alpha=1.):
    return Logo(width,height,tuple((x,y,alpha,(255.,255.,255.)) for y in range(height) for x in range(width)))

def bounds(frame):
    coordinates=[(i%64,i//64) for i in range(3456) if any(frame[i*3:i*3+3])]
    return (min(x for x,y in coordinates),min(y for x,y in coordinates),max(x for x,y in coordinates),max(y for x,y in coordinates))

class LogoScale245Tests(unittest.TestCase):
    def test_100_percent_exactly_preserves_all_historical_layouts(self):
        logo=Logo(58,48,tuple((x,y,((x+y)%3+1)/3,((x*11)%256,(y*13)%256,((x+y)*7)%256)) for y in range(48) for x in range(58)))
        frame=bytes((13,31,77))*3456
        golden=json.loads((ROOT/'tests/fixtures/logo_scale245_normal.json').read_text())
        for key,digest in golden.items():
            style,position=key.split(':')
            with self.subTest(key=key):
                result=compose_frame(frame,logo,style,position,100)
                self.assertEqual(hashlib.sha256(result).hexdigest(),digest)
                self.assertEqual(compose_frame(frame,logo,style,position),result)

    def test_half_and_three_quarter_sizes_keep_proportions_and_anchor(self):
        for size,width,height in ((100,20,10),(75,15,8),(50,10,5)):
            for position in ('top','centre','bottom','bottom_rail'):
                with self.subTest(size=size,position=position):
                    result=compose_frame(bytes(FRAME_BYTES),solid_logo(),'logo',position,size)
                    x,y,right,bottom=bounds(result)
                    self.assertEqual((right-x+1,bottom-y+1),(width,height))
                    self.assertEqual(x,(64-width)//2)
                    self.assertEqual(y,2 if position=='top' else (45-height)//2 if position=='centre' else 43-height if position=='bottom' else 54-height-3)
                    if position!='bottom_rail':self.assertEqual(set(result[45*64*3:]),{0})

    def test_shrinking_tall_logos_is_relative_to_normal_fitted_size(self):
        normal=bounds(compose_frame(bytes(FRAME_BYTES),solid_logo(58,48),'logo','bottom',100))
        small=bounds(compose_frame(bytes(FRAME_BYTES),solid_logo(58,48),'logo','bottom',50))
        self.assertEqual(normal[3]-normal[1]+1,40)
        self.assertEqual((small[2]-small[0]+1,small[3]-small[1]+1),(24,20))

    def test_area_filter_keeps_coverage_without_transparent_colour_bleeding(self):
        # One covered white source pixel in a 2x2 block -> 25% white coverage.
        logo=Logo(2,2,((0,0,1.,(255.,255.,255.)),(1,0,0.,(255.,0.,0.))))
        result=compose_frame(bytes(FRAME_BYTES),logo,'logo','top',50)
        self.assertEqual(result[3*(2*64+31):3*(2*64+31)+3],bytes((64,64,64)))
        half=compose_frame(bytes(FRAME_BYTES),solid_logo(alpha=.5),'logo','top',50)
        x,y,_,_=bounds(half)
        self.assertEqual(half[3*(y*64+x):3*(y*64+x)+3],bytes((128,128,128)))

    def test_missing_or_disabled_overlay_keeps_image_and_repeated_frames_reuse_filter(self):
        frame=bytes((17,44,99))*3456
        for size in (50,75,100):
            self.assertEqual(compose_frame(frame,None,'logo_only','top',size),frame)
            self.assertEqual(compose_frame(frame,solid_logo(),'art','bottom',size),frame)
        _resize_logo.cache_clear();logo=solid_logo()
        for _ in range(6):compose_frame(frame,logo,'logo','top',50)
        self.assertEqual(_resize_logo.cache_info().misses,1)
        self.assertEqual(_resize_logo.cache_info().hits,5)

    def test_native_compilation_static_pan_and_animation_share_scaled_overlay(self):
        for mode,count in (('static',1),('pan',3),('source',3)):
            frames=[bytes((8+i*8,16,32))*3456 for i in range(count)]
            with self.subTest(mode=mode),patch('signalbar.faceplate.steamgriddb.decode_frames',return_value=frames),patch('signalbar.faceplate.artwork_layout.prepare_logo',return_value=solid_logo()) as prepare:
                data,load,total,backgrounds=compile_source('fixture.png',animation_style=mode,include_frames=True,appid=620,art_style='logo',logo_position='top',logo_scale=50)
            self.assertEqual(total,count);self.assertEqual(len(backgrounds),count);prepare.assert_called_once_with(620)
            self.assertTrue(data.startswith(b'GIF89a'));self.assertGreater(load,0)
            for index,background in enumerate(backgrounds):
                self.assertEqual(background,compose_frame(frames[index],solid_logo(),'logo','top',50))

    def test_size_survives_restart_home_copy_export_and_configuration_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            lib=SteamGridDBFaceplate(directory)
            asset=dict(id=42,url='https://example.test/a.png',thumb='https://example.test/t.png',animated=False,kind='grid',author='test',width=64,height=54)
            def download(url,path,progress=None):Path(path).write_bytes(b'fixture');return 'png',7
            with patch.object(lib,'_download_to',side_effect=download),patch('signalbar.faceplate.steamgriddb.decode_frames',return_value=[bytes((10,20,30))*3456]),patch('signalbar.faceplate.artwork_layout.prepare_logo',return_value=solid_logo()):
                saved=lib.prepare_choice(620,asset,'static',art_style='logo',logo_position='top',logo_scale=65)
            self.assertEqual(saved['logo_scale'],65)
            lib.activate_prepared(620,'static');lib.assign_home(620,'static')
            restarted=SteamGridDBFaceplate(directory)
            self.assertEqual(restarted.selected_manifest(620)['logo_scale'],65)
            self.assertEqual(restarted.home_dashboard_manifest(620)['logo_scale'],65)
            self.assertEqual(restarted.library_entries()[0]['logo_scale'],65)
            self.assertIn('"logo_scale": 65',json.dumps(restarted.configuration_snapshot()))
            with ZipFile(io.BytesIO(creation_archive(restarted,620,'static',saved['sha256']))) as archive:
                self.assertEqual(json.loads(archive.read('creation.json'))['manifest']['logo_scale'],65)

    def test_request_and_isolated_worker_forward_size_without_hardware(self):
        with tempfile.TemporaryDirectory() as directory,patch('signalbar.faceplate.artwork_jobs.shutil.which',return_value='/usr/bin/python3'),patch('signalbar.faceplate.artwork_jobs.subprocess.Popen',return_value=jobs_fixture._Process()),patch('signalbar.faceplate.artwork_jobs.threading.Thread',jobs_fixture._Thread):
            jobs=ArtworkPreparationJobs(jobs_fixture._Library(directory),lambda:{'appid':0})
            jobs.start(dict(appid=620,asset_id=42,asset_kind='grid',mode='static',logo_scale=75))
            request=next((Path(directory)/'jobs').glob('*.request.json'))
            self.assertEqual(json.loads(request.read_text())['logo_scale'],75)
            library=Mock();library.prepare_choice.return_value={'logo_scale':75}
            progress=Path(directory)/'worker-progress.json'
            with patch.object(prepare_worker,'SteamGridDBFaceplate',return_value=library),patch.object(prepare_worker,'exclusive_render_lock',return_value=contextlib.nullcontext()):
                self.assertEqual(prepare_worker.main(['worker',directory,str(request),str(progress)]),0)
            self.assertEqual(library.prepare_choice.call_args.kwargs['logo_scale'],75)
            self.assertEqual(json.loads(progress.read_text())['prepared']['logo_scale'],75)

    def test_rpc_reaches_preparation_and_rejects_invalid_sizes_before_start(self):
        with patch.dict(sys.modules,{'decky':types.ModuleType('decky')}):
            spec=importlib.util.spec_from_file_location('logo_scale_rpc_test',ROOT/'main.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        plugin=module.Plugin();plugin.engine=Mock();plugin.engine.settings.all.return_value={};plugin.diagnostics=Mock();plugin.faceplate_artwork_jobs=Mock()
        plugin.faceplate_artwork_jobs.start.return_value={'state':'queued'}
        args=(620,42,'grid','static',50,110,100)
        asyncio.run(plugin.prepare_faceplate_artwork(*args,logo_scale=55))
        self.assertEqual(plugin.faceplate_artwork_jobs.start.call_args.args[0]['logo_scale'],55)
        asyncio.run(plugin.prepare_faceplate_artwork(*args))
        self.assertEqual(plugin.faceplate_artwork_jobs.start.call_args.args[0]['logo_scale'],100)
        plugin.faceplate_artwork_jobs.start.reset_mock()
        for invalid in (49,101,0,True,75.5,'75',None):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):asyncio.run(plugin.prepare_faceplate_artwork(*args,logo_scale=invalid))
        plugin.faceplate_artwork_jobs.start.assert_not_called()
        plugin.engine.faceplate.set_power.assert_not_called()
