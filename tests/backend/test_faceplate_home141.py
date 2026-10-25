"""Reproduce the Lab140 report with a panel that rejects END without a body.

These are serial simulations, not optical or flash-lifetime measurements.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.faceplate import protocol
from signalbar.faceplate.coordinator import FaceplateCoordinator, encode_frame
from signalbar.faceplate.flash import FlashWearProtection, identity
from signalbar.faceplate.transport import Link, LinkError, ReplyTimeout, GifCommitUnconfirmed
from signalbar.models import GameState
import test_native_clock


class SessionPanel:
    def __init__(self):
        self.stored=None;self.pending=None;self.calls=[];self.bodies=0
        self.file_error=False;self.native=False;self.lose_end=False

    def command(self,packet,**kwargs):
        kind,cmd=packet[2:4];self.calls.append((kind,cmd));status=1
        if kind==1 and cmd==4:
            if packet[6:-2]==self.stored:status=2
            else:self.pending=packet[6:-2]
        elif kind==2 and cmd==2:self.bodies+=1
        elif kind==1 and cmd==11:
            if self.pending is None and not self.native:
                self.file_error=True;status=0
            else:
                if self.pending is not None:self.stored,self.pending=self.pending,None
                self.native=False
            if self.lose_end:raise ReplyTimeout('no reply to type=0x01 cmd=0x0b')
        return protocol.Reply(kind,cmd,bytes([status]))


class HomeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.guard=FlashWearProtection();self.panel=SessionPanel()
        self.sleep=patch('signalbar.faceplate.transport.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)

    def link(self,activate=False):
        link=Link('/dev/null');link.flash_manager=self.guard
        link.command=self.panel.command;link.activate_stored_gif=activate
        return link

    def test_duplicate_after_success_does_not_trigger_the_reported_file_icon(self):
        home=b'home-dashboard'*5487
        self.assertTrue(self.link().send_gif(home))
        body_count=self.panel.bodies;link=self.link()
        self.assertFalse(link.send_gif(home))
        self.assertFalse(self.panel.file_error);self.assertEqual(self.panel.bodies,body_count)
        self.assertEqual(link.last_transfer_timings['begin_status'],2)
        self.assertFalse(link.last_transfer_timings['end_sent'])
        self.assertFalse(link.last_transfer_timings['payload_complete'])
        self.assertEqual(self.guard.session['confirmed'],1);self.assertEqual(self.guard.session['reused'],1)

    def test_actual_home_game_home_changes_upload_bodies_but_crc_reuse_does_not(self):
        for data in (b'home',b'home',b'game-artwork',b'game-artwork',b'home',b'home'):
            self.link().send_gif(data)
        self.assertFalse(self.panel.file_error)
        self.assertEqual(self.panel.bodies,3)
        self.assertEqual(self.guard.session['confirmed'],3)
        self.assertEqual(self.guard.session['reused'],3)

    def test_explicit_native_return_still_activates_the_stored_gif_once(self):
        self.link().send_gif(b'home');self.panel.native=True;body_count=self.panel.bodies
        link=self.link(activate=True)
        self.assertFalse(link.send_gif(b'home'))
        self.assertFalse(self.panel.native);self.assertEqual(self.panel.bodies,body_count)
        self.assertTrue(link.last_transfer_timings['stored_display_restarted'])
        self.assertEqual(link.last_transfer_timings['end_status'],1)

    def test_real_refusal_is_not_hidden_and_records_the_status(self):
        self.link().send_gif(b'home');link=self.link(activate=True)
        with self.assertRaisesRegex(LinkError,'refused stored GIF display'):link.send_gif(b'home')
        self.assertEqual(link.last_transfer_timings['end_status'],0)

    def test_fresh_commit_timeout_is_not_retried_or_called_confirmed(self):
        self.panel.lose_end=True;link=self.link();link.transport_profile='auto'
        with self.assertRaises(GifCommitUnconfirmed):link.send_gif(b'home')
        self.assertEqual(self.panel.bodies,1);self.assertEqual(len(link.last_transfer_timings['attempt_profiles']),1)
        self.assertEqual(self.guard.session['confirmed'],0)

    def test_delegation_requires_explicit_stored_activation_on_normal_return_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home=encode_frame(bytes([10,0,0])*3456)
            coordinator=FaceplateCoordinator(Path(directory),Path(directory)/'state.json')
            coordinator.flash=self.guard
            # Ordinary duplicates still avoid END (Lab141 regression).
            coordinator._send_protected(self.link(),home,scene='weather')
            before=self.panel.calls.count((1,11))
            coordinator._send_protected(self.link(),home,scene='weather')
            self.assertEqual(self.panel.calls.count((1,11)),before)
            # A delegated commit may leave the physical mode unknown, even if
            # the firmware reports the previously stored normal CRC afterward.
            coordinator._send_protected(self.link(),b'screensaver',scene='screensaver')
            self.assertTrue(coordinator._delegated_gif_activation_pending)
            self.panel.stored=protocol.gif_begin(home)[6:-2]
            self.panel.native=True # Stored but not currently visible.
            link=self.link();body_count=self.panel.bodies
            coordinator._send_protected(link,home,scene='weather',reason='current-route-restore')
            coordinator._finish_scene_power(link)
            self.assertGreater(self.panel.bodies,body_count)
            self.assertTrue(link.last_transfer_timings['restore_repacked'])
            self.assertFalse(coordinator._delegated_gif_activation_pending)
            self.assertFalse(self.panel.native)
            before=self.panel.calls.count((1,11))
            coordinator._send_protected(self.link(),home,scene='weather')
            self.assertEqual(self.panel.calls.count((1,11)),before)

    def test_uncertain_delegated_commit_does_not_clear_restoration_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            home=encode_frame(bytes([10,0,0])*3456)
            coordinator=FaceplateCoordinator(Path(directory),Path(directory)/'state.json')
            coordinator.flash=self.guard;self.panel.lose_end=True
            with self.assertRaises(GifCommitUnconfirmed):
                coordinator._send_protected(self.link(),b'screensaver',scene='screensaver')
            self.assertTrue(coordinator._delegated_gif_activation_pending)
            self.panel.stored=protocol.gif_begin(home)[6:-2];self.panel.native=True
            with self.assertRaises(GifCommitUnconfirmed):
                coordinator._send_protected(self.link(),home,scene='weather',reason='current-route-restore')
            self.assertTrue(coordinator._delegated_gif_activation_pending)

    def test_full_legacy_windows_cannot_block_home_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.json';old=FlashWearProtection(path)
            old.reserve_body(identity(b'old'),'restore');old.receipt(identity(b'old'),wrote=True);old.flush(force=True)
            raw=json.loads(path.read_text());raw.update(tokens=0,attempt_ages=[0]*120,
                daily_attempt_ages=[0]*128,background_attempt_ages=[0]*24)
            path.write_text(json.dumps(raw))
            restored=FlashWearProtection(path)
            for priority in ('background','interactive','assistant','restore'):
                restored.preflight(priority.encode(),priority)
                restored.reserve_body(identity(priority.encode()),priority)
                restored.receipt(identity(priority.encode()),wrote=True)
            self.assertEqual(restored.total['confirmed'],5)
            self.assertFalse(restored.status()['hard_limit_enabled'])
            self.assertEqual(restored.status()['day_limit'],0)

    def test_game_exit_does_not_force_a_second_ticket_after_periodic_won_race(self):
        fixture=test_native_clock.NativeSceneTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        engine=fixture.engine;engine._game=GameState(620,'Portal 2')
        engine._sync_display_power_policy=lambda:engine._reconcile_faceplate('periodic')
        engine.set_game(0,'')
        self.assertEqual(engine.faceplate_worker.submit.call_count,1)
        self.assertEqual(engine.faceplate_router.status()['effective_scene'],'native-clock')


if __name__=='__main__':unittest.main()
