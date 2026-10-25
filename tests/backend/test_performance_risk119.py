"""Lab 119 compatibility inputs may no longer enable Performance on JSAUX."""
from pathlib import Path
import tempfile
import unittest

from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.flash import FlashWearProtection, UploadDeferred, identity
from signalbar.faceplate.performance_policy import CONSENT_REVISION
from signalbar.faceplate.service import FaceplateWorker
from signalbar.settings import SettingsStore


class RetiredPerformanceTests(unittest.TestCase):
    def test_old_consent_does_not_reenable_coordinator_or_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            coordinator = FaceplateCoordinator(Path(folder), Path(folder)/"state.json", port_finder=lambda: None)
            coordinator.configure(True, 100)
            coordinator.configure_performance(1, CONSENT_REVISION)
            result = coordinator.synchronize_scene(encode_frame(bytes(3456*3)), "performance", "retired")
            self.assertFalse(result.get("synchronized"))
            self.assertIn("removed", result["error"])
            self.assertFalse(coordinator.flash.status()["performance_unlimited"])
            worker = FaceplateWorker(lambda request: None)
            self.assertIn("removed", worker._gate_request("performance", {"scene_class":"performance", "upload_interval_seconds": 1}))

    def test_old_consent_setting_is_discarded(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(str(Path(folder)/"settings.json"))
            store.update({"faceplate_performance_consent": CONSENT_REVISION})
            self.assertEqual("", store.all()["faceplate_performance_consent"])

    def test_arbitrary_priority_cannot_create_an_exemption(self):
        guard = FlashWearProtection()
        for index in range(8):
            guard.reserve_body(identity(str(index).encode()), "restore")
        guard.configure_performance(True)
        guard.preflight(b"cpu", "performance-consented")
        self.assertFalse(guard.status()['performance_unlimited'])
        self.assertFalse(guard.status()['hard_limit_enabled'])
