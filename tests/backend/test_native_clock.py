"""Native 0x05 scene: simulated serial ACKs, never a physical panel test."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import itertools
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from signalbar.backend import Engine
from signalbar.models import GameState
from signalbar.settings import SettingsStore
from signalbar.faceplate import protocol
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.flash import CAPACITY, default_manager, install_manager, UploadDeferred
from signalbar.faceplate.routing import FaceplatePreferencesStore, FaceplateSceneRouter
from signalbar.faceplate.transport import Link, LinkBusy, LinkError, ReplyTimeout


class ProtocolTests(unittest.TestCase):
    def test_exact_frame_crc_and_seven_payload_bytes(self):
        packet = protocol.native_clock(datetime(2026, 10, 13, 16, 55, 10, tzinfo=timezone.utc))
        self.assertEqual(packet[:6], b'DY\x01\x05\x00\x07')
        self.assertEqual(packet[6:-2], bytes.fromhex('07 ea 09 0c 10 37 0a'))
        self.assertEqual(len(packet), 15)
        self.assertEqual(protocol.crc16_kermit(packet[:-2]), int.from_bytes(packet[-2:], 'big'))
        replies, junk = protocol.parse(bytearray(packet))
        self.assertFalse(junk)
        self.assertEqual(replies[0].payload, packet[6:-2])

    def test_calendar_boundaries_midnight_and_endianness(self):
        for date in [(1, 1, 1), (255, 12, 31), (256, 1, 1), (2000, 2, 29),
                     (2024, 2, 29), (2026, 2, 28), (2026, 3, 1), (9999, 12, 31)]:
            with self.subTest(date=date):
                year, month, day = date
                payload = protocol.native_clock(datetime(*date, tzinfo=timezone.utc))[6:-2]
                self.assertEqual(payload, year.to_bytes(2, 'big') + bytes((month-1, day-1, 0, 0, 0)))
        for kwargs in [dict(year=2025, month=2, day=29), dict(year=2026, month=13, day=1),
                       dict(year=0, month=1, day=1), dict(year=2026, month=1, day=0)]:
            with self.assertRaises(ValueError):
                protocol.native_clock(datetime(**kwargs, tzinfo=timezone.utc))

    def test_rejects_naive_invalid_objects_and_broken_tzinfo(self):
        for value in [None, '2026-10-17', b'1234567', 2026]:
            with self.assertRaises(TypeError): protocol.native_clock(value)
        with self.assertRaises(ValueError): protocol.native_clock(datetime(2026, 1, 1))
        from datetime import tzinfo
        class NoOffset(tzinfo):
            def utcoffset(self, value): return None
        with self.assertRaises(ValueError):
            protocol.native_clock(datetime(2026, 1, 1, tzinfo=NoOffset()))

    def test_encodes_given_local_wall_fields_including_dst_fold(self):
        paris = ZoneInfo('Europe/Paris')
        for fold in (0, 1):
            local = datetime(2026, 10, 25, 2, 30, tzinfo=paris, fold=fold)
            self.assertEqual(protocol.native_clock(local)[10:13], b'\x02\x1e\x00')
        india = datetime(2026, 10, 17, 0, 1, 2, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        self.assertEqual(protocol.native_clock(india)[10:13], b'\x00\x01\x02')


class TransportTests(unittest.TestCase):
    def test_exact_dispatch_and_strict_ack(self):
        link = Link('/test')
        when = datetime.now().astimezone()
        link.command = Mock(return_value=protocol.Reply(1, 5, b'\x01'))
        link.synchronize_native_clock(when)
        link.command.assert_called_once_with(protocol.native_clock(when), timeout=1.0, retries=1)
        for reply in [None, protocol.Reply(1, 5, b''), protocol.Reply(1, 5, b'\x00'),
                      protocol.Reply(1, 5, b'\x02'), protocol.Reply(1, 5, b'\x01\x00'),
                      protocol.Reply(2, 5, b'\x01'), protocol.Reply(1, 4, b'\x01')]:
            link.command.return_value = reply
            with self.assertRaises(LinkError): link.synchronize_native_clock(when)

    def test_timeout_never_resends_and_ignores_unrelated_reply(self):
        link = Link('/test')
        link.write = Mock()
        link.read_replies = Mock(return_value=[])
        # Exercise the real bounded command loop without waiting a whole second.
        with patch('signalbar.faceplate.transport.time.monotonic', side_effect=itertools.count(0, .3)):
            with self.assertRaises(ReplyTimeout): link.synchronize_native_clock(datetime.now().astimezone())
        link.write.assert_called_once()
        link = Link('/test'); link.write = Mock()
        link.read_replies = Mock(side_effect=[[protocol.Reply(1, 4, b'\x01')], [protocol.Reply(1, 5, b'\x01')]])
        link.synchronize_native_clock(datetime.now().astimezone())
        link.write.assert_called_once()

    def test_existing_exclusive_port_lock_applies(self):
        import errno
        link = Link('/test')
        with patch('signalbar.faceplate.transport.port_owner_details', return_value=[]), \
             patch('signalbar.faceplate.transport.os.open', return_value=42), \
             patch('signalbar.faceplate.transport.os.close') as close, \
             patch('signalbar.faceplate.transport.fcntl.flock', side_effect=OSError(errno.EAGAIN, 'busy')):
            with self.assertRaises(LinkBusy): link.open()
            close.assert_called_once_with(42)


class NativeSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.calls = []; self.error = None; self.token = 'usb-session-1'; self.available = True
        self.offset = 0
        self.addCleanup(install_manager, default_manager())
        owner = self
        class Panel(Link):
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def write(self, data): owner.calls.append(data)
            def command(self, data, **kwargs):
                owner.calls.append(data)
                if data[3] == 5 and owner.error: raise owner.error
                return protocol.Reply(data[2], data[3], b'\x01')
        self.faceplate = FaceplateCoordinator(self.root/'assets', self.root/'panel.json',
            port_finder=lambda: '/test' if self.available else None,
            identity_reader=lambda _: self.token, link_factory=Panel)
        self.faceplate.configure(True, 100)
        self.settings = SettingsStore(str(self.root/'settings.json'))
        self.settings.update({'signalbar_enabled': True, 'faceplate_lab_enabled': True})
        self.prefs = FaceplatePreferencesStore(self.root/'routes.json')
        self.prefs.update(home_scene='native-clock')
        self.engine = Engine(self.settings, str(self.root/'cache.json'),
            faceplate=self.faceplate, faceplate_preferences=self.prefs)
        self.addCleanup(self.engine.stop)
        # Synchronous queue adapter exercises the real handler deterministically.
        self.engine.faceplate_worker = Mock()
        self.engine.faceplate_worker.status.return_value = {'busy': False, 'queued': False}
        self.engine.faceplate_worker.submit.side_effect = self.dispatch
        self.engine._render_faceplate_scene = Mock(side_effect=AssertionError('native must not render'))
        self.engine._write_faceplate_runtime_status = Mock()
        self.engine._reconcile_cinema = Mock(return_value=False)

    def dispatch(self, scene, payload, metadata):
        self.result = self.engine._handle_faceplate_scene({'payload': payload, 'metadata': metadata,
            '_cancelled': threading.Event()})
        return 1

    def activate(self, key='stable', reason='route'):
        return self.faceplate.synchronize_native_clock(sync_key=key, reason=reason)

    def activations(self): return [p for p in self.calls if p[2:4] == b'\x01\x05']

    def test_stable_home_does_not_render_budget_or_send_per_second_minute_or_midnight(self):
        with patch.object(self.faceplate.flash, 'preflight', side_effect=AssertionError('GIF budget')), \
             patch.object(self.faceplate.flash, 'delay', side_effect=AssertionError('GIF budget')):
            self.engine._reconcile_faceplate('routing-change', force=True)
            for _ in range(180): self.engine._reconcile_faceplate()
            self.engine._reconcile_faceplate('unrelated-theme-change', force=True)
        self.assertEqual(len(self.activations()), 1)
        self.assertEqual(self.faceplate.writes_session, 0)
        self.assertEqual(self.faceplate.uploads_session, 0)
        self.assertEqual(self.faceplate.flash.session['confirmed'], 0)
        self.assertEqual(self.faceplate.native_clock['confirmed_session'], 1)
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'], 'native-clock')
        self.engine._render_faceplate_scene.assert_not_called()
        self.assertNotIn(3, [p[3] for p in self.calls])
        self.assertEqual(set(p[3] for p in self.calls), {1, 2, 5})

    def test_local_system_timezone_is_sampled_near_send(self):
        old = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'Asia/Kolkata'; time.tzset()
            before = datetime.now().astimezone()
            self.assertTrue(self.activate()['synchronized'])
            payload = self.activations()[0][6:-2]
            self.assertEqual(tuple(payload[2:5]), (before.month-1, before.day-1, before.hour))
            self.assertTrue(self.faceplate.native_clock['last_success_at'].endswith('+05:30'))
        finally:
            if old is None: os.environ.pop('TZ', None)
            else: os.environ['TZ'] = old
            time.tzset()

    def test_timeout_and_io_failure_are_unconfirmed_without_retry_storm(self):
        for error in (ReplyTimeout('no reply to 0x05'), OSError('USB disconnected')):
            self.faceplate._native_attempt = None; self.error = error
            first = self.activate()
            for _ in range(50): result = self.activate()
            self.assertTrue(first['sent_unconfirmed']); self.assertTrue(result['unchanged'])
            self.assertFalse(self.faceplate.last_synchronized)
        self.assertEqual(len(self.activations()), 2)
        self.assertEqual(self.faceplate.native_clock['confirmed_session'], 0)
        self.assertEqual(self.faceplate.writes_session, 0)

    def test_engine_unconfirmed_does_not_commit_or_retry_after_sixty_seconds(self):
        self.error = ReplyTimeout('no reply to type=0x01 cmd=0x05')
        self.engine._reconcile_faceplate(force=True)
        self.assertEqual(self.engine.faceplate_router.status()['preparation']['state'], 'unconfirmed')
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'], '')
        for _ in range(100): self.engine._reconcile_faceplate()
        self.assertEqual(len(self.activations()), 1)

    def test_rotation_disabled_power_and_cancellation_never_send_clock(self):
        self.faceplate.rotate_180 = True
        self.assertIn('rotate', self.activate()['error'])
        self.faceplate.rotate_180 = False; self.faceplate.enabled = False
        self.activate(); self.faceplate.enabled = True; self.faceplate.powered = False
        self.activate(); self.faceplate.powered = None
        self.faceplate.synchronize_native_clock(sync_key='x', cancelled=lambda: True)
        self.assertFalse(self.calls)
        self.engine._faceplate_suspended = True
        self.assertEqual(self.engine._reconcile_faceplate(), 0)
        self.assertFalse(self.calls)

    def test_concurrent_same_key_and_forced_events_are_coalesced_under_lock(self):
        threads = [threading.Thread(target=self.activate) for _ in range(20)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3); self.assertFalse(thread.is_alive())
        self.assertEqual(len(self.activations()), 1)
        self.assertEqual(len([p for p in self.calls if p[3] == 2]), 1)

    def test_usb_identity_change_and_power_cycle_reactivate_once(self):
        self.activate(); self.token = 'usb-session-2'
        self.activate(); self.activate()
        self.faceplate.set_power(False); self.faceplate.set_power(True)
        self.activate(); self.activate()
        self.assertEqual(len(self.activations()), 3)

    def test_pending_stale_ticket_or_cancelled_generation_cannot_replace_new_route(self):
        ticket = self.engine.faceplate_router.reconcile(game_running=False)
        self.prefs.update(home_scene='weather')
        self.engine.faceplate_router.reconcile(game_running=False)
        result = self.engine._handle_faceplate_scene({'payload': {'kind': 'native-clock', 'ticket': ticket}})
        self.assertTrue(result['superseded']); self.assertFalse(self.activations())

    def test_actual_game_or_companion_cinema_replacement_then_home_clock(self):
        self.engine._reconcile_faceplate(force=True)
        data = encode_frame(bytes([1, 2, 3]) * (64*54))
        for scene in ('artwork', 'gabe', 'cinema', 'dashboard'):
            with patch('signalbar.faceplate.transport.time.sleep'):
                result = self.faceplate.synchronize_scene(data, scene, scene, reason='restore')
            self.assertTrue(result['synchronized'])
            self.faceplate.flash.tokens = CAPACITY
            self.faceplate.flash.attempts.clear()
            self.engine._reconcile_faceplate('gabe-finished-current-route', force=True)
        self.assertEqual(len(self.activations()), 5)
        self.assertEqual(self.prefs.read().home_scene, 'native-clock')
        self.assertEqual(self.prefs.read().game_scene, 'artwork')

    def test_return_to_gif_requires_durable_admission_and_panel_begin_metadata(self):
        self.activate()
        data = encode_frame(bytes([1, 2, 3]) * (64*54))
        self.faceplate.flash.tokens = 0
        before = len(self.calls)
        with patch.object(self.faceplate.flash,'preflight',side_effect=UploadDeferred(60)):
            result = self.faceplate.synchronize_scene(data, 'dashboard', 'image')
        self.assertTrue(result['deferred']); self.assertEqual(len(self.calls), before)
        self.assertTrue(self.activate()['unchanged'])
        self.assertTrue(self.faceplate.last_synchronized)
        self.assertEqual(self.faceplate.delivery['scene'], 'native-clock')
        self.faceplate.flash.tokens = CAPACITY
        with patch('signalbar.faceplate.transport.time.sleep'):
            result = self.faceplate.synchronize_scene(data, 'dashboard', 'image')
        self.assertTrue(result['wrote'])  # panel answered 01: host cache cannot override
        self.assertEqual(self.faceplate.writes_session, 1)
        self.assertEqual(self.faceplate.native_clock['confirmed_session'], 1)

    def test_resume_and_reconnect_route_recovery(self):
        self.engine._reconcile_faceplate(force=True)
        self.engine.faceplate_worker.configure = Mock()
        self.engine._apply_faceplate_power = Mock(side_effect=lambda *args, **kwargs: self.faceplate.set_power(args[0]))
        self.engine.resume_faceplate()
        self.engine._reconcile_faceplate()
        self.assertEqual(len(self.activations()), 2)
        self.token = 'usb-after-reconnect'
        self.engine._reconcile_faceplate()
        self.engine._reconcile_faceplate()
        self.assertEqual(len(self.activations()), 3)

    def test_epoch_jump_offset_change_dst_and_midnight_continuity(self):
        probe = self.engine._faceplate_continuity
        hardware = {'available': True, 'port': '/test', 'device_identity': self.token}
        def observe(wall, mono, offset=3600):
            return probe(wall_clock=wall, monotonic_clock=mono, hardware=hardware,
                         local_offset=timedelta(seconds=offset))[0]
        self.assertEqual(observe(1000, 100), '')
        self.assertEqual(observe(87400, 86500), '')  # midnight/day rollover
        self.assertEqual(observe(87401, 86501, 7200), 'local-timezone-change')
        self.assertEqual(observe(87402, 86502, 3600), 'local-timezone-change')
        self.assertEqual(observe(87500, 86503), 'clock-discontinuity')
        self.assertEqual(observe(87000, 86504), 'clock-discontinuity')

    def test_game_route_and_return_are_integrated_without_changing_preferences(self):
        self.engine._reconcile_faceplate(force=True)
        data = encode_frame(bytes([1, 2, 3]) * (64*54))
        def artwork(*_):
            with patch('signalbar.faceplate.transport.time.sleep'):
                result = self.faceplate.synchronize_scene(data, 'artwork', 'art')
            return {**result, 'found': result.get('synchronized', False)}
        self.engine._synchronize_artwork_with_projection = artwork
        self.engine._game = GameState(620, 'Portal 2')
        self.engine._reconcile_faceplate('automatic-game-change', force=True)
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'], 'artwork')
        self.engine._game = GameState()
        self.engine._reconcile_faceplate('automatic-game-change', force=True)
        self.assertEqual(self.engine.faceplate_router.status()['effective_scene'], 'native-clock')
        self.engine._reconcile_faceplate()
        self.assertEqual(len(self.activations()), 2)
        self.assertEqual(self.prefs.read().game_scene, 'artwork')

    def test_uncertain_stored_gif_display_invalidates_native_receipt(self):
        self.activate()
        owner = self
        original = self.faceplate.link_factory
        class LostStoredDisplayACK(original):
            def command(self, packet, **kwargs):
                if packet[3] == protocol.CMD_GIF_BEGIN:
                    owner.calls.append(packet)
                    return protocol.Reply(1, protocol.CMD_GIF_BEGIN, b'\x02')
                if packet[3] == protocol.CMD_GIF_END:
                    owner.calls.append(packet)
                    raise ReplyTimeout('stored display ACK missing')
                return super().command(packet, **kwargs)
        self.faceplate.link_factory = LostStoredDisplayACK
        data = encode_frame(bytes([1, 2, 3]) * (64*54))
        result = self.faceplate.synchronize_scene(data, 'dashboard', 'stored')
        self.assertFalse(result['synchronized'])
        self.faceplate.link_factory = original
        self.assertTrue(self.activate()['attempted'])
        self.assertEqual(len(self.activations()), 2)

    def test_actual_offset_and_clock_events_reactivate_once_per_change(self):
        self.engine._reconcile_faceplate(force=True)
        for event in ('local-timezone-change', 'clock-discontinuity'):
            with patch.object(self.engine, '_faceplate_continuity', return_value=(event, False)):
                self.engine._reconcile_faceplate()
            with patch.object(self.engine, '_faceplate_continuity', return_value=('', False)):
                self.engine._reconcile_faceplate('overlapping-event', force=True)
                self.engine._reconcile_faceplate()
        self.assertEqual(len(self.activations()), 3)
        self.assertEqual(self.faceplate.native_clock['reason'], 'clock-discontinuity')

    def test_stale_request_waiting_for_serial_lock_is_cancelled_before_transmit(self):
        gate = threading.Event(); result = []
        self.faceplate.lock.acquire()
        thread = threading.Thread(target=lambda: result.append(
            self.faceplate.synchronize_native_clock(sync_key='old', cancelled=gate.is_set)))
        thread.start(); gate.set(); self.faceplate.lock.release(); thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertTrue(result[0]['superseded'])
        self.assertFalse(self.calls)

    def test_negative_ack_is_failure_and_stays_inert_on_retry(self):
        from signalbar.faceplate.transport import NativeClockRejected
        self.error = NativeClockRejected('faceplate refused native clock (invalid 0x05 ACK)')
        self.assertFalse(self.activate()['sent_unconfirmed'])
        self.assertEqual(self.faceplate.native_clock['state'], 'error')
        self.assertFalse(self.activate()['attempted'])
        self.assertEqual(len(self.activations()), 1)
        self.assertEqual(self.faceplate.native_clock['confirmed_session'], 0)

    def test_new_usb_session_reapplies_manual_brightness_before_power(self):
        self.activate(); self.calls.clear(); self.token = 'new-panel'
        self.activate()
        self.assertEqual(self.calls[0], protocol.brightness(70))
        self.assertEqual(self.calls[1], protocol.power(True))
        self.assertEqual(self.calls[2][3], protocol.CMD_NATIVE_CLOCK)

    def test_session_restart_resends_without_persisting_a_false_native_receipt(self):
        self.activate()
        self.faceplate.flush_statistics(force=True)
        other = FaceplateCoordinator(self.root/'assets', self.root/'panel.json',
            port_finder=lambda: '/test', identity_reader=lambda _: self.token,
            link_factory=self.faceplate.link_factory)
        other.configure(True, 100)
        other.synchronize_native_clock(sync_key='stable')
        self.assertEqual(len(self.activations()), 2)
        self.assertEqual(other.writes_session, 0)


class PreferenceTests(unittest.TestCase):
    def test_legacy_migration_keeps_both_routes_and_native_is_home_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'prefs.json'; store = FaceplatePreferencesStore(path)
            for schema in (1, 2):
                path.write_text(json.dumps({'schema': schema, 'revision': 12,
                                           'routes': {'home': 'weather', 'game': 'artwork-dashboard'}}))
                self.assertEqual(store.read().home_scene, 'weather')
                self.assertEqual(store.read().game_scene, 'artwork-dashboard')
                store.update(home_scene='native-clock')
                self.assertEqual(FaceplatePreferencesStore(path).read().home_scene, 'native-clock')
                with self.assertRaises(ValueError): store.update(game_scene='native-clock')
            router = FaceplateSceneRouter(store)
            home = router.reconcile(game_running=False); router.commit(home)
            self.assertEqual(router.reconcile(game_running=True).scene, 'artwork-dashboard')
            self.assertFalse(router.commit(home))
            self.assertEqual(router.reconcile(game_running=False).scene, 'native-clock')
            self.assertEqual(router.reconcile(game_running=False).generation, router.status()['generation'])
