"""Real compositor, account isolation and visible-change upload contracts."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from signalbar.backend import Engine
from signalbar.dashboard_settings import dashboard_context
from signalbar.settings import SettingsStore
from signalbar.faceplate.artwork_dashboard import (build_artwork_dashboard, _draw_bottom_row,
    _battery_bar, quantize_battery, PLAYER_ONE, RAIL_BACKGROUND)
from signalbar.faceplate.scenes import Canvas
from signalbar.faceplate.scene_renderer import render_isolated
from signalbar.steam.dashboard_stats import DashboardStats, parse_vdf, achievement_counts

RGB = bytes((40, 70, 110)) * (64 * 54)
INSTANT = '2026-10-22T12:00:00+02:00'


def build(variant, **kw):
    args = dict(game_running=True, game_row=variant, show_weather_notch=False,
        bottom_mode='controllers', session_minutes=102, controllers=[{'percent':80}],
        game_stats={'total_minutes':184*60, 'achieved':12, 'achievements_total':48})
    args.update(kw)
    return build_artwork_dashboard((RGB,), INSTANT, args.pop('session_minutes'), **args)


class StrictCanvas(Canvas):
    def pixel(self, x, y, colour):
        if not (0 <= x < 64 and 45 <= y < 54):
            raise AssertionError((x,y))
        super().pixel(x,y,colour)


class DashboardABCDTests(unittest.TestCase):
    def test_native_bounds_long_values_missing_values_and_unchanged_upper_picture(self):
        for variant in 'abcde':
            for minutes in (None, 0, 102, 999999999):
                for stats in ({}, {'achieved':0,'achievements_total':0},
                              {'total_minutes':9999999999,'achieved':100000,'achievements_total':100000}):
                    canvas=StrictCanvas()
                    _draw_bottom_row(canvas,'controllers',game_running=True,game_row=variant,
                        session_minutes=minutes,game_stats=stats,controllers=[{'percent':100}])
                    result=build(variant,session_minutes=minutes,game_stats=stats)
                    self.assertEqual(RGB[:45*64*3], result.frames[0][:45*64*3])
                    self.assertEqual(64*54*3,len(result.frames[0]))

    def test_text_icons_and_batteries_have_disjoint_lit_pixel_masks(self):
        import signalbar.faceplate.bottom_stats as rows
        import signalbar.faceplate.artwork_dashboard as dashboard
        def tracked(function, occupied):
            def call(canvas,*args,**kw):
                isolated=Canvas();function(isolated,*args,**kw)
                pixels={i for i,c in enumerate(isolated.pixels) if c != (0,0,0)}
                self.assertFalse(occupied.intersection(pixels),function.__name__)
                occupied.update(pixels)
                return function(canvas,*args,**kw)
            return call
        for variant in 'abcde':
            for style in ('bar','percent'):
                for percent in (None,0,80,100):
                    for done,total in ((12,48),(123,456),(100000,100000)):
                        occupied=set()
                        with patch.object(rows,'draw_text',tracked(rows.draw_text,occupied)), \
                             patch.object(rows,'_icon',tracked(rows._icon,occupied)), \
                             patch.object(dashboard,'_battery_bar',tracked(dashboard._battery_bar,occupied)):
                            build(variant,battery_style=style,controllers=[{'percent':percent}],
                                  game_stats={'achieved':done,'achievements_total':total,'total_minutes':9999999999})

    def test_a_uses_exact_native_battery_and_respects_percentage_preference(self):
        frame=build('a',battery_style='bar').frames[0]
        expected=Canvas();expected.rect(0,45,64,9,RAIL_BACKGROUND)
        _battery_bar(expected,50,48,quantize_battery(78,step=5),PLAYER_ONE)
        for y in range(48,53):
            for x in range(50,63):
                self.assertEqual(expected.pixels[y*64+x],tuple(frame[(y*64+x)*3:(y*64+x+1)*3]))
        self.assertNotEqual(frame,build('a',battery_style='percent').frames[0])
        self.assertNotEqual(build('a',controllers=[{'percent':100}]).frames,
                            build('c',controllers=[{'percent':100}]).frames)
        self.assertNotEqual(build('a',game_stats={}).frames,build('c',game_stats={}).frames)

    def test_full_battery_keeps_all_three_measures_and_two_dark_columns(self):
        import signalbar.faceplate.bottom_stats as rows
        from signalbar.faceplate.scenes import measure_text
        for minutes in (100,1120,None,999999999):
            with patch.object(rows,'draw_text',wraps=rows.draw_text) as text:
                build('a',battery_style='percent',controllers=[{'percent':100}],session_minutes=minutes)
                values=[call.args for call in text.call_args_list]
                self.assertEqual(3,len(values))
                self.assertEqual('99%',values[-1][3])
                self.assertIn(values[-2][3],('25%','12/48'))
                stat_end=values[-2][1]+measure_text(values[-2][3])
                self.assertGreaterEqual(values[-1][1]-stat_end,2)
        self.assertEqual(build('a',controllers=[{'percent':99}]).signature,
                         build('a',controllers=[{'percent':100}]).signature)
        original=[{'percent':100}]
        build('a',controllers=original)
        self.assertEqual(100,original[0]['percent'])
        import signalbar.faceplate.artwork_dashboard as dashboard
        for variant in ('a','e'):
            for style in ('bar','percent'):
                with patch.object(rows,'draw_text',wraps=rows.draw_text) as text, patch.object(dashboard,'_battery_bar',wraps=dashboard._battery_bar) as battery:
                    build(variant,battery_style=style,controllers=[{'percent':100}],session_minutes=999999999,
                          game_stats={'total_minutes':9999999999,'achieved':100000,'achievements_total':100000})
                    values=[call.args for call in text.call_args_list]
                    stat_end=values[1][1]+measure_text(values[1][3])
                    battery_x=battery.call_args.args[1] if style=='bar' else values[2][1]
                    self.assertGreaterEqual(battery_x-stat_end,2)

    def test_session_three_values_have_no_clock_and_total_spreads_photo_values_until_real_100(self):
        import signalbar.faceplate.bottom_stats as rows
        from signalbar.faceplate.scenes import measure_text
        with patch.object(rows,'_icon',wraps=rows._icon) as icons, patch.object(rows,'draw_text',wraps=rows.draw_text) as text:
            build('a',controllers=[{'percent':100}])
            self.assertEqual([rows.TROPHY],[call.args[2] for call in icons.call_args_list])
            self.assertEqual(1,text.call_args_list[0].args[1])
            self.assertEqual('99%',text.call_args_list[-1].args[3])
        positions=[]
        for percent in (79,80,95,99,100):
            with patch.object(rows,'draw_text',wraps=rows.draw_text) as text, patch.object(rows,'_icon',wraps=rows._icon) as icons:
                build('e',controllers=[{'percent':percent}],game_stats={'total_minutes':16*60,'achieved':6,'achievements_total':30})
                duration,ratio,battery=[call.args for call in text.call_args_list]
                self.assertEqual(('16H','6/30',f'{percent}%'),(duration[3],ratio[3],battery[3]))
                trophy=icons.call_args_list[-1].args[1]
                self.assertGreaterEqual(trophy-(duration[1]+measure_text(duration[3])),3)
                self.assertGreaterEqual(battery[1]-(ratio[1]+measure_text(ratio[3])),3)
                positions.append((trophy,ratio[1],battery[1]))
        self.assertTrue(all(value==positions[0] for value in positions[:4]))
        self.assertEqual(52,positions[0][2]);self.assertEqual(48,positions[4][2])
        for percent in (98,99,99.9):
            self.assertEqual(99,quantize_battery(percent,step=5)['percent'])
        self.assertEqual(100,quantize_battery(100,step=5)['percent'])

    def test_engine_controllers_always_both_without_session_and_combinations_always_p1(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'settings.json'))
            store.update({'faceplate_lab_enabled':False})
            engine=Engine(store,str(Path(folder)/'art.json'));self.addCleanup(engine.stop)
            engine.set_game(620,launch=True);engine._faceplate_game_started_monotonic=1000
            values=store.all()
            for game in (False,True):
                context='game' if game else 'home'
                values['faceplate_dashboard_contexts']={context:{'bottom_mode':'controllers','show_p2':False,'show_session':True,'battery_style':'bar'}}
                with patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')), \
                     patch.object(engine,'_faceplate_playtime_facts',return_value={}), \
                     patch.object(engine.controllers,'faceplate_batteries',return_value=[{'percent':99},{'percent':35}]):
                    facts=engine._faceplate_artwork_dashboard_facts(values,game)
                    self.assertEqual(2,len(facts['controllers']));self.assertTrue(facts['show_p2'])
                    self.assertFalse(facts['show_game_session']);self.assertEqual(0,facts['session_minutes'])
                    self.assertEqual('bar',facts['battery_style'])
            for variant in ('a','c','e'):
                values['faceplate_dashboard_contexts']={'game':{'game_row':variant,'show_p2':True,'battery_style':'percent'}}
                with patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')), \
                     patch.object(engine,'_faceplate_playtime_facts',return_value={}), \
                     patch.object(engine.controllers,'faceplate_batteries',return_value=[{'percent':100},{'percent':35}]), \
                     patch.object(engine.dashboard_stats,'snapshot',return_value={'total_minutes':960,'achieved':6,'achievements_total':30}), \
                     patch('signalbar.backend.engine.time.monotonic',return_value=1000+100*60):
                    facts=engine._faceplate_artwork_dashboard_facts(values,True)
                    self.assertEqual(variant,facts['game_row']);self.assertEqual(1,len(facts['controllers']))
                    self.assertFalse(facts['show_p2'])
                    self.assertEqual(99 if variant=='a' else 100,facts['controllers'][0]['percent'])
                    if variant!='e':self.assertEqual(100,facts['session_minutes'])

    def test_only_controller_row_shows_two_pads_and_combined_rows_keep_p1(self):
        pads=[{'percent':None},{'percent':35}]
        for variant in ('a','c','e'):
            one=build(variant,controllers=pads[:1],show_p2=False,connected_controller_count=1)
            two=build(variant,controllers=pads,show_p2=True,connected_controller_count=2)
            self.assertEqual(one.frames,two.frames);self.assertEqual(one.signature,two.signature)
        self.assertEqual(build('existing',controllers=pads,show_p2=False).frames,
                         build('existing',controllers=pads,show_p2=True).frames)
        self.assertNotEqual(build('c',controllers=[{'percent':None}]).frames,
                            build('c',controllers=[{'percent':0}]).frames)

    def test_new_glyph_ink_does_not_dither_in_high_quality_modes(self):
        from io import BytesIO
        from PIL import Image
        for compression in ('compatible','balanced','fine'):
            result=build('c',battery_style='bar',compression=compression)
            decoded=Image.open(BytesIO(result.gif())).convert('RGB')
            hands=[decoded.getpixel(point) for point in ((3,49),(3,50),(4,51))]
            self.assertEqual(hands,[hands[0]]*3)
            from signalbar.faceplate.artwork_dashboard import DURATION_HAND, PALETTE_332, _palette_index
            self.assertEqual(PALETTE_332[_palette_index(*PLAYER_ONE)],hands[0])
            self.assertEqual(PALETTE_332[_palette_index(*DURATION_HAND)],decoded.getpixel((2,48)))

    def test_session_clock_reverses_only_total_clock_colours_with_identical_geometry(self):
        from signalbar.faceplate.artwork_dashboard import DURATION_HAND
        icons={}
        for variant in ('b','c','e'):
            frame=build(variant).frames[0]
            icons[variant]=[[tuple(frame[(y*64+x)*3:(y*64+x+1)*3]) for x in range(1,6)] for y in range(48,53)]
        self.assertEqual(icons['b'],icons['e'])
        self.assertNotEqual(icons['c'],icons['b'])
        for session,total in zip(sum(icons['c'],[]),sum(icons['b'],[])):
            self.assertEqual({PLAYER_ONE:DURATION_HAND,DURATION_HAND:PLAYER_ONE}.get(total,total),session)

    def test_total_achievements_battery_keeps_all_three_values_and_ignores_session(self):
        import signalbar.faceplate.bottom_stats as rows
        from signalbar.faceplate.scenes import measure_text
        self.assertEqual(build('e',session_minutes=0).signature,build('e',session_minutes=1000).signature)
        self.assertEqual(build('e',session_minutes=0).frames,build('e',session_minutes=1000).frames)
        for style in ('bar','percent'):
            with patch.object(rows,'draw_text',wraps=rows.draw_text) as text:
                build('e',battery_style=style,controllers=[{'percent':100}])
                labels=[call.args[3] for call in text.call_args_list]
                self.assertEqual('184H',labels[0]);self.assertIn(labels[1],('12/48','25%'))
                if style=='percent':
                    self.assertEqual('100%',labels[2])
                    values=[call.args for call in text.call_args_list]
                    self.assertGreaterEqual(values[2][1]-(values[1][1]+measure_text(values[1][3])),2)
        self.assertNotEqual(build('e',controllers=[{'percent':None}]).frames,build('e',controllers=[{'percent':0}]).frames)
        self.assertNotEqual(build('e',game_stats={}).frames,build('e',game_stats={'total_minutes':0}).frames)

    def test_b_has_no_underline_and_d_has_separate_progress_gauge(self):
        frame=build('b').frames[0]
        self.assertEqual(bytes(RAIL_BACKGROUND)*64,frame[53*64*3:])
        empty=build('d',game_stats={'achieved':0,'achievements_total':48}).frames
        unknown=build('d',game_stats={}).frames
        full=build('d',game_stats={'achieved':48,'achievements_total':48}).frames
        self.assertNotEqual(empty,unknown);self.assertNotEqual(empty,full)
        f=build('d').frames[0]
        for x in range(20,25):
            self.assertEqual(RAIL_BACKGROUND,tuple(f[(49*64+x)*3:(49*64+x+1)*3]))

    def test_hidden_timer_and_home_ignore_all_statistics_modes(self):
        for variant in 'abcde':
            for overrides in ({'game_running':False}, {'show_status_rail':False},
                              {'countdown':{'state':'remaining','minutes':10,'urgency':'warning'}}):
                a=build(variant,**overrides)
                b=build('existing',**overrides)
                self.assertEqual(a.frames,b.frames)

    def test_real_gifs_reuse_device_body_until_visible_change_and_restore_after_screensaver(self):
        from test_flash_protection import Panel
        from signalbar.faceplate.transport import Link
        from signalbar.faceplate.flash import FlashWearProtection,default_manager,install_manager
        from signalbar.faceplate import gif
        old=default_manager();self.addCleanup(install_manager,old)
        install_manager(FlashWearProtection())
        panel=Panel();link=Link('/dev/null');link.command=panel.command;link.write=lambda _:None
        game=build('a',battery_style='bar',session_minutes=100).gif()
        changed=build('a',battery_style='bar',session_minutes=105).gif()
        home=build('existing',game_running=False).gif()
        saver=gif.encode(64,54,((0,0,0),(255,0,0)),(bytes(64*54),))
        with patch('signalbar.faceplate.transport.time.sleep'):
            self.assertTrue(link.send_gif(game));before=panel.bodies
            self.assertFalse(link.send_gif(game));self.assertEqual(before,panel.bodies)
            for scene,data in [('game',changed),('home',home),('screensaver',saver),('home',home)]:
                link.flash_scene=scene
                self.assertTrue(link.send_gif(data))
                self.assertGreater(panel.bodies,before);before=panel.bodies
            self.assertFalse(link.send_gif(home));self.assertEqual(before,panel.bodies)

    def test_actual_isolated_worker_carries_statistics_and_signature(self):
        request=dict(kind='artwork-dashboard',display_at=INSTANT,
            dashboard_background_rgb=RGB.hex(),dashboard_pack_frames=1,
            dashboard_pack_sha256=hashlib.sha256(RGB).hexdigest(),
            game_row='d',game_running=True,show_weather_notch=False,
            game_stats={'achieved':12,'achievements_total':48})
        gif,meta=render_isolated(request)
        self.assertTrue(gif.startswith(b'GIF'))
        other,_=render_isolated({**request,'game_stats':{'achieved':48,'achievements_total':48}})
        self.assertNotEqual(gif,other)
        for kind in ('artwork-dashboard','dashboard'):
            case={**request,'kind':kind,'visual_theme':'weather-artwork-v2','condition':'rain',
                'variant':0,'temperature_c':12,'unit':'celsius',
                'sunrise':'2026-10-22T07:00:00+02:00','sunset':'2026-10-22T19:00:00+02:00',
                'game_row':'e','controllers':[{'percent':100}],'session_minutes':100,
                'game_stats':{'total_minutes':11040,'achieved':12,'achievements_total':48}}
            first,meta=render_isolated(case)
            same,identity=render_isolated({**case,'session_minutes':200})
            self.assertEqual(first,same);self.assertEqual(meta['signature'],identity['signature'])
            changed,_=render_isolated({**case,'controllers':[{'percent':0}]})
            self.assertNotEqual(first,changed)
            changed,_=render_isolated({**case,'game_stats':{**case['game_stats'],'total_minutes':11100}})
            self.assertNotEqual(first,changed)

    def test_engine_facts_are_bucketed_and_hidden_stats_never_read(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'settings.json'))
            store.update({'faceplate_lab_enabled':False})
            engine=Engine(store,str(Path(folder)/'art.json'));self.addCleanup(engine.stop)
            engine.set_game(620,launch=True)
            engine._faceplate_game_started_monotonic=1000
            values=store.all();values['faceplate_dashboard_contexts']={'game':{'game_row':'a'}}
            with patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')), \
                 patch.object(engine,'_faceplate_playtime_facts',return_value={}) as timer, \
                 patch.object(engine.controllers,'faceplate_batteries',return_value=[{'percent':78}]), \
                 patch.object(engine.dashboard_stats,'snapshot',return_value={'achieved':12,'achievements_total':48}) as stats, \
                 patch('signalbar.backend.engine.time.monotonic',return_value=1000+102*60) as now:
                a=engine._faceplate_artwork_dashboard_facts(values,True)
                now.return_value+=60
                b=engine._faceplate_artwork_dashboard_facts(values,True)
                self.assertEqual(a,b);self.assertEqual(100,a['session_minutes'])
                self.assertEqual(80,a['controllers'][0]['percent'])
                self.assertEqual(build('a',**{k:a[k] for k in ('session_minutes','controllers','game_stats')}).frames,
                                 build('a',**{k:b[k] for k in ('session_minutes','controllers','game_stats')}).frames)
                now.return_value+=120
                self.assertEqual(105,engine._faceplate_artwork_dashboard_facts(values,True)['session_minutes'])
                engine._session_start_known=False
                self.assertIsNone(engine._faceplate_artwork_dashboard_facts(values,True)['session_minutes'])
                stats.reset_mock();timer.return_value={'state':'remaining','minutes':10,'urgency':'warning'}
                self.assertNotIn('game_stats',engine._faceplate_artwork_dashboard_facts(values,True));stats.assert_not_called()
                timer.return_value={};values['faceplate_dashboard_contexts']['game']['show_bottom_row']=False
                self.assertNotIn('game_stats',engine._faceplate_artwork_dashboard_facts(values,True));stats.assert_not_called()
                self.assertEqual('existing',dashboard_context(values,False)['game_row'])


    def test_native_rpc_accepts_only_current_game_and_reaches_render_facts(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'settings.json'))
            store.update({'faceplate_lab_enabled':False})
            engine=Engine(store,str(Path(folder)/'art.json'));self.addCleanup(engine.stop)
            engine.dashboard_stats.roots=lambda:[]
            engine.set_game(620,launch=True)
            stats={'total_minutes':2251,'achieved':21,'achievements_total':25}
            self.assertFalse(engine.report_dashboard_stats(570,stats))
            self.assertTrue(engine.report_dashboard_stats(620,stats))
            values=store.all();values['faceplate_dashboard_contexts']={'game':{'game_row':'b'}}
            with patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')), \
                 patch.object(engine,'_faceplate_playtime_facts',return_value={}):
                facts=engine._faceplate_artwork_dashboard_facts(values,True)
                self.assertEqual({'total_minutes':2220,'achieved':21,'achievements_total':25},facts['game_stats'])
                request=dict(kind='artwork-dashboard',display_at=INSTANT,
                    dashboard_background_rgb=RGB.hex(),dashboard_pack_frames=1,
                    dashboard_pack_sha256=hashlib.sha256(RGB).hexdigest(),**facts)
                data,_=render_isolated(request)
                self.assertNotEqual(data,build('b',game_stats={}).gif())
                engine.set_game(0)
                engine.set_game(620,launch=True)
                self.assertEqual({},engine.dashboard_stats.snapshot(620))

    def test_each_achievement_changes_identity_even_if_percent_is_equal_and_total_stays_hourly(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SettingsStore(str(Path(folder)/'settings.json'))
            store.update({'faceplate_lab_enabled':False})
            engine=Engine(store,str(Path(folder)/'art.json'));self.addCleanup(engine.stop)
            engine.set_game(620,launch=True)
            values=store.all();values['faceplate_dashboard_contexts']={'game':{'game_row':'d'}}
            with patch.object(engine,'_faceplate_weather_payload',return_value=({}, {}, '')), \
                 patch.object(engine,'_faceplate_playtime_facts',return_value={}), \
                 patch.object(engine.dashboard_stats,'snapshot',return_value={'achieved':12,'achievements_total':48}) as stats:
                a=engine._faceplate_artwork_dashboard_facts(values,True)
                stats.return_value={'achieved':25,'achievements_total':100}
                self.assertNotEqual(a,engine._faceplate_artwork_dashboard_facts(values,True))
                values['faceplate_dashboard_contexts']['game']['game_row']='b'
                stats.return_value={'total_minutes':11040}
                a=engine._faceplate_artwork_dashboard_facts(values,True)
                stats.return_value={'total_minutes':11099}
                self.assertEqual(a,engine._faceplate_artwork_dashboard_facts(values,True))
                values['faceplate_dashboard_contexts']['game']['game_row']='e'
                with patch.object(engine.controllers,'faceplate_batteries',return_value=[{'percent':100}]), \
                     patch('signalbar.backend.engine.time.monotonic',return_value=1000):
                    a=engine._faceplate_artwork_dashboard_facts(values,True)
                self.assertEqual('e',a['game_row'])
                self.assertEqual(11040,a['game_stats']['total_minutes'])
                self.assertIsNone(a['session_minutes'])
                self.assertEqual(100,a['controllers'][0]['percent'])
                values['faceplate_dashboard_contexts']['game']['game_row']='b'
                store.update({'faceplate_dashboard_contexts':{'home':{'game_row':'d'},'game':{'game_row':'b'}}})
                restored=SettingsStore(str(Path(folder)/'settings.json')).all()
                self.assertEqual('existing',dashboard_context(restored,False)['game_row'])
                self.assertEqual('b',dashboard_context(restored,True)['game_row'])
                store.update({'faceplate_dashboard_contexts':{'home':{'game_row':'e'},'game':{'game_row':'e'}}})
                restored=SettingsStore(str(Path(folder)/'settings.json')).all()
                self.assertEqual('existing',dashboard_context(restored,False)['game_row'])
                self.assertEqual('e',dashboard_context(restored,True)['game_row'])


class LocalStatsTests(unittest.TestCase):
    def fixture(self, root, sid='76561197960265729', account='1'):
        (root/'config').mkdir(exist_ok=True)
        (root/'config/loginusers.vdf').write_text('"users" { "'+sid+'" { "MostRecent" "1" } }')
        base=root/'userdata'/account/'config';(base/'librarycache').mkdir(parents=True,exist_ok=True)
        (base/'localconfig.vdf').write_text('"UserLocalConfigStore" {"Software" {"Valve" {"Steam" {"apps" {"620" {"Playtime" "11040"}}}}}}')
        (base/'librarycache/620.json').write_text(json.dumps([['achievements',{'version':2,'data':{'nAchieved':12,'nTotal':48}}]]))
        return base

    def test_reads_only_confirmed_account_and_never_adds_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=self.fixture(root);reader=DashboardStats(roots=lambda:[root]);self.addCleanup(reader.stop)
            self.assertEqual({'total_minutes':11040,'achieved':12,'achievements_total':48},reader.read(620))
            reader.snapshot(620);reader._worker.join(2)
            self.assertEqual(11040,reader.snapshot(620)['total_minutes'])
            (root/'config/loginusers.vdf').write_text('"users" {}')
            self.assertEqual({},reader.snapshot(620));self.assertEqual({},reader.read(620))
            self.fixture(root,sid='76561197960265730',account='2')
            (root/'userdata/2/config/localconfig.vdf').unlink()
            self.assertNotIn('total_minutes',reader.read(620))
            self.assertEqual({},reader.read(0))

    def test_old_known_cache_survives_but_malformed_and_invalid_counts_are_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=self.fixture(root);reader=DashboardStats(roots=lambda:[root]);self.addCleanup(reader.stop)
            path=base/'librarycache/620.json';os.utime(path,(1,1))
            self.assertEqual({'total_minutes':11040,'achieved':12,'achievements_total':48},reader.read(620))
            path.write_text('{broken');self.assertEqual({'total_minutes':11040},reader.read(620))
            for value in ('"A" {', '"A" "B" }', 'garbage'):
                with self.assertRaises(ValueError):parse_vdf(value)
            for value in (True,-1,49):
                with self.assertRaises(ValueError):achievement_counts(json.dumps([['achievements',{'version':2,'data':{'nAchieved':value,'nTotal':48}}]]))

    def test_current_autologin_format_and_conflicting_accounts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root);reader=DashboardStats(roots=lambda:[root]);self.addCleanup(reader.stop)
            login=root/'config/loginusers.vdf'
            login.write_text('"users" {"76561197960265729" {"AutoLogin" "1"}}')
            self.assertEqual(11040,reader.read(620)['total_minutes'])
            login.write_text('"users" {"76561197960265729" {"AutoLogin" "1"} "76561197960265730" {"AutoLogin" "1"}}')
            self.assertEqual({},reader.read(620))
            login.write_text('"users" {"76561197960265729" {"AutoLogin" "0"}}')
            self.assertEqual({},reader.read(620))

    def test_live_steam_samples_work_without_account_file_and_expire(self):
        now=[100.0];reader=DashboardStats(roots=lambda:[],clock=lambda:now[0]);self.addCleanup(reader.stop)
        self.assertTrue(reader.update_live(620,{'total_minutes':2251,'achieved':21,'achievements_total':25}))
        self.assertEqual({'total_minutes':2251,'achieved':21,'achievements_total':25},reader.snapshot(620))
        self.assertEqual({},reader.snapshot(570))
        now[0]+=46;self.assertEqual({},reader.snapshot(620))
        reader.update_live(620,{'total_minutes':True,'achieved':99,'achievements_total':25})
        self.assertEqual({},reader.snapshot(620))

    def test_slow_disk_does_not_block_snapshot_or_start_parallel_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root);reader=DashboardStats(roots=lambda:[root]);self.addCleanup(reader.stop)
            entered=threading.Event();release=threading.Event()
            def read(*args):entered.set();release.wait(2);return {'total_minutes':60}
            with patch.object(reader,'read',side_effect=read) as slow:
                self.assertEqual({},reader.snapshot(620));self.assertTrue(entered.wait(1))
                self.assertEqual({},reader.snapshot(620));self.assertEqual(1,slow.call_count)
                self.assertEqual({},reader.snapshot(570))
                release.set();reader._worker.join(2)
            self.assertEqual(60,reader.snapshot(620)['total_minutes'])
