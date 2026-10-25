from __future__ import annotations

import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.models import LED_COUNT
from signalbar.providers.onboarding import (
    immersive_preview_output,
    synthetic_screen_sync_frame,
    synthetic_slow_prism_frame,
)
from signalbar.settings import SettingsStore
from test_lab101_runtime_ack import FakeHardware


class OnboardingPreviewTests(unittest.TestCase):
    def test_four_real_render_paths_without_persisting_or_opening_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            store=SettingsStore(str(path))
            store.update({'home_display':'customization','faceplate_lab_enabled':False,
                          'valve_ownership_policy':'critical','light_bar_day_brightness':29})
            before=path.read_bytes()
            hardware=FakeHardware()
            engine=Engine(store,str(Path(directory)/'artwork.json'),hardware_factory=lambda:hardware)
            def wait_for(predicate, seconds=3):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    state=engine.status()
                    if predicate(state):return state
                    time.sleep(.02)
                self.fail(str(engine.status().get('error'))+' / '+engine.status()['provider'])
            with patch.object(engine.audio_sync.capture,'set_active') as audio_configure, \
                 patch.object(engine.screen_sync,'set_active') as video_configure:
                engine.start()
                try:
                    wait_for(lambda s:s['debug']['guard_state']=='ready')
                    for preset,provider in [('moderate','customization:'),('atmosphere','audio-sync:slow-prism-demo'),
                                            ('signals','controller:'),('immersive','audio-sync:slow-prism-demo')]:
                        engine.preview_display_preset(preset,owner='setup-test')
                        state=wait_for(lambda s:s['display_preset_preview']['on_bar'] and s['provider'].startswith(provider))
                        first=state['display_preset_preview']['colors']
                        self.assertEqual(17,len(first));self.assertTrue(any(any(p) for p in first))
                        self.assertEqual([list(p) for p in hardware.frame],first)
                        if preset!='moderate':  # Its current Customization+ recipe is steady.
                            wait_for(lambda s:s['display_preset_preview']['colors']!=first)
                        if preset=='immersive':
                            state=wait_for(lambda s:s['provider']=='screen-sync:panorama-demo',seconds=7)
                            self.assertEqual('Screen Sync',state['display_preset_preview']['phase'])
                        if preset=='signals':
                            with engine._lock:
                                engine._display_preset_preview_until=time.monotonic()-.01
                            wait_for(lambda s:not s['display_preset_preview']['active']
                                     and s['provider'].startswith('customization:'))
                            self.assertIsNone(engine.controllers._active)
                        self.assertEqual(before,path.read_bytes())
                        self.assertEqual(29,store.all()['light_bar_day_brightness'])
                        self.assertFalse(engine.stop_display_preset_preview('other-setup'))
                        self.assertTrue(engine.stop_display_preset_preview('setup-test'))
                        wait_for(lambda s:not s['display_preset_preview']['active'] and s['provider'].startswith('customization:'))
                    sampled,release=threading.Event(),threading.Event()
                    original=engine.controllers.event_output
                    def held_sample():
                        result=original()
                        if (threading.current_thread() is engine._thread and not sampled.is_set()
                                and engine._display_preset_preview_owner=='race-setup'):
                            sampled.set();release.wait(2)
                        return result
                    with patch.object(engine.controllers,'event_output',side_effect=held_sample):
                        engine.preview_display_preset('signals',owner='race-setup')
                        self.assertTrue(sampled.wait(2))
                        try:self.assertTrue(engine.stop_display_preset_preview('race-setup'))
                        finally:release.set()
                        wait_for(lambda s:s['provider'].startswith('customization:'))
                        self.assertIsNone(engine.controllers._active)
                    self.assertFalse(any(call.args[0] for call in audio_configure.call_args_list))
                    self.assertFalse(any(call.args[0] for call in video_configure.call_args_list))
                finally:engine.stop()

    def test_stop_only_cancels_its_own_demo_and_preserves_a_real_controller_event(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=Engine(SettingsStore(str(Path(directory)/'settings.json')),str(Path(directory)/'cache'))
            engine.preview_display_preset('signals',owner='old')
            engine.controllers.preview('duo',engine.settings.all(),count=2,target=1)
            engine.preview_display_preset('immersive',owner='new')
            self.assertFalse(engine.stop_display_preset_preview('old'))
            self.assertEqual('new',engine.status()['display_preset_preview']['owner'])
            self.assertTrue(engine.stop_display_preset_preview('new'))
            engine.preview_display_preset('signals',owner='setup')
            engine.controllers.preview('duo',engine.settings.all(),count=2,owner='different-control')
            self.assertTrue(engine.stop_display_preset_preview('setup'))
            self.assertIsNotNone(engine.controllers._active)
            engine.preview_display_preset('signals',owner='setup')
            with engine.controllers._lock:
                engine.controllers._active=('low','flash',{},False)
            self.assertTrue(engine.stop_display_preset_preview('setup'))
            self.assertIsNotNone(engine.controllers._active)
            engine.controllers.clear_transients()

    def test_slow_prism_demo_is_mirrored_bounded_and_breathes(self):
        first = synthetic_slow_prism_frame(0.0)
        expanded = synthetic_slow_prism_frame(0.65)
        self.assertEqual(len(first), LED_COUNT)
        self.assertEqual(first, tuple(reversed(first)))
        self.assertEqual(expanded, tuple(reversed(expanded)))
        self.assertNotEqual(first, expanded)
        self.assertGreater(sum(pixel != (0, 0, 0) for pixel in first), 0)
        self.assertGreater(
            sum(pixel != (0, 0, 0) for pixel in expanded),
            sum(pixel != (0, 0, 0) for pixel in first),
        )

    def test_screen_sync_demo_is_spatial_bounded_and_moves(self):
        first = synthetic_screen_sync_frame(0.0)
        moved = synthetic_screen_sync_frame(1.2)
        self.assertEqual(len(first), LED_COUNT)
        self.assertNotEqual(first, moved)
        self.assertGreater(len(set(first)), 8)
        for frame in (first, moved):
            for pixel in frame:
                self.assertTrue(all(0 <= channel <= 255 for channel in pixel))

    def test_immersive_demo_switches_from_audio_to_screen(self):
        audio = immersive_preview_output(1.0, 10.0)
        screen = immersive_preview_output(7.0, 10.0)
        self.assertEqual(audio.provider, "audio-sync:slow-prism-demo")
        self.assertEqual(screen.provider, "screen-sync:panorama-demo")
        self.assertIsNotNone(audio.frame)
        self.assertIsNotNone(screen.frame)

    def test_engine_status_exposes_the_synthetic_preview_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(str(Path(directory) / "settings.json"))
            engine = Engine(store, str(Path(directory) / "artwork.json"))
            with patch("signalbar.backend.engine.time.monotonic", return_value=100.0):
                self.assertTrue(engine.preview_display_preset("immersive"))
            with patch("signalbar.backend.engine.time.monotonic", return_value=101.0):
                preview = engine.status()["display_preset_preview"]
            self.assertTrue(preview["active"])
            self.assertEqual(preview["phase"], "Audio Sync")
            self.assertEqual(len(preview["colors"]), LED_COUNT)


if __name__ == "__main__":
    unittest.main()
