"""Ownership policy, real descriptor lifetime and mocked-device engine guards."""
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import tempfile
import termios
import threading
import sys
import unittest
from unittest.mock import Mock, patch

from signalbar.faceplate.control import FaceplateControl, allows_output, allows_integration, wants_claim
from signalbar.faceplate import transport
from signalbar.settings import SettingsStore
from signalbar.backend import Engine


class PolicyTests(unittest.TestCase):
    def test_default_preserves_automatic_policy_and_integrations(self):
        self.assertTrue(allows_output({}))
        self.assertTrue(allows_integration({}, 'das'))
        self.assertTrue(allows_integration({}, 'dva'))
        self.assertFalse(wants_claim({}))
        self.assertTrue(wants_claim({'faceplate_lab_enabled': True}))

    def test_release_overrides_follow_and_both_companions(self):
        values={'faceplate_control_mode':'other-app','faceplate_lab_enabled':True}
        self.assertFalse(wants_claim(values))
        self.assertFalse(allows_output(values))
        self.assertFalse(allows_integration(values,'das'))
        self.assertFalse(allows_integration(values,'dva'))

    def test_priority_reserves_independently_and_has_scoped_permissions(self):
        values={'faceplate_control_mode':'gca-priority','faceplate_lab_enabled':False,'faceplate_allow_das':False}
        self.assertTrue(wants_claim(values))
        self.assertFalse(allows_integration(values,'das'))
        self.assertTrue(allows_integration(values,'dva'))
        self.assertFalse(allows_integration(values,'unregistered-app'))

    def test_settings_persist_and_invalid_edits_do_not_change_the_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'settings.json');store=SettingsStore(path)
            self.assertEqual(store.all()['faceplate_control_mode'],'automatic')
            store.update({'faceplate_control_mode':'other-app','faceplate_allow_dva':False})
            saved=SettingsStore(path).all()
            self.assertEqual(saved['faceplate_control_mode'],'other-app')
            self.assertFalse(saved['faceplate_allow_dva'])
            for changes in [{'faceplate_control_mode':'forced-root'},{'faceplate_allow_das':'false'}]:
                with self.assertRaises(ValueError):store.update(changes)
            self.assertEqual(store.all()['faceplate_control_mode'],'other-app')


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self.master,self.slave=pty.openpty()
        self.port=os.ttyname(self.slave)
        self.control=FaceplateControl({'faceplate_control_mode':'gca-priority'})
        self.addCleanup(self.control.close)
        self.addCleanup(lambda:os.close(self.master))
        self.addCleanup(lambda:os.close(self.slave))

    def retain(self):
        self.control.begin()
        self.control.retain(self.slave,self.port,('device',1))
        self.control.end()

    def test_duplicate_survives_transactions_and_release_closes_it(self):
        self.retain()
        self.assertTrue(self.control.status()['reserved'])
        self.control.begin();fd=self.control.reuse(self.port,('device',1))
        self.assertIsNotNone(fd);os.fstat(fd);os.close(fd);self.control.end()
        self.assertTrue(self.control.status()['reserved'])
        self.control.configure({'faceplate_control_mode':'other-app'})
        self.assertEqual(self.control.status()['phase'],'released')
        self.assertFalse(self.control.status()['reserved'])
        # Explicitly clear exclusive mode even when an outside duplicate exists.
        fd=os.open(self.port,os.O_RDWR|os.O_NOCTTY);os.close(fd)

    def test_releasing_is_not_reported_as_released_while_a_transaction_is_active(self):
        self.retain();self.control.begin()
        fd=self.control.reuse(self.port,('device',1))
        self.control.configure({'faceplate_control_mode':'other-app'})
        self.assertEqual(self.control.status()['phase'],'releasing')
        self.assertFalse(self.control.permitted())
        os.close(fd);self.control.end()
        self.assertEqual(self.control.status()['phase'],'released')

    def test_a_waiting_opener_cannot_enter_after_release_was_requested(self):
        self.control.begin();result=[];started=threading.Event()
        def enter():
            started.set()
            try:self.control.begin()
            except OSError as error:result.append(error.errno)
            else:self.control.end();result.append('opened')
        thread=threading.Thread(target=enter);thread.start();self.assertTrue(started.wait(1))
        self.control.configure({'faceplate_control_mode':'other-app'});self.control.end();thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(result,[errno.EBUSY])

    def test_automatic_does_not_retain_the_descriptor(self):
        self.control.configure({});self.control.begin()
        self.control.retain(self.slave,self.port,('device',1));self.control.end()
        self.assertFalse(self.control.status()['reserved'])

    def test_device_replacement_discards_the_old_reserved_descriptor(self):
        self.retain();self.control.begin()
        self.assertIsNone(self.control.reuse(self.port,('replacement',2)))
        self.control.end();self.assertFalse(self.control.status()['reserved'])

    def test_no_silent_fallback_if_exclusive_mode_fails(self):
        self.control.begin()
        with patch('signalbar.faceplate.control.fcntl.ioctl',side_effect=OSError('unsupported')):
            with self.assertRaises(OSError):self.control.retain(self.slave,self.port,('device',1))
        self.control.end();self.assertFalse(self.control.status()['reserved'])

    @unittest.skipIf(sys.platform!='linux' or os.geteuid()==0,'requires an unprivileged Linux process')
    def test_exclusive_reservation_blocks_a_new_unprivileged_open(self):
        self.retain()
        with self.assertRaises(OSError) as caught:os.open(self.port,os.O_RDWR|os.O_NOCTTY)
        self.assertEqual(caught.exception.errno,errno.EBUSY)

    def test_closed_backend_cannot_be_reopened_by_a_late_configuration(self):
        self.retain();self.control.close();self.control.configure({'faceplate_control_mode':'gca-priority'})
        self.assertFalse(self.control.permitted());self.assertFalse(self.control.status()['reserved'])

    def test_release_fences_actual_open_and_write_syscalls(self):
        self.control.configure({'faceplate_control_mode':'other-app'})
        with patch('signalbar.faceplate.control.os.open') as opener, patch('signalbar.faceplate.control.os.write') as writer:
            with self.assertRaises(OSError):self.control.open_port(self.port,os.O_RDWR)
            with self.assertRaises(OSError):self.control.write_port(self.slave,b'blocked')
        opener.assert_not_called();writer.assert_not_called()

    def test_failed_device_is_not_reused_or_reported_as_reserved(self):
        self.retain();self.control.failed(OSError('USB disconnected'))
        self.assertFalse(self.control.status()['reserved'])
        self.assertEqual(self.control.status()['phase'],'waiting')
        self.control.begin()
        self.assertIsNone(self.control.reuse(self.port,('device',1)))
        self.control.end()

    def test_failure_discards_retained_copy_only_after_active_transaction_closes(self):
        self.retain();self.control.begin()
        fd=self.control.reuse(self.port,('device',1))
        self.control.failed(OSError('USB disconnected'))
        self.assertFalse(self.control.current_reservation(self.port,('device',1)))
        os.fstat(fd);os.close(fd);self.control.end()
        self.assertIsNone(self.control._fd)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.control=FaceplateControl()
        self.manager=transport.PhysicalOwnership(Path(self.folder.name)/'ownership',control=self.control)
        old=transport._ownership_manager;transport.install_ownership_manager(self.manager)
        self.addCleanup(lambda:transport.install_ownership_manager(old));self.addCleanup(self.manager.close)

    def test_released_link_does_not_even_probe_or_open_the_port(self):
        self.control.configure({'faceplate_control_mode':'other-app'})
        with patch.object(transport,'port_owner_details') as probe,patch.object(transport.os,'open') as opener:
            with self.assertRaises(transport.LinkBusy):transport.Link('/dev/fake').open()
        probe.assert_not_called();opener.assert_not_called()
        self.assertEqual(self.control.status()['active_transactions'],0)

    def test_existing_transaction_cannot_write_after_release_request(self):
        self.control.begin();link=transport.Link('/dev/fake');link._usb_control=self.control
        self.control.configure({'faceplate_control_mode':'other-app'})
        with patch.object(transport.os,'write') as writer:
            with self.assertRaises(transport.TransferCancelled):link.write(b'blocked')
        writer.assert_not_called();link.close()
        self.assertEqual(self.control.status()['phase'],'released')

    def test_open_failure_does_not_leak_a_transaction(self):
        with patch.object(transport,'device_identity',return_value=None),patch.object(transport,'port_owner_details',return_value=['peer']),patch.object(self.manager,'claim',return_value=True):
            with self.assertRaises(transport.LinkError):transport.Link('/dev/fake').open()
        self.assertEqual(self.control.status()['active_transactions'],0)

    def test_real_link_reuses_one_open_then_releases_it_and_recovers_after_error(self):
        master,slave=pty.openpty();port=os.ttyname(slave)
        try:
            self.control.configure({'faceplate_control_mode':'gca-priority'})
            actual_open=os.open
            with patch.object(transport,'port_owner_details',return_value=[]), \
                 patch.object(self.manager,'claim',return_value=True), \
                 patch.object(transport.termios,'B1000000',termios.B9600,create=True), \
                 patch.object(transport.os,'open',wraps=actual_open) as opened:
                with transport.Link(port):pass
                with transport.Link(port):pass
                self.assertEqual(opened.call_count,1)
                with self.assertRaisesRegex(OSError,'lost device'):
                    with transport.Link(port):raise OSError('lost device')
                self.assertFalse(self.control.status()['reserved'])
                with transport.Link(port):pass
                self.assertEqual(opened.call_count,2)
                self.control.configure({'faceplate_control_mode':'other-app'})
                self.assertEqual(self.control.status()['phase'],'released')
                self.control.configure({})
                with transport.Link(port):pass
                self.assertFalse(self.control.status()['reserved'])
        finally:
            self.control.close();os.close(slave);os.close(master)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.store=SettingsStore(str(Path(self.folder.name)/'settings.json'))
        self.engine=Engine(self.store,str(Path(self.folder.name)/'cache'))
        self.engine.faceplate_worker=Mock()
        self.engine.assistant=Mock(active=False)
        self.engine.faceplate.set_power=Mock(return_value={'ok':True})
        self.engine.faceplate.steamgriddb=Mock()
        self.addCleanup(self.engine.faceplate_control.close)

    def test_release_clears_recovery_and_rejects_every_power_path(self):
        self.engine._faceplate_power_target=True
        self.engine.update_settings({'faceplate_control_mode':'other-app'})
        self.assertIsNone(self.engine._faceplate_power_target)
        self.assertFalse(self.engine.set_faceplate_power(True)['ok'])
        self.assertFalse(self.engine.set_faceplate_power(False)['ok'])
        self.assertFalse(self.engine._apply_faceplate_power(False,'sleep')['ok'])
        self.engine._sync_display_power_policy({'available':True})
        self.engine._service_faceplate_power_retry(999999)
        self.engine.faceplate.set_power.assert_not_called()
        self.engine.faceplate_worker.configure.assert_called_with(False)

    def test_a_queued_control_or_screensaver_exit_cannot_bypass_release(self):
        self.engine.update_settings({'faceplate_control_mode':'other-app'})
        for kind in ['control','return-stop','broker','broker-exit','external','weather-preview']:
            result=self.engine._handle_faceplate_scene({'payload':{'kind':kind,'powered':True}})
            self.assertFalse(result['attempted'])
        self.engine.faceplate.set_power.assert_not_called()
        self.assertEqual(self.engine._reconcile_faceplate(),0)

    def test_dva_permission_does_not_disable_voice_or_lightbar_preferences(self):
        before=self.store.all()
        self.engine.update_settings({'faceplate_control_mode':'gca-priority','faceplate_allow_dva':False})
        self.assertFalse(self.engine._assistant_visual_capabilities()['matrix_available'])
        for key in ['gabe_assistant','signalbar_enabled','light_bar_day_brightness','faceplate_lab_enabled']:
            self.assertEqual(before[key],self.store.all()[key])
        self.assertFalse(self.engine._handle_faceplate_scene({'payload':{'kind':'external'}})['attempted'])
        self.engine.faceplate_worker.cancel_scene_class.assert_called_with('external')

    def test_release_does_not_bypass_bar_or_voice_policy_and_resume_cannot_restart_usb(self):
        self.engine.update_settings({'faceplate_control_mode':'other-app','steam_control_enabled':True})
        self.engine.assistant.detach_visuals.assert_any_call('bar-unavailable',matrix=False,bar=True)
        self.assertEqual(self.engine._assistant_wake_allowed,self.engine._assistant_wake_policy(self.store.all()))
        self.assertTrue(self.engine.resume_faceplate()['skipped'])
        self.assertFalse(self.engine.activate_faceplate_setup())
        self.assertIsNone(self.engine._faceplate_power_target)
        self.engine.faceplate_worker.configure.assert_called_with(False)
        self.engine.faceplate.set_power.assert_not_called()

    def test_das_permission_revokes_pending_broker_work(self):
        self.engine.jsaux_broker_adapter=Mock()
        self.engine.update_settings({'faceplate_control_mode':'gca-priority','faceplate_allow_das':False})
        self.engine.jsaux_broker_adapter.release_for_control.assert_called()
        self.assertFalse(self.engine._broker_allowed(self.store.all()))
        self.assertFalse(self.engine._handle_faceplate_scene({'payload':{'kind':'return-stop'}})['attempted'])

    def test_reentry_invalidates_receipts_without_erasing_routes_or_media(self):
        before=self.engine.faceplate_router.status()['routes']
        self.engine.update_settings({'faceplate_control_mode':'other-app'})
        self.engine.faceplate.last_synchronized=True
        self.engine.faceplate._native_attempt=('old','clock')
        self.engine.update_settings({'faceplate_control_mode':'automatic'})
        self.assertFalse(self.engine.faceplate.last_synchronized)
        self.assertIsNone(self.engine.faceplate._native_attempt)
        self.assertEqual(before,self.engine.faceplate_router.status()['routes'])

    def test_reset_returns_to_automatic_and_default_integration_permissions(self):
        self.store.update({'faceplate_control_mode':'other-app','faceplate_allow_das':False})
        self.engine.reset_settings_only()
        values=self.store.all();self.assertEqual(values['faceplate_control_mode'],'automatic')
        self.assertTrue(values['faceplate_allow_das']);self.assertTrue(values['faceplate_allow_dva'])


if __name__=='__main__':unittest.main()
