"""Real provider, engine facts and compositor; no claim of physical USB acceptance."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from signalbar.backend import Engine
from signalbar.settings import SettingsStore
from signalbar.steam.dashboard_stats import DashboardStats
from signalbar.faceplate.scene_renderer import render_isolated
import test_dashboard_abcd as fixture
from test_dashboard_abcd import RGB, INSTANT

class RefreshTests(unittest.TestCase):
    def test_total_advances_complete_observed_hours_without_double_counting_or_regression(self):
        wall=[100.0];mono=[1000.0]
        reader=DashboardStats(roots=lambda:[],clock=lambda:wall[0],monotonic=lambda:mono[0]);self.addCleanup(reader.stop)
        reader.select_game(620)
        def sample(total):
            reader.update_live(620,dict(total_minutes=total,achieved=1,achievements_total=10))
            return reader.snapshot(620)['total_minutes']
        self.assertEqual(sample(2251),2251)
        mono[0]+=3599;self.assertEqual(sample(2251),2251)
        mono[0]+=1;self.assertEqual(sample(2251),2311)
        self.assertEqual(sample(2311),2311,'Steam catches up; do not add the session twice')
        mono[0]+=3600;self.assertEqual(sample(2311),2371)
        self.assertEqual(sample(2440),2440);self.assertEqual(sample(2251),2440,'A delayed native sample cannot lower the display')
        wall[0]-=100000;self.assertEqual(sample(2251),2440,'Wall-clock change cannot invent elapsed time')
        mono[0]+=3600;self.assertEqual(sample(2251),2500,'A higher authoritative total starts the next hourly baseline')
        reader.select_game(570);self.assertEqual(reader.snapshot(620),{})
        reader.select_game(620);self.assertEqual(sample(300),300,'New session starts with its own baseline')
        reader.stop();self.assertEqual(reader.snapshot(620),{})

    def test_total_baseline_does_not_follow_a_different_local_account(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fixture.LocalStatsTests().fixture(root);mono=[1000.0]
            reader=DashboardStats(roots=lambda:[root],monotonic=lambda:mono[0]);self.addCleanup(reader.stop);reader.select_game(620)
            reader.snapshot(620);reader._worker.join(2);self.assertEqual(reader.snapshot(620)['total_minutes'],11040)
            mono[0]+=3600;self.assertEqual(reader.snapshot(620)['total_minutes'],11100)
            base=fixture.LocalStatsTests().fixture(root,sid='76561197960265730',account='2')
            (root/'config/loginusers.vdf').write_text('"users" {"76561197960265730" {"MostRecent" "1"}}')
            (base/'localconfig.vdf').write_text('"UserLocalConfigStore" {"Software" {"Valve" {"Steam" {"apps" {"620" {"Playtime" "60"}}}}}}')
            self.assertEqual(reader.snapshot(620),{});reader._worker.join(2)
            self.assertEqual(reader.snapshot(620)['total_minutes'],60)

    def test_missing_total_is_unknown_and_hidden_time_never_becomes_a_fake_zero(self):
        reader=DashboardStats(roots=lambda:[],monotonic=lambda:9999999);self.addCleanup(reader.stop);reader.select_game(620)
        reader.update_live(620,dict(achieved=1,achievements_total=5))
        self.assertNotIn('total_minutes',reader.snapshot(620))

    def test_achievement_invalidates_local_cache_immediately_but_keeps_last_known_while_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=fixture.LocalStatsTests().fixture(root)
            reader=DashboardStats(roots=lambda:[root]);self.addCleanup(reader.stop)
            reader.snapshot(620);reader._worker.join(2)
            self.assertEqual(reader.snapshot(620)['achieved'],12)
            (base/'librarycache/620.json').write_text(json.dumps([['achievements',{'data':{'nAchieved':13,'nTotal':48}}]]))
            reader.invalidate(620);first=reader.snapshot(620);reader._worker.join(2)
            self.assertEqual(first['achieved'],12)
            self.assertEqual(reader.snapshot(620)['achieved'],13)

    def test_invalidating_during_disk_read_fences_old_result_and_reloads_on_next_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fixture.LocalStatsTests().fixture(root);reader=DashboardStats(roots=lambda:[root]);self.addCleanup(reader.stop)
            entered=threading.Event();release=threading.Event()
            def slow(*args):entered.set();release.wait(2);return dict(achieved=1,achievements_total=10)
            with patch.object(reader,'read',side_effect=slow):
                reader.snapshot(620);self.assertTrue(entered.wait(1));reader.invalidate(620);release.set();reader._worker.join(2)
            self.assertFalse(reader._cache)
            reader.snapshot(620);reader._worker.join(2);self.assertEqual(reader.snapshot(620)['achieved'],12)

    def test_real_router_queues_new_gifs_for_success_and_hour_but_not_unchanged_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=SettingsStore(str(Path(folder)/'settings.json'))
            settings.update(dict(faceplate_lab_enabled=True,faceplate_dashboard_contexts={'game':{'game_row':'b'}}))
            engine=Engine(settings,str(Path(folder)/'art.json'));self.addCleanup(engine.stop)
            engine.set_game(620,launch=True);engine.faceplate_preferences.update(game_scene='artwork-dashboard')
            mono=[1000.0];engine.dashboard_stats.monotonic=lambda:mono[0]
            with patch.object(engine,'_faceplate_continuity',return_value=('',False)),patch.object(engine.weather,'configure'), \
                 patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')), \
                 patch.object(engine,'_write_faceplate_runtime_status'),patch.object(engine.faceplate_worker,'submit',return_value=1) as submit:
                def run(done):
                    engine.report_dashboard_stats(620,dict(total_minutes=2251,achieved=done,achievements_total=48))
                    engine._reconcile_faceplate()
                run(12);self.assertEqual(submit.call_count,1);first=submit.call_args.args[1]['ticket'].content_key
                for _ in range(10):run(12)
                self.assertEqual(submit.call_count,1)
                run(13);self.assertEqual(submit.call_count,2);self.assertNotEqual(first,submit.call_args.args[1]['ticket'].content_key)
                mono[0]+=3599;run(13);self.assertEqual(submit.call_count,2)
                mono[0]+=1;run(13);self.assertEqual(submit.call_count,3)
                self.assertEqual(submit.call_args.args[1]['game_stats']['total_minutes'],2280)

    def test_engine_and_real_gif_change_on_achievement_and_hour_without_rewriting_background(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=SettingsStore(str(Path(folder)/'settings.json'));engine=Engine(settings,str(Path(folder)/'artwork.json'));self.addCleanup(engine.stop)
            engine.set_game(620,launch=True);mono=[1000.0];engine.dashboard_stats.monotonic=lambda:mono[0]
            values=settings.all();values['faceplate_dashboard_contexts']={'game':{'game_row':'b'}}
            def facts(done=12,total=2251):
                engine.report_dashboard_stats(620,dict(total_minutes=total,achieved=done,achievements_total=48))
                return engine._faceplate_artwork_dashboard_facts(values,True)
            def render(f):
                return render_isolated(dict(kind='artwork-dashboard',display_at=INSTANT,dashboard_background_rgb=RGB.hex(),dashboard_pack_frames=1,dashboard_pack_sha256=hashlib.sha256(RGB).hexdigest(),**f))[0]
            with patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')),patch.object(engine,'_faceplate_playtime_facts',return_value={}):
                first=facts();gif1=render(first)
                second=facts(13);gif2=render(second);self.assertNotEqual(first,second);self.assertNotEqual(gif1,gif2)
                self.assertEqual(second,facts(13),'Repeated same samples never dirty the render')
                mono[0]+=3599;self.assertEqual(second,facts(13))
                mono[0]+=1;hour=facts(13);self.assertEqual(hour['game_stats']['total_minutes'],2280);self.assertNotEqual(render(hour),gif2)
                engine.set_game(620,title='same game');self.assertEqual(hour,facts(13),'Title-only updates retain live totals and baseline')
                values['faceplate_dashboard_show_bottom_row']=False
                hidden=facts(13);self.assertNotIn('game_stats',hidden)
                self.assertEqual(hidden,facts(14))
                values['faceplate_dashboard_show_bottom_row']=True
                for variant in ('a','b','d','e'):
                    values['faceplate_dashboard_contexts']['game']['game_row']=variant
                    a=facts(1);b=facts(2);self.assertNotEqual(a,b,variant)
                with patch.object(engine.dashboard_stats,'invalidate') as invalidate:
                    engine.trigger_event('achievement',preview=True);invalidate.assert_not_called()
                    engine.trigger_event('achievement');invalidate.assert_called_once_with(620)
