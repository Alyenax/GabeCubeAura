"""City uses the established Dashboard symbols, colours and battery choices."""
from io import BytesIO
import unittest
from unittest.mock import Mock

from PIL import Image

from signalbar.faceplate import player_city_row as row
from signalbar.faceplate.artwork_dashboard import PLAYER_ONE, PLAYER_TWO, DURATION_HAND, WARM_WHITE, WEATHER_WHITE
from signalbar.faceplate.bottom_stats import CLOCK, SESSION_CLOCK, TROPHY, _icon
from signalbar.faceplate.scenes import Canvas, measure_text
from signalbar.faceplate.player_city import build_player_city
from signalbar.faceplate.player_city_animation import animated_rgb, animation_manifest
from signalbar.faceplate.gif_transform import rotate_gif, repack_for_restore
from signalbar.faceplate.power import profile, indexed_peak


class CityNative235(unittest.TestCase):
    def test_count_only_skips_hidden_batteries_and_controller_style_is_visible(self):
        from signalbar.backend import Engine
        engine=Engine.__new__(Engine)
        engine._faceplate_playtime_facts=Mock(return_value={})
        engine.controllers=Mock()
        engine.controllers.faceplate_batteries.return_value=[dict(percent=85,charging=False)]
        self.assertEqual(engine._faceplate_player_city_facts({}),{'mode':'count'})
        engine.controllers.faceplate_batteries.assert_not_called()
        for style in ('percent','bar'):
            self.assertEqual(engine._faceplate_player_city_facts(dict(faceplate_player_city_row='controllers',
                faceplate_player_city_battery_style=style)),dict(mode='controllers',percent=85,battery_style=style))

    def test_count_only_is_the_renderer_default_and_centred(self):
        for count in (999, 12345, 4294967295):
            rail = row.build_rail(count)
            self.assertEqual(rail, row.build_rail(count, {'mode':'count'}))
            columns = self.columns(rail)
            self.assertLessEqual(abs(min(columns)-(63-max(columns))), 1)

    @staticmethod
    def columns(rail):
        return [p % 64 for p in range(64*9) if rail[p*3:p*3+3] != bytes(row.BACKGROUND)]

    def test_compact_modes_keep_two_dark_columns_at_each_edge_when_they_fit(self):
        for mode in ('controllers','session','achievements','total'):
            for style in ('percent','bar'):
                facts = dict(mode=mode, percent=100, battery_style=style, session_minutes=125,
                             achieved=42, achievements_total=100, total_minutes=12345)
                columns = self.columns(row.build_rail(12345, facts))
                self.assertGreaterEqual(min(columns), 2)
                self.assertLessEqual(max(columns), 61)
        # Longest values use the available width without dropping the count.
        self.assertEqual(len(row.build_rail(4294967295, dict(mode='total',total_minutes=999999999))), 1728)

    def test_clocks_and_trophy_are_exact_native_multicolour_pixels(self):
        for mode, pattern, label in (('session',SESSION_CLOCK,'2H05'),('total',CLOCK,'205H'),('achievements',TROPHY,'42/100')):
            rail = row.build_rail(12345, dict(mode=mode,session_minutes=125,total_minutes=12345,
                                            achieved=42,achievements_total=100))
            x = 62-(measure_text(label)+7)
            native = Canvas(row.BACKGROUND); _icon(native,x,pattern)
            expected = native.bytes()[45*64*3:]
            for y in range(3,8):
                for dx in range(5):
                    at = ((y*64)+x+dx)*3
                    self.assertEqual(rail[at:at+3], expected[at:at+3])
            self.assertIn(bytes(WARM_WHITE),rail)

    def test_p1_percent_and_bar_match_native_labels_and_battery(self):
        from signalbar.faceplate.artwork_dashboard import _battery_bar
        from signalbar.faceplate.scenes import draw_text
        for percent in (None,0,85,100):
            for style in ('percent','bar'):
                facts = dict(mode='controllers',percent=percent,battery_style=style)
                rail = row.build_rail(12345,facts)
                label = '--%' if percent is None else f'{percent}%'
                x = 62-10-(13 if style=='bar' else measure_text(label))
                expected=Canvas(row.BACKGROUND); draw_text(expected,x,48,'P1',PLAYER_ONE)
                if style=='bar': _battery_bar(expected,x+10,48,facts,PLAYER_ONE,True)
                else: draw_text(expected,x+10,48,label,PLAYER_ONE)
                native=expected.bytes()[45*64*3:]
                for y in range(9):
                    self.assertEqual(rail[(y*64+x)*3:(y*64+64)*3],native[(y*64+x)*3:(y*64+64)*3])

    def test_all_city_banks_keep_native_icon_colours(self):
        for bank in animation_manifest()['images']:
            art=animated_rgb(bank['weather'],bank['phase'],bank['tier'])
            for mode, colours in (('session',(PLAYER_ONE,DURATION_HAND)),('total',(PLAYER_ONE,DURATION_HAND)),
                                   ('achievements',(PLAYER_TWO,)),('controllers',(PLAYER_ONE,WEATHER_WHITE))):
                raw=row.build_rail(12345,dict(mode=mode,session_minutes=125,total_minutes=12345,
                    achieved=42,achievements_total=100,percent=100,battery_style='bar'))
                fitted=row.fit_rail_palette(art,raw)
                for colour in colours+(WARM_WHITE,row.ACCENT,):
                    for at in range(0,len(raw),3):
                        if raw[at:at+3]==bytes(colour):
                            self.assertEqual(fitted[at:at+3],bytes(colour),(bank['file'],mode,colour))

    def test_full_256_colour_gif_preserves_every_frame_rotation_restore_and_power(self):
        scene=build_player_city('STR','day',100000,row=dict(mode='session',session_minutes=125))
        colours={f[p:p+3] for f in scene.frames for p in range(0,len(f),3)}
        self.assertEqual(len(colours),256)
        payload=scene.gif()
        for data,rotated in ((payload,False),(rotate_gif(payload),True),(repack_for_restore(payload),False)):
            self.assertLessEqual(len(data),196608)
            im=Image.open(BytesIO(data)); self.assertEqual(im.n_frames,192)
            duration=0
            for n,frame in enumerate(scene.frames):
                im.seek(n); duration+=im.info['duration']
                expected=Image.frombytes('RGB',(64,54),frame)
                if rotated: expected=expected.transpose(Image.Transpose.ROTATE_180)
                self.assertEqual(im.convert('RGB').tobytes(),expected.tobytes())
            self.assertEqual(duration,24000)
        palette=list(colours); lookup={c:n for n,c in enumerate(palette)}
        indices=[bytes(lookup[f[p:p+3]] for p in range(0,len(f),3)) for f in scene.frames]
        expected=indexed_peak([tuple(c) for c in palette],indices)
        self.assertAlmostEqual(profile(payload)['peak_load'],expected)

    def test_all_indices_changed_uses_an_opaque_frame_without_losing_colours(self):
        from signalbar.faceplate.player_city import PlayerCityResult
        palette=[bytes((n,(n*3)%256,(n*7)%256)) for n in range(256)]
        frames=tuple(b''.join(palette[(p+n)%256] for p in range(3456)) for n in range(3))
        scene=PlayerCityResult(frames,'fixture',delays_cs=(12,13,12))
        for payload,rotated in ((scene.gif(),False),(rotate_gif(scene.gif()),True)):
            im=Image.open(BytesIO(payload)); self.assertEqual(im.n_frames,3)
            for n,frame in enumerate(frames):
                im.seek(n); expected=Image.frombytes('RGB',(64,54),frame)
                if rotated: expected=expected.transpose(Image.Transpose.ROTATE_180)
                self.assertEqual(im.convert('RGB').tobytes(),expected.tobytes())


if __name__=='__main__': unittest.main()
