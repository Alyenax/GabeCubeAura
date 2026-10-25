"""Real-report timing envelopes, repeated cycles and late evidence regressions."""
import unittest
from unittest.mock import patch
from signalbar.faceplate import protocol, timing
from signalbar.faceplate.transport import Link, gif_end_timeout, ReplyTimeout, GifCommitUnconfirmed
from signalbar.faceplate.flash import FlashWearProtection
import test_jsaux_broker_core as core_fixture
import test_screensaver_restore148 as serial_fixture


class Timing149Tests(unittest.TestCase):
    def test_known_reports_are_not_underestimated(self):
        for size, measured in ((147518, 17653), (68931, 9330), (52790, 6605)):
            self.assertGreater(timing.transfer_ms(size), measured)
        self.assertFalse(timing.admits(147518, 15000))
        self.assertTrue(timing.admits(80*1024, 15000))
        self.assertFalse(timing.admits(80*1024+1, 15000))
        self.assertFalse(timing.admits(65536, 5000))

    def test_model_is_monotonic_bounded_and_keeps_small_legacy_start(self):
        self.assertTrue(timing.admits(1024, 2500))
        for size in (1, 498, 4096, 16384, 65536, 81920, 147518, 196608):
            self.assertGreaterEqual(timing.transfer_ms(size+1), timing.transfer_ms(size))
            self.assertLessEqual(gif_end_timeout(size), 10)
        self.assertGreater(gif_end_timeout(147518), 6.0)
        with self.assertRaises(ValueError): timing.transfer_ms(0)

    def test_late_final_ack_waits_once_without_resending_end_or_body(self):
        link=Link('/test');link.flash_manager=FlashWearProtection()
        calls=[]
        def command(packet,**options):
            calls.append((packet[2],packet[3]))
            if packet[3]==11:
                self.assertEqual(options['retries'],1)
                # Model a 6.2s commit: the old 4.95s wait fails this trace.
                if options['timeout']<6.2:raise ReplyTimeout('late END')
            return protocol.Reply(packet[2],packet[3],b'\x01')
        link.command=command
        with patch('signalbar.faceplate.transport.time.sleep'):
            self.assertTrue(link.send_gif(b'x'*147518))
        self.assertEqual(calls.count((1,11)),1)
        self.assertEqual(calls.count((2,2)),297)
        self.assertEqual(link.flash_manager.session['confirmed'],1)

    def test_absent_final_ack_remains_unconfirmed_without_fallback_upload(self):
        link=Link('/test',transport_profile='auto');link.flash_manager=FlashWearProtection()
        calls=[]
        def command(packet,**options):
            calls.append((packet[2],packet[3]))
            if packet[3]==11:raise ReplyTimeout('lost END')
            return protocol.Reply(packet[2],packet[3],b'\x01')
        link.command=command
        with patch('signalbar.faceplate.transport.time.sleep'):
            with self.assertRaises(GifCommitUnconfirmed):link.send_gif(b'x'*65536)
        self.assertEqual(calls.count((1,4)),1)
        self.assertEqual(calls.count((1,11)),1)
        self.assertEqual(link.flash_manager.session['confirmed'],0)

    def fixture(self):
        f=core_fixture.CoreTests();f.setUp();self.addCleanup(f.tearDown);return f

    def test_oversized_collection_is_refused_before_reservation_or_usb(self):
        f=self.fixture();content,collection=f.content()
        # Only the actual immutable file's byte size is read by admission.
        from pathlib import Path
        sized=Path(f.temporary.name)/'sized-fixture.gif'
        sized.write_bytes(b'x'*147518)
        f.broker.contents[content]['path']=sized
        f.error('ALIGNMENT_EXPIRED','acquire_display',dict(
            content_id=content,collection_id=collection,mode='sync',
            activation_id='activation-1',session_id='session-1'))
        self.assertEqual(f.adapter.reservations,[])
        self.assertEqual(f.adapter.jobs,[])

    def test_three_broker_cycles_survive_old_start_deadline_after_confirmation(self):
        f=self.fixture()
        for n in range(3):
            activation='activation-'+str(n)
            f.adapter.state['steam'].update(activation_id=activation,activation_closed=False)
            lease=f.acquire('sync',activation_id=activation,session_id='session-'+str(n))
            f.ok('player_ready',f.ready(lease,'sync',deadline_mono_ms=f.broker.now_ms()+15000))
            f.clock.now+=6
            f.broker.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
            status=f.ok('operation_status',dict(operation_id=lease['operation_id']))
            f.ok('tv_started',dict(lease_id=lease['lease_id'],generation=lease['generation'],
                alignment_attempt_id=lease['alignment_attempt_id'],
                started_mono_ms=f.broker.now_ms(),candidate_id=status['candidate']['candidate_id'],
                outcome='software-coordinated'))
            # Stay active well past 15 seconds, with genuine renewed authority.
            for seq in range(1,21):
                f.clock.now+=1 if seq==1 else 2
                f.ok('renew_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],sequence=seq))
                f.broker.tick()
            self.assertEqual(f.broker.lease['lease_state'],'active')
            f.ok('release_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],reason='player-ended'))
            f.broker.report(lease['operation_id'],restore_state='confirmed')
            self.assertEqual(f.ok('status',{})['lease']['reason'],'PLAYER_ENDED')
        self.assertEqual(len(f.adapter.jobs),3)
        self.assertEqual(len(f.adapter.restorations),3)

    def test_late_missing_ack_keeps_original_expiry_reason(self):
        f=self.fixture();lease=f.acquire('sync')
        f.ok('player_ready',f.ready(lease,'sync',deadline_mono_ms=f.broker.now_ms()+15000))
        f.adapter.quiescent=False
        for seq in range(1,8):
            f.clock.now+=2
            f.ok('renew_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],sequence=seq))
            f.broker.tick()
        f.clock.now+=2
        f.broker.tick()
        f.broker.report(lease['operation_id'],transfer_state='unconfirmed',reason='USB_UNCONFIRMED')
        status=f.ok('operation_status',dict(operation_id=lease['operation_id']))
        self.assertEqual(status['reason'],'ALIGNMENT_EXPIRED')
        event=f.broker.diagnostic_snapshot()['attempts'][-1]
        self.assertEqual(event['revocation_reason'],'ALIGNMENT_EXPIRED')
        self.assertEqual(event['transfer_reason'],'USB_UNCONFIRMED')
        self.assertIsNone(status['candidate'])

    def test_three_real_transport_handoffs_return_to_current_home(self):
        f=serial_fixture.Restore148Tests();f.setUp();self.addCleanup(f.doCleanups)
        c=f.coordinator;c.powered=True
        external=serial_fixture.encode_frame(bytes([0,1,8])*3456)
        for n in range(3):
            shown=c.synchronize_scene(external,'screensaver','external',peak_load=.1,delegated=True)
            self.assertTrue(shown['synchronized'])
            self.assertTrue(c.set_power(False,'screensaver-exit')['ok'])
            self.assertTrue(f.restore()['synchronized'])
            self.assertEqual(f.panel.visible,serial_fixture.HOME)
            self.assertFalse(c.restoration_status()['held_dark'])
        self.assertEqual(f.panel.commits,6)
        self.assertEqual(f.panel.empty_ends,0)

    def test_late_successful_ack_never_revives_expired_alignment(self):
        f=self.fixture();lease=f.acquire('sync')
        f.ok('player_ready',f.ready(lease,'sync',deadline_mono_ms=f.broker.now_ms()+15000))
        f.adapter.quiescent=False
        for seq in (1,2):
            f.clock.now+=7
            f.ok('renew_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],sequence=seq))
        f.clock.now+=2;f.broker.tick()
        f.broker.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        state=f.ok('operation_status',dict(operation_id=lease['operation_id']))
        self.assertEqual(state['lease_state'],'expired')
        self.assertEqual(state['reason'],'ALIGNMENT_EXPIRED')
        self.assertEqual(state['transfer_state'],'confirmed')
        self.assertIsNone(state['candidate'])
        self.assertEqual(state['alignment_state'],'abandoned')
        self.assertEqual(len(f.adapter.restorations),1)


if __name__=='__main__':unittest.main()
