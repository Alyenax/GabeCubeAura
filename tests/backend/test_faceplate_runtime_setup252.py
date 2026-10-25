"""Real engine loop and asynchronous worker; only hardware/provider boundaries fake."""
import asyncio,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.onboarding import OnboardingDraft,OnboardingTransaction
from signalbar.faceplate.routing import FaceplatePreferencesStore
from signalbar.faceplate.steamgriddb import SteamGridDBFaceplate
from test_cinema_integration import plugin_class
import test_screensaver_restore148 as fixture

class RuntimeSetup252Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Restore148Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.store=SettingsStore(str(self.f.root/'config.json'),first_install_defaults=True)
        self.store.update({'faceplate_lab_enabled':False})
        self.f.coordinator.asset_root=Path(__file__).resolve().parents[2]/'assets/faceplate'
        self.f.coordinator.steamgriddb=SteamGridDBFaceplate(self.f.root/'library')
        self.engine=Engine(self.store,str(self.f.root/'cache.json'),faceplate=self.f.coordinator,
            faceplate_preferences=FaceplatePreferencesStore(self.f.root/'routes.json'),
            hardware_factory=Mock(side_effect=RuntimeError('LED boundary simulated')))
        self.addCleanup(self.engine.stop)
        self.plugin=plugin_class()();self.plugin.engine=self.engine
        self.plugin._onboarding_commit_lock=threading.RLock();self.plugin._onboarding_recovery_error=''
        self.plugin.onboarding_draft=OnboardingDraft(self.f.root/'draft.json')
        self.plugin.onboarding_transaction=OnboardingTransaction(self.f.root/'transaction.json')
        self.plugin._configure_faceplate_power_events=Mock()
        self.engine.set_faceplate_power(False)
        command=self.f.panel.command
        def checked(packet,**kwargs):
            self.assertFalse(self.engine._onboarding_applying)
            self.assertFalse(self.store._lock._is_owned())
            return command(packet,**kwargs)
        self.f.panel.command=checked
        with patch.object(self.engine.weather,'start'),patch.object(self.engine.dashboard_stats,'start'):
            self.engine.start()

    def finish(self,home):
        asyncio.run(self.plugin.complete_onboarding({'faceplate_requested':True,'home':home,'game':'keep'}))

    def wait_for(self,predicate):
        end=time.monotonic()+5
        while time.monotonic()<end:
            if predicate():return
            threading.Event().wait(.01)
        self.fail(str({'worker':self.engine.faceplate_worker.status(),
            'power':self.engine._faceplate_power_status,'route':self.engine.faceplate_router.status()}))

    def assert_route(self,home):
        self.wait_for(lambda:self.engine.faceplate_router.status()['effective_scene']==home
            and self.f.coordinator.powered is True)
        self.assertTrue(self.engine._thread.is_alive())
        self.assertTrue(self.engine.faceplate_worker.status()['running'])
        self.assertEqual(self.f.panel.commits,1)

    def test_legacy_home_choice_is_forced_to_dashboard_with_real_loop(self):
        self.finish('weather');self.assert_route('dashboard')

    def test_dashboard_weather_completes_with_real_loop_without_a_decky_action(self):
        self.finish('dashboard');self.assert_route('dashboard')

    def test_reconfirming_setup_retries_a_retained_uncertain_image_immediately(self):
        self.f.panel.lose_end=True;self.finish('weather')
        self.wait_for(lambda:self.engine.faceplate_router.status()['preparation']['state']=='unconfirmed'
            and not self.engine.faceplate_worker.status()['busy'])
        self.assertEqual(self.f.panel.commits,1);self.assertFalse(self.f.coordinator.powered)
        self.f.panel.lose_end=False;self.finish('weather')
        self.wait_for(lambda:self.f.coordinator.powered is True
            and self.engine.faceplate_router.status()['preparation']['state']=='ready')
        self.assertEqual(self.f.panel.commits,2)

    def test_a_paused_replacement_cannot_reuse_an_old_ready_receipt(self):
        self.finish('weather');self.assert_route('dashboard')
        with patch.object(self.engine,'_assistant_holds_matrix',return_value=True):
            self.finish('weather')
            self.assertNotEqual(self.engine.faceplate_router.status()['preparation']['state'],'ready')
        self.wait_for(lambda:self.engine.faceplate_router.status()['preparation']['state']=='ready')
