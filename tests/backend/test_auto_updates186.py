"""Opt-in scheduler and verified installer; no network or real service launch."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from signalbar.settings import SettingsStore
from signalbar.updates import UpdateManager, UpdateError
import test_updates as fixture


class AutoUpdates186Tests(unittest.TestCase):
    def manager(self, version='1.1.1', installed='1.1.0'):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        base=Path(temp.name).resolve();archive=base/'release.zip'
        fixture.write_archive(archive,version);active=base/'plugins/GabeCubeAura'
        fixture.write_plugin(active,installed)
        settings=SettingsStore(str(base/'settings/config.json'))
        settings.update({'updates_auto_check':True})
        self.now=1000
        m=UpdateManager(installed,settings,str(base/'runtime'),str(active),fixture.FakeLogger(),
                        client=fixture.FakeClient(archive,version),clock=lambda:self.now,
                        companion_root=base/'user/components')
        return m

    def enable(self,m):
        m.set_preferences(True,True,1440,'stable',True)

    def launch(self,m):
        with patch('signalbar.updates.shutil.which',side_effect=lambda name:'/usr/bin/'+name), patch('signalbar.updates.subprocess.run') as run:
            result=m._automatic_update()
        return result,run

    def test_opt_in_is_off_for_new_and_old_configurations(self):
        m=self.manager();self.assertFalse(m.status()['auto_install'])
        m.check()
        with patch.object(m,'_prepare_locked') as prepare:
            m._automatic_update()
        prepare.assert_not_called()
        self.enable(m)
        m.set_preferences(True,False,60,'stable') # old four-argument UI preserves the option
        self.assertTrue(m.settings.all()['updates_auto_install'])
        self.assertFalse(SettingsStore(m.settings.path).all()['updates_auto_install'], 'Public restart drops a Lab automatic-install opt-in')
        self.assertNotIn('aggressive_check_minutes',m.status())

    def test_only_the_selected_interval_drives_checks_with_or_without_auto_install(self):
        for minutes in (60,180,360,720,1440):
            for automatic in (False,True):
                with self.subTest(minutes=minutes,automatic=automatic):
                    m=self.manager(version='1.1.0')
                    m.set_preferences(True,True,minutes,'stable',automatic);m.check()
                    calls=len(m.client.calls)
                    deadline=self.now+minutes*60
                    self.assertEqual(m.status()['next_check_at'],deadline)
                    self.now+=299;m._automatic_tick();self.assertEqual(len(m.client.calls),calls)
                    if minutes!=5:
                        self.now+=1;m._automatic_tick();self.assertEqual(len(m.client.calls),calls)
                    self.now=deadline;m._automatic_tick();self.assertEqual(len(m.client.calls),calls+1)
                    self.assertEqual(m.status()['next_check_at'],deadline+minutes*60)
                    self.assertEqual(SettingsStore(m.settings.path).all()['updates_check_interval_minutes'],minutes)

    def test_changing_interval_longer_or_shorter_reschedules_from_last_check(self):
        m=self.manager(version='1.1.0');m.set_preferences(True,True,60,'stable');m.check()
        checked=self.now;self.now+=60
        m.set_preferences(True,True,180,'stable')
        self.assertEqual(m.status()['next_check_at'],checked+10800)
        self.now=checked+300;calls=len(m.client.calls);m._automatic_tick()
        self.assertEqual(len(m.client.calls),calls)
        m.set_preferences(True,True,60,'stable')
        self.assertEqual(m.status()['next_check_at'],checked+3600)

    def test_auto_install_only_uses_selected_interval_and_preserves_it_when_toggled(self):
        m=self.manager(version='1.1.0');m.set_preferences(False,True,60,'stable',True);m.check()
        calls=len(m.client.calls);self.now+=300;m._automatic_tick()
        self.assertEqual(len(m.client.calls),calls)
        m.set_preferences(False,True,60,'stable')
        self.assertTrue(m.status()['auto_install'])
        self.assertEqual(m.status()['next_check_at'],1000+3600)
        m.set_preferences(False,True,60,'stable',False)
        self.assertEqual(m.status()['check_interval_minutes'],60)

    def test_lab186_stale_extra_deadline_is_removed_and_cannot_trigger_a_check(self):
        m=self.manager(version='1.1.0');m.check()
        m._set(next_aggressive_check_at=0,aggressive_check_minutes=5)
        restored=UpdateManager(m.installed_version,m.settings,str(m.runtime_dir),str(m.plugin_dir),fixture.FakeLogger(),client=m.client,clock=lambda:self.now,companion_root=m.companion_root)
        self.assertNotIn('next_aggressive_check_at',restored.status())
        calls=len(m.client.calls);self.now+=300;restored._automatic_tick()
        self.assertEqual(len(m.client.calls),calls)

    def test_rate_limit_backoff_survives_shorter_interval_selection(self):
        m=self.manager()
        with patch.object(m.client,'latest',side_effect=UpdateError('rate_limited','fixture rate limit')) as latest:
            m._automatic_tick();self.assertEqual(latest.call_count,1)
            m.set_preferences(True,True,60,'stable',True)
            self.now+=300;m._automatic_tick();self.assertEqual(latest.call_count,1)
            self.now+=3300;m._automatic_tick();self.assertEqual(latest.call_count,2)

    def test_auto_install_runs_with_auto_checks_off_and_reuses_verified_helper(self):
        m=self.manager();m.set_preferences(False,True,1440,'stable',True)
        with patch('signalbar.updates.shutil.which',side_effect=lambda name:'/usr/bin/'+name),patch('signalbar.updates.subprocess.run') as run:
            m._automatic_tick()
        self.assertEqual(run.call_count,1)
        self.assertEqual(m.status()['phase'],'installing')
        transaction=json.loads(next((m.root/'transactions').glob('*.json')).read_text())
        self.assertEqual(transaction['to_version'],'1.1.1')
        self.assertTrue(transaction['digest'])
        self.assertIn('restore_state',transaction)
        self.assertIn('systemd-run',run.call_args.args[0][0])
        with patch.object(m,'_prepare_locked') as prepare:
            m._automatic_tick()
        prepare.assert_not_called()

    def test_fresh_release_supersedes_an_older_prepared_package(self):
        m=self.manager();self.enable(m);m.check();m.prepare()
        archive=m.client.archive.parent/'new.zip';fixture.write_archive(archive,'1.1.2')
        m.client=fixture.FakeClient(archive,'1.1.2')
        result,run=self.launch(m)
        self.assertTrue(result['accepted']);self.assertEqual(result['version'],'1.1.2')
        self.assertEqual(run.call_count,1)

    def test_checksum_failure_never_installs_or_retries_same_release_in_a_loop(self):
        m=self.manager();self.enable(m);m.check()
        m.client.digest='0'*64
        # read_checksum matches fake digest, but the computed archive still differs.
        with patch.object(m.client,'download_archive',return_value='f'*64),patch.object(m,'_install_locked') as install:
            m._automatic_update();self.assertEqual(m.status()['phase'],'error')
            self.now+=300;m._automatic_tick()
        install.assert_not_called()
        self.assertEqual(m.status()['auto_attempt_version'],'1.1.1')
        self.assertTrue(m.status()['auto_install_paused'])

    def test_disabling_or_channel_aba_during_download_prevents_install(self):
        for change in ('off','off-on','channel'):
            with self.subTest(change=change):
                m=self.manager();self.enable(m);m.check()
                entered=threading.Event();resume=threading.Event();download=m.client.download_archive
                def delayed(*args,**kwargs):
                    entered.set();assert resume.wait(4);return download(*args,**kwargs)
                with patch.object(m.client,'download_archive',side_effect=delayed),patch.object(m,'_install_locked') as install:
                    worker=threading.Thread(target=m._automatic_update);worker.start();self.assertTrue(entered.wait(3))
                    if change=='channel':m.set_preferences(True,True,1440,'beta',True)
                    else:
                        m.set_preferences(True,True,1440,'stable',False)
                        if change=='off-on':self.enable(m)
                    resume.set();worker.join(4);self.assertFalse(worker.is_alive())
                install.assert_not_called()

    def test_no_automatic_downgrade_or_recovery_installation(self):
        m=self.manager(version='1.1.0',installed='1.2.0');self.enable(m);m.check()
        with patch.object(m,'_install_locked') as install:m._automatic_update()
        install.assert_not_called()
        for marker in ('recovery_source_token','lab114_rollback'):
            m=self.manager();self.enable(m);m.check();m.prepare();m._state[marker]='recovery'
            with patch.object(m,'_install_locked') as install:m._automatic_update()
            install.assert_not_called()

    def test_stop_and_install_operation_lock_prevent_parallel_automatic_work(self):
        m=self.manager();self.enable(m);m.check()
        m._operation_lock.acquire()
        try:
            with patch.object(m,'_prepare_locked') as prepare:m._automatic_update()
            prepare.assert_not_called()
        finally:m._operation_lock.release()
        m.stop()
        with patch.object(m,'_prepare_locked') as prepare:m._automatic_update()
        prepare.assert_not_called()

    def test_automatic_consent_is_revalidated_at_install_commit(self):
        m=self.manager();self.enable(m);m.check();m.prepare()
        context=('stable',m._preferences_generation,m._auto_install_generation)
        m.set_preferences(True,True,1440,'stable',False)
        with self.assertRaises(UpdateError) as error:
            m._install_locked(m.status()['confirmation_token'],automatic_context=context)
        self.assertEqual(error.exception.category,'cancelled')
        self.assertEqual(m.status()['phase'],'ready')

    def test_manual_prepared_update_is_checked_again_at_the_selected_interval(self):
        m=self.manager();m.set_preferences(True,True,60,'stable');m.check();m.prepare();calls=len(m.client.calls)
        deadline=m.status()['next_check_at']
        self.now+=300;m._automatic_tick();self.assertEqual(len(m.client.calls),calls)
        self.now=deadline;m._automatic_tick()
        self.assertEqual(len(m.client.calls),calls+1)
        self.assertEqual(m.status()['phase'],'ready')
        self.assertEqual(m.status()['next_check_at'],deadline+3600)

    def test_failed_helper_is_not_relaunched_by_polling_or_a_plugin_restart(self):
        m=self.manager();self.enable(m);m.check()
        with patch('signalbar.updates.shutil.which',side_effect=lambda name:'/usr/bin/'+name),patch('signalbar.updates.subprocess.run',side_effect=OSError('fixture cannot launch')) as run:
            m._automatic_update();self.assertEqual(run.call_count,1)
            self.now+=300;m._automatic_tick();self.assertEqual(run.call_count,1)
        restarted=UpdateManager(m.installed_version,m.settings,str(m.runtime_dir),str(m.plugin_dir),fixture.FakeLogger(),client=m.client,clock=lambda:self.now,companion_root=m.companion_root)
        restarted.check()
        with patch.object(restarted,'_install_locked') as install:restarted._automatic_update()
        install.assert_not_called()
        restarted.set_preferences(True,True,1440,'stable',False)
        restarted.set_preferences(True,True,1440,'stable',True)
        self.assertEqual(restarted.status()['auto_attempt_version'],'')

    def test_both_automatic_options_off_prevents_checks_and_installation(self):
        m=self.manager();m.set_preferences(False,False,1440,'stable',False)
        with patch.object(m.client,'latest') as latest,patch.object(m,'_install_locked') as install:
            m._automatic_tick();m._check_on_startup()
        latest.assert_not_called();install.assert_not_called()
