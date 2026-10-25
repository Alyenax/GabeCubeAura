"""Regression for oversized City writes and an upgrade after a failed Lab222 attempt."""
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from signalbar.faceplate import gif, power, protocol
from signalbar.faceplate.gif_transform import rotate_gif, repack_for_restore, GifTransformError
from signalbar.faceplate.coordinator import validate_gif
from signalbar.faceplate.flash import FlashWearProtection
from signalbar.faceplate.player_city import PlayerCityCadence, build_player_city
from signalbar.faceplate.transport import Link, LinkError
from signalbar.jsaux_broker.limits import LIMITS
from test_flash_protection import Clock, Panel


class GifAdmissionTests(unittest.TestCase):
    def link(self, panel):
        link=Link('/dev/null')
        link.command=panel.command
        link.flash_manager=FlashWearProtection()
        return link

    def test_size_boundary_is_shared_and_oversize_cannot_write_even_a_begin(self):
        self.assertEqual(protocol.MAX_GIF_BYTES,196608)
        self.assertEqual(protocol.MAX_GIF_BYTES,LIMITS['max_content_bytes'])
        panel=Panel();link=self.link(panel)
        with self.assertRaisesRegex(ValueError,'192 KiB'):
            link.send_gif(b'x'*(196608+1))
        self.assertEqual(panel.calls,[])
        with patch('signalbar.faceplate.transport.time.sleep'):
            self.assertTrue(link.send_gif(b'x'*196608))
        self.assertEqual(panel.bodies,math.ceil(196608/protocol.CHUNK_SIZE))

    def test_reported_failing_city_is_below_limit_without_colour_or_duration_change(self):
        scene=build_player_city('RAN','day',9964)
        data=scene.gif();validate_gif(data)
        self.assertLess(len(data),196608)
        self.assertEqual(len(scene.frames),192)
        self.assertEqual(scene.delays_cs,(12,13)*96)
        self.assertEqual(sum(scene.delays_cs),2400)

    def test_refused_chunk_records_its_offset_and_status_without_retrying_body(self):
        panel=Panel();link=self.link(panel)
        original=panel.command
        def refuse(data,**kw):
            if tuple(data[2:4])==(protocol.TYPE_DATA,protocol.CMD_GIF_CHUNK):
                seq=int.from_bytes(data[6:8],'big')
                if seq==1:
                    return protocol.Reply(protocol.TYPE_DATA,protocol.CMD_GIF_CHUNK,b'\x00')
            return original(data,**kw)
        link.command=refuse
        with patch('signalbar.faceplate.transport.time.sleep'),self.assertRaises(LinkError):
            link.send_gif(b'x'*1000)
        self.assertEqual(link.last_transfer_timings['failed_chunk'],1)
        self.assertEqual(link.last_transfer_timings['chunk_status'],0)
        self.assertEqual(link.last_transfer_timings['payload_bytes_confirmed'],498)
        self.assertEqual(panel.calls.count((protocol.TYPE_CONTROL,protocol.CMD_GIF_BEGIN)),1)
        self.assertNotIn((protocol.TYPE_CONTROL,protocol.CMD_GIF_END),panel.calls)

    def test_lab222_failure_does_not_delay_fixed_renderer_but_new_failure_still_coalesces(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'city.json';clock=Clock()
            city=PlayerCityCadence(path,clock=clock.wall)
            sample=dict(appid=620,usable=True,state='ready',players=9964,sampled_at=clock.wall())
            weather=dict(condition='rain',phase='day')
            job=city.plan(620,sample,weather);city.reserve(job);city.receipt(job,dict(error='chunk rejected'))
            saved=json.loads(path.read_text())
            saved['attempt']['render_revision']='player-city-architectural-presence-1'
            path.write_text(json.dumps(saved))
            clock.advance(60)
            city=PlayerCityCadence(path,clock=clock.wall)
            fixed=city.plan(620,sample,weather)
            self.assertIsNotNone(fixed)
            city.reserve(fixed);city.receipt(fixed,dict(error='new failure'))
            self.assertIsNone(city.plan(620,sample,weather))
            self.assertEqual(city.status()['reason'],'cadence')


class LosslessDeltaTests(unittest.TestCase):
    def native(self, first=None):
        return gif.encode(64,54,[(1,2,3),(90,100,110),(0,0,0)],
                          [bytes(3456) if first is None else first,
                           bytes([1])+bytes([2])*3455],delay_cs=(12,13),
                          transparent_index=2)

    def test_rotation_and_recovery_preserve_displayed_pixels_and_timing(self):
        data=self.native()
        expected=[bytes((1,2,3))*3456,bytes((90,100,110))+bytes((1,2,3))*3455]
        for result,frames in ((data,expected),(repack_for_restore(data),expected),
                              (rotate_gif(data),[b''.join(frame[i:i+3] for i in range(len(frame)-3,-1,-3)) for frame in expected])):
            decoded=Image.open(BytesIO(result))
            self.assertEqual(decoded.n_frames,2)
            for i,frame in enumerate(frames):
                decoded.seek(i)
                self.assertEqual(decoded.convert('RGB').tobytes(),frame)
                self.assertEqual(decoded.info['duration'],(120,130)[i])
        profile=power.profile(data)
        self.assertEqual(profile['frames'],2)
        self.assertAlmostEqual(profile['peak_load'],(3455*6+300)/(3456*765))
        self.assertAlmostEqual(power.profile(rotate_gif(data))['peak_load'],profile['peak_load'])

    def test_unsupported_disposal_and_uninitialised_pixels_fail_closed(self):
        data=self.native();gce=data.index(b'\x21\xf9\x04')
        bad_disposal=data[:gce+3]+b'\x09'+data[gce+4:]
        bad_alpha=data[:gce+6]+b'\xff'+data[gce+7:]
        for malformed in (bad_disposal,bad_alpha,self.native(bytes([2])*3456)):
            with self.assertRaises(GifTransformError):rotate_gif(malformed)
            with self.assertRaises(GifTransformError):power.profile(malformed)

    def test_city_does_not_quantise_when_no_transparent_entry_is_available(self):
        from signalbar.faceplate.player_city import PlayerCityResult
        frame=(b''.join(bytes((i,0,0)) for i in range(256))*14)[:3456*3]
        payload=PlayerCityResult((frame,),'test',(12,)).gif()
        decoded=Image.open(BytesIO(payload))
        self.assertEqual(decoded.convert('RGB').tobytes(),frame)
        self.assertEqual(len(decoded.getcolors()),256)
