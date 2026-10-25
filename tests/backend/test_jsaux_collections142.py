"""Extended readiness does not extend authority or manufacture USB evidence."""
import json
import hashlib
import unittest
import test_jsaux_broker_core as fixture
from signalbar.faceplate.flash import FlashWearProtection,SCREENSAVER_CONTINUITY_SECONDS
from signalbar.faceplate.transport import coordinated_transfer_ms,timing_admission


class Collections142Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.CoreTests();self.f.setUp();self.addCleanup(self.f.tearDown)

    def test_ack_after_old_window_can_start_within_new_immutable_gate(self):
        f=self.f;lease=f.acquire('sync');gate=f.ready(lease,'sync',deadline_mono_ms=f.broker.now_ms()+15000)
        f.ok('player_ready',gate)
        f.clock.now+=6
        f.broker.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        state=f.ok('operation_status',dict(operation_id=lease['operation_id']))
        self.assertIsNotNone(state['candidate'])
        f.ok('tv_started',dict(lease_id=lease['lease_id'],generation=lease['generation'],
            alignment_attempt_id=lease['alignment_attempt_id'],started_mono_ms=f.broker.now_ms(),
            outcome='software-coordinated',candidate_id=state['candidate']['candidate_id']))
        self.assertEqual(len(f.adapter.jobs),1)
        evidence=f.broker.diagnostic_snapshot()['attempts'][-1]
        self.assertEqual(evidence['correlation_id'],hashlib.sha256(lease['operation_id'].encode()).hexdigest()[:16])
        self.assertEqual(evidence['transfer_state'],'confirmed');self.assertTrue(evidence['fresh_commit_ack'])
        self.assertNotIn(lease['operation_id'],json.dumps(evidence))
        self.assertEqual(evidence['optical_playback'],'not-measured')
        f.ok('release_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],reason='player-ended'))
        self.assertEqual(len(f.adapter.restorations),1)

    def test_oversized_wait_and_late_reply_never_reactivate_a_released_session(self):
        f=self.f;lease=f.acquire('sync')
        f.error('CLOCK_UNAVAILABLE','player_ready',f.ready(lease,'sync',deadline_mono_ms=f.broker.now_ms()+15001))
        f.ok('player_ready',f.ready(lease,'sync',deadline_mono_ms=f.broker.now_ms()+15000))
        f.ok('release_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],reason='player-ended'))
        f.broker.report(lease['operation_id'],transfer_state='confirmed',fresh_ack=True)
        state=f.ok('operation_status',dict(operation_id=lease['operation_id']))
        self.assertIsNone(state['candidate']);self.assertEqual(len(f.adapter.jobs),1)

    def test_largest_admitted_gif_has_bounded_start_estimate(self):
        self.assertFalse(timing_admission(196608,15000))
        self.assertTrue(timing_admission(81920,15000))
        self.assertGreater(coordinated_transfer_ms(196608),10000)
        self.assertFalse(timing_admission(196608,2500))

    def test_old_ten_minute_guard_migrates_without_clearing_usage_history(self):
        from pathlib import Path
        f=self.f;path=Path(f.temporary.name)/'flash.json'
        guard=FlashWearProtection(path,monotonic=f.clock,wall_clock=lambda:1000)
        guard.reserve_screensaver_attempt();guard.flush(force=True)
        data=json.loads(path.read_text());data['screensaver_remaining']=599
        path.write_text(json.dumps(data))
        recovered=FlashWearProtection(path,monotonic=f.clock,wall_clock=lambda:1000)
        self.assertLessEqual(recovered.screensaver_delay(),SCREENSAVER_CONTINUITY_SECONDS)
        self.assertEqual(recovered.total,guard.total)
