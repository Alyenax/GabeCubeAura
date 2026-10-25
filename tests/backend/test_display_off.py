import tempfile
import time
import threading
import termios
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.models import GameState, ProviderOutput, normalize_frame
from signalbar.arbiter.arbiter import Arbiter


class DisplayOffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = SettingsStore(str(Path(self.directory.name)/'settings.json'))
        self.store.update({'faceplate_lab_enabled': True, 'home_display':'audio_sync', 'game_display':'artwork'})
        self.engine = Engine(self.store, str(Path(self.directory.name)/'cache'))
        self.engine._game = GameState(42, 'Test')
        self.engine.faceplate.powered = True
        self.engine.faceplate_worker = Mock()
        self.engine.assistant = Mock(active=False)
        def power(enabled, reason, **kwargs):
            self.engine.faceplate.powered = enabled
            return {'ok':True, 'powered':enabled, 'error':''}
        self.power = Mock(side_effect=power)
        self.engine.faceplate.set_power = self.power
        self.presence = {'available':True, 'port':'/dev/test'}

    def tick(self):
        self.engine._sync_display_power_policy(self.presence)
        return self.engine._service_faceplate_power_retry(time.monotonic()+3)

    def test_two_scoped_off_routes_persist_without_mutating_master_brightness_or_other_games(self):
        before = self.store.all()
        for scene in ('bar_off','displays_off'):
            self.store.update_display(42,scene)
            self.assertEqual(self.store.display_for(42)['selected'],scene)
            self.assertEqual(self.store.display_for(42)['mode'],'disabled')
            self.assertEqual(self.store.display_for(99)['selected'],'artwork')
            self.assertEqual(self.store.display_for(0)['selected'],'audio_sync')
            after=self.store.all()
            for key in ('signalbar_enabled','faceplate_lab_enabled','faceplate_brightness','light_bar_day_brightness','home_display','game_display'):
                self.assertEqual(after[key],before[key])
            self.assertEqual(SettingsStore(self.store.path).display_for(42)['selected'],scene)

    def test_bar_only_off_never_sends_panel_power_or_changes_matrix_worker(self):
        self.store.update_display(42,'bar_off'); self.tick()
        self.assertTrue(self.engine._display_bar_off())
        self.assertFalse(self.engine._display_panel_off())
        self.power.assert_not_called(); self.engine.faceplate_worker.configure.assert_not_called()
        self.assertFalse(self.engine._assistant_wake_allowed)

    def test_both_off_only_queues_from_rpc_and_then_powers_off_once_on_the_existing_loop(self):
        self.engine.update_display(42,'displays_off')
        self.power.assert_not_called()
        self.assertTrue(self.engine._display_faceplate_off)
        self.tick(); self.assertFalse(self.engine.faceplate.powered)
        self.assertEqual(self.power.call_count,1)
        for _ in range(10): self.tick()
        self.assertEqual(self.power.call_count,1)

    def test_game_exit_restores_home_and_prior_on_state_not_a_stored_route_or_new_brightness(self):
        self.store.update_display(42,'displays_off'); self.tick()
        with patch.object(self.engine,'_reconcile_faceplate',return_value=0):
            self.engine.set_game(0)
        self.assertFalse(self.engine._display_panel_off())
        self.tick(); self.assertTrue(self.engine.faceplate.powered)
        self.assertEqual([call.args[0] for call in self.power.call_args_list],[False,True])
        self.assertEqual(self.store.display_for(0)['selected'],'audio_sync')

    def test_manual_off_is_never_automatically_undone(self):
        self.engine.set_faceplate_power(False)
        self.store.update_display(42,'displays_off'); self.tick()
        self.engine._game=GameState(0,''); self.tick()
        self.assertFalse(self.engine.faceplate.powered)
        self.assertNotIn(True,[call.args[0] for call in self.power.call_args_list])

    def test_manual_off_during_override_cancels_the_restore_lease(self):
        self.store.update_display(42,'displays_off'); self.tick()
        self.engine.set_faceplate_power(False)
        self.engine._game=GameState(0,''); self.tick()
        self.assertFalse(self.engine.faceplate.powered)

    def test_master_off_and_game_off_overlap_without_a_flash_or_lost_restore(self):
        self.store.update_display(42,'displays_off'); self.tick()
        self.engine.update_settings({'signalbar_enabled':False})
        self.engine._game=GameState(0,''); self.tick()
        self.assertFalse(self.engine.faceplate.powered)
        self.engine.update_settings({'signalbar_enabled':True}); self.tick()
        self.assertEqual([call.args[0] for call in self.power.call_args_list],[False,True])

    def test_standby_resume_and_manual_power_on_cannot_bypass_off(self):
        self.store.update_display(42,'displays_off'); self.tick()
        self.assertFalse(self.engine.set_faceplate_power(True)['ok'])
        self.engine.resume_faceplate()
        self.assertFalse(self.engine.faceplate.powered)
        self.assertNotIn(True,[call.args[0] for call in self.power.call_args_list])
        result=self.engine._handle_faceplate_scene({'payload':{'kind':'control','powered':True}})
        self.assertTrue(result['superseded'])

    def test_reconnect_while_off_reapplies_volatile_power_without_gif_upload(self):
        self.store.update_display(42,'displays_off'); self.tick()
        self.engine._sync_display_power_policy({'available':False})
        self.tick()
        self.assertEqual([call.args[0] for call in self.power.call_args_list],[False,False])
        self.engine.faceplate_worker.submit.assert_not_called()

    def test_global_toggle_off_darkens_panel_and_restores_after_reenable(self):
        self.engine.update_settings({'signalbar_enabled':False}); self.tick()
        self.assertFalse(self.engine.faceplate.powered)
        self.engine.update_settings({'signalbar_enabled':True}); self.tick()
        self.assertTrue(self.engine.faceplate.powered)

    def test_master_toggle_does_not_wait_for_the_serial_transfer_lock(self):
        done=threading.Event()
        self.engine.faceplate.lock.acquire()
        thread=threading.Thread(target=lambda:(self.engine.update_settings({'signalbar_enabled':False}), done.set()), daemon=True)
        try:
            thread.start()
            self.assertTrue(done.wait(.5), 'master toggle waited for unrelated GIF serial lock')
        finally:
            self.engine.faceplate.lock.release(); thread.join(2)

    def test_unchanged_weather_is_queued_again_after_a_cancelled_off_on_transition(self):
        self.engine._game=GameState(0,'')
        self.engine.faceplate_preferences.update(home_scene='weather')
        self.engine.faceplate_worker.status.return_value={'busy':False,'queued':False}
        self.engine.faceplate_worker.submit.return_value=1
        self.engine._write_faceplate_runtime_status=Mock()
        self.engine.faceplate.device_status=Mock(return_value=self.presence)
        self.engine._faceplate_weather_payload=Mock(return_value=({'signature':'same','condition':'rain','variant':0,'temperature_c':12,'unit':'celsius','phase':'night'}, {}, ''))
        self.assertEqual(self.engine._reconcile_faceplate(force=True),1)
        self.engine.update_settings({'signalbar_enabled':False}); self.tick()
        self.engine.update_settings({'signalbar_enabled':True}); self.tick()
        self.assertEqual(self.engine._reconcile_faceplate(),1)
        self.assertEqual(self.engine.faceplate_worker.submit.call_count,2)
        self.assertFalse(self.engine._faceplate_resume_requested)
        self.assertEqual(self.engine._reconcile_faceplate(),0)

    def test_steam_switch_preserves_previous_content_brightness_and_matrix_power(self):
        before=self.store.all()
        self.engine.set_steam_control(True)
        self.assertTrue(self.store.all()['steam_control_enabled'])
        self.assertFalse(self.engine._display_panel_off())
        self.assertFalse(self.engine._assistant_wake_allowed)
        self.engine.set_steam_control(False)
        after=self.store.all()
        for key in ('home_display','game_display','display_profiles','faceplate_lab_enabled','faceplate_brightness','light_bar_day_brightness'):
            self.assertEqual(before[key],after[key])
        self.power.assert_not_called()

    def test_explicit_reclaim_repairs_legacy_steam_context_without_resetting_other_games(self):
        self.store.update_display(42,'steam'); self.store.update_display(99,'performance')
        self.engine.set_steam_control(False)
        self.assertEqual(self.store.display_for(42)['selected'],'artwork')
        self.assertEqual(self.store.display_for(99)['selected'],'performance')
        self.engine._game=GameState(0,''); self.store.update({'home_display':'steam'})
        self.engine.set_steam_control(False)
        self.assertNotEqual(self.store.display_for(0)['selected'],'steam')

    def test_manual_diagnostic_snapshot_is_live_and_never_scans_usb(self):
        with patch.object(self.engine.faceplate,'status',side_effect=AssertionError('USB probe')):
            state=self.engine.display_control_snapshot()
        self.assertIn('engine_alive',state)
        self.assertEqual(state['selected'],'artwork')

    def test_serial_driver_fault_cannot_kill_the_common_render_loop(self):
        self.engine._write_faceplate_runtime_status=Mock()
        self.engine._reconcile_faceplate=Mock(return_value=0)
        self.engine.faceplate.device_status=Mock(return_value=self.presence)
        self.engine.faceplate_worker.status.return_value={}
        self.power.side_effect=termios.error(5,'Input/output error')
        self.engine.hardware_factory=Mock(side_effect=OSError('test bar absent'))
        self.engine.start()
        try:
            deadline=time.monotonic()+1
            while self.engine._faceplate_power_status['ok'] and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(self.engine._thread.is_alive())
            self.assertFalse(self.engine._faceplate_power_status['ok'])
            self.assertIn('Input/output error',self.engine._faceplate_power_status['error'])
            self.assertTrue(self.engine._faceplate_power_target)
        finally: self.engine.stop()

    def test_failed_off_command_retries_and_cannot_leak_into_a_changed_context(self):
        self.store.update_display(42,'displays_off')
        self.power.side_effect=lambda *args,**kwargs: {'ok':False,'powered':True,'error':'busy'}
        self.tick(); self.assertIs(self.engine._faceplate_power_target,False)
        self.assertTrue(self.engine.faceplate.powered)
        self.engine._game=GameState(0,'')
        self.engine._sync_display_power_policy()
        self.assertIs(self.engine._faceplate_power_target,True)

    def test_late_ack_or_failure_cannot_erase_a_newer_power_target(self):
        for ok in (True,False):
            def complete(enabled, reason, **kwargs):
                self.engine._faceplate_power_target=True
                self.engine._faceplate_power_retry_at=0
                return {'ok':ok,'powered':False,'error':'' if ok else 'late failure'}
            self.power.side_effect=complete
            self.engine._faceplate_power_target=False
            self.engine._apply_faceplate_power(False,'old off command')
            self.assertIs(self.engine._faceplate_power_target,True)

    def test_preview_payloads_are_blocked_while_panel_off_but_not_bar_only(self):
        self.store.update_display(42,'displays_off')
        with patch.object(self.engine.faceplate,'synchronize_scene') as upload:
            result=self.engine._handle_faceplate_scene({'payload':{'kind':'gabe'}})
            self.assertTrue(result['superseded']); upload.assert_not_called()
        self.store.update_display(42,'bar_off')
        self.assertFalse(self.engine._display_panel_off())

    def test_real_render_loop_master_switch_holds_bar_black_and_restores_home(self):
        class Hardware:
            device_path='/test/off-bar'; reverse=False
            def __init__(self): self.frame=normalize_frame([(5,6,7)]*17)
            def set_reverse(self,value): self.reverse=value
            def read_frame(self): return self.frame
            def read_signature(self): return self.frame
            def write_frame(self,value): self.frame=value
            def try_restore(self,value): self.frame=value
        hardware=Hardware()
        self.store.update({'home_display':'customization', 'game_display':'customization', 'valve_ownership_policy':'cooperative'})
        # Two seconds was exactly the real stable-state guard, before a render
        # tick could publish ownership. Respect the guard/cooldown instead of
        # racing it or weakening the production coexistence protection.
        ownership_timeout=self.store.all()['guard_cooldown_s']+self.store.all()['guard_stable_s']+1
        self.engine.hardware_factory=lambda:hardware
        self.engine.faceplate_worker.status.return_value={}
        self.engine._write_faceplate_runtime_status=Mock()
        self.engine._reconcile_faceplate=Mock(return_value=0)
        self.engine.faceplate.device_status=Mock(return_value=self.presence)
        self.engine.assistant=Mock(active=False,holds_bar=False,output=Mock(return_value=None))
        self.engine.start()
        try:
            deadline=time.monotonic()+ownership_timeout
            while self.engine.status()['owner']!='GabeCubeAura' and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(self.engine.status()['owner'],'GabeCubeAura')
            self.engine.set_steam_control(True)
            deadline=time.monotonic()+ownership_timeout
            while self.engine.status()['owner']!='Valve' and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(self.engine.status()['owner'],'Valve')
            self.assertEqual(hardware.frame,normalize_frame([(5,6,7)]*17))
            self.engine.set_steam_control(False)
            deadline=time.monotonic()+ownership_timeout
            while self.engine.status()['owner']!='GabeCubeAura' and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(self.engine.status()['owner'],'GabeCubeAura')
            self.engine.update_settings({'signalbar_enabled':False})
            deadline=time.monotonic()+2
            while (any(any(color) for color in hardware.frame) or self.engine.faceplate.powered is not False) and time.monotonic()<deadline: time.sleep(.01)
            self.assertFalse(any(any(color) for color in hardware.frame))
            self.assertFalse(self.engine.faceplate.powered)
            self.engine.update_settings({'signalbar_enabled':True})
            deadline=time.monotonic()+2
            while not any(any(color) for color in hardware.frame) and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(any(any(color) for color in hardware.frame))
        finally:
            self.engine.stop()

    def test_explicit_off_is_strict_black_even_with_a_gabe_frame_alert_or_countdown(self):
        bright=ProviderOutput('gabe:voice',normalize_frame([(200,30,10)]*17),'test')
        decision=Arbiter().choose(mode='bar_off',guard_allows=True,game=GameState(42,'Test'),
            performance=bright,artwork=bright,idle=bright,assistant_base=bright,event=bright,
            signal=bright,signal_critical=True,launch_artwork=bright,recording_marker=True)
        self.assertEqual(decision.provider,'blackout')
        self.assertEqual(decision.frame,normalize_frame([(0,0,0)]*17))
        native=Arbiter().choose(mode='steam_control',guard_allows=True,game=GameState(42,'Test'),
            performance=bright,artwork=bright,idle=bright,assistant_base=bright,event=bright,signal=bright,signal_critical=True)
        self.assertEqual(native.provider,'valve'); self.assertIsNone(native.frame)
