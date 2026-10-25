"""Overlapping native Apply calls cannot corrupt promoted Home/game artwork."""
import asyncio
import threading
from unittest.mock import patch
import unittest
import test_lab103_artwork_activation as fixture

class ArtworkApply249Tests(unittest.TestCase):
    setUp=fixture.ArtworkActivationTests.setUp
    prepare=fixture.ArtworkActivationTests.prepare

    def test_duplicate_rpc_joins_one_copy_route_and_queue(self):
        manifest,_=self.prepare('animated',draft=True)
        entered=threading.Event();release=threading.Event();original=self.library.assign_home
        def blocked(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise AssertionError('test copy never released')
            return original(*args,**kwargs)
        async def run():
            args=(620,'animated',True,False,manifest['sha256'],False)
            a=asyncio.create_task(self.plugin.assign_faceplate_dashboard_artwork(*args))
            b=asyncio.create_task(self.plugin.assign_faceplate_dashboard_artwork(*args))
            self.assertTrue(await asyncio.to_thread(entered.wait,2))
            await asyncio.sleep(0)
            self.assertEqual(copy.call_count,1)
            release.set()
            return await asyncio.gather(a,b)
        with patch.object(self.library,'assign_home',side_effect=blocked) as copy:
            try:results=asyncio.run(run())
            finally:release.set()
        self.assertEqual(results[0],results[1])
        self.assertEqual(results[0]['sha256'],manifest['sha256'])
        self.assertEqual(self.library.home_selected(620)[1]['sha256'],manifest['sha256'])
        self.assertEqual(self.library.selected(620)[1]['sha256'],manifest['sha256'])
        self.engine.faceplate_worker.submit.assert_called_once()
        self.assertEqual(self.plugin._faceplate_artwork_applies,{})
        self.assertFalse(list(self.library.artwork_root.rglob('*.applying')))
        self.assertFalse(list(self.library.artwork_root.rglob('*.previous')))

    def test_cancelling_one_rpc_does_not_cancel_the_shared_copy(self):
        manifest,_=self.prepare(draft=True)
        entered=threading.Event();release=threading.Event();original=self.library.assign_home
        def blocked(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise AssertionError('test copy never released')
            return original(*args,**kwargs)
        async def run():
            args=(620,'static',True,False,manifest['sha256'],False)
            a=asyncio.create_task(self.plugin.assign_faceplate_dashboard_artwork(*args))
            b=asyncio.create_task(self.plugin.assign_faceplate_dashboard_artwork(*args))
            self.assertTrue(await asyncio.to_thread(entered.wait,2));await asyncio.sleep(0)
            a.cancel()
            with self.assertRaises(asyncio.CancelledError):await a
            release.set();return await b
        with patch.object(self.library,'assign_home',side_effect=blocked) as copy:
            try:result=asyncio.run(run())
            finally:release.set()
        self.assertEqual(copy.call_count,1);self.assertEqual(result['sha256'],manifest['sha256'])
        self.engine.faceplate_worker.submit.assert_called_once()

    def test_game_only_duplicate_is_joined_too(self):
        manifest,_=self.prepare(draft=True)
        entered=threading.Event();release=threading.Event();original=self.library.activate_prepared
        def blocked(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise AssertionError('test copy never released')
            return original(*args,**kwargs)
        async def run():
            args=(620,'static',True,manifest['sha256'],'artwork')
            tasks=[asyncio.create_task(self.plugin.activate_faceplate_artwork(*args)) for _ in range(2)]
            self.assertTrue(await asyncio.to_thread(entered.wait,2));await asyncio.sleep(0)
            self.assertEqual(copy.call_count,1);release.set();return await asyncio.gather(*tasks)
        with patch.object(self.library,'activate_prepared',side_effect=blocked) as copy:
            try:asyncio.run(run())
            finally:release.set()
        self.engine.faceplate_worker.submit.assert_called_once()

    def test_saved_new_home_is_replaceable_and_survives_restart(self):
        old,_=self.prepare('animated',colour=(170,40,20));self.library.assign_home(620,'animated')
        new,_=self.prepare('animated',draft=True,colour=(20,170,70))
        self.assertNotEqual(old['sha256'],new['sha256'])
        result=asyncio.run(self.plugin.assign_faceplate_dashboard_artwork(620,'animated',True,False,new['sha256'],False))
        restarted=type(self.library)(self.library.root)
        self.assertEqual(restarted.home_selected(620)[1]['sha256'],new['sha256'])
        self.assertEqual(restarted.selected(620)[1]['sha256'],new['sha256'])
        self.assertEqual(result['sha256'],new['sha256'])

    def test_status_failure_cannot_turn_a_completed_new_ui_apply_into_failure(self):
        manifest,_=self.prepare(draft=True)
        self.engine.status.side_effect=RuntimeError('unrelated telemetry failure')
        result=asyncio.run(self.plugin.assign_faceplate_dashboard_artwork(620,'static',True,False,manifest['sha256'],False))
        self.assertEqual(result['sha256'],manifest['sha256']);self.engine.status.assert_not_called()
        self.engine.faceplate_worker.submit.assert_called_once()

    def test_failure_records_only_local_stage_and_releases_pending_operation_for_retry(self):
        manifest,_=self.prepare(draft=True)
        args=(620,'static',True,False,manifest['sha256'],False)
        with patch.object(self.library,'assign_home',side_effect=PermissionError('/private/user/path')):
            with self.assertRaises(PermissionError):asyncio.run(self.plugin.assign_faceplate_dashboard_artwork(*args))
        self.assertEqual(self.plugin._faceplate_artwork_applies,{})
        call=self.plugin.diagnostics.record.call_args
        self.assertEqual(call.args,('faceplate_artwork_apply_failed',))
        self.assertEqual(call.kwargs['stage'],'save-home');self.assertEqual(call.kwargs['error_type'],'PermissionError')
        self.assertNotIn('/private/user/path',str(call))
        self.engine.faceplate_worker.submit.assert_not_called()
        result=asyncio.run(self.plugin.assign_faceplate_dashboard_artwork(*args))
        self.assertEqual(result['sha256'],manifest['sha256'])

    def test_distinct_destinations_serialize_home_promotions_without_revision_conflict(self):
        manifest,_=self.prepare('animated',draft=True)
        entered=threading.Event();release=threading.Event();original=self.library.assign_home
        calls=[]
        def blocked(*args,**kwargs):
            calls.append(1)
            if len(calls)==1:
                entered.set()
                if not release.wait(3):raise AssertionError('test copy never released')
            return original(*args,**kwargs)
        async def run():
            tasks=[asyncio.create_task(self.plugin.assign_faceplate_dashboard_artwork(
                620,'animated',True,home_only,manifest['sha256'],False)) for home_only in (True,False)]
            self.assertTrue(await asyncio.to_thread(entered.wait,2));await asyncio.sleep(0)
            self.assertEqual(len(calls),1);release.set();return await asyncio.gather(*tasks)
        with patch.object(self.library,'assign_home',side_effect=blocked):
            try:results=asyncio.run(run())
            finally:release.set()
        self.assertEqual(len(calls),2)
        self.assertTrue(all(item['sha256']==manifest['sha256'] for item in results))
        self.assertEqual(self.library.home_selected(620)[1]['sha256'],manifest['sha256'])
        self.assertEqual(self.library.selected(620)[1]['sha256'],manifest['sha256'])
        self.assertEqual(self.plugin._faceplate_artwork_applies,{})
