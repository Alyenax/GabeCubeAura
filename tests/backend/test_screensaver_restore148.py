"""Regression of Lab147 diagnostics: ACKed Off must not replay a stale GIF.

Exercises real coordinator + transport packets against a strict simulated MCU.
No physical panel or optical alignment is claimed by this test suite.
"""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from signalbar.faceplate import gif, protocol
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.gif_transform import repack_for_restore, GifTransformError
from signalbar.faceplate.transport import Link, ReplyTimeout
import test_native_clock
import test_broker_adapter


HOME = gif.encode(64, 54, [(0, 0, 0), (20, 0, 0)],
                  [bytes([0, 1])*1728, bytes([1, 0])*1728], [11, 23])


class StrictPanel:
    """CRC may match normal content while the visible mode is still external.

    An END without a fresh body is silent (not the former native-mode fake
    that always accepted it). Fresh END verifies size/CRC before committing.
    """
    def __init__(self, stored=HOME):
        self.stored = stored
        self.visible = 'screensaver'
        self.pending = None
        self.body = bytearray()
        self.events = []
        self.empty_ends = 0
        self.commits = 0
        self.lose_end = False
        self.refuse_begin = False
        self.refuse_end = False
        self.all_stored = False
        self.token = 'usb-1'
        self.after_chunk = None
        self.after_end = None
        self.lose_off = False

    def command(self, packet, **kwargs):
        kind, cmd = packet[2:4]
        payload = packet[6:-2]
        self.events.append((kind, cmd, payload))
        status = 1
        if (kind, cmd) == (1, 1):
            self.visible = self.stored if payload == b'\x01' else None
            if payload == b'\x00' and self.lose_off:
                raise ReplyTimeout('no reply to power off')
        elif (kind, cmd) == (1, 4):
            if self.refuse_begin:
                status = 0
            elif self.all_stored or payload == protocol.gif_begin(self.stored)[6:-2]:
                status = 2
            else:
                self.pending = payload
                self.body.clear()
        elif (kind, cmd) == (2, 2):
            if self.pending is None:
                raise AssertionError('body without fresh BEGIN')
            self.body.extend(payload[2:])
            if self.after_chunk:
                self.after_chunk()
        elif (kind, cmd) == (1, 11):
            if self.pending is None:
                self.empty_ends += 1
                raise ReplyTimeout('no reply to type=0x01 cmd=0x0b')
            expected = len(self.body).to_bytes(4, 'big') + (zlib.crc32(self.body) & 0xffffffff).to_bytes(4, 'big')
            if expected != self.pending:
                raise AssertionError('incorrect wire size/CRC')
            if self.refuse_end:
                status = 0
            else:
                self.stored = bytes(self.body)
                self.pending = None
                self.commits += 1
            if self.lose_end:
                raise ReplyTimeout('no reply to type=0x01 cmd=0x0b')
            if self.after_end:
                self.after_end()
        return protocol.Reply(kind, cmd, bytes([status]))


class Restore148Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.panel = StrictPanel()
        panel = self.panel

        class PanelLink(Link):
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def write(self, packet): panel.events.append((packet[2], packet[3], packet[6:-2]))
            def command(self, packet, **kwargs): return panel.command(packet, **kwargs)

        self.factory = PanelLink
        self.coordinator = self.new_coordinator()
        sleeper = patch('signalbar.faceplate.transport.time.sleep')
        sleeper.start(); self.addCleanup(sleeper.stop)

    def new_coordinator(self):
        c = FaceplateCoordinator(self.root/'assets', self.root/'panel.json',
            port_finder=lambda: '/test', identity_reader=lambda _: self.panel.token,
            link_factory=self.factory)
        c.configure(True, 20)
        return c

    def exit(self):
        self.assertTrue(self.coordinator.set_power(False, 'screensaver-exit')['ok'])
        self.panel.events.clear()

    def restore(self, data=HOME, scene='weather'):
        return self.coordinator.synchronize_scene(data, scene, 'current',
            peak_load=.1, reason='current-route-restore')

    def assert_no_on(self):
        self.assertNotIn((1, 1, b'\x01'), self.panel.events)

    def test_acked_exit_old_automatic_on_is_deferred_without_usb_or_false_ack(self):
        self.exit()
        for reason in ('automatic power recovery', 'automatic resume', 'Decky control'):
            result = self.coordinator.set_power(True, reason)
            self.assertFalse(result['ok'])
            self.assertTrue(result['deferred_to_route'])
            self.assertEqual(self.panel.events, [])
        self.assertFalse(self.coordinator.powered)
        self.assertTrue(self.coordinator.restoration_status()['held_dark'])

    def test_silent_stored_activation_is_replaced_by_one_lossless_budgeted_upload(self):
        self.exit()
        result = self.restore()
        self.assertTrue(result['synchronized'])
        self.assertTrue(result['wrote'])
        self.assertEqual(self.panel.empty_ends, 0)
        self.assertEqual(self.panel.commits, 1)
        self.assertTrue(result['transfer']['restore_repacked'])
        self.assertEqual(result['transfer']['restore_begin_status'], 1)
        self.assertEqual(result['transfer']['begin_status'], 1)
        self.assertEqual(result['transfer']['source_begin_status'], 2)
        self.assertFalse(result['transfer']['already_stored'])
        self.assertEqual(self.panel.visible, repack_for_restore(HOME))
        end = next(i for i, e in enumerate(self.panel.events) if e[:2] == (1, 11))
        on = self.panel.events.index((1, 1, b'\x01'))
        self.assertLess(end, on)
        self.assertEqual(self.coordinator.flash.session['confirmed'], 1)
        event = self.coordinator.state['observability']['journal'][-1]
        self.assertEqual(event['sha256'], hashlib.sha256(self.panel.stored).hexdigest())
        self.assertEqual(event['size_bytes'], len(self.panel.stored))
        self.assertEqual(event['source_sha256'], hashlib.sha256(HOME).hexdigest())
        self.assertFalse(self.coordinator.restoration_status()['pending'])
        # Stable normal routes reuse the ACTUAL wire representation, not the
        # canonical source, so this workaround cannot cause a second write.
        self.restore()
        self.assertEqual(self.panel.commits, 1)
        self.assertEqual(self.panel.empty_ends, 0)

    def test_fresh_normal_crc_uses_one_ordinary_body_without_repacking(self):
        self.panel.stored = encode_frame(bytes([0, 0, 3])*3456)
        self.exit()
        result = self.restore()
        self.assertTrue(result['synchronized'])
        self.assertNotIn('restore_repacked', result['transfer'])
        self.assertEqual(self.panel.stored, HOME)
        self.assertEqual(self.panel.commits, 1)

    def test_lost_final_ack_stays_dark_and_does_not_retry_same_body_or_power(self):
        self.exit(); self.panel.lose_end = True
        result = self.restore()
        self.assertFalse(result['synchronized'])
        self.assertTrue(result['sent_unconfirmed'])
        self.assertFalse(self.coordinator.powered)
        count = len(self.panel.events)
        for _ in range(30):
            self.assertTrue(self.restore()['retry_suppressed'])
            self.assertTrue(self.coordinator.set_power(True, 'automatic power recovery')['deferred_to_route'])
        self.assertEqual(len(self.panel.events), count)
        self.assertEqual(self.panel.commits, 1)
        self.assertEqual(self.coordinator.flash.session['confirmed'], 0)
        self.assertEqual(self.coordinator.flash.session['uncertain'], 1)
        self.assert_no_on()
        # A real USB continuity change permits a new justified attempt.
        self.panel.token = 'usb-2'; self.panel.lose_end = False
        self.assertTrue(self.restore()['synchronized'])

    def test_negative_end_or_second_stored_reply_never_powers_old_picture_on(self):
        for field in ('refuse_end', 'all_stored'):
            with self.subTest(field=field):
                self.exit(); setattr(self.panel, field, True)
                result = self.restore()
                self.assertFalse(result['synchronized'])
                self.assert_no_on()
                self.assertEqual(self.panel.empty_ends, 0)
                setattr(self.panel, field, False)

    def test_cancel_during_body_never_finalizes_or_turns_on(self):
        self.exit()
        cancelled = [False]
        self.panel.after_chunk = lambda: cancelled.__setitem__(0, True)
        result = self.coordinator.synchronize_scene(HOME, 'weather', 'current',
            peak_load=.1, reason='current-route-restore', cancelled=lambda: cancelled[0])
        self.assertTrue(result['superseded'])
        self.assertEqual(self.panel.commits, 0)
        self.assert_no_on()

    def test_cancel_at_commit_ack_never_powers_on_obsolete_route(self):
        self.exit()
        cancelled = [False]
        self.panel.after_end = lambda: cancelled.__setitem__(0, True)
        result = self.coordinator.synchronize_scene(HOME, 'weather', 'current',
            peak_load=.1, reason='current-route-restore', cancelled=lambda: cancelled[0])
        self.assertTrue(result['superseded'])
        self.assertEqual(self.panel.commits, 1)
        self.assert_no_on()

    def test_missing_off_ack_keeps_intent_without_claiming_panel_is_off(self):
        self.panel.lose_off = True
        self.coordinator.powered = True
        result = self.coordinator.set_power(False, 'screensaver-exit')
        self.assertFalse(result['ok'])
        status = self.coordinator.restoration_status()
        self.assertTrue(status['held_dark'])
        self.assertFalse(status['power_off_confirmed'])
        self.panel.events.clear()
        self.assertTrue(self.coordinator.set_power(True, 'automatic power recovery')['deferred_to_route'])
        self.assertEqual(self.panel.events, [])
        self.panel.lose_off = False
        self.assertTrue(self.restore()['synchronized'])

    def test_read_only_handoff_state_does_not_refuse_an_acknowledged_transfer(self):
        self.coordinator.powered = True
        with patch.object(self.coordinator, '_save_state', side_effect=OSError('read-only')):
            result = self.coordinator.synchronize_scene(encode_frame(bytes((10,20,30))*3456), 'screensaver', 'external',
                peak_load=.1, delegated=True)
        self.assertTrue(result['synchronized'])
        self.assertTrue(any(e[:2] == (1, 4) for e in self.panel.events))
        self.assertEqual(self.panel.commits, 1)

    def test_failed_optional_save_keeps_live_recovery_state_without_blocking_delegation(self):
        with patch.object(self.coordinator, '_save_state', side_effect=OSError('read-only')):
            self.assertTrue(self.coordinator.set_power(False, 'screensaver-exit')['ok'])
            self.assertTrue(self.coordinator.state['delegated_display_pending'])
            self.coordinator.powered = True
            self.panel.events.clear()
            result = self.coordinator.synchronize_scene(encode_frame(bytes((10,20,30))*3456), 'screensaver', 'external',
                peak_load=.1, delegated=True)
        self.assertTrue(result['synchronized'])
        self.assertTrue(any(e[:2] == (1, 4) for e in self.panel.events))

    def test_negative_final_ack_suppresses_automatic_body_retries(self):
        self.exit(); self.panel.refuse_end = True
        self.assertFalse(self.restore()['synchronized'])
        count = len(self.panel.events)
        result = self.restore()
        self.assertTrue(result['retry_suppressed'])
        self.assertFalse(result['sent_unconfirmed'])
        self.assertEqual(len(self.panel.events), count)
        self.assert_no_on()

    def test_pending_handoff_survives_plugin_restart_and_success_clears_it(self):
        self.exit()
        self.coordinator = self.new_coordinator()
        self.assertTrue(self.coordinator.restoration_status()['pending'])
        self.assertTrue(self.coordinator.set_power(True, 'automatic resume')['deferred_to_route'])
        self.assertTrue(self.restore()['synchronized'])
        self.coordinator = self.new_coordinator()
        self.assertFalse(self.coordinator.restoration_status()['pending'])

    def test_lab147_unconfirmed_journal_is_migrated_without_claiming_visibility(self):
        path = self.root/'panel.json'
        path.write_text(json.dumps({'schema': 2, 'writes': 8, 'observability': {'journal': [
            {'scene': 'weather', 'outcome': 'written'},
            {'scene': 'screensaver', 'outcome': 'unconfirmed'},
            {'scene': 'weather', 'outcome': 'unconfirmed'}]}}))
        self.coordinator = self.new_coordinator()
        self.assertEqual(self.coordinator.state['writes'], 8)
        self.assertTrue(self.coordinator.restoration_status()['held_dark'])
        self.assertTrue(self.restore()['synchronized'])
        self.assertEqual(self.panel.empty_ends, 0)

    def test_new_current_game_route_replaces_failed_weather_without_old_snapshot(self):
        self.exit(); self.panel.lose_end = True
        self.restore()
        self.panel.lose_end = False
        artwork = encode_frame(bytes([1, 1, 6])*3456)
        result = self.restore(artwork, 'artwork-dashboard')
        self.assertTrue(result['synchronized'])
        self.assertEqual(self.panel.visible, artwork)
        self.assertFalse(self.coordinator.restoration_status()['held_dark'])

    def test_manual_off_stays_off_and_ordinary_manual_on_remains_usable(self):
        self.assertTrue(self.coordinator.set_power(False, 'Decky control')['ok'])
        self.assertFalse(self.coordinator.powered)
        self.assertTrue(self.coordinator.set_power(True, 'Decky control')['ok'])

    def test_engine_releases_stale_on_job_so_current_route_can_run(self):
        f = test_native_clock.NativeSceneTests(); f.setUp(); self.addCleanup(f.doCleanups)
        engine, c = f.engine, f.faceplate
        c.set_power(False, 'screensaver-exit'); f.calls.clear()
        engine._faceplate_power_target = True
        engine._faceplate_power_retry_at = 0
        self.assertFalse(engine._service_faceplate_power_retry())
        self.assertIsNone(engine._faceplate_power_target)
        self.assertTrue(engine._faceplate_resume_requested)
        self.assertTrue(engine._faceplate_power_status['deferred_to_route'])
        self.assertNotIn(protocol.power(True), f.calls)
        engine._reconcile_faceplate('periodic')
        self.assertEqual(len([p for p in f.calls if p[2:4] == b'\x01\x05']), 1)
        self.assertTrue(c.last_synchronized)
        self.assertFalse(c.restoration_status()['held_dark'])

    def test_later_current_route_receipt_updates_old_unconfirmed_diagnostic(self):
        f = test_broker_adapter.BrokerAdapterTests(); f.setUp(); self.addCleanup(f.tearDown)
        f.start(); f.adapter.cancel('operation'); f.adapter.restore('operation', f.report); f.wait()
        f.adapter.normal_completed({'sent_unconfirmed': True})
        self.assertEqual(f.adapter.diagnostic_snapshot()['normal_route_restoration']['state'], 'unconfirmed')
        f.adapter.normal_completed({'synchronized': True})
        trace = f.adapter.diagnostic_snapshot()['normal_route_restoration']
        self.assertEqual(trace['state'], 'confirmed')
        self.assertTrue(trace['late_current_route_receipt'])

    def test_broker_and_engine_diagnostics_expose_the_same_guard(self):
        f = test_broker_adapter.BrokerAdapterTests(); f.setUp(); self.addCleanup(f.tearDown)
        f.engine.faceplate = self.coordinator
        self.coordinator.set_power(False, 'screensaver-exit')
        snapshot = f.adapter.diagnostic_snapshot()
        state = snapshot['normal_route_restoration']['coordinator']
        self.assertEqual(state, self.coordinator.restoration_status())
        self.assertTrue(state['power_off_confirmed'])
        self.assertEqual(state['physical_playback'], 'not-measured')


class LosslessRepackTests(unittest.TestCase):
    def test_all_compressed_data_and_extension_bytes_are_preserved(self):
        from signalbar.faceplate.gif_transform import _subblocks
        def streams(data):
            offset = 13 + 3*(1 << ((data[10] & 7) + 1)); result = []
            while data[offset] != 0x3b:
                if data[offset] == 0x21:
                    _, end = _subblocks(data, offset + 2)
                    result.append(('extension', data[offset:end])); offset = end
                else:
                    head = data[offset:offset+11]
                    compressed, offset = _subblocks(data, offset+11)
                    result.append((head, compressed))
            return result
        for count in (1, 2, 80, 360):
            frames = [bytes([i % 2, (i+1) % 2])*1728 for i in range(count)]
            source = gif.encode(64, 54, [(0,0,0), (50,0,50)], frames,
                                [11+i % 7 for i in range(count)])
            result = repack_for_restore(source)
            self.assertNotEqual((len(source), zlib.crc32(source)), (len(result), zlib.crc32(result)))
            self.assertEqual(source[:19], result[:19])
            self.assertEqual(streams(source), streams(result))
            self.assertLess(abs(len(source)-len(result)), 50)

    def test_pillow_independent_decode_preserves_exact_pixels_frames_and_durations(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('optional independent Pillow decoder unavailable')
        def decode(data):
            image = Image.open(io.BytesIO(data)); frames = []
            for n in range(image.n_frames):
                image.seek(n); frames.append((image.convert('RGB').tobytes(), image.info.get('duration')))
            return frames, image.info.get('loop')
        self.assertEqual(decode(HOME), decode(repack_for_restore(HOME)))

    def test_native_static_gif87a_remains_supported_without_header_changes(self):
        static = encode_frame(bytes([1, 2, 4])*3456)
        source = b'GIF87a' + static[6:]
        self.assertEqual(repack_for_restore(source)[:6], b'GIF87a')

    def test_real_shipped_assets_survive_independent_decode_unchanged(self):
        try:
            from PIL import Image, ImageSequence
        except ImportError:
            self.skipTest('optional independent Pillow decoder unavailable')
        assets = Path(__file__).resolve().parents[2]/'assets'
        # Real Weather/Gabe assets exercise production palettes and timing,
        # not only a flat synthetic two-colour frame.
        paths = [Path(__file__).resolve().parents[1]/'fixtures/restore-multicolour-reference.gif']
        paths.extend(sorted(assets.glob('**/rain-bluewater-64x54.gif')))
        self.assertTrue(all(p.is_file() for p in paths))
        def frames(data):
            image = Image.open(io.BytesIO(data))
            return [(f.convert('RGB').tobytes(), f.info.get('duration'))
                    for f in ImageSequence.Iterator(image)]
        for path in paths:
            source = path.read_bytes()
            self.assertEqual(frames(source), frames(repack_for_restore(source)))

    def test_rejects_malformed_oversized_and_non_native_gifs(self):
        bad = [b'', b'GIF89a', HOME[:-1], HOME+b'junk', HOME[:30],
               HOME[:6]+b'\x41\x00'+HOME[8:], HOME[:6]+b'x'*2100000]
        for data in bad:
            with self.subTest(size=len(data)):
                with self.assertRaises(GifTransformError): repack_for_restore(data)


if __name__ == '__main__': unittest.main()
