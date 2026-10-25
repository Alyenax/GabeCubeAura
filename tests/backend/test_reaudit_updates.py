import tempfile
import threading
import unittest
from pathlib import Path
from signalbar.updates import UpdateManager,UpdateError
from signalbar.settings import SettingsStore
from test_updates import FakeClient,FakeLogger,write_archive

class ChannelReauditTests(unittest.TestCase):
    def manager(self,root,initial):
        settings=SettingsStore(str(root/'settings.json'));settings.update({'updates_channel':initial})
        manager=UpdateManager('1.4.0',settings,str(root/'runtime'),str(root/'plugin'),FakeLogger())
        clients={}
        for channel,version in [('beta','1.4.2-beta.1'),('stable','1.4.2')]:
            archive=root/(channel+'.zip');write_archive(archive,version);clients[channel]=FakeClient(archive,version)
        manager._release_client=lambda channel:clients[channel]
        return manager,clients

    def test_late_check_rechecks_latest_intent_and_only_stages_selected_channel(self):
        for initial,final in [('beta','stable'),('stable','beta')]:
            for failure in (False,True):
                with self.subTest(initial=initial,failure=failure),tempfile.TemporaryDirectory() as d:
                    m,clients=self.manager(Path(d),initial);entered=threading.Event();release=threading.Event()
                    original=clients[initial].latest
                    def delayed(*a,**kw):
                        value=original(*a,**kw);entered.set();assert release.wait(2)
                        if failure:raise UpdateError('network','synthetic outage')
                        return value
                    clients[initial].latest=delayed
                    worker=threading.Thread(target=m.check);worker.start();self.assertTrue(entered.wait(2))
                    # Multiple edits must collapse to the latest intent.
                    m.set_preferences(False,False,channel=final)
                    m.set_preferences(False,False,channel=initial)
                    m.set_preferences(False,False,channel=final)
                    release.set();worker.join(2);self.assertFalse(worker.is_alive())
                    state=m.status();self.assertEqual(final,state['channel']);self.assertEqual(final,state['checked_channel'])
                    self.assertEqual(clients[final].release['version'],state['available_version'])
                    self.assertEqual('ready',m.prepare()['phase'])
                    packages=list((m.root/'staged').rglob('package.json'));self.assertEqual(1,len(packages))
                    import json
                    self.assertEqual(clients[final].release['version'],json.loads(packages[0].read_text())['version'])

    def test_change_during_download_cannot_publish_previous_channel_staging(self):
        with tempfile.TemporaryDirectory() as d:
            m,clients=self.manager(Path(d),'beta');m.check()
            entered=threading.Event();release=threading.Event();original=clients['beta'].download_archive
            def delayed(*a,**kw):entered.set();assert release.wait(2);return original(*a,**kw)
            clients['beta'].download_archive=delayed
            worker=threading.Thread(target=m.prepare);worker.start();self.assertTrue(entered.wait(2))
            m.set_preferences(False,False,channel='stable');release.set();worker.join(2)
            self.assertFalse(worker.is_alive());self.assertEqual('stable',m.status()['checked_channel'])
            self.assertEqual([],list((m.root/'staged').rglob('package.json')))
            self.assertEqual('ready',m.prepare()['phase'])

    def test_channel_change_before_download_cannot_overwrite_new_idle_or_stall_recheck(self):
        with tempfile.TemporaryDirectory() as d:
            m,clients=self.manager(Path(d),'beta');m.check()
            entered=threading.Event();release=threading.Event();original=m._release_client
            def delayed(channel):
                if channel=='beta':entered.set();assert release.wait(2)
                return original(channel)
            m._release_client=delayed
            worker=threading.Thread(target=m.prepare);worker.start();self.assertTrue(entered.wait(2))
            m.set_preferences(False,False,channel='stable');release.set();worker.join(2)
            self.assertFalse(worker.is_alive());self.assertEqual('stable',m.status()['checked_channel'])
            self.assertEqual('available',m.status()['phase']);self.assertEqual([],list((m.root/'staged').rglob('package.json')))

    def test_channel_edit_cannot_clear_an_installation_transaction(self):
        for phase in ('preparing_install','installing','restart_pending'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as d:
                m,_=self.manager(Path(d),'beta');m._set(phase=phase,pending_token='active-transaction',confirmation_token='ready-token')
                before=m.settings.all();state=dict(m._state)
                with self.assertRaises(UpdateError) as error:m.set_preferences(False,False,channel='stable')
                self.assertEqual('busy',error.exception.category);self.assertEqual(before,m.settings.all());self.assertEqual(state,m._state)
