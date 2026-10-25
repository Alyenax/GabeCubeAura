from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from signalbar.settings import SettingsStore
from signalbar.renderer import Renderer

class HostBrightnessAuditTests(unittest.TestCase):
    def test_renderer_constant_frames_bound_host_writes_and_recover_latest_steam_gain(self):
        class Hardware:
            def __init__(self):self.brightness=78;self.writes=[];self.frame=[(0,0,0)]*17
            def read_brightness_scale(self):return self.brightness
            def set_brightness_scale(self,value):self.writes.append(value);self.brightness=value;return True
            def restore_brightness_scale_if(self,expected,saved):
                if self.brightness!=expected:return False
                return self.set_brightness_scale(saved)
            def read_frame(self):return self.frame
            def write_frame(self,frame):self.frame=frame
            def read_signature(self):return str(self.frame)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'recovery.json';hardware=Hardware();now=[1.]
            renderer=Renderer(hardware,clock=lambda:now[0],brightness_recovery_path=str(path))
            renderer.set_output_brightness_scale(9)
            import os
            with patch('signalbar.renderer.renderer.os.replace',wraps=os.replace) as writes:
                for i in range(100):
                    now[0]+=.1;renderer.render([(i%255,20,30)]*17,force=True)
                self.assertEqual([9],hardware.writes);self.assertEqual(1,writes.call_count)
                self.assertEqual(78,json.loads(path.read_text())['saved_brightness_scale'])
                hardware.brightness=31;now[0]+=.1;renderer.render([(1,2,3)]*17,force=True)
                self.assertEqual(9,hardware.brightness);self.assertEqual(2,writes.call_count)
            Renderer(hardware,brightness_recovery_path=str(path))
            self.assertEqual(31,hardware.brightness);self.assertFalse(path.exists())
