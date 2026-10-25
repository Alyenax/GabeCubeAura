from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from signalbar.faceplate.coordinator import FaceplateCoordinator


class PresenceTests(unittest.TestCase):
    def coordinator(self, folder):
        clock=[0.0]; port=['']
        panel=FaceplateCoordinator(Path(folder),Path(folder)/'state.json',
            monotonic=lambda:clock[0],port_finder=lambda:port[0])
        return panel,clock,port

    def test_never_seen_disconnected_busy_serial_and_exact_ten_minute_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            panel,clock,port=self.coordinator(folder)
            for locked in (False,True):
                if locked: panel.lock.acquire()
                try:
                    self.assertFalse(panel.status()['recently_detected'])
                    self.assertIsNone(panel.status()['last_detected_age_s'])
                finally:
                    if locked: panel.lock.release()
            port[0]='/dev/ttyUSB0'
            self.assertTrue(panel.device_status()['recently_detected'])
            port[0]=''; clock[0]=599.999
            self.assertFalse(panel.device_status()['available'])
            self.assertTrue(panel.status()['recently_detected'])
            clock[0]=600
            self.assertFalse(panel.status()['recently_detected'])
            self.assertEqual(panel.status()['last_detected_age_s'],600)
            port[0]='/dev/ttyUSB0'
            self.assertTrue(panel.device_status()['recently_detected'])
            self.assertFalse(panel.enabled)
            self.assertFalse((Path(folder)/'state.json').exists())

    def test_status_is_current_without_invalidating_owner_cache_or_waiting_for_serial(self):
        with tempfile.TemporaryDirectory() as folder:
            panel,clock,port=self.coordinator(folder)
            port[0]='/dev/ttyUSB0'
            with patch('signalbar.faceplate.coordinator.port_owner_details',return_value=['another-process']) as owners:
                self.assertTrue(panel.status()['available'])
                clock[0]=5; self.assertTrue(panel.status()['available'])
                self.assertEqual(owners.call_count,1)
                port[0]=''; clock[0]=6
                self.assertFalse(panel.status()['available'])
                self.assertEqual(panel.status()['last_detected_age_s'],1)
                panel.lock.acquire()
                try:
                    clock[0]=605
                    self.assertFalse(panel.status()['recently_detected'])
                finally: panel.lock.release()

    def test_restart_does_not_trust_stored_asset_or_an_old_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            panel,clock,port=self.coordinator(folder)
            port[0]='/dev/ttyUSB0'; panel.device_status()
            restarted,_,_=self.coordinator(folder)
            self.assertFalse(restarted.device_status()['recently_detected'])
