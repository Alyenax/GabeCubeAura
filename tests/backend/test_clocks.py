"""Host scheduling and channel contracts; no hardware claims."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from signalbar.faceplate.clocks import ClockPacket,ClockRuntime,catalog,is_night
from signalbar.faceplate.routing import FaceplatePreferencesStore


class ClockContracts(unittest.TestCase):
    def test_standard_clock_provider_cannot_encode_invalid_frames_or_timeline(self):
        good=bytes(64*54*3)
        for frames,delays in [((b'bad',),(100,)),((good,),(0,)),((good,),(25001,)),((good,),()),((good,),(1.5,))]:
            with self.subTest(delays=delays), self.assertRaisesRegex(ValueError,'Invalid native clock timeline'):
                ClockPacket(frames,delays,'test').gif()
    def test_channel_catalog_cannot_be_unlocked_by_update_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'assets/clocks-lab';p.mkdir(parents=True)
            (p/'catalog.json').write_text(json.dumps([{'id':'private-study','label':'Study'}]))
            self.assertEqual([],catalog('1.5.1-beta.22',root))
            self.assertEqual([],catalog('1.5.1-beta.28',root))
            self.assertEqual([],catalog('1.5.1-lab.287',root))
            self.assertEqual([],catalog('1.5.1-beta.29',root))
            self.assertEqual([],catalog('1.5.1-lab.288',root))
            self.assertEqual([],catalog('1.5.1',root))
            self.assertEqual([],catalog('1.5.1-test.3',root))
            self.assertEqual('private-study',catalog('1.5.1-lab.264',root)[0]['id'])

    def test_standards_can_extend_shared_catalog_without_private_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'assets/clocks';p.mkdir(parents=True)
            (p/'catalog.json').write_text(json.dumps([{'id':'standard','label':'Standard'}]))
            self.assertEqual(False,catalog('1.5.1-beta.22',root)[0]['private'])

    def test_routes_persist_independently_and_revision_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FaceplatePreferencesStore(Path(folder)/'prefs.json')
            p=store.update(home_scene='clock',game_scene='clock',expected_revision=0)
            self.assertEqual('clock',store.read().game_scene)
            self.assertEqual(1,p.revision)

    def test_solar_selector_and_unconfigured_fallback(self):
        self.assertTrue(is_night(0,{'enabled':True,'available':True,'is_night':True}))
        self.assertFalse(is_night(0,{'enabled':True,'available':True,'is_night':False}))
        with patch('signalbar.faceplate.clocks.datetime') as dt:
            dt.fromtimestamp.return_value.hour=22
            self.assertTrue(is_night(0,{'enabled':False,'available':True,'is_night':False}))
            dt.fromtimestamp.return_value.hour=12
            self.assertFalse(is_night(0,{}))

    @patch('signalbar.faceplate.clocks.require_clock',return_value={})
    def test_no_completion_drift_across_hundreds_of_cycles(self,_):
        runtime=ClockRuntime();now=240*1000+10
        p=runtime.plan('standard','home',now,False,monotonic=now)
        for i in range(300):
            target=p['display_at']
            runtime.receipt(p,{'synchronized':True,'upload_ms':4000,'clock_bytes':30000},target+.17)
            next_boundary=runtime.active['renew_at']
            self.assertEqual(0,next_boundary%240)
            self.assertIsNone(runtime.plan('standard','home',next_boundary-13,False,monotonic=next_boundary-13))
            p=runtime.plan('standard','home',next_boundary-12,False,monotonic=next_boundary-12)
            self.assertEqual(next_boundary,p['display_at'])

    @patch('signalbar.faceplate.clocks.require_clock',return_value={})
    def test_uncertain_ack_and_stale_completion_cannot_claim_new_clock(self,_):
        r=ClockRuntime();first=r.plan('standard','home',1000,False,monotonic=1000)
        r.receipt(first,{'sent_unconfirmed':True},first['display_at'])
        self.assertIsNone(r.active);self.assertEqual('unconfirmed',r.state)
        newer=r.plan('other','game',1100,False,monotonic=1100)
        r.receipt(first,{'synchronized':True},1101)
        self.assertEqual(newer,r.pending);self.assertIsNone(r.active)

    @patch('signalbar.faceplate.clocks.require_clock',return_value={})
    def test_sleep_or_ntp_jump_discards_pending_timeline(self,_):
        r=ClockRuntime();old=r.plan('standard','home',1000,False,monotonic=10)
        fresh=r.plan('standard','home',3000,False,monotonic=11)
        self.assertGreater(fresh['display_at'],old['end_at'])
        self.assertIsNone(r.active)


if __name__=='__main__':unittest.main()
