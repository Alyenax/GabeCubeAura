"""Real adapter/core/policy recovery, fake hardware; no optical claim."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from signalbar.backend import Engine
import test_broker_adapter as adapter_fixture
import test_jsaux_broker_core as core_fixture
import test_screensaver_brief_alerts172 as integration_fixture

class SteamContinuityTests(unittest.TestCase):
    def setUp(self):
        self.f=adapter_fixture.BrokerAdapterTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.a=self.f.adapter;self.clock=self.f.clock

    def test_error_does_not_refresh_real_proof_or_close_live_delegation(self):
        self.f.start();activation=self.a._activation;at=self.a._observation_at
        self.clock.now+=1.2;self.a.observe_steam(False,'error','poll')
        steam=self.a._steam();self.assertEqual(steam['observed'],'active');self.assertFalse(steam['activation_closed'])
        self.assertEqual(self.a._observation_at,at)
        self.clock.now+=4;self.assertEqual(self.a._steam()['observation_age_ms'],5200)
        self.assertTrue(self.a._valid(self.f.job))
        self.a.observe_steam(True,'available','poll')
        self.assertEqual(self.a._activation,activation);self.assertFalse(self.a._closed)
        self.assertEqual(len(self.f.calls),1)
        self.assertEqual(self.a.diagnostic_snapshot()['steam_observation']['query_health'],'available')

    def test_persistent_loss_expires_without_artificial_refresh_and_cannot_resurrect(self):
        self.f.start();old=self.a._activation
        for _ in range(8):self.clock.now+=1;self.a.observe_steam(False,'error','poll')
        self.clock.now+=.001
        self.assertEqual(self.a._steam()['observed'],'unknown');self.assertTrue(self.a._closed)
        self.a.observe_steam(True)
        self.assertTrue(self.a._closed);self.assertEqual(self.a._activation,old)
        self.a.observe_steam(False);self.a.observe_steam(True)
        self.assertNotEqual(self.a._activation,old);self.assertFalse(self.a._closed)

    def test_true_inactive_stopped_and_suspend_win_immediately(self):
        self.f.start();self.a.observe_steam(False,'available','notification')
        self.assertTrue(self.a._closed);self.assertEqual(self.a._steam()['observed'],'inactive')
        self.a.observe_steam(False);self.a.observe_steam(True)
        self.a.observe_steam(False,'unavailable','stopped');self.assertTrue(self.a._closed)
        for source in ('startup','resume'):
            self.a.observe_steam(False);self.a.observe_steam(True)
            self.a.observe_steam(False,'waiting',source)
            self.assertTrue(self.a._closed);self.assertIsNone(self.a._observation_at)
            self.a.observe_steam(True);self.assertTrue(self.a._closed)
        self.a.observe_steam(False);self.a.observe_steam(True)
        self.f.engine._faceplate_suspended=True;self.assertTrue(self.a._steam()['activation_closed'])

    def test_no_existing_delegation_retains_strict_five_second_admission(self):
        self.clock.now+=5.1
        self.assertEqual(self.a._steam()['observed'],'unknown')
        self.a.observe_steam(True);self.assertTrue(self.a._closed)

class BrokerContinuityTests(unittest.TestCase):
    def setUp(self):
        self.f=core_fixture.CoreTests();self.f.setUp();self.addCleanup(self.f.tearDown)

    def test_existing_lease_accepts_observation_recovery_but_new_acquisition_does_not(self):
        f=self.f;lease=f.acquire();f.adapter.state['steam']['observation_age_ms']=5100
        f.broker.tick();self.assertTrue(f.broker.is_valid(lease['operation_id']))
        renewed=f.ok('renew_display',dict(lease_id=lease['lease_id'],generation=lease['generation'],sequence=1))
        self.assertEqual(renewed['expires_in_ms'],8000)
        f.adapter.state['steam']['observation_age_ms']=8001;f.broker.tick()
        self.assertEqual(f.broker.lease['reason'],'STEAM_STATE_STALE')
        self.assertIn('activation-1',f.broker.fenced)

    def test_lease_expiry_and_explicit_off_still_override_grace(self):
        f=self.f;lease=f.acquire();f.clock.now+=8;f.broker.tick()
        self.assertEqual(f.broker.lease['reason'],'LEASE_EXPIRED')

class AssistantContinuityTests(unittest.TestCase):
    def engine(self):
        e=Engine.__new__(Engine)
        e.settings=SimpleNamespace(all=lambda:dict(faceplate_lab_enabled=True,mode='weather',steam_control_enabled=False))
        e._available=True;e._stop=threading.Event();e.thermal_protection=SimpleNamespace(active=False)
        e._display_panel_off=lambda v:False;e._display_bar_off=lambda v:False
        e._faceplate_suspended=False;e._faceplate_extension_present=True;e.faceplate=SimpleNamespace(powered=True)
        e.jsaux_broker_adapter=SimpleNamespace(holds_display=lambda:True)
        e.assistant=SimpleNamespace(active=True,visual_available=True,leased=True)
        e._assistant_route_lock=threading.RLock();e.faceplate_worker=Mock();e._assistant_detach_visuals=Mock()
        return e

    def test_voice_bar_remain_available_but_matrix_and_stale_preflight_cannot_replace_screensaver(self):
        e=self.engine();caps=e._assistant_visual_capabilities()
        self.assertTrue(caps['bar_available']);self.assertFalse(caps['matrix_available'])
        self.assertFalse(e._assistant_holds_matrix())
        e._assistant_acquire(b'gif',{},threading.Event())
        e.faceplate_worker.submit.assert_not_called()
        e._assistant_detach_visuals.assert_called_once_with('screensaver-owns-matrix',matrix=True,bar=False)
        e.jsaux_broker_adapter.holds_display=lambda:False
        self.assertTrue(e._assistant_visual_capabilities()['matrix_available'])
        self.assertTrue(e._assistant_holds_matrix())

class AssistantBrokerIntegrationTests(unittest.TestCase):
    def test_voice_sessions_keep_one_live_gif_and_thermal_still_preempts(self):
        f=integration_fixture.ScreensaverBriefAlerts172Tests();f.setUp();self.addCleanup(f.doCleanups)
        e=f.engine;e.assistant=SimpleNamespace(active=False,visual_available=False,leased=False)
        e._assistant_holds_matrix=Engine._assistant_holds_matrix.__get__(e,Engine)
        e.jsaux_broker_adapter=SimpleNamespace(holds_display=lambda:bool(f.core.broker.lease and f.core.broker.lease['lease_state'] not in ('released','preempted','expired','rejected')))
        lease=f.start()
        for ending in ('success','cancelled','error'):
            e.assistant.active=True;e.assistant.visual_available=True;e.assistant.leased=True
            f.event='notification';f.core.broker.tick()
            self.assertNotIn(f.core.broker.lease['lease_state'],('released','preempted','expired','rejected'))
            e.assistant.active=False;e.assistant.visual_available=False;e.assistant.leased=False
            f.core.broker.tick()
        self.assertEqual(len(f.core.adapter.jobs),1)
        self.assertEqual(f.core.adapter.cancellations,[]);self.assertEqual(f.core.adapter.restorations,[])
        e.thermal_protection.active=True;f.core.broker.tick()
        self.assertEqual(f.core.broker.lease['reason'],'PRIORITY_ACTIVE')
        self.assertEqual(f.core.adapter.cancellations,[lease['operation_id']])
